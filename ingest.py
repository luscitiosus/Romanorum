"""Descarga las fuentes y construye la base SQLite con índice FTS5.

Fuentes:
  - BIA (CNR): ediciones TEI del Corpus Iuris y fuentes preiustinianeas
  - digilibLT: Novelas post-teodosianas y Código de Eurico (TEI)
  - archive.org: ediciones antiguas en dominio público, como texto OCR por páginas
  - EDH: inscripciones latinas de la Epigraphic Database Heidelberg

Uso:
    python ingest.py            # descarga (si falta) y construye data/romanlaw.db
    python ingest.py --offline  # construye solo con lo ya presente en data/raw
"""

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

from catalog import (ARCHIVE, DIGILIBLT, DSPACE_API, EDH_TITLE, EDH_URL, LICENSE, LICENSE_DIGILIBLT,
                     LICENSE_EDH, LICENSE_PD, NOVPT_BOOKS, WORKS)
from refs import ALIASES, fold, key_of, split_ref

ROOT = Path(__file__).resolve().parent
DATA = Path(os.environ.get("ROMANLAW_DATA", ROOT / "data"))
RAW = DATA / "raw"
DB_PATH = DATA / "romanlaw.db"

_DIV = re.compile(r"^div\d*$")
_WS = re.compile(r"\s+")
_BLOCK = {"p", "head", "argument", "lg", "l", "ab", "lb", "milestone"}

SCHEMA = """
CREATE TABLE works(
    id TEXT PRIMARY KEY, abbr TEXT, title TEXT, handle TEXT, uuid TEXT,
    license TEXT, source TEXT, data_prefix TEXT, n_nodes INTEGER,
    kind TEXT, n_vols INTEGER
);
CREATE TABLE aliases(alias TEXT, work_id TEXT, key_prefix TEXT DEFAULT '',
    PRIMARY KEY(alias, work_id, key_prefix));
CREATE TABLE nodes(
    rowid INTEGER PRIMARY KEY,
    work_id TEXT, key TEXT, n TEXT, xml_id TEXT, type TEXT, leaf INTEGER,
    depth INTEGER, parent INTEGER, ord INTEGER, head TEXT, text TEXT, trail TEXT,
    meta TEXT DEFAULT '', url TEXT DEFAULT ''
);
CREATE INDEX nodes_key ON nodes(work_id, key);
CREATE INDEX nodes_parent ON nodes(parent);
CREATE VIRTUAL TABLE nodes_fts USING fts5(
    text, meta, content='nodes', content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2'
);
"""

INSERT_NODE = (
    "INSERT INTO nodes(work_id,key,n,xml_id,type,leaf,depth,parent,ord,head,text,trail,meta,url)"
    " VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)"
)


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
        if name == "milestone" and e.get("n"):
            out.append(f" §{e.get('n')} ")
        elif name in _BLOCK:
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


def retry(label: str, fn, attempts: int = 4):
    for attempt in range(attempts):
        try:
            return fn()
        except Exception as e:  # red inestable: reintento con espera
            print(f"    {label}: error {type(e).__name__}: {e}", file=sys.stderr)
            time.sleep(2 ** (attempt + 1))
    raise RuntimeError(f"{label}: no se pudo descargar")


def download_dspace(client: httpx.Client, uuid: str, dest: Path) -> None:
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


