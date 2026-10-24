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
    return "".join(prefix), rest


def key_of(parts: list[str]) -> str:
    return ".".join(parts)
