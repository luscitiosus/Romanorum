# Fontes iuris Romani: conector MCP de fuentes del derecho romano

Servidor MCP que da a Claude acceso al texto latino (y griego) de las fuentes del derecho romano, con citas en notación romanística, búsqueda de texto completo y navegación por libros y títulos.

## Qué contiene

**Textos críticos** (citables por libro, título, fragmento y párrafo):
- Las 18 ediciones de **BIA, Bibliotheca Iuris Antiqui** (IGSG-CNR), CC BY-NC-SA 4.0: Digesto, Instituciones, Código, Novelas (con Appendices y XIII Edicta), Gayo, Epitome Gai, Fragmenta Augustodunensia, Tituli Ulpiani, Pauli Sententiae, Fragmenta Vaticana, Collatio, Consultatio, Codex Theodosianus con su Interpretatio, Lex Romana Burgundionum y Edictum Theoderici.
- De **digilibLT** (CC BY-NC 3.0): las Novelas post-teodosianas (Teodosio II, Valentiniano III, Marciano, Mayoriano, Severo y Antemio), citables como «Nov. Val. 35», y el Codex Euricianus.

**Ediciones antiguas en dominio público** (texto OCR por páginas, con enlace a la imagen de cada página en archive.org):
- **GdC**: *Cuerpo del Derecho Civil Romano*, traducción de García del Corral (1889-1898), en 6 tomos con el latín al lado.
- **Bruns**: *Fontes iuris Romani antiqui* (1909), con XII Tablas, leges, senatus consulta, edicta y negotia.
- **Theoph.**: la Paráfrasis de Teófilo, en la versión latina de Reitz.
- **Ep. Iul.**: el Epitome Iuliani de las Novelas.

**Epigrafía:** las 81.883 inscripciones latinas de la **Epigraphic Database Heidelberg** (CC BY 4.0, dataset SDAM 2022). Se pueden buscar por texto o por referencia («CIL II 5439»).

**No disponible en abierto:** las Basílicas (la edición digital de Brill es de pago), el Breviario de Alarico como obra autónoma y textos epigráficos recientes como la lex Irnitana, salvo lo que recoja la EDH.

## Herramientas

- `citar("D. 1.1.10 pr.")` (también «Nov. Val. 35», «GdC 2.145», «Bruns 120» o «EDH HD022109»): devuelve el texto de un lugar (párrafo, fragmento, título o libro) con inscriptio y subscriptio. Acepta comas o puntos, «pr.», «Dig.», «Gai.», «CTh.», etc.
- `buscar("stipulat* NEAR(dolo, 10)", fuentes=["D"], tipos=["Inscriptio"])`: búsqueda de texto completo en latín, sin distinguir diacríticos. Con `tipos=["Inscriptio"]` se busca por jurista y obra de procedencia («Ulpianus 28 ad ed»).
- `explorar("D. 18.1")`: muestra la estructura (libros, títulos con su rúbrica, fragmentos con su inscriptio).
- `listar_fuentes()`: lista las obras con su edición de base y licencia.
- `leer_web(url)`: lee una página de las bibliotecas permitidas.

## Despliegue

Un conector personalizado de claude.ai necesita una URL HTTPS pública. El servidor descarga las ediciones de BIA y crea la base SQLite durante la construcción de la imagen Docker, así que no hay que subir datos.

### Opción A: Render (gratis, recomendado)

1. Sube esta carpeta a un repositorio de GitHub (puede ser privado).
2. En [render.com](https://render.com), «New → Blueprint» y elige el repositorio. `render.yaml` crea el servicio y genera un `MCP_SECRET` aleatorio.
3. Cuando termine la construcción, copia el valor de `MCP_SECRET` (pestaña Environment). Tu URL será `https://<servicio>.onrender.com/<MCP_SECRET>/mcp`.
4. En claude.ai: Configuración → Conectores → Añadir conector personalizado, pega esa URL y deja vacíos los campos de OAuth.

El plan gratuito se duerme tras 15 minutos sin uso; la primera llamada después tarda unos 30–60 segundos.

### Opción B: cualquier servicio con Docker

Fly.io, Railway, Google Cloud Run o un VPS: `docker build -t fontes . && docker run -p 8000:8000 -e MCP_SECRET=<algo-largo> fontes`. La URL es `https://<host>/<MCP_SECRET>/mcp`.

### Opción C: en tu ordenador

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python ingest.py          # descarga y crea data/romanlaw.db (una vez)
python server.py --stdio           # para Claude Desktop o Claude Code
```

Para Claude Desktop, añade en `claude_desktop_config.json`:

```json
{"mcpServers": {"fontes-iuris-romani": {"command": "/ruta/.venv/bin/python", "args": ["/ruta/server.py", "--stdio"]}}}
```

Para usarlo desde claude.ai sin servidor, arranca `python server.py` y expón el puerto con un túnel (`cloudflared tunnel --url http://localhost:8000`). La URL dura lo que dure el túnel.

## Sobre la seguridad

claude.ai admite conectores sin autenticación. `MCP_SECRET` mete un valor aleatorio en la ruta para que solo quien conozca la URL pueda usarlo. Los textos son públicos; el secreto sirve sobre todo para que nadie consuma tu servicio.

## Licencias

- Textos: © BIA – Bibliotheca Iuris Antiqui (IGSG-CNR), CC BY-NC-SA 4.0. Uso no comercial, citando la fuente; las obras derivadas deben llevar la misma licencia.
- Las páginas leídas con `leer_web` se rigen por los términos de cada sitio.
