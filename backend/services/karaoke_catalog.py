"""Catalogue automatique pour le blind test : extraits de 30 s de l'API publique Deezer.

Gratuit et sans clé : la recherche, les classements et les playlists de l'API Deezer renvoient, pour
chaque titre, un extrait MP3 de 30 s (champ `preview`). On évite ainsi de remplir à la main un
dossier de musique : il suffit d'indiquer des playlists ou des recherches (voir les variables
`KARAOKE_DEEZER_*` dans `routers/activity_karaoke.py`).

Les extraits ne sont jamais lus depuis le navigateur : le backend les télécharge une fois, les garde
sur disque puis les sert lui-même (même route audio que les fichiers locaux). Les URL d'extraits
expirent au bout de quelques heures : elles sont donc redemandées à Deezer au moment du téléchargement
et jamais conservées dans le catalogue.

Ce module ne garde aucun état global : le routeur gère le cache et la concurrence.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from urllib.parse import urlparse

import httpx

logger = logging.getLogger("karaoke.catalog")

DEEZER_API = "https://api.deezer.com"
PAGE_SIZE = 100
MAX_PREVIEW_BYTES = 3_000_000  # un extrait de 30 s pèse ~500 Ko
PREVIEW_HOST_SUFFIXES = (".dzcdn.net", ".deezer.com")
PAUSE_BETWEEN_CALLS = 0.12  # l'API limite à ~50 requêtes / 5 s


def _text(value, limit: int = 200) -> str:
    return value.strip()[:limit] if isinstance(value, str) else ""


def valid_preview_url(url) -> bool:
    """Seuls des extraits servis par Deezer sont téléchargés (la valeur vient d'une réponse d'API)."""
    if not isinstance(url, str):
        return False
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host.endswith(suffix) for suffix in PREVIEW_HOST_SUFFIXES)


def parse_track(item) -> dict | None:
    """Entrée de catalogue `{id, title, title_short, artist, album}` ou None si le titre est inutilisable."""
    if not isinstance(item, dict):
        return None
    identifier = item.get("id")
    if isinstance(identifier, bool) or not isinstance(identifier, int) or identifier <= 0:
        return None
    title = _text(item.get("title"))
    if not title or not valid_preview_url(item.get("preview")):
        return None
    artist = item.get("artist") if isinstance(item.get("artist"), dict) else {}
    album = item.get("album") if isinstance(item.get("album"), dict) else {}
    return {
        "id": identifier,
        "title": title,
        "title_short": _text(item.get("title_short")) or title,
        "artist": _text(artist.get("name")),
        "album": _text(album.get("title")),
    }


async def _pages(client: httpx.AsyncClient, url: str, params: dict, limit: int) -> list[dict]:
    """Parcourt les pages d'une liste Deezer jusqu'à `limit` titres exploitables."""
    found: list[dict] = []
    index = 0
    while len(found) < limit:
        response = await client.get(url, params={**params, "index": index, "limit": min(PAGE_SIZE, limit)})
        if response.status_code != 200:
            break
        payload = response.json()
        items = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(items, list) or not items:
            break
        found.extend(entry for entry in map(parse_track, items) if entry)
        if not payload.get("next"):
            break
        index += len(items)
        await asyncio.sleep(PAUSE_BETWEEN_CALLS)
    return found[:limit]


async def build_catalog(
    client: httpx.AsyncClient,
    base_url: str,
    playlists: list[str],
    queries: list[str],
    chart: bool,
    limit: int,
    total: int,
) -> list[dict]:
    """Rassemble classement + playlists + recherches, sans doublon. Les erreurs réseau sont journalisées."""
    base = base_url.rstrip("/")
    sources: list[tuple[str, str, dict]] = []
    if chart:
        sources.append(("classement", f"{base}/chart/0/tracks", {}))
    sources += [(f"playlist {pid}", f"{base}/playlist/{pid}/tracks", {}) for pid in playlists]
    sources += [(f"recherche « {q} »", f"{base}/search", {"q": q}) for q in queries]

    catalog: dict[int, dict] = {}
    for label, url, params in sources:
        try:
            for entry in await _pages(client, url, params, limit):
                catalog.setdefault(entry["id"], entry)
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Deezer indisponible pour %s : %s", label, exc)
        if len(catalog) >= total:
            break
        await asyncio.sleep(PAUSE_BETWEEN_CALLS)
    return list(catalog.values())[:total]


async def fresh_preview_url(client: httpx.AsyncClient, base_url: str, deezer_id: int) -> str | None:
    try:
        response = await client.get(f"{base_url.rstrip('/')}/track/{int(deezer_id)}")
        if response.status_code != 200:
            return None
        url = (response.json() or {}).get("preview")
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("Extrait Deezer %s introuvable : %s", deezer_id, exc)
        return None
    return url if valid_preview_url(url) else None


async def download_preview(client: httpx.AsyncClient, url: str, target: Path) -> bool:
    """Télécharge l'extrait de façon atomique (fichier temporaire puis renommage), taille bornée."""
    if not valid_preview_url(url):
        return False
    temporary = target.with_suffix(".part")
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        size = 0
        async with client.stream("GET", url) as response:
            if response.status_code != 200:
                return False
            with temporary.open("wb") as handle:
                async for chunk in response.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_PREVIEW_BYTES:
                        raise ValueError("extrait trop volumineux")
                    handle.write(chunk)
        if size == 0:
            return False
        temporary.replace(target)
        return True
    except (httpx.HTTPError, OSError, ValueError) as exc:
        logger.warning("Téléchargement d'extrait échoué : %s", exc)
        return False
    finally:
        temporary.unlink(missing_ok=True)


def prune_previews(directory: Path, keep: int) -> None:
    """Garde les `keep` extraits les plus récents (le cache ne grossit pas indéfiniment)."""
    try:
        files = sorted(directory.glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for stale in files[keep:]:
        stale.unlink(missing_ok=True)


# --------------------------------------------------------------------------------------
# Persistance du catalogue (relu au démarrage, rafraîchi quand il est trop vieux)
# --------------------------------------------------------------------------------------
def load_catalog_file(path: Path) -> tuple[float, list[dict]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0.0, []
    if not isinstance(data, dict) or not isinstance(data.get("entries"), list):
        return 0.0, []
    entries = [entry for entry in data["entries"] if isinstance(entry, dict) and isinstance(entry.get("id"), int)]
    fetched = data.get("fetched_at")
    return (float(fetched) if isinstance(fetched, (int, float)) else 0.0), entries


def save_catalog_file(path: Path, entries: list[dict]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps({"fetched_at": time.time(), "entries": entries}), encoding="utf-8")
        temporary.replace(path)
    except OSError as exc:
        logger.warning("Catalogue non enregistré (%s) : %s", path, exc)
