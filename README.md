# Fontes iuris Romani: conector MCP de fuentes del derecho romano

Servidor MCP que da a Claude acceso al texto latino (y griego) de las fuentes del derecho romano, con citas en notación romanística, búsqueda de texto completo y navegación por libros y títulos.

## Qué contiene

Las 18 ediciones digitales de **BIA, Bibliotheca Iuris Antiqui** (IGSG-CNR), publicadas en el repositorio CLARIN-IT con licencia **CC BY-NC-SA 4.0**:

| Abrev. | Obra |
|---|---|
| D. | Digesta Iustiniani (Mommsen) |
| I. | Institutiones Iustiniani |
| C. | Codex Iustinianus (Krüger, 1895) |
| Nov. · App. Nov. · Ed. Iust. | Novellae, sus Appendices y los XIII Edicta |
| Gai. · Ep. Gai. · Fr. Aug. | Instituciones de Gayo, Epitome Gai y Fragmenta Augustodunensia |
| Tit. Ulp. · PS. | Tituli ex corpore Ulpiani, Pauli Sententiae |
| FV. · Coll. · Cons. | Fragmenta Vaticana, Collatio, Consultatio |
| CTh. · CTh. int. | Codex Theodosianus (con las Sirmondianas) e Interpretatio |
| LRB. · Ed. Theod. | Lex Romana Burgundionum, Edictum Theoderici |

Lo que BIA no tiene (Ley de las XII Tablas, leyes y senadoconsultos, traducciones) se lee en vivo con la herramienta `leer_web`, limitada a The Roman Law Library de Lassard y Koptev, The Latin Library, Wikisource (la/es), Perseus y LacusCurtius.

## Herramientas

- `citar("D. 1.1.10 pr.")`: devuelve el texto de un lugar (párrafo, fragmento, título o libro) con inscriptio y subscriptio. Acepta comas o puntos, «pr.», «Dig.», «Gai.», «CTh.», etc.
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
