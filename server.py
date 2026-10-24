"""Servidor MCP «Fontes iuris Romani»: fuentes del derecho romano para Claude.

Transportes:
    python server.py                 # HTTP (Streamable HTTP) en 0.0.0.0:$PORT$MCP_PATH
    python server.py --stdio         # stdio, para Claude Desktop / Claude Code en local
"""

import html
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

import httpx
from mcp.server.fastmcp import FastMCP

from store import MAX_CHARS, Store

DB = Path(os.environ.get("ROMANLAW_DB", Path(__file__).parent / "data" / "romanlaw.db"))
store = Store(DB)

INSTRUCTIONS = """\
Fuentes primarias del derecho romano en latín (y griego en Digesto y Novelas), \
según las ediciones críticas digitalizadas por BIA – Bibliotheca Iuris Antiqui (CNR), \
licencia CC BY-NC-SA 4.0. Incluye el Corpus Iuris Civilis (Digesto, Instituciones, \
Código, Novelas), Gayo, Tituli Ulpiani, Pauli Sententiae, Fragmenta Vaticana, Collatio, \
Consultatio, Codex Theodosianus con su Interpretatio y leyes romano-bárbaras.

Uso recomendado: `citar` cuando el usuario da una cita (D. 1.1.10 pr., Gai. 1.8, I. 2.1.1, \
C. 4.44.2, CTh. 9.1.1, Nov. 118.1); `buscar` para localizar pasajes por palabras latinas \
(acepta comodín * , OR y "frases"; para buscar por jurista y obra \
vale «Ulp. 28 ad ed.» con tipos=["Inscriptio"]); `explorar` para ver libros, títulos y rúbricas. \
Cita siempre el lugar exacto devuelto. No hay traducciones: tradúcelas tú y adviértelo. \
Para la Ley de las XII Tablas usa `leer_web` con https://www.thelatinlibrary.com/12tables.html; \
para leyes, senadoconsultos y traducciones, The Roman Law Library \
(droitromain.univ-grenoble-alpes.fr), que a veces no responde."""

# MCP_SECRET convierte la URL en «secreta» (/<secreto>/mcp): sin él, cualquiera
# que conozca la dirección puede usar el conector.
_SECRET = os.environ.get("MCP_SECRET", "").strip("/")
PATH = os.environ.get("MCP_PATH") or (f"/{_SECRET}/mcp" if _SECRET else "/mcp")
mcp = FastMCP(
    "Fontes iuris Romani",
    instructions=INSTRUCTIONS,
    host="0.0.0.0",
    port=int(os.environ.get("PORT", "8000")),
    streamable_http_path=PATH,
    stateless_http=True,
    json_response=True,
)


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(request):
    from starlette.responses import PlainTextResponse
    return PlainTextResponse("ok")


def _work_label(wid: str) -> str:
    w = store.work(wid)
    return f"{w['abbr']} ({w['title']})" if w else wid


@mcp.tool()
def listar_fuentes() -> str:
    """Lista las obras disponibles con su abreviatura, número de unidades, edición de base y licencia."""
    lines = ["| Abrev. | Obra | Unidades | Fuente | Edición (teiHeader) |", "|---|---|---|---|---|"]
    for w in store.works():
        src = (w["source"] or "").replace("|", "/")[:160]
        lines.append(f"| {w['abbr']} | {w['title']} | {w['n_nodes']} | {w['handle']} | {src} |")
    lines.append("\nTextos: BIA – Bibliotheca Iuris Antiqui (IGSG-CNR), CLARIN-IT. Licencia CC BY-NC-SA 4.0.")
    return "\n".join(lines)


@mcp.tool()
def citar(referencia: str, obra: str | None = None, max_caracteres: int = MAX_CHARS) -> str:
    """Devuelve el texto latino de un lugar de las fuentes.

    referencia: cita en notación romanística, p. ej. "D. 1.1.10 pr.", "D. 50,17,202",
        "Gai. 1.8", "I. 2.1.1", "C. 4.44.2", "CTh. 9.1.1", "Nov. 118.1", "PS. 1.1.1".
        Si se cita un título o libro entero se devuelve todo su contenido (truncado a max_caracteres).
    obra: opcional, para forzar la obra si la abreviatura es ambigua (p. ej. "cth", "gai").
    """
    rows, msg = store.find(referencia, obra)
    if not rows:
        return msg
    parts = []
    for r in rows:
        head = f"# {_work_label(r['work_id'])} — {r['n']}"
        if r["trail"]:
            head += f"\n_{r['trail']}_"
        parts.append(f"{head}\n\n{store.render(r, max_caracteres)}")
    parts.append("\nFuente: BIA – Bibliotheca Iuris Antiqui (CNR), CC BY-NC-SA 4.0.")
    return "\n\n".join(parts)


