"""Descarga las ediciones TEI de BIA y construye la base SQLite con índice FTS5.

Uso:
    python ingest.py            # descarga (si falta) y construye data/romanlaw.db
    python ingest.py --offline  # construye solo con los XML ya presentes en data/raw
"""

import argparse
import os
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

from catalog import DSPACE_API, LICENSE, WORKS
from refs import ALIASES, fold, key_of, split_ref

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("ROMANLAW_DATA", ROOT / "data"))
RAW = DATA / "raw"
DB_PATH = DATA / "romanlaw.db"

_DIV = re.compile(r"^div\d*$")
_WS = re.compile(r"\s+")
_BLOCK = {"p", "head", "argument", "lg", "l", "ab", "lb"}

SCHEMA = """
CREATE TABLE works(
    id TEXT PRIMARY KEY, abbr TEXT, title TEXT, handle TEXT, uuid TEXT,
    license TEXT, source TEXT, data_prefix TEXT, n_nodes INTEGER
);
CREATE TABLE aliases(alias TEXT, work_id TEXT, PRIMARY KEY(alias, work_id));
CREATE TABLE nodes(
    rowid INTEGER PRIMARY KEY,
    work_id TEXT, key TEXT, n TEXT, xml_id TEXT, type TEXT, leaf INTEGER,
    depth INTEGER, parent INTEGER, ord INTEGER, head TEXT, text TEXT, trail TEXT
);
CREATE INDEX nodes_key ON nodes(work_id, key);
CREATE INDEX nodes_parent ON nodes(parent);
CREATE VIRTUAL TABLE nodes_fts USING fts5(
    text, content='nodes', content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);
"""


def local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def clean(s: str) -> str:
    return _WS.sub(" ", s).strip()


def own_text(el: ET.Element, skip_head: bool = False) -> str:
    """Texto del elemento sin descender a las <div*> hijas."""
    out: list[str] = []

    def walk(e: ET.Element, top: bool) -> None:
        name = local(e.tag)
        if not top and _DIV.match(name):
            return
        if name == "teiHeader" or (skip_head and not top and name == "head"):
            if e.tail and not top:
                out.append(e.tail)
            return
        if local(e.tag) in _BLOCK:
            out.append(" ")
        if e.text:
            out.append(e.text)
        for c in e:
            walk(c, False)
            # la cola de una div hija pertenece al padre
            if _DIV.match(local(c.tag)) and c.tail:
                out.append(c.tail)
        if not top and e.tail:
            out.append(e.tail)

    walk(el, True)
    return clean("".join(out))


def head_text(el: ET.Element) -> str:
    for c in el:
        if local(c.tag) in ("head", "argument"):
            return clean(" ".join(c.itertext()))
    # los títulos llevan su rúbrica en una <div type="Rubrica"> hija
    for c in el:
        if _DIV.match(local(c.tag)) and (c.get("type") or "").lower() in ("rubrica", "rubric"):
            return own_text(c)
    return ""


def source_desc(root: ET.Element) -> str:
    for e in root.iter():
        if local(e.tag) == "sourceDesc":
            return clean(" ".join(e.itertext()))[:500]
    return ""


def download(client: httpx.Client, uuid: str, dest: Path) -> None:
    bundles = client.get(f"{DSPACE_API}/core/items/{uuid}/bundles").json()
    for b in bundles["_embedded"]["bundles"]:
        if b["name"] != "ORIGINAL":
            continue
        bits = client.get(b["_links"]["bitstreams"]["href"]).json()
        for bs in bits["_embedded"]["bitstreams"]:
            if not bs["name"].lower().endswith(".xml"):
                continue
            r = client.get(f"{DSPACE_API}/core/bitstreams/{bs['uuid']}/content")
            r.raise_for_status()
            dest.write_bytes(r.content)
            return
    raise RuntimeError(f"El ítem {uuid} no tiene ningún XML en ORIGINAL")


def ingest_work(con: sqlite3.Connection, wid: str, path: Path) -> tuple[int, str, str]:
    root = ET.parse(path).getroot()
    body = next((e for e in root.iter() if local(e.tag) == "body"), root)
    counter = {"ord": 0, "n": 0}
    prefixes: dict[str, int] = {}

    def visit(el: ET.Element, parent_id, parent_key, depth: int, trail: list[str]) -> None:
        for child in el:
            if not _DIV.match(local(child.tag)):
                continue
            n = child.get("n") or ""
            typ = child.get("type") or ""
            pre, parts = split_ref(n)
            if pre:
                prefixes[pre] = prefixes.get(pre, 0) + 1
            key = key_of(parts)
            # inscriptio / subscriptio comparten @n con su fragmento
            if parent_key is not None and key == parent_key:
                key = f"{key}#{fold(typ) or 'x'}"
            leaf = not any(_DIV.match(local(c.tag)) for c in child)
            head = head_text(child)
            text = own_text(child, skip_head=not leaf)
            counter["ord"] += 1
            cur = con.execute(
                "INSERT INTO nodes(work_id,key,n,xml_id,type,leaf,depth,parent,ord,head,text,trail)"
                " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (wid, key, n, child.get("{http://www.w3.org/XML/1998/namespace}id"), typ,
                 int(leaf), depth, parent_id, counter["ord"], head, text, " › ".join(trail)),
            )
            counter["n"] += 1
            label = f"{n} {head}".strip() if head and not leaf else n
            visit(child, cur.lastrowid, key, depth + 1, trail + [label] if label else trail)

    visit(body, None, None, 0, [])
    data_prefix = max(prefixes, key=prefixes.get) if prefixes else ""
    return counter["n"], data_prefix, source_desc(root)


def build(offline: bool = False, only: list[str] | None = None) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    tmp = DB_PATH.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    client = httpx.Client(timeout=120, follow_redirects=True, headers={"User-Agent": "romanlaw-mcp/1.0"})
    for wid, abbr, title, uuid, handle, extra in WORKS:
        if only and wid not in only:
            continue
        xml = RAW / f"{wid}.xml"
        if not xml.exists():
            if offline:
                print(f"  - {wid}: falta {xml.name}, se omite", file=sys.stderr)
                continue
            for attempt in range(4):
                try:
                    print(f"  ↓ {wid} ({title})", file=sys.stderr)
                    download(client, uuid, xml)
                    break
                except Exception as e:  # red inestable: reintento con espera
                    print(f"    error: {e}", file=sys.stderr)
                    time.sleep(2 ** (attempt + 1))
            else:
                print(f"  ✗ {wid}: no se pudo descargar", file=sys.stderr)
                continue
        count, data_prefix, src = ingest_work(con, wid, xml)
        con.execute(
            "INSERT INTO works VALUES(?,?,?,?,?,?,?,?,?)",
            (wid, abbr, title, f"http://hdl.handle.net/20.500.11752/{handle}", uuid, LICENSE, src, data_prefix, count),
        )
        aliases = {wid, split_ref(abbr)[0], data_prefix, *extra}
        aliases |= {a for a, w in ALIASES.items() if w == wid}
        con.executemany("INSERT OR IGNORE INTO aliases VALUES(?,?)", [(a, wid) for a in aliases if a])
        print(f"  ✓ {wid}: {count} nodos (prefijo en los datos: {data_prefix!r})", file=sys.stderr)
    if not con.execute("SELECT count(*) FROM works").fetchone()[0]:
        sys.exit("No se ha podido ingerir ninguna obra.")
    con.execute("INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild')")
    con.commit()
    con.close()
    tmp.replace(DB_PATH)
    print(f"Base creada en {DB_PATH}", file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    build(offline=a.offline, only=a.only)
