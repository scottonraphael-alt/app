"""Paroles synchronisées (LRC), romanisation multilingue et récupération sur LRCLIB.

Tout ce module est « pur » (sans état partagé hors caches) pour rester testable hors ligne :
- `parse_lrc` lit le format LRC (lignes horodatées, tags de mots « enhanced », offset) ;
- `tokenize` découpe une ligne en mots et ajoute leur romanisation (`r`) :
    ja → pykakasi (léger ; cutlet facultatif si déjà installé), zh → pypinyin,
    ko → romanisation révisée (liaisons simples), autres alphabets → anyascii ;
- `build_lines` produit le JSON consommé par le front : chaque mot reçoit un début `s` et une
  fin `e` (en secondes), interpolés dans la ligne quand les paroles n'ont pas de tags par mot ;
- `fetch_lrclib` interroge LRCLIB (gratuit, sans clé) côté serveur uniquement.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from functools import lru_cache

import httpx

logger = logging.getLogger("karaoke.text")

LRCLIB_USER_AGENT = "IRIS-Karaoke/1.0 (https://iris.loasis.app)"

_STAMP_RE = re.compile(r"\[(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?\]")
_META_RE = re.compile(r"^\[([A-Za-z#]+):(.*)\]\s*$")
_WORD_STAMP_RE = re.compile(r"<(\d{1,3}):(\d{1,2})(?:[.:](\d{1,3}))?>")

# Durée de chant estimée par « unité de poids » (caractère de lecture) : borne la vitesse de
# remplissage quand deux lignes sont séparées par un long passage instrumental.
SECONDS_PER_UNIT = 0.17  # par syllabe (more en japonais)
MIN_LINE_SPAN = 1.5
LINE_BREATH = 0.15  # respiration laissée avant la ligne suivante quand on chante sans interruption
CONTINUOUS_GAP = 6.0  # en dessous de cet écart (ou 2,2 × la durée naturelle), la ligne dure jusqu'à la suivante
MAX_LINE_LENGTH = 400


# --------------------------------------------------------------------------------------
# Scripts
# --------------------------------------------------------------------------------------
def _script_counts(text: str) -> dict[str, int]:
    counts = {"kana": 0, "han": 0, "hangul": 0, "other": 0, "latin": 0}
    for ch in text:
        code = ord(ch)
        if 0x3040 <= code <= 0x30FF or 0x31F0 <= code <= 0x31FF or 0xFF66 <= code <= 0xFF9F:
            counts["kana"] += 1
        elif 0x4E00 <= code <= 0x9FFF or 0x3400 <= code <= 0x4DBF:
            counts["han"] += 1
        elif 0xAC00 <= code <= 0xD7AF or 0x1100 <= code <= 0x11FF or 0x3130 <= code <= 0x318F:
            counts["hangul"] += 1
        elif ch.isalpha():
            if unicodedata.name(ch, "").startswith("LATIN"):
                counts["latin"] += 1
            else:
                counts["other"] += 1
    return counts


def detect_lang(text: str) -> str:
    """Code de script/langue approximatif : ja, ko, zh, other (cyrillique, grec, arabe…) ou latin."""
    counts = _script_counts(text)
    if counts["kana"]:
        return "ja"
    if counts["hangul"] > counts["han"]:
        return "ko"
    if counts["han"]:
        return "zh"
    if counts["other"] > counts["latin"]:
        return "other"
    return "latin"


def _has(text: str, key: str) -> bool:
    return _script_counts(text)[key] > 0


# --------------------------------------------------------------------------------------
# Romanisation : un « token » = {"t": texte, "r": lecture latine ou "", "sp": espace après}
# --------------------------------------------------------------------------------------
@lru_cache(maxsize=1)
def _cutlet():
    import cutlet  # import tardif : dictionnaire UniDic chargé à la première chanson japonaise

    engine = cutlet.Cutlet()
    engine.use_foreign_spelling = False
    return engine


def _needs_reading(surface: str, romaji: str) -> bool:
    return bool(romaji) and romaji != surface and not surface.isascii()


@lru_cache(maxsize=1)
def _kakasi():
    from pykakasi import kakasi
    return kakasi()


def _tokens_ja_light(text: str) -> list[dict]:
    tokens = []
    for item in _kakasi().convert(text):
        surface = item['orig']
        if not surface.strip():
            continue
        reading = {'は': 'wa', 'へ': 'e', 'を': 'o'}.get(surface, item['hepburn'])
        tokens.append({'t': surface, 'r': reading if _needs_reading(surface, reading) else '',
                       'sp': surface.isascii() and surface.endswith(' ')})
    return tokens


def _tokens_ja(text: str) -> list[dict]:
    try:
        from cutlet.cutlet import normalize_text
    except ImportError:
        return _tokens_ja_light(text)

    engine = _cutlet()
    words = engine.tagger(normalize_text(text))
    romaji_tokens = engine.romaji_tokens(words, capitalize=False)
    tokens: list[dict] = []
    for word, romaji in zip(words, romaji_tokens):
        surface = word.surface
        if not surface.strip():
            continue
        reading = romaji.surface if _needs_reading(surface, romaji.surface) else ""
        tokens.append({"t": surface, "r": reading, "sp": surface.isascii() and bool(romaji.space)})
    return tokens


def _tokens_zh(text: str) -> list[dict]:
    from pypinyin import Style, pinyin

    # `errors` renvoie les portions non chinoises telles quelles : l'alignement texte/lecture est exact.
    syllables = pinyin(text, style=Style.TONE, errors=lambda chunk: [chunk])
    tokens: list[dict] = []
    position = 0
    for item in syllables:
        reading = item[0]
        if position < len(text) and _has(text[position], "han"):
            tokens.append({"t": text[position], "r": reading, "sp": False})
            position += 1
        else:
            chunk = reading
            position += len(chunk)
            if chunk.strip():
                tokens.append({"t": chunk, "r": "", "sp": False})
    return tokens


# Romanisation révisée du coréen (Unicode : initiale × voyelle × finale).
_KO_INITIAL = ["g", "kk", "n", "d", "tt", "r", "m", "b", "pp", "s", "ss", "", "j", "jj", "ch", "k", "t", "p", "h"]
_KO_VOWEL = [
    "a", "ae", "ya", "yae", "eo", "e", "yeo", "ye", "o", "wa", "wae", "oe", "yo", "u", "wo", "we", "wi",
    "yu", "eu", "ui", "i",
]
_KO_FINAL = [
    "", "k", "k", "ks", "n", "nj", "nh", "t", "l", "lk", "lm", "lb", "ls", "lt", "lp", "lh", "m", "p",
    "ps", "t", "t", "ng", "t", "t", "k", "t", "p", "t",
]
# Liaison devant une syllabe qui commence par ㅇ : finale -> (reste de la finale, consonne déplacée).
_KO_LIAISON = {
    1: ("", "g"), 2: ("", "kk"), 3: ("k", "s"), 4: ("", "n"), 5: ("n", "j"), 6: ("n", ""),
    7: ("", "d"), 8: ("", "r"), 9: ("l", "g"), 10: ("l", "m"), 11: ("l", "b"), 12: ("l", "s"),
    13: ("l", "t"), 14: ("l", "p"), 15: ("l", ""), 16: ("", "m"), 17: ("", "b"), 18: ("p", "s"),
    19: ("", "s"), 20: ("", "ss"), 22: ("", "j"), 23: ("", "ch"), 24: ("", "k"), 25: ("", "t"),
    26: ("", "p"), 27: ("", ""),
}


def romanize_hangul(word: str) -> str:
    """Romanisation révisée approchée : liaisons gérées, autres assimilations ignorées."""
    parts: list[tuple[int, int, int] | str] = []
    for ch in word:
        code = ord(ch) - 0xAC00
        if 0 <= code < 11172:
            parts.append((code // 588, (code % 588) // 28, code % 28))
        else:
            parts.append(ch)
    out: list[str] = []
    carried = ""  # consonne déplacée par une liaison, à placer devant la syllabe suivante
    for index, part in enumerate(parts):
        if isinstance(part, str):
            out.append(part)
            carried = ""
            continue
        initial, vowel, final = part
        onset = carried if (initial == 11 and carried) else _KO_INITIAL[initial]
        carried = ""
        nxt = parts[index + 1] if index + 1 < len(parts) else None
        if final and isinstance(nxt, tuple) and nxt[0] == 11 and final in _KO_LIAISON:
            stay, carried = _KO_LIAISON[final]
            coda = stay
        else:
            coda = _KO_FINAL[final]
        out.append(onset + _KO_VOWEL[vowel] + coda)
    return "".join(out)


def _tokens_ko(text: str) -> list[dict]:
    words = text.split()
    return [
        {"t": word, "r": romanize_hangul(word) if _has(word, "hangul") else "", "sp": i < len(words) - 1}
        for i, word in enumerate(words)
    ]


def _tokens_generic(text: str) -> list[dict]:
    from anyascii import anyascii

    words = text.split()
    tokens = []
    for i, word in enumerate(words):
        reading = anyascii(word).strip()
        tokens.append(
            {"t": word, "r": reading if reading and reading != word else "", "sp": i < len(words) - 1}
        )
    return tokens


def _tokens_plain(text: str) -> list[dict]:
    words = text.split()
    return [{"t": word, "r": "", "sp": i < len(words) - 1} for i, word in enumerate(words)]


def tokenize(text: str, lang: str | None = None) -> list[dict]:
    """Découpe une ligne en mots avec lecture latine. Ne lève jamais : repli sans romanisation."""
    text = (text or "").strip()[:MAX_LINE_LENGTH]
    if not text:
        return []
    lang = lang or detect_lang(text)
    counts = _script_counts(text)
    try:
        if lang == "ja" and (counts["kana"] or counts["han"]):
            return _tokens_ja(text)
        if lang == "zh" and counts["han"]:
            return _tokens_zh(text)
        if lang == "ko" and counts["hangul"]:
            return _tokens_ko(text)
        if lang == "other" or counts["other"]:
            return _tokens_generic(text)
    except ImportError as exc:
        logger.warning("Romanisation %s indisponible (bibliothèque manquante : %s)", lang, exc)
    except Exception:  # noqa: BLE001 - une ligne illisible ne doit jamais casser le karaoké
        logger.exception("Romanisation %s échouée pour une ligne", lang)
    return _tokens_plain(text)


def romanize_plain(text: str) -> str:
    """Texte romanisé sur une seule chaîne (sert à comparer les réponses du blind test)."""
    lang = detect_lang(text or "")
    if lang == "latin":
        return text or ""
    return " ".join((tok["r"] or tok["t"]) for tok in tokenize(text, lang))


# --------------------------------------------------------------------------------------
# Format LRC
# --------------------------------------------------------------------------------------
def _to_seconds(minutes: str, seconds: str, fraction: str | None) -> float:
    value = int(minutes) * 60 + int(seconds)
    if fraction:
        value += float(f"0.{fraction}")
    return float(value)


def _parse_words(body: str, line_start: float) -> list[tuple[float, str]] | None:
    matches = list(_WORD_STAMP_RE.finditer(body))
    if not matches:
        return None
    words: list[tuple[float, str]] = []
    head = body[: matches[0].start()]
    if head.strip():
        words.append((line_start, head))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(body)
        words.append((_to_seconds(*match.groups()), body[match.end():end]))
    return [(start, text) for start, text in words if text.strip()]


def parse_lrc(raw: str) -> list[dict]:
    """Lignes triées `{"t", "text", "words"}` (words = None ou [(début, texte)]).

    Gère plusieurs horodatages par ligne, le tag [offset:±ms] (positif = paroles plus tôt),
    ignore les métadonnées ([ar:], [ti:]…) et conserve les lignes vides (pauses instrumentales).
    """
    offset = 0.0
    entries: list[dict] = []
    for raw_line in (raw or "").splitlines():
        line = raw_line.strip().lstrip("﻿")
        if not line:
            continue
        stamps: list[float] = []
        position = 0
        while True:
            match = _STAMP_RE.match(line, position)
            if not match:
                break
            stamps.append(_to_seconds(*match.groups()))
            position = match.end()
        if not stamps:
            meta = _META_RE.match(line)
            if meta and meta.group(1).lower() == "offset":
                try:
                    offset = int(meta.group(2).strip()) / 1000.0
                except ValueError:
                    pass
            continue
        body = line[position:]
        for start in stamps:
            words = _parse_words(body, start)
            text = _WORD_STAMP_RE.sub("", body).strip()
            entries.append({"t": start, "text": text, "words": words})
    for entry in entries:
        shift = entry["t"] - offset
        if entry["words"]:
            entry["words"] = [(max(0.0, w - offset), s) for w, s in entry["words"]]
        entry["t"] = max(0.0, shift)
    entries.sort(key=lambda e: e["t"])
    return entries


# --------------------------------------------------------------------------------------
# Construction du JSON de paroles
# --------------------------------------------------------------------------------------
_VOWELS = "aeiouyàáâäèéêëìíîïòóôöùúûüāēīōū"
_VOWEL_RUN_RE = re.compile(f"[{_VOWELS}]+", re.IGNORECASE)
_SYLLABIC_N_RE = re.compile(f"n(?![{_VOWELS}])", re.IGNORECASE)


def _weight(token: dict, lang: str = "") -> float:
    """Durée relative d'un mot : nombre de syllabes (more en japonais), pas de lettres.

    « shizumu » (3 more) pèse plus que « no » (1) alors que leurs lettres seraient 7 contre 2 ;
    c'est ce qui rend le remplissage conforme à ce que le chanteur articule.
    """
    label = token["r"] or token["t"]
    if lang == "ja" and token["r"]:
        count = sum(1 for ch in label.lower() if ch in "aeiou") + len(_SYLLABIC_N_RE.findall(label))
    elif label.isascii() or token["r"]:
        count = len(_VOWEL_RUN_RE.findall(label))
    else:  # CJK ou hangul sans lecture : un caractère = une syllabe
        count = sum(1 for ch in label if ch.isalnum())
    if count:
        return float(count)
    letters = sum(1 for ch in label if ch.isalnum())
    return 1.0 if letters else 0.25


def _time_tokens(tokens: list[dict], start: float, end: float, lang: str = "") -> None:
    """Répartit [start, end] entre les mots proportionnellement à leur nombre de syllabes."""
    total = sum(_weight(tok, lang) for tok in tokens) or 1.0
    cursor = start
    for tok in tokens:
        span = (end - start) * _weight(tok, lang) / total
        tok["s"] = round(cursor, 3)
        cursor += span
        tok["e"] = round(cursor, 3)


def build_lines(raw_lrc: str, lang_hint: str | None = None) -> dict:
    """JSON final : {"synced", "lang", "lines": [{"t", "e", "tokens": [...]}]}."""
    entries = parse_lrc(raw_lrc)
    lang = lang_hint or detect_lang(" ".join(e["text"] for e in entries))
    lines: list[dict] = []
    for index, entry in enumerate(entries):
        start = entry["t"]
        following = next((e["t"] for e in entries[index + 1:] if e["t"] > start), None)
        if entry["words"]:
            tokens = []
            for word_start, word_text in entry["words"]:
                pieces = tokenize(word_text, lang)
                if not pieces:
                    continue
                pieces[-1]["sp"] = word_text != word_text.rstrip()
                pieces[0]["_ws"] = word_start
                tokens.extend(pieces)
            _apply_word_times(tokens, start, following, lang)
            end = tokens[-1]["e"] if tokens else start
            lines.append({"t": start, "e": round(end, 3), "tokens": _clean(tokens)})
            continue
        tokens = tokenize(entry["text"], lang)
        if not tokens:
            lines.append({"t": start, "e": round(following if following else start, 3), "tokens": []})
            continue
        natural = max(MIN_LINE_SPAN, sum(_weight(tok, lang) for tok in tokens) * SECONDS_PER_UNIT + 0.4)
        if following is None:
            end = start + natural
        elif following - start <= max(CONTINUOUS_GAP, natural * 2.2):
            end = following - LINE_BREATH  # chant continu : le remplissage accompagne la voix jusqu'au bout
        else:
            end = start + natural * 1.15  # long passage instrumental : on ne ralentit pas le remplissage
        end = max(end, start + 0.2)
        _time_tokens(tokens, start, end, lang)
        lines.append({"t": start, "e": round(end, 3), "tokens": tokens})
    return {"synced": bool(lines), "lang": lang, "lines": lines}


def _apply_word_times(tokens: list[dict], line_start: float, following: float | None, lang: str = "") -> None:
    """Tags par mot : chaque groupe de tokens occupe l'intervalle jusqu'au mot suivant."""
    groups: list[list[dict]] = []
    for tok in tokens:
        if "_ws" in tok or not groups:
            groups.append([])
        groups[-1].append(tok)
    for i, group in enumerate(groups):
        group_start = group[0].get("_ws", line_start)
        if i + 1 < len(groups):
            group_end = groups[i + 1][0].get("_ws", group_start + 0.4)
        else:
            weight = sum(_weight(t, lang) for t in group)
            group_end = group_start + max(0.4, weight * SECONDS_PER_UNIT)
            if following is not None:
                group_end = min(group_end, following)
        group_end = max(group_end, group_start + 0.05)
        _time_tokens(group, group_start, group_end, lang)


def _clean(tokens: list[dict]) -> list[dict]:
    for tok in tokens:
        tok.pop("_ws", None)
    return tokens


# --------------------------------------------------------------------------------------
# LRCLIB (https://lrclib.net) — API gratuite, sans clé ; appelée uniquement depuis le backend
# --------------------------------------------------------------------------------------
def _pick_synced(items: list, duration: float | None) -> str | None:
    candidates = [
        item for item in items if isinstance(item, dict) and (item.get("syncedLyrics") or "").strip()
    ]
    if not candidates:
        return None
    if duration:
        candidates.sort(key=lambda item: abs(float(item.get("duration") or 0) - duration))
    return candidates[0]["syncedLyrics"]


async def fetch_lrclib(
    client: httpx.AsyncClient,
    base_url: str,
    title: str,
    artist: str = "",
    album: str = "",
    duration: float | None = None,
) -> str | None:
    """Paroles synchronisées (texte LRC) ou None. Les erreurs réseau sont avalées et journalisées."""
    base = base_url.rstrip("/")
    try:
        if title and artist and album and duration:
            response = await client.get(
                f"{base}/api/get",
                params={
                    "track_name": title,
                    "artist_name": artist,
                    "album_name": album,
                    "duration": int(round(duration)),
                },
            )
            if response.status_code == 200:
                synced = (response.json() or {}).get("syncedLyrics")
                if synced and synced.strip():
                    return synced
        params = {"track_name": title}
        if artist:
            params["artist_name"] = artist
        response = await client.get(f"{base}/api/search", params=params)
        if response.status_code != 200:
            return None
        payload = response.json()
        return _pick_synced(payload if isinstance(payload, list) else [], duration)
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("LRCLIB indisponible pour « %s » : %s", title, exc)
        return None