def download_stream(client: httpx.Client, url: str, dest: Path) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    with client.stream("GET", url) as r:
        r.raise_for_status()
        with open(tmp, "wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
    tmp.replace(dest)


# --- TEI (BIA, digilibLT) ----------------------------------------------------

def ingest_tei(con: sqlite3.Connection, wid: str, path: Path) -> tuple[int, str, str, list[tuple[str, str]]]:
    """Devuelve nº de nodos, prefijo de cita usado en @n, edición de base y libros de primer nivel."""
    root = ET.parse(path).getroot()
    body = next((e for e in root.iter() if local(e.tag) == "body"), root)
    counter = {"ord": 0, "n": 0}
    prefixes: dict[str, int] = {}
    top: list[tuple[str, str]] = []

    def visit(el: ET.Element, parent_id, parent_key, depth: int, trail: list[str]) -> None:
        seen: set[str] = set()
        idx = 0
        for child in el:
            if not _DIV.match(local(child.tag)):
                continue
            idx += 1
            n = child.get("n") or ""
            typ = child.get("type") or ""
            pre, parts = split_ref(n)
            if pre:
                prefixes[pre] = prefixes.get(pre, 0) + 1
            # en ediciones cuyo @n es local (digilibLT: n="1" dentro de cada libro)
            # se antepone la clave del padre
            if parent_key and not pre and parts:
                parts = parent_key.split("#")[0].split(".") + parts
            key = key_of(parts) if parts else (f"{parent_key}.{idx}" if parent_key else str(idx))
            # inscriptio / subscriptio comparten @n con su fragmento
            if parent_key is not None and key == parent_key:
                key = f"{key}#{fold(typ) or 'x'}"
            if key in seen:
                key = f"{parent_key}.{idx}" if parent_key else str(idx)
            seen.add(key)
            leaf = not any(_DIV.match(local(c.tag)) for c in child)
            head = head_text(child)
            text = own_text(child, skip_head=not leaf)
            counter["ord"] += 1
            label_n = n or key
            cur = con.execute(INSERT_NODE, (
                wid, key, label_n, child.get("{http://www.w3.org/XML/1998/namespace}id"), typ,
                int(leaf), depth, parent_id, counter["ord"], head, text, " › ".join(trail), "", ""))
            counter["n"] += 1
            if depth == 0:
                top.append((key, head))
            label = f"{label_n} {head}".strip() if head and not leaf else label_n
            visit(child, cur.lastrowid, key, depth + 1, trail + [label] if label else trail)

    visit(body, None, None, 0, [])
    data_prefix = max(prefixes, key=prefixes.get) if prefixes else ""
    return counter["n"], data_prefix, source_desc(root), top


# --- archive.org (OCR) -------------------------------------------------------

def archive_meta(client: httpx.Client, ident: str) -> dict:
    return client.get(f"https://archive.org/metadata/{ident}").json()


def download_archive(client: httpx.Client, ident: str, dest: Path) -> dict:
    meta = archive_meta(client, ident)
    names = [f["name"] for f in meta.get("files", []) if f["name"].endswith("_djvu.txt")]
    if not names:
        raise RuntimeError(f"{ident}: sin texto OCR (_djvu.txt)")
    url = f"https://archive.org/download/{ident}/{names[0]}"
    download_stream(client, url, dest)
    m = meta.get("metadata", {})
    info = {"title": m.get("title", ""), "date": m.get("date", ""), "volume": m.get("volume", "")}
    dest.with_suffix(".json").write_text(json.dumps(info, ensure_ascii=False))
    return info


_HYPH = re.compile(r"(\w)[-¬]\s*\n\s*(\w)")


def ingest_ocr(con: sqlite3.Connection, wid: str, abbr: str, vols: list[tuple[str, Path, dict]]) -> int:
    count = 0
    ord_ = 0
    for v, (ident, path, info) in enumerate(vols, start=1):
        raw = path.read_text(encoding="utf-8", errors="replace")
        pages = raw.split("\f")
        vol_label = clean(" ".join(x for x in (info.get("title", ""), info.get("volume", ""),
                                               str(info.get("date", ""))) if x))
        ord_ += 1
        cur = con.execute(INSERT_NODE, (
            wid, str(v), f"{abbr} {v}", ident, "Tomo", 0, 0, None, ord_, vol_label[:300], "", "", "",
            f"https://archive.org/details/{ident}"))
        vol_id = cur.lastrowid
        count += 1
        for p, page in enumerate(pages, start=1):
            text = clean(_HYPH.sub(r"\1\2", page))
            if len(text) < 40:  # páginas en blanco o láminas
                continue
            ord_ += 1
            con.execute(INSERT_NODE, (
                wid, f"{v}.{p}", f"{abbr} {v}, pág. {p}", None, "Página (OCR)", 1, 1, vol_id, ord_, "",
                text, f"{abbr} {v}", "", f"https://archive.org/details/{ident}/page/n{p - 1}/mode/1up"))
            count += 1
    return count


# --- EDH -----------------------------------------------------------------------

_EDH_TEXT = ("clean_text_interpretive_sentence", "clean_text_interpretive_word", "clean_text_conservative",
             "transcription", "diplomatic_text")


def _val(rec: dict, *keys: str) -> str:
    for k in keys:
        v = rec.get(k)
        if isinstance(v, (list, dict)) or v is None:
            continue
        v = str(v).strip()
        if v and v not in ("NULL", "NA", "{}", "[]"):
            return v
    return ""


def iter_json_records(path: Path):
    """Recorre un JSON de registros (array o JSON lines) sin cargarlo entero en memoria."""
    with open(path, "rb") as f:
        first = f.read(1)
        while first and first.isspace():
            first = f.read(1)
        f.seek(0)
        if first == b"[":
            import ijson
            yield from ijson.items(f, "item", use_float=True)
        else:
            for line in f:
                line = line.strip()
                if line:
                    yield json.loads(line)


def ingest_edh(con: sqlite3.Connection, path: Path) -> int:
    count = 0
    for rec in iter_json_records(path):
        hd = _val(rec, "id")
        text = _val(rec, *_EDH_TEXT)
        if not hd or not text:
            continue
        num = re.sub(r"\D", "", hd).lstrip("0") or "0"
        place = _val(rec, "findspot_ancient_clean", "findspot_ancient", "findspot_modern_clean", "findspot_modern")
        region = _val(rec, "province_label_clean", "province_label", "modern_region_clean", "modern_region",
                      "country_clean", "country")
        date = _val(rec, "origdate_text_clean")
        if not date:
            nb, na = _val(rec, "not_before"), _val(rec, "not_after")
            date = f"{nb}–{na}" if nb or na else ""
        typ = _val(rec, "type_of_inscription_clean", "type_of_inscription")
        lit = _val(rec, "literature")
        head = " · ".join(x for x in (place, region, date, typ) if x)
        meta = " ".join(x for x in (hd, lit, place, region, typ) if x)
        count += 1
        con.execute(INSERT_NODE, (
            "edh", num, hd, hd, "Inscripción", 1, 0, None, count, head, text, "", meta,
            f"https://edh.ub.uni-heidelberg.de/edh/inschrift/{hd}"))
    return count


# --- construcción ----------------------------------------------------------------

def add_work(con, wid, abbr, title, handle, uuid, lic, src, data_prefix, count, kind, n_vols, aliases):
    con.execute("INSERT INTO works VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (wid, abbr, title, handle, uuid, lic, src, data_prefix, count, kind, n_vols))
    aliases = set(aliases) | {wid, split_ref(abbr)[0], data_prefix}
    aliases |= {a for a, w in ALIASES.items() if w == wid}
    con.executemany("INSERT OR IGNORE INTO aliases(alias, work_id) VALUES(?,?)", [(a, wid) for a in aliases if a])


def build(offline: bool = False, only: list[str] | None = None) -> None:
    RAW.mkdir(parents=True, exist_ok=True)
    tmp = DB_PATH.with_suffix(".tmp")
    tmp.unlink(missing_ok=True)
    con = sqlite3.connect(tmp)
    con.executescript(SCHEMA)
    client = httpx.Client(timeout=httpx.Timeout(300, connect=30), follow_redirects=True,
                          headers={"User-Agent": "romanlaw-mcp/2.0 (estudio personal)"})
    want = (lambda w: not only or w in only)

    def fetch(label: str, dest: Path, fn) -> bool:
        if dest.exists():
            return True
        if offline:
            print(f"  - {label}: falta {dest.name}, se omite", file=sys.stderr)
            return False
        try:
            print(f"  ↓ {label}", file=sys.stderr)
            retry(label, fn)
            return True
        except Exception as e:
            print(f"  ✗ {e}", file=sys.stderr)
            return False

    # 1. BIA y digilibLT (TEI)
    tei = [(w, a, t, u, f"http://hdl.handle.net/20.500.11752/{h}", LICENSE, x, "BIA") for w, a, t, u, h, x in WORKS]
    tei += [(w, a, t, u, f"https://dspace-clarin-it.ilc.cnr.it/items/{u}", LICENSE_DIGILIBLT, x, "digilibLT")
            for w, a, t, u, x in DIGILIBLT]
    for wid, abbr, title, uuid, handle, lic, extra, origin in tei:
        if not want(wid):
            continue
        xml = RAW / f"{wid}.xml"
        if not fetch(f"{wid} ({title[:50]})", xml, lambda: download_dspace(client, uuid, xml)):
            continue
        try:
            count, data_prefix, src, top = ingest_tei(con, wid, xml)
        except Exception as e:
            print(f"  ✗ {wid}: error al procesar: {e}", file=sys.stderr)
            continue
        add_work(con, wid, abbr, title, handle, uuid, lic, f"{origin}: {src}", data_prefix, count, "tei", 0, extra)
        if wid == "novpt":
            for key, head in top:
                h = fold(head).upper()
                for word, als in NOVPT_BOOKS.items():
                    if word in h:
                        con.executemany("INSERT OR IGNORE INTO aliases VALUES(?,?,?)", [(a, wid, key) for a in als])
        print(f"  ✓ {wid}: {count} nodos (prefijo en los datos: {data_prefix!r})", file=sys.stderr)

    # 2. archive.org (OCR)
    for wid, abbr, title, idents, extra in ARCHIVE:
        if not want(wid):
            continue
        vols = []
        for ident in idents:
            txt = RAW / f"{ident}.txt"
            if fetch(f"{wid}: {ident}", txt, lambda: download_archive(client, ident, txt)):
                info_p = txt.with_suffix(".json")
                info = json.loads(info_p.read_text()) if info_p.exists() else {}
                vols.append((ident, txt, info))
        if not vols:
            continue
        try:
            count = ingest_ocr(con, wid, abbr, vols)
        except Exception as e:
            print(f"  ✗ {wid}: error al procesar: {e}", file=sys.stderr)
            continue
        missing = len(idents) - len(vols)
        src = "archive.org (OCR): " + ", ".join(v[0] for v in vols) + (f" — faltan {missing} tomos" if missing else "")
        add_work(con, wid, abbr, title, f"https://archive.org/details/{vols[0][0]}", "", LICENSE_PD, src, "",
                 count, "ocr", len(vols), extra)
        print(f"  ✓ {wid}: {count} páginas", file=sys.stderr)

    # 3. EDH
    if want("edh"):
        dest = RAW / "edh.json"
        if fetch("edh (Epigraphic Database Heidelberg, ~260 MB)", dest, lambda: download_stream(client, EDH_URL, dest)):
            try:
                count = ingest_edh(con, dest)
                add_work(con, "edh", "EDH", EDH_TITLE, "https://doi.org/10.5281/zenodo.7303886", "", LICENSE_EDH,
                         "Epigraphic Database Heidelberg, dataset SDAM (Heřmánková–Kaše, Aarhus) 2022", "hd",
                         count, "edh", 0, ["edh", "hd", "edhhd", "insc", "inscr", "epigraf"])
                print(f"  ✓ edh: {count} inscripciones", file=sys.stderr)
            except Exception as e:
                print(f"  ✗ edh: error al procesar: {e}", file=sys.stderr)

    if not con.execute("SELECT count(*) FROM works").fetchone()[0]:
        sys.exit("No se ha podido ingerir ninguna obra.")
    con.execute("INSERT INTO nodes_fts(nodes_fts) VALUES('rebuild')")
    con.commit()
    con.execute("VACUUM")
    con.close()
    tmp.replace(DB_PATH)
    print(f"Base creada en {DB_PATH}", file=sys.stderr)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--only", nargs="*")
    a = ap.parse_args()
    build(offline=a.offline, only=a.only)
