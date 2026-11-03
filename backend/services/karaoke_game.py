"""Bibliothèque musicale, comparaison des réponses et machine à états du blind test.

Aucune dépendance réseau ni asyncio ici : la partie est un objet pur, avec une horloge injectable,
ce qui permet de la tester sans WebSocket. Le routeur (`routers/activity_karaoke.py`) l'anime.

Dossier de musique : un fichier audio par morceau, avec des fichiers « compagnons » facultatifs
portant le même nom :
    Artiste - Titre.mp3
    Artiste - Titre.json   {"title", "artist", "source", "lang", "aliases", "artist_aliases",
                            "source_aliases", "album", "preview_start"}
    Artiste - Titre.lrc    paroles synchronisées (sinon récupérées sur LRCLIB)
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import random
import re
import time
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable

from services.karaoke_text import romanize_plain

logger = logging.getLogger("karaoke.game")

AUDIO_TYPES = {
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".m4a": "audio/mp4",
    ".aac": "audio/aac",
    ".flac": "audio/flac",
    ".wav": "audio/wav",
    ".webm": "audio/webm",
}
CATEGORIES = ("title", "artist", "source")
BASE_POINTS = {"title": 100, "artist": 50, "source": 50}
MAX_ALIASES = 20
MAX_TEXT = 200
MAX_GUESS_LENGTH = 120
MAX_GUESSES_PER_ROUND = 25


# --------------------------------------------------------------------------------------
# Bibliothèque
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Track:
    id: str
    name: str
    path: Path
    media_type: str
    size: int
    mtime: int
    title: str
    artist: str = ""
    source: str = ""
    album: str = ""
    lang: str | None = None
    title_answers: tuple[str, ...] = ()
    artist_answers: tuple[str, ...] = ()
    source_answers: tuple[str, ...] = ()
    lrc_path: Path | None = None
    lrc_mtime: int = 0
    preview_start: float | None = None

    def answers(self, category: str) -> tuple[str, ...]:
        return getattr(self, f"{category}_answers")

    def categories(self) -> list[str]:
        return [c for c in CATEGORIES if self.answers(c)]

    def public(self) -> dict:
        return {
            "id": self.id,
            "title": self.title,
            "artist": self.artist,
            "source": self.source,
            "lang": self.lang,
        }


def track_id(name: str, key: str) -> str:
    """Identifiant opaque : n'expose ni le nom du fichier (qui donnerait la réponse) ni son ordre."""
    return hmac.new(key.encode("utf-8"), name.encode("utf-8"), hashlib.sha256).hexdigest()[:16]


def _clean_text(value, limit: int = MAX_TEXT) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def _clean_list(value) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [_clean_text(v) for v in value[:MAX_ALIASES] if _clean_text(v)]


