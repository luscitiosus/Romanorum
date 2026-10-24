"""Catálogo de ediciones digitales BIA (Bibliotheca Iuris Antiqui, IGSG-CNR).

Todas están publicadas en el repositorio CLARIN-IT del ILC-CNR con licencia
CC BY-NC-SA 4.0. `uuid` es el identificador del ítem en DSpace 7.
"""

DSPACE_API = "https://dspace-clarin-it.ilc.cnr.it/server/api"
LICENSE = "CC BY-NC-SA 4.0 (https://creativecommons.org/licenses/by-nc-sa/4.0/)"

# id, abreviatura usual, título, uuid DSpace, handle, alias extra
# (la edición impresa de base se lee del teiHeader al ingerir)
WORKS = [
    ("digesta", "D.", "Digesta Iustiniani", "df516228-3a20-4e4c-bcbc-4b6f5483d113", "OPEN-972", []),
    ("inst", "I.", "Institutiones Iustiniani", "e412fd76-6830-4e1a-8fb1-df496d63a049", "OPEN-962", []),
    ("codex", "C.", "Codex Iustinianus", "8db00bdc-18ac-4fa2-9151-71d9318892f8", "OPEN-967", []),
    ("nov", "Nov.", "Novellae Iustiniani", "bbab2f18-133f-4cad-af4c-c832730bace0", "OPEN-964", []),
    ("appnov", "App. Nov.", "Appendices Novellarum", "a99182fd-60b4-43ac-a85d-7ed8a745693c", "OPEN-957", ["appnov"]),
    ("edicta", "Ed. Iust.", "Iustiniani XIII Edicta", "a6e5b75e-b33c-4802-86f8-359d97c05043", "OPEN-973", ["ediust", "edicta"]),
    ("gai", "Gai.", "Gai Institutionum commentarii quattuor", "e4b7d831-03f6-4ba8-85e1-8cc814ed1ede", "OPEN-961", []),
    ("epgai", "Ep. Gai.", "Gai Institutionum Epitome", "1bfc0662-49c8-482a-85cd-c42356c834e1", "OPEN-958", []),
    ("fragaug", "Fr. Aug.", "Fragmenta interpretationis Gai Institutionum Augustodunensia", "23f7e945-9190-4446-920c-912a9befffe1", "OPEN-959", ["fraug", "fragaug", "aug"]),
    ("ulp", "Tit. Ulp.", "Tituli XXVIII ex corpore Ulpiani", "c6b8b915-27e9-460c-b1b8-5e25b166c52d", "OPEN-966", []),
    ("ps", "PS.", "Pauli Sententiae", "4968ba6f-ce21-400a-87c7-767e69cf0ca9", "OPEN-965", []),
    ("fv", "FV.", "Fragmenta Vaticana", "eb0ef901-e8db-489f-865f-d71a5aae9ffc", "OPEN-960", []),
    ("coll", "Coll.", "Mosaicarum et Romanarum Legum Collatio", "c0d03ffa-64c7-4c25-895a-3b96ee31c0c3", "OPEN-970", []),
    ("cons", "Cons.", "Consultatio veteris cuiusdam iurisconsulti", "38fb2297-1679-43ee-aff8-3e9f47985e32", "OPEN-971", []),
    ("cth", "CTh.", "Codex Theodosianus (cum constitutionibus Sirmondianis)", "abd9457a-d67a-4567-80a2-b540d9286e4a", "OPEN-968", []),
    ("cthint", "CTh. int.", "Interpretatio Visigothica al Codex Theodosianus", "46c4fca1-81f7-40dd-90e4-61393ae15fe7", "OPEN-969", ["cthint", "int", "interpretatio"]),
    ("lrb", "LRB.", "Lex Romana Burgundionum", "c4f9b8f3-f69a-4ec1-831d-2304e6d4060e", "OPEN-963", ["lrb", "burg"]),
    ("edtheod", "Ed. Theod.", "Edictum Theoderici regis", "9253484e-4778-49fd-975b-6b32b7b32c57", "OPEN-974", ["edtheod", "edth"]),
]
