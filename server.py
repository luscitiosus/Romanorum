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
Fuentes del derecho romano, en tres capas:
1. Textos críticos (latín; griego en Digesto y Novelas): BIA – Bibliotheca Iuris Antiqui (CNR) y \
digilibLT. Corpus Iuris Civilis (D., I., C., Nov.), Gayo, Tit. Ulp., PS., FV., Coll., Cons., \
Codex Theodosianus con su Interpretatio, Novelas post-teodosianas (Nov. Theod., Nov. Val., \
Nov. Marc., Nov. Maior., Nov. Sev., Nov. Anth.), Codex Euricianus, Lex Romana Burgundionum, \
Edictum Theoderici.
2. Ediciones antiguas en dominio público escaneadas (OCR, puede tener errores; cada página \
enlaza a su imagen en archive.org): GdC = traducción española de García del Corral del Corpus \
Iuris completo (6 tomos, con el latín al lado); Bruns = Fontes iuris Romani antiqui (1909: \
XII Tablas, leges, senatus consulta, edicta, negotia); Theoph. = Paráfrasis de Teófilo (versión \
latina); Ep. Iul. = Epitome Iuliani de las Novelas.
3. EDH: 81.883 inscripciones latinas de la Epigraphic Database Heidelberg (leyes municipales \
y coloniales de Hispania, senadoconsultos, diplomas…). Se buscan también por referencia \
bibliográfica ("CIL II 5439", "AE 1986").

Uso: `citar` con la cita (D. 1.1.10 pr., Gai. 1.8, Nov. Val. 35, GdC 2.145 = tomo 2, \
página 145 del escaneo, EDH HD022109); `buscar` por palabras (comodín *, OR, "frases"; \
«Ulp. 28 ad ed.» con tipos=["Inscriptio"] busca por jurista y obra; ambito="textos", \
"ocr" o "inscripciones" acota); `explorar` para ver la estructura. Para la traducción \
española de un pasaje, busca en GdC las palabras latinas del pasaje (fuentes=["GdC"]) y \
revisa la página. Cita siempre el lugar exacto devuelto y advierte cuando un texto viene \
de OCR. Para la Ley de las XII Tablas en texto limpio: `leer_web` con \
https://www.thelatinlibrary.com/12tables.html."""

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
    lines = ["| Abrev. | Obra | Unidades | Tipo | Licencia | Fuente | Edición |", "|---|---|---|---|---|---|---|"]
    kinds = {"tei": "texto crítico", "ocr": "OCR por páginas", "edh": "inscripciones"}
    for w in store.works():
        src = (w["source"] or "").replace("|", "/")[:160]
        lic = (w["license"] or "").split(" (")[0]
        lines.append(f"| {w['abbr']} | {w['title']} | {w['n_nodes']} | {kinds.get(w['kind'], '')} | {lic} "
                     f"| {w['handle']} | {src} |")
    return "\n".join(lines)


@mcp.tool()
def citar(referencia: str, obra: str | None = None, max_caracteres: int = MAX_CHARS) -> str:
    """Devuelve el texto latino de un lugar de las fuentes.

    referencia: cita en notación romanística, p. ej. "D. 1.1.10 pr.", "D. 50,17,202",
        "Gai. 1.8", "I. 2.1.1", "C. 4.44.2", "CTh. 9.1.1", "Nov. 118.1", "PS. 1.1.1",
        "Nov. Val. 35", "Nov. Marc. 4", "CE. 305", "GdC 2.145" (tomo 2, página 145 del escaneo),
        "Bruns 120" (página), "EDH HD022109" (inscripción).
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
    for wid in dict.fromkeys(r["work_id"] for r in rows):
        w = store.work(wid)
        note = " Texto procedente de OCR: puede contener errores; compruébalo en la imagen." if w["kind"] == "ocr" else ""
        parts.append(f"Fuente: {w['source'][:200]} — {w['handle']}. Licencia: {w['license']}.{note}")
    return "\n\n".join(parts)


@mcp.tool()
def buscar(
    consulta: str,
    fuentes: list[str] | None = None,
    tipos: list[str] | None = None,
    limite: int = 20,
    ambito: str | None = None,
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
    ambito: "textos" (ediciones críticas), "ocr" (ediciones escaneadas, incl. la traducción
        española GdC) o "inscripciones" (EDH). Por defecto, todo.
    """
    wids: list[str] | None = None
    if fuentes:
        wids = sorted({w for f in fuentes for w in store.resolve_work(f)})
        if not wids:
            return f"No reconozco ninguna de las fuentes {fuentes}. Usa listar_fuentes."
    if ambito:
        kind = {"textos": "tei", "texto": "tei", "ocr": "ocr", "traduccion": "ocr", "inscripciones": "edh",
                "epigrafia": "edh", "edh": "edh"}.get(ambito.lower().strip())
        if not kind:
            return "ambito debe ser «textos», «ocr» o «inscripciones»."
        pool = [w["id"] for w in store.works() if w["kind"] == kind]
        wids = [w for w in (wids or pool) if w in pool]
        if not wids:
            return "Ninguna fuente coincide con ese filtro."
    rows = store.search(consulta, wids, tipos, max(1, min(limite, 100)))
    if not rows:
        return "Sin resultados. Prueba con prefijos (emptio* vendit*) o quitando filtros."
    out = [f"{len(rows)} resultado(s) para «{consulta}»:\n"]
    for r in rows:
        frag = store.parent_fragment(r)
        insc = store.inscriptio(frag["rowid"]) if frag is not None and r["type"].lower() != "inscriptio" else ""
        if not insc and r["type"] == "Inscripción":
            insc = r["head"]
        w = store.work(r["work_id"])
        loc = r["n"] if w["kind"] != "tei" or r["n"][:1].isalpha() else f"{w['abbr']} {r['n']}"
        url = f" [{r['url']}]" if r["url"] and r["type"] != "Inscripción" else ""
        out.append(f"- **{loc}**{' (' + insc + ')' if insc else ''}: {r['snip']}{url}")
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
            top = store.top(wid)
            for n in top[:150]:
                out.append(f"- {n['n']} {n['head'] or n['text'][:120]}".rstrip())
            if len(top) > 150:
                out.append(f"… y {len(top) - 150} más. Usa `buscar` con fuentes=[\"{wid}\"].")
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
        for k in kids[:200]:
            label = k["head"] or k["text"] or store.inscriptio(k["rowid"])
            out.append(f"- {k['n']} [{k['type']}] {label[:140]}")
        if len(kids) > 200:
            out.append(f"… y {len(kids) - 200} más.")
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
    "archive.org",
    "edh.ub.uni-heidelberg.de",
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
