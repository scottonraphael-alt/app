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


# Stable IDs are shared with the host controls; labels describe thematic selections,
# not an inferred genre or original release date for every recording.
STYLES = {
    'anime': ('Animé', 'anime', ('anime', 'animé', 'アニメ', 'otaku')),
    'pop': ('Pop', 'pop', ('pop',)),
    'rock': ('Rock', 'rock', ('rock',)),
    'jpop': ('J-pop', 'jpop', ('jpop', 'j-pop', 'j pop', 'japanese pop')),
    'kpop': ('K-pop', 'kpop', ('kpop', 'k-pop', 'k pop', 'korean pop')),
    'jazz': ('Jazz', 'jazz', ('jazz',)),
    'electro': ('Électro', 'electro', ('electro', 'electronic', 'edm', 'techno', 'house')),
    'hiphop': ('Rap / Hip-hop', 'hip hop rap', ('rap', 'hip hop', 'hip-hop', 'hiphop')),
    'rnb': ('R&B', 'rnb', ('rnb', 'r&b', 'r and b', 'rhythm and blues')),
    'soul': ('Soul', 'soul', ('soul',)),
    'funk': ('Funk', 'funk', ('funk',)),
    'disco': ('Disco', 'disco', ('disco',)),
    'metal': ('Metal', 'metal', ('metal',)),
    'reggae': ('Reggae', 'reggae', ('reggae',)),
    'country': ('Country', 'country', ('country',)),
    'blues': ('Blues', 'blues', ('blues',)),
    'classical': ('Classique', 'classical', ('classical', 'classique')),
    'french': ('Chanson française', 'chanson française', ('chanson', 'francais', 'french')),
    'latin': ('Latino', 'latin', ('latin', 'latino', 'reggaeton', 'salsa')),
    'indie': ('Indie / Alternative', 'indie alternative', ('indie', 'alternative')),
}
DECADES = tuple(str(year) for year in range(1950, 2030, 10))


def category_options():
    return {'styles': [{'id': key, 'label': value[0]} for key, value in STYLES.items()],
            'decades': [{'id': year, 'label': 'Années ' + year} for year in DECADES]}


def validate_category(style, decade):
    if not isinstance(style, str) or not isinstance(decade, str) or (style and style not in STYLES) or (decade and decade not in DECADES):
        raise ValueError('Style ou décennie inconnus.')


def _themed_title(title, style, decade):
    import re
    import unicodedata
    def normalize(value):
        return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold()) if not unicodedata.combining(c))
    title = normalize(title)
    if style and not any(re.search(r'(?<!\w)' + re.escape(normalize(alias)) + r'(?!\w)', title) for alias in STYLES[style][2]):
        return False
    if decade:
        short = decade[2:]
        if not re.search(r'(?<!\d)' + re.escape(decade[:3]) + r'\d(?!\d)|(?<!\d)' + short + r"(?:\s*['’]?s|\s*['’]?\s*$|(?=\s|[.,:/-]))", title):
            return False
    return True


async def build_category(client, base_url, style='', decade='', limit=160):
    """Use matching public playlist titles, never silently fall back to global charts."""
    validate_category(style, decade)
    if not style and not decade:
        raise ValueError('Choisis un style ou une décennie.')
    query = ' '.join(part for part in (STYLES[style][1] if style else '', decade + 's' if decade else '') if part)
    base = base_url.rstrip('/')
    response = await client.get(base + '/search/playlist', params={'q': query, 'limit': 20})
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get('error'):
        raise ValueError('La sélection Deezer est indisponible.')
    playlists = payload.get('data', [])
    if not isinstance(playlists, list):
        raise ValueError('Réponse Deezer invalide.')
    found, seen = {}, set()
    for playlist in playlists:
        if not isinstance(playlist, dict):
            continue
        ident = playlist.get('id')
        if isinstance(ident, bool) or not isinstance(ident, int) or ident <= 0 or ident in seen:
            continue
        if not _themed_title(_text(playlist.get('title')), style, decade):
            continue
        seen.add(ident)
        try:
            for entry in await _pages(client, f'{base}/playlist/{ident}/tracks', {}, min(limit, 100)):
                found.setdefault(entry['id'], entry)
        except (httpx.HTTPError, ValueError):
            logger.warning('Playlist thématique Deezer %s indisponible', ident)
        if len(found) >= limit or len(seen) >= 3:
            break
        await asyncio.sleep(PAUSE_BETWEEN_CALLS)
    return list(found.values())[:limit]
