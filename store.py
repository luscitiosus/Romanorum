"""Consultas sobre la base SQLite generada por romanlaw.ingest."""

import re
import sqlite3
from pathlib import Path

from refs import expand_query, fold, key_of, split_ref

MAX_CHARS = 12000


class Store:
    def __init__(self, path: Path):
        if not path.exists():
            raise FileNotFoundError(f"No existe {path}. Ejecuta antes: python ingest.py")
        self.con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, check_same_thread=False)
        self.con.row_factory = sqlite3.Row

    # --- obras -----------------------------------------------------------
    def works(self) -> list[sqlite3.Row]:
        return self.con.execute("SELECT * FROM works ORDER BY rowid").fetchall()

    def resolve_work(self, name: str) -> list[str]:
        return sorted({w for w, _ in self.resolve_ref(name)})

    def resolve_ref(self, name: str) -> list[tuple[str, str]]:
        """Alias -> [(obra, prefijo de clave)]; el prefijo lleva a un libro concreto (Nov. Val. -> libro 2)."""
        a = "".join(re.findall(r"[a-z]+", fold(name)))
        rows = self.con.execute("SELECT work_id, key_prefix FROM aliases WHERE alias=?", (a,)).fetchall()
        return [(r[0], r[1] or "") for r in rows]

    def work(self, wid: str) -> sqlite3.Row | None:
        return self.con.execute("SELECT * FROM works WHERE id=?", (wid,)).fetchone()

    # --- citas -----------------------------------------------------------
    def find(self, ref: str, work: str | None = None) -> tuple[list[sqlite3.Row], str]:
        """Devuelve los nodos que corresponden a una cita y un mensaje de diagnóstico."""
        prefix, parts = split_ref(ref)
        targets = self.resolve_ref(work) if work else self.resolve_ref(prefix) if prefix else []
        wids = sorted({w for w, _ in targets})
        if not targets:
            known = ", ".join(f"{w['abbr']}" for w in self.works())
            return [], f"No reconozco la obra de «{ref}». Abreviaturas disponibles: {known}"
        if not parts:
            return [], "Indica el lugar (p. ej. D. 1.1.1 pr.)."
        rows: list[sqlite3.Row] = []
        for wid, key_prefix in targets:
            w = self.work(wid)
            bases = [key_prefix.split(".") + list(parts) if key_prefix else list(parts)]
            if w is not None and w["kind"] == "ocr" and w["n_vols"] == 1 and len(parts) == 1:
                bases.append(["1"] + list(parts))  # «Bruns 120» = tomo único, página 120
            for base in bases:
                # se prueba la cita exacta y, si falla, quitando sufijos finales
                # (p. ej. «D. 50.17.1 pr» cuando el fragmento no tiene párrafos)
                cand = base
                hit = []
                while cand:
                    hit = self.con.execute(
                        "SELECT * FROM nodes WHERE work_id=? AND key=? ORDER BY ord", (wid, key_of(cand))
                    ).fetchall()
                    if hit:
                        break
                    cand = cand[:-1] if not cand[-1].isdigit() or cand[-1] == "0" else []
                if hit:
                    rows += hit
                    break
        if not rows:
            return [], f"No encuentro «{ref}» en {', '.join(wids)}. Usa `explorar` para ver la numeración."
        return rows, ""

    def children(self, node_id: int) -> list[sqlite3.Row]:
        return self.con.execute("SELECT * FROM nodes WHERE parent=? ORDER BY ord", (node_id,)).fetchall()

    def top(self, wid: str) -> list[sqlite3.Row]:
        return self.con.execute(
            "SELECT * FROM nodes WHERE work_id=? AND parent IS NULL ORDER BY ord", (wid,)
        ).fetchall()

    def render(self, node: sqlite3.Row, limit: int = MAX_CHARS) -> str:
        """Texto completo de un nodo y sus descendientes, con el @n de cada hoja."""
        out: list[str] = []
        size = 0

        def walk(n: sqlite3.Row) -> bool:
            nonlocal size
            if n["leaf"]:
                label = n["n"]
                t = n["type"].lower()
                line = f"[{label}{' · ' + n['type'] if t in ('inscriptio', 'subscriptio', 'rubrica') else ''}] {n['text']}"
                if n["head"] and t in ("inscripción", "inscripcion"):
                    line = f"[{label} · {n['head']}] {n['text']}"
                if n["url"]:
                    line += f"\n(Imagen/ficha: {n['url']})"
            else:
                line = f"## {n['n']} {n['head']}".rstrip() if n["head"] else ""
            if line:
                out.append(line)
                size += len(line)
            if size > limit:
                out.append("[…texto truncado: cita un lugar más concreto o sube `max_caracteres`]")
                return False
            for c in self.children(n["rowid"]):
                if not walk(c):
                    return False
            return True

        walk(node)
        return "\n".join(out)

    # --- búsqueda --------------------------------------------------------
    def search(self, query: str, works: list[str] | None, types: list[str] | None, limit: int):
        sql = (
            "SELECT n.*, snippet(nodes_fts, -1, '«', '»', ' … ', 24) AS snip, bm25(nodes_fts, 1.0, 0.4) AS score "
            "FROM nodes_fts JOIN nodes n ON n.rowid = nodes_fts.rowid WHERE nodes_fts MATCH ?"
        )
        args: list = []
        if works:
            sql += f" AND n.work_id IN ({','.join('?' * len(works))})"
            args += works
        if types:
            sql += f" AND lower(n.type) IN ({','.join('?' * len(types))})"
            args += [t.lower() for t in types]
        sql += " ORDER BY score LIMIT ?"
        try:
            return self.con.execute(sql, [expand_query(query), *args, limit]).fetchall()
        except sqlite3.OperationalError:
            # consulta con caracteres que FTS5 no acepta: se entrecomilla cada palabra
            safe = " ".join(f'"{w}"' for w in re.findall(r"\w+\*?", query) if w)
            safe = safe.replace('*"', '"*')
            if not safe:
                return []
            return self.con.execute(sql, [safe, *args, limit]).fetchall()

    def parent_fragment(self, node: sqlite3.Row) -> sqlite3.Row | None:
        if node["parent"] is None:
            return None
        return self.con.execute("SELECT * FROM nodes WHERE rowid=?", (node["parent"],)).fetchone()

    def inscriptio(self, fragment_id: int) -> str:
        r = self.con.execute(
            "SELECT text FROM nodes WHERE parent=? AND lower(type)='inscriptio' ORDER BY ord LIMIT 1",
            (fragment_id,),
        ).fetchone()
        return r[0] if r else ""
