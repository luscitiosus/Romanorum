"""Normalización de citas romanísticas (D. 1,1,1 pr. / Gai. 1.1 / C. 4.44.2 ...)."""

import re
import unicodedata

# Alias habituales en la literatura -> identificador de obra en la base.
# El identificador de cada obra es el prefijo que usa la propia edición BIA
# en el atributo @n (se aprende al ingerir); estos alias se añaden encima.
ALIASES = {
    "d": "digesta", "dig": "digesta", "digesto": "digesta", "digesta": "digesta", "ff": "digesta",
    "c": "codex", "cod": "codex", "ci": "codex", "cj": "codex", "codex": "codex",
    "i": "inst", "inst": "inst", "ij": "inst", "j": "inst", "iust": "inst",
    "gai": "gai", "g": "gai", "gaius": "gai", "gayo": "gai",
    "nov": "nov", "n": "nov", "novellae": "nov", "novelas": "nov",
    "cth": "cth", "ct": "cth", "codtheod": "cth", "theod": "cth",
    "ps": "ps", "paul": "ps", "pauli": "ps", "paulsent": "ps",
    "ulp": "ulp", "tit": "ulp", "titulp": "ulp", "epulp": "ulp",
    "fv": "fv", "vat": "fv", "fragvat": "fv",
    "coll": "coll", "collatio": "coll",
    "cons": "cons", "consult": "cons", "consultatio": "cons",
    "epgai": "epgai", "epitgai": "epgai",
}

_TOKEN = re.compile(r"[0-9]+|[a-z]+")


def fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(ch for ch in s if not unicodedata.combining(ch)).lower()


def split_ref(ref: str) -> tuple[str, list[str]]:
    """'D. 1, 1, 1 pr.' -> ('d', ['1', '1', '1', 'pr']).

    El prefijo son las letras anteriores al primer número; el resto son
    números y sufijos (pr, r, a, b...) que identifican el lugar.
    """
    toks = _TOKEN.findall(fold(ref))
    prefix: list[str] = []
    i = 0
    while i < len(toks) and not toks[i].isdigit():
        prefix.append(toks[i])
        i += 1
    rest = toks[i:]
    # "pr" escrito como "principium"
    rest = ["pr" if t in ("princ", "principium") else t for t in rest]
    rest = [(t.lstrip("0") or "0") if t.isdigit() else t for t in rest]  # HD000123 -> 123
    return "".join(prefix), rest


def key_of(parts: list[str]) -> str:
    return ".".join(parts)


# --- búsqueda por inscriptio: «Ulp. 28 ad ed.» -> «Ulpianus vicensimo octavo ad edictum»

_UNITS = ["", "primo", "secundo", "tertio", "quarto", "quinto", "sexto", "septimo", "octavo", "nono"]
_TEENS = {10: ["decimo"], 11: ["undecimo"], 12: ["duodecimo"], 18: ["duodevicensimo", "duodevicesimo"],
          19: ["undevicensimo", "undevicesimo"]}
_TENS = {
    2: ["vicensimo", "vicesimo"], 3: ["trigensimo", "tricensimo", "trigesimo", "tricesimo"],
    4: ["quadragensimo", "quadragesimo"], 5: ["quinquagensimo", "quinquagesimo"],
    6: ["sexagensimo", "sexagesimo"], 7: ["septuagensimo", "septuagesimo"],
    8: ["octogensimo", "octogesimo"], 9: ["nonagensimo", "nonagesimo"],
}


def ordinal_forms(n: int) -> list[str]:
    """Formas en ablativo con que las inscriptiones escriben el número de libro."""
    if n < 1 or n > 99:
        return []
    t, u = divmod(n, 10)
    if t == 0:
        return [_UNITS[u]]
    if t == 1:
        forms = list(_TEENS.get(n, []))
        if u >= 3:
            forms.append(f"{_UNITS[u]} decimo")
        return forms
    tens = _TENS[t]
    if u == 0:
        return list(tens)
    forms = [f"{w} {_UNITS[u]}" for w in tens]
    if u in (8, 9) and t < 9:  # duodetricensimo, undequadragensimo...
        pre = "duode" if u == 8 else "unde"
        forms += [pre + w for w in _TENS[t + 1]]
    return forms


JURISTS = {
    "ulp": "ulpianus", "paul": "paulus", "pomp": "pomponius", "iul": "iulianus", "pap": "papinianus",
    "marcian": "marcianus", "marci": "marcianus", "mod": "modestinus", "scaev": "scaevola",
    "cels": "celsus", "afr": "africanus", "marcell": "marcellus", "iav": "iavolenus",
    "herm": "hermogenianus", "call": "callistratus", "tryph": "tryphoninus", "flor": "florentinus",
    "lab": "labeo", "proc": "proculus", "ner": "neratius", "alf": "alfenus", "gai": "gaius",
    "ed": "edictum", "sab": "sabinum", "inst": "institutionum", "resp": "responsorum",
    "quaest": "quaestionum", "disp": "disputationum", "dig": "digestorum", "reg": "regularum",
    "fideic": "fideicommissorum", "prov": "provinciale", "sent": "sententiarum",
}

_FTS_OPS = {"AND", "OR", "NOT"}


def expand_query(q: str) -> str:
    """Traduce cifras y abreviaturas de juristas a la forma escrita en las inscriptiones.

    Solo actúa sobre consultas sin comillas; cada número de 1 a 99 se convierte en
    (N OR "forma ordinal" ...), así siguen funcionando las cifras de las subscriptiones.
    """
    if '"' in q or "NEAR(" in q:
        return q
    out = []
    for tok in q.split():
        bare = tok.rstrip(".")
        low = fold(bare)
        if tok in _FTS_OPS or not bare:
            out.append(tok)
        elif bare.isdigit() and ordinal_forms(int(bare)):
            alts = [bare] + [f'"{f}"' for f in ordinal_forms(int(bare))]
            out.append("(" + " OR ".join(alts) + ")")
        elif low in JURISTS and (tok.endswith(".") or low != JURISTS[low]):
            out.append(f"({low}* OR {JURISTS[low]})")
        elif tok.endswith(".") and bare.isalpha():
            out.append(f"{bare}*")  # abreviatura con punto: se busca como prefijo
        else:
            out.append(tok)
    # FTS5 no admite AND implícito delante de un grupo entre paréntesis
    joined: list[str] = []
    for tok in out:
        if joined and joined[-1] not in _FTS_OPS and tok not in _FTS_OPS:
            joined.append("AND")
        joined.append(tok)
    return " ".join(joined)