def _read_sidecar(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as exc:
        logger.warning("Fichier compagnon illisible (%s) : %s", path.name, exc)
        return {}
    return data if isinstance(data, dict) else {}


def _answers(primary: str, extra: list[str]) -> tuple[str, ...]:
    seen: list[str] = []
    for candidate in [primary, *extra]:
        if candidate and candidate not in seen:
            seen.append(candidate)
    return tuple(seen)


def scan_library(directory: Path, key: str) -> dict[str, Track]:
    """Tous les fichiers audio du dossier, indexés par identifiant opaque."""
    try:
        entries = sorted(directory.iterdir(), key=lambda p: p.name.lower())
    except OSError:
        return {}
    tracks: dict[str, Track] = {}
    for entry in entries:
        media_type = AUDIO_TYPES.get(entry.suffix.lower())
        if media_type is None or entry.name.startswith(".") or not entry.is_file():
            continue
        meta = _read_sidecar(entry.with_suffix(".json"))
        artist_part, sep, title_part = entry.stem.partition(" - ")
        title = _clean_text(meta.get("title")) or (title_part.strip() if sep else entry.stem)
        artist = _clean_text(meta.get("artist")) or (artist_part.strip() if sep else "")
        source = _clean_text(meta.get("source"))
        lrc = entry.with_suffix(".lrc")
        has_lrc = lrc.is_file()
        preview = meta.get("preview_start")
        stat = entry.stat()
        track = Track(
            id=track_id(entry.name, key),
            name=entry.name,
            path=entry,
            media_type=media_type,
            size=stat.st_size,
            mtime=int(stat.st_mtime),
            title=title,
            artist=artist,
            source=source,
            album=_clean_text(meta.get("album")),
            lang=_clean_text(meta.get("lang"), 8).lower() or None,
            title_answers=_answers(title, _clean_list(meta.get("aliases"))),
            artist_answers=_answers(artist, _clean_list(meta.get("artist_aliases"))),
            source_answers=_answers(source, _clean_list(meta.get("source_aliases"))),
            lrc_path=lrc if has_lrc else None,
            lrc_mtime=int(lrc.stat().st_mtime) if has_lrc else 0,
            preview_start=float(preview)
            if isinstance(preview, (int, float)) and not isinstance(preview, bool) and preview >= 0
            else None,
        )
        tracks[track.id] = track
    return tracks


# --------------------------------------------------------------------------------------
# Comparaison des réponses
# --------------------------------------------------------------------------------------
_BRACKETS_RE = re.compile(r"[\(\[（【「『].*?[\)\]）】」』]")
_SUBTITLE_RE = re.compile(r"\s[-~:–—]\s")


def _strip_latin_accents(text: str) -> str:
    """Retire les accents des lettres latines uniquement (が ne doit pas devenir か)."""
    out = []
    for ch in text:
        if unicodedata.name(ch, "").startswith("LATIN"):
            ch = "".join(c for c in unicodedata.normalize("NFD", ch) if not unicodedata.combining(c))
        out.append(ch)
    return "".join(out)


def normalize(text: str, strip_brackets: bool = True) -> str:
    value = unicodedata.normalize("NFKC", text or "").casefold()
    if strip_brackets:
        stripped = _BRACKETS_RE.sub(" ", value)
        value = stripped if stripped.strip() else value
    value = _strip_latin_accents(value)
    value = re.sub(r"[^\w\s]|_", " ", value)
    return " ".join(value.split())


def _forms(text: str) -> set[str]:
    """Formes comparables d'un texte : normalisée, sans sous-titre, et romanisée (kana/kanji → romaji)."""
    variants = {text}
    head = _SUBTITLE_RE.split(text)[0]
    if head:
        variants.add(head)
    forms: set[str] = set()
    for variant in variants:
        for candidate in (variant, romanize_plain(variant)):
            normalized = normalize(candidate)
            if normalized:
                forms.add(normalized.replace(" ", ""))  # « yoru ni kakeru » == « yorunikakeru »
    return forms


def _threshold(length: int) -> float | None:
    if length <= 4:
        return None  # titres courts : correspondance exacte uniquement
    return 0.88 if length <= 8 else 0.84


def matches(guess: str, answers: tuple[str, ...] | list[str]) -> bool:
    guess_forms = _forms(guess[:MAX_GUESS_LENGTH])
    if not guess_forms:
        return False
    for answer in answers:
        for target in _forms(answer):
            for candidate in guess_forms:
                if candidate == target:
                    return True
                limit = _threshold(len(target))
                if limit is not None and SequenceMatcher(None, candidate, target).ratio() >= limit:
                    return True
    return False


def speed_points(category: str, elapsed: float, duration: float) -> int:
    """Points de base, moitié moins si la réponse arrive à la dernière seconde."""
    ratio = 0.0 if duration <= 0 else max(0.0, min(1.0, 1 - elapsed / duration))
    return round(BASE_POINTS[category] * (0.5 + 0.5 * ratio))


# --------------------------------------------------------------------------------------
# Partie de blind test
# --------------------------------------------------------------------------------------
MIN_ROUNDS, MAX_ROUNDS, DEFAULT_ROUNDS = 1, 50, 10
MIN_SECONDS, MAX_SECONDS, DEFAULT_SECONDS = 5, 90, 20
REVEAL_SECONDS = 8


def clean_name(value) -> str:
    text = "".join(ch for ch in str(value or "") if ch.isprintable())
    return " ".join(text.split())[:32] or "Joueur"


def clamp_int(value, low: int, high: int, default: int) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return default
    return max(low, min(high, int(value)))


@dataclass
class Player:
    id: str
    name: str
    score: int = 0
    titles: int = 0
    delta: int = 0


@dataclass
class Round:
    track: Track
    started: float
    start_ratio: float
    found: dict[str, dict[str, int]] = field(default_factory=dict)  # joueur -> {catégorie: points}
    attempts: dict[str, int] = field(default_factory=dict)


@dataclass
class GuessOutcome:
    status: str  # "ok" | "wrong" | "closed" | "throttled"
    found: list[str] = field(default_factory=list)
    points: int = 0


class BlindTest:
    def __init__(
        self,
        tracks: list[Track],
        rounds: int = DEFAULT_ROUNDS,
        seconds: int = DEFAULT_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        rng: random.Random | None = None,
    ) -> None:
        self.clock = clock
        self.rng = rng or random.Random()
        playable = [t for t in tracks if t.title_answers]
        count = min(clamp_int(rounds, MIN_ROUNDS, MAX_ROUNDS, DEFAULT_ROUNDS), len(playable))
        self.queue = self.rng.sample(playable, k=count)
        self.seconds = clamp_int(seconds, MIN_SECONDS, MAX_SECONDS, DEFAULT_SECONDS)
        self.players: dict[str, Player] = {}
        self.phase = "idle"  # idle -> round -> reveal -> round … -> final
        self.index = 0  # numéro de la manche en cours (1-based)
        self.round: Round | None = None
        self.reveal_started = 0.0

    @property
    def total(self) -> int:
        return len(self.queue)

    # -- joueurs -------------------------------------------------------------------
    def player(self, user_id: str, name: str | None = None) -> Player:
        existing = self.players.get(user_id)
        if existing:
            if name:
                existing.name = clean_name(name)
            return existing
        created = Player(user_id, clean_name(name))
        self.players[user_id] = created
        return created

    # -- déroulement ---------------------------------------------------------------
    def start(self) -> bool:
        if not self.queue:
            return False
        return self._start_round()

    def _start_round(self) -> bool:
        self.index += 1
        for player in self.players.values():
            player.delta = 0
        self.round = Round(
            track=self.queue[self.index - 1],
            started=self.clock(),
            start_ratio=round(self.rng.uniform(0.15, 0.55), 3),
        )
        self.phase = "round"
        return True

    def elapsed(self) -> float:
        return max(0.0, self.clock() - self.round.started) if self.round else 0.0

    def remaining(self) -> float:
        return max(0.0, self.seconds - self.elapsed()) if self.phase == "round" else 0.0

    def reveal_remaining(self) -> float:
        if self.phase != "reveal":
            return 0.0
        return max(0.0, REVEAL_SECONDS - (self.clock() - self.reveal_started))

    def submit(self, user_id: str, name: str | None, text: str) -> GuessOutcome:
        if self.phase != "round" or self.round is None or self.remaining() <= 0:
            return GuessOutcome("closed")
        player = self.player(user_id, name)
        current = self.round
        attempts = current.attempts.get(user_id, 0)
        if attempts >= MAX_GUESSES_PER_ROUND:
            return GuessOutcome("throttled")
        current.attempts[user_id] = attempts + 1
        won = current.found.setdefault(user_id, {})
        found: list[str] = []
        points = 0
        for category in current.track.categories():
            if category in won or not matches(text, current.track.answers(category)):
                continue
            earned = speed_points(category, self.elapsed(), self.seconds)
            won[category] = earned
            found.append(category)
            points += earned
        if not found:
            return GuessOutcome("wrong")
        player.score += points
        player.delta += points
        if "title" in found:
            player.titles += 1
        return GuessOutcome("ok", found, points)

    def everyone_found_title(self, present: set[str]) -> bool:
        """Vrai quand tous les joueurs présents (inscrits) ont trouvé le titre."""
        ids = [uid for uid in present if uid in self.players]
        if self.phase != "round" or self.round is None or not ids:
            return False
        return all("title" in self.round.found.get(uid, {}) for uid in ids)

    def end_round(self) -> None:
        if self.phase == "round":
            self.phase = "reveal"
            self.reveal_started = self.clock()

    def advance(self) -> bool:
        """Manche suivante, ou écran final. Renvoie False quand la partie est terminée."""
        if self.index >= self.total:
            self.phase = "final"
            return False
        return self._start_round()

    # -- état envoyé aux clients ---------------------------------------------------
    def scores(self) -> list[dict]:
        ranked = sorted(self.players.values(), key=lambda p: (-p.score, -p.titles, p.name.lower()))
        return [
            {"id": p.id, "name": p.name, "score": p.score, "titles": p.titles, "delta": p.delta}
            for p in ranked
        ]

    def snapshot(self) -> dict:
        """Ne contient jamais la réponse tant que la manche est en cours."""
        data: dict = {
            "phase": self.phase,
            "index": self.index,
            "total": self.total,
            "seconds": self.seconds,
            "scores": self.scores(),
        }
        current = self.round
        if current is None or self.phase == "idle":
            return data
        data["round"] = {
            "audio_id": current.track.id,
            "start": current.track.preview_start,
            "start_ratio": current.start_ratio,
            "elapsed": round(self.elapsed(), 2),
            "remaining": round(self.remaining(), 2),
            "asks": current.track.categories(),
            "found": [
                {"id": uid, "name": self.players[uid].name, "categories": sorted(won)}
                for uid, won in current.found.items()
                if won and uid in self.players
            ],
        }
        if self.phase in ("reveal", "final"):
            data["round"]["answer"] = current.track.public()
            data["round"]["reveal_remaining"] = round(self.reveal_remaining(), 2)
        return data