@mcp.tool()
def buscar(
    consulta: str,
    fuentes: list[str] | None = None,
    tipos: list[str] | None = None,
    limite: int = 20,
) -> str:
    """Búsqueda de texto completo en latín (sin distinguir mayúsculas ni diacríticos).

    consulta: sintaxis FTS5: palabras sueltas (todas deben aparecer), "frase exacta",
        OR, NOT, NEAR(a b, 5) y prefijos con * (p. ej. stipulat* para todas las formas).
    fuentes: abreviaturas o ids para filtrar, p. ej. ["D", "Gai"].
    tipos: tipos de unidad para filtrar, p. ej. ["Inscriptio"] para buscar por jurista y obra
        de procedencia, o ["Rubrica"] para buscar títulos. Las cifras de 1 a 99 y las abreviaturas
        usuales (Ulp., Paul., Pomp., ed., Sab., resp.…) se traducen solas: "Ulp. 28 ad ed."
        encuentra «Ulpianus libro vicensimo octavo ad edictum».
    limite: número máximo de resultados (máx. 100).
    """
    wids: list[str] | None = None
    if fuentes:
        wids = sorted({w for f in fuentes for w in store.resolve_work(f)})
        if not wids:
            return f"No reconozco ninguna de las fuentes {fuentes}. Usa listar_fuentes."
    rows = store.search(consulta, wids, tipos, max(1, min(limite, 100)))
    if not rows:
        return "Sin resultados. Prueba con prefijos (emptio* vendit*) o quitando filtros."
    out = [f"{len(rows)} resultado(s) para «{consulta}»:\n"]
    for r in rows:
        frag = store.parent_fragment(r)
        insc = store.inscriptio(frag["rowid"]) if frag is not None and r["type"].lower() != "inscriptio" else ""
        loc = f"{_work_label(r['work_id'])} {r['n']}"
        out.append(f"- **{loc}**{' (' + insc + ')' if insc else ''}: {r['snip']}")
    return "\n".join(out)


@mcp.tool()
def explorar(referencia: str) -> str:
    """Muestra la estructura de una obra o de una de sus partes (libros, títulos, fragmentos).

    referencia: una abreviatura de obra ("D", "Gai", "CTh") para ver sus libros,
        o un lugar ("D. 18", "D. 18.1", "C. 4.44") para ver lo que contiene.
    """
    wids = [] if re.search(r"\d", referencia) else store.resolve_work(referencia)
    if wids:
        out = []
        for wid in wids:
            out.append(f"# {_work_label(wid)}")
            for n in store.top(wid):
                out.append(f"- {n['n']} {n['head'] or n['text'][:120]}".rstrip())
        return "\n".join(out)
    rows, msg = store.find(referencia)
    if not rows:
        return msg
    out = []
    for r in rows:
        out.append(f"# {_work_label(r['work_id'])} {r['n']} {r['head']}".rstrip())
        kids = store.children(r["rowid"])
        if not kids:
            out.append("(unidad sin subdivisiones; usa `citar`)")
        for k in kids:
            label = k["head"] or k["text"] or store.inscriptio(k["rowid"])
            out.append(f"- {k['n']} [{k['type']}] {label[:140]}")
    return "\n".join(out)


# --- lectura de páginas web de referencia ---------------------------------

ALLOWED_HOSTS = {
    "droitromain.univ-grenoble-alpes.fr",
    "www.thelatinlibrary.com",
    "thelatinlibrary.com",
    "la.wikisource.org",
    "es.wikisource.org",
    "www.perseus.tufts.edu",
    "penelope.uchicago.edu",
}


BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; FontesIurisRomani/1.1; +estudio personal)",
    "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "es,fr;q=0.8,en;q=0.6,la;q=0.4",
}


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.buf: list[str] = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "nav"):
            self.skip += 1
        elif tag in ("p", "br", "div", "tr", "li", "h1", "h2", "h3", "h4"):
            self.buf.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style", "nav") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)


@mcp.tool()
async def leer_web(url: str, desde: int = 0, max_caracteres: int = 15000) -> str:
    """Lee como texto una página de una biblioteca de fuentes romanas de una lista permitida.

    Útil para lo que no está en BIA: Ley de las XII Tablas, leyes y senadoconsultos,
    y traducciones (francés/inglés) de The Roman Law Library de Y. Lassard y A. Koptev
    (https://droitromain.univ-grenoble-alpes.fr/), The Latin Library, Wikisource latina
    o española, Perseus y LacusCurtius. Respeta los términos de uso de cada sitio.
    desde: posición de inicio para leer páginas largas por tramos.
    """
    host = urlparse(url).hostname or ""
    if host not in ALLOWED_HOSTS:
        return f"Dominio no permitido. Permitidos: {', '.join(sorted(ALLOWED_HOSTS))}"
    # algunos sitios universitarios solo responden por http o rechazan clientes sin
    # cabeceras de navegador; se prueba https y, si falla la conexión, http
    candidates = [url]
    if url.startswith("https://"):
        candidates.append("http://" + url[len("https://"):])
    elif url.startswith("http://"):
        candidates.insert(0, "https://" + url[len("http://"):])
    errors = []
    r = None
    async with httpx.AsyncClient(timeout=httpx.Timeout(45, connect=15), follow_redirects=True,
                                 headers=BROWSER_HEADERS) as c:
        for cand in candidates:
            try:
                r = await c.get(cand)
                break
            except httpx.HTTPError as e:
                errors.append(f"{cand}: {type(e).__name__} {e}".strip())
    if r is None:
        return ("No se ha podido conectar con el sitio (" + "; ".join(errors) + "). "
                "Para la Ley de las XII Tablas prueba https://www.thelatinlibrary.com/12tables.html")
    if r.status_code != 200:
        return f"Error HTTP {r.status_code} al leer {r.url}"
    if urlparse(str(r.url)).hostname not in ALLOWED_HOSTS:
        return "La página redirige a un dominio no permitido."
    p = _Text()
    p.feed(r.text)
    text = html.unescape("".join(p.buf))
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text).strip()
    chunk = text[desde: desde + max_caracteres]
    more = f"\n\n[…sigue: llama de nuevo con desde={desde + max_caracteres}; total {len(text)}]" \
        if desde + max_caracteres < len(text) else ""
    return f"Fuente: {r.url}\n\n{chunk}{more}"


if __name__ == "__main__":
    if "--stdio" in sys.argv:
        mcp.run("stdio")
    else:
        print(f"Escuchando en http://0.0.0.0:{mcp.settings.port}{PATH}", file=sys.stderr)
        mcp.run("streamable-http")
