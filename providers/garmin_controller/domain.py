"""Domain model, serialization, and byte-budget enforcement for Garmin Connect IQ."""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

API_PREFIX = "/api/garmin/v1"
API_VERSION = 1
PLUGIN_VERSION = "0.1.0"

CONF_SETTLE_TIMEOUT_MS = "settle_timeout_ms"
CONF_PREFERRED_PLAYER = "preferred_player"
DEFAULT_SETTLE_TIMEOUT_MS = 500
MIN_SETTLE_TIMEOUT_MS = 100
MAX_SETTLE_TIMEOUT_MS = 1500

# Hard UTF-8 byte caps matching Connect IQ BLE buffer and watch heap limits.
BUDGET_HEALTH = 512
BUDGET_STATE = 1024
BUDGET_LIST = 3072
BUDGET_ERROR = 384

MAX_PLAYERS_LIMIT = 15
MAX_ITEMS_LIMIT = 12

MAX_PLAYER_NAME = 24
MAX_TITLE = 48
MAX_ARTIST = 36
MAX_ALBUM = 36
MAX_NEXT_TITLE = 36
MAX_ITEM_TITLE = 40
MAX_ITEM_SUB = 28
MAX_ERROR_TEXT = 120

MOBILE_PLAYER_PROVIDERS = frozenset({"sendspin", "builtin_player"})
MOBILE_NAME_HINTS = ("phone", "iphone", "pixel", "android", "mobile", "companion", "web player")

_REPEAT_CYCLE: dict[str, str] = {
    "off": "all",
    "all": "one",
    "one": "off",
}
_PLAYBACK_RANK: dict[str, int] = {
    "playing": 0,
    "paused": 1,
    "idle": 2,
}
_WS_RE = re.compile(r"\s+")
_REQ_ID_RE = re.compile(r"[^A-Za-z0-9_.-]")


class ActionName(StrEnum):
    """Supported wrist playback and queue actions."""

    PLAY = "play"
    PAUSE = "pause"
    PLAY_PAUSE = "play_pause"
    STOP = "stop"
    NEXT = "next"
    PREVIOUS = "previous"
    REPEAT = "repeat"
    SHUFFLE = "shuffle"
    VOLUME_SET = "volume_set"
    VOLUME_UP = "volume_up"
    VOLUME_DOWN = "volume_down"
    MUTE = "mute"
    SEEK = "seek"
    FAVORITE = "favorite"
    PLAY_INDEX = "play_index"
    PLAY_MEDIA = "play_media"


class ItemKind(StrEnum):
    """Supported paginated list kinds for GET /items."""

    QUEUE = "queue"
    PLAYLISTS = "playlists"
    FAVORITES = "favorites"


@dataclass(frozen=True, slots=True)
class DomainError(Exception):
    """Structured domain error mapped to a compact JSON HTTP error response."""

    status: int
    code: str
    message: str


def sanitize_req_id(raw: str | None, fallback: str) -> str:
    """Sanitize X-Garmin-Req-Id to strict printable ASCII safe for HTTP headers and logs."""
    cleaned = _REQ_ID_RE.sub("", raw or "")[:32]
    return cleaned or fallback


def sanitize_text(value: Any, max_chars: int) -> str:
    """Strip glyphs Garmin MIP fonts cannot render and truncate safely on code points."""
    if value is None:
        return ""
    raw = str(value)
    # Remove control characters and supplementary-plane glyphs (4-byte UTF-8 emoji)
    # that render as missing-glyph boxes on Garmin MIP displays and waste byte budget.
    cleaned = "".join(ch for ch in raw if 0x20 <= ord(ch) <= 0xFFFF)
    collapsed = _WS_RE.sub(" ", cleaned).strip()
    if len(collapsed) <= max_chars:
        return collapsed
    if max_chars <= 3:
        return collapsed[:max_chars]
    return f"{collapsed[: max_chars - 3].rstrip()}..."


def truncate_utf8(text: str, max_bytes: int) -> str:
    """Truncate text so its UTF-8 encoding never exceeds `max_bytes` without splitting code points."""
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    if max_bytes <= 3:
        return encoded[:max_bytes].decode("utf-8", errors="ignore")
    cut = encoded[: max_bytes - 3].decode("utf-8", errors="ignore").rstrip()
    return f"{cut}..."


def _enum_str(value: Any, default: str) -> str:
    """Normalize StrEnum or string attribute values to lowercase strings."""
    if value is None:
        return default
    raw = getattr(value, "value", value)
    text = str(raw).lower()
    return text or default


def _raw_playback_state(player: Any) -> Any:
    """Read playback_state with fallback to MA 2.x legacy Player.state attribute."""
    state = getattr(player, "playback_state", None)
    return state if state is not None else getattr(player, "state", None)


def normalize_playback_state(value: Any) -> str:
    """Normalize Music Assistant PlaybackState to playing, paused, or idle."""
    state = _enum_str(value, "idle")
    return state if state in _PLAYBACK_RANK else "idle"


def normalize_repeat_mode(value: Any) -> str:
    """Normalize Music Assistant RepeatMode to off, one, or all."""
    mode = _enum_str(value, "off")
    return mode if mode in _REPEAT_CYCLE else "off"


def next_repeat_mode(current: str) -> str:
    """Return the next repeat mode in the off -> all -> one -> off cycle."""
    return _REPEAT_CYCLE.get(normalize_repeat_mode(current), "all")


def is_group_player(player: Any) -> bool:
    """Return True if the player represents a speaker group or sync leader."""
    player_type = _enum_str(getattr(player, "type", None), "player")
    members = getattr(player, "group_members", None) or ()
    return player_type == "group" or len(members) > 1


def is_mobile_player(player: Any) -> bool:
    """Return True if the player appears to be a background phone/mobile client."""
    provider = _enum_str(getattr(player, "provider", None), "")
    if provider in MOBILE_PLAYER_PROVIDERS:
        return True
    name = str(getattr(player, "display_name", None) or getattr(player, "name", "")).lower()
    return any(hint in name for hint in MOBILE_NAME_HINTS)


def _player_name(player: Any) -> str:
    """Extract display name from a Music Assistant player object."""
    return str(
        getattr(player, "display_name", None)
        or getattr(player, "name", None)
        or getattr(player, "player_id", "Player")
    )


def _join_artists(artists: Any) -> str:
    """Join an iterable of Music Assistant Artist objects or strings."""
    if not artists:
        return ""
    return ", ".join(str(getattr(a, "name", a)) for a in artists if getattr(a, "name", a))


def effective_volume(player: Any, *, grouped: bool) -> tuple[int | None, bool]:
    """Read effective volume (0..100 or None) and mute state, respecting speaker groups."""
    vol = getattr(player, "group_volume", None) if grouped else None
    if vol is None:
        vol = getattr(player, "volume_level", None)
    muted = getattr(player, "group_volume_muted", None) if grouped else None
    if muted is None:
        muted = getattr(player, "volume_muted", False)
    clamped = max(0, min(100, round(vol))) if vol is not None else None
    return clamped, bool(muted)


def _player_features(player: Any) -> set[str]:
    """Return lowercase PlayerFeature names supported by the player."""
    raw = getattr(player, "supported_features", None) or ()
    return {_enum_str(feat, "") for feat in raw}


def sort_players(players: list[Any], preferred: str = "") -> list[Any]:
    """
    Filter to available enabled players and sort deterministically.

    Order: playing > paused > idle, preferred player first, mobile/Sendspin players next,
    then alphabetical display name.
    """
    pref = preferred.strip().lower()
    usable = [p for p in players if getattr(p, "available", False) and getattr(p, "enabled", True)]

    def _key(player: Any) -> tuple[int, int, int, str]:
        state = normalize_playback_state(_raw_playback_state(player))
        pid = str(getattr(player, "player_id", "")).lower()
        name = _player_name(player).lower()
        pref_rank = 0 if (pref and (pid == pref or pref in name)) else 1
        mob_rank = 0 if is_mobile_player(player) else 1
        return (_PLAYBACK_RANK[state], pref_rank, mob_rank, name)

    return sorted(usable, key=_key)


def select_default_player(players: list[Any], preferred: str = "") -> Any | None:
    """Pick the best default player when the watch does not specify player_id."""
    ranked = sort_players(players, preferred=preferred)
    return ranked[0] if ranked else None


def build_player_summary(player: Any, *, has_queue: bool) -> dict[str, Any]:
    """Project a Music Assistant player into a compact summary dict."""
    grouped = is_group_player(player)
    vol, muted = effective_volume(player, grouped=grouped)
    return {
        "id": str(getattr(player, "player_id", "")),
        "n": sanitize_text(_player_name(player), MAX_PLAYER_NAME),
        "s": normalize_playback_state(_raw_playback_state(player)),
        "v": vol,
        "m": muted,
        "g": grouped,
        "q": has_queue,
        "ph": is_mobile_player(player),
    }


def _compute_elapsed(player: Any, queue: Any | None, duration: int) -> int:
    """Compute corrected elapsed seconds using wall-clock delta while playing."""
    source = queue if queue is not None else getattr(player, "current_media", None)
    raw_elapsed = getattr(source, "elapsed_time", None) if source is not None else None
    if raw_elapsed is None:
        return 0
    calc = float(raw_elapsed)
    state = normalize_playback_state(_raw_playback_state(player))
    last_updated = getattr(source, "elapsed_time_last_updated", None)
    speed = float(getattr(queue, "playback_speed", 1.0) or 1.0) if queue is not None else 1.0
    if state == "playing" and last_updated:
        calc += max(0.0, time.time() - float(last_updated)) * speed
    elapsed = max(0, int(calc))
    return min(elapsed, duration) if duration > 0 else elapsed


def _extract_next_title(queue: Any | None) -> str:
    """Extract upcoming track title from the queue if available."""
    next_item = getattr(queue, "next_item", None) if queue is not None else None
    if next_item is None:
        return ""
    next_media = getattr(next_item, "media_item", None)
    raw = (
        getattr(next_media, "name", None)
        if next_media is not None
        else getattr(next_item, "name", "")
    )
    return sanitize_text(raw or "", MAX_NEXT_TITLE)


def _extract_media_fields(
    player: Any, queue: Any | None
) -> tuple[str, str, str, int, int, bool, str]:
    """Extract sanitized (title, artist, album, elapsed, duration, favorite, next_title)."""
    current_item = getattr(queue, "current_item", None) if queue is not None else None
    media_item = getattr(current_item, "media_item", None) if current_item is not None else None
    current_media = getattr(player, "current_media", None)

    album_obj = getattr(media_item, "album", None)
    title = (
        (getattr(media_item, "name", None) if media_item is not None else None)
        or (getattr(current_item, "name", None) if current_item is not None else None)
        or (getattr(current_media, "title", None) if current_media is not None else None)
        or ""
    )
    artist = (
        _join_artists(getattr(media_item, "artists", None))
        or (getattr(current_media, "artist", None) if current_media is not None else None)
        or ""
    )
    album = (
        (getattr(album_obj, "name", None) if album_obj is not None else None)
        or (getattr(current_media, "album", None) if current_media is not None else None)
        or ""
    )
    duration = max(
        0,
        int(
            (getattr(media_item, "duration", None) if media_item is not None else None)
            or (getattr(current_item, "duration", None) if current_item is not None else None)
            or (getattr(current_media, "duration", None) if current_media is not None else None)
            or 0
        ),
    )
    favorite = bool(getattr(media_item, "favorite", False)) if media_item is not None else False
    elapsed = _compute_elapsed(player, queue, duration)

    return (
        sanitize_text(title, MAX_TITLE),
        sanitize_text(artist, MAX_ARTIST),
        sanitize_text(album, MAX_ALBUM),
        elapsed,
        duration,
        favorite,
        _extract_next_title(queue),
    )


def build_player_snapshot(player: Any, queue: Any | None) -> dict[str, Any]:
    """Project a Music Assistant player and optional active queue into a compact snapshot."""
    grouped = is_group_player(player)
    vol, muted = effective_volume(player, grouped=grouped)
    features = _player_features(player)
    has_queue = queue is not None
    title, artist, album, elapsed, duration, favorite, next_title = _extract_media_fields(
        player, queue
    )

    repeat_mode = (
        normalize_repeat_mode(getattr(queue, "repeat_mode", "off")) if has_queue else "off"
    )
    shuffle_enabled = bool(getattr(queue, "shuffle_enabled", False)) if has_queue else False

    can_vol = grouped or ("volume_set" in features) or (vol is not None)
    can_mute = grouped or ("volume_mute" in features)
    can_seek = ("seek" in features) or (has_queue and duration > 0)
    can_fav = has_queue and getattr(queue, "current_item", None) is not None

    return {
        "id": str(getattr(player, "player_id", "")),
        "n": sanitize_text(_player_name(player), MAX_PLAYER_NAME),
        "s": normalize_playback_state(_raw_playback_state(player)),
        "v": vol,
        "m": muted,
        "t": title,
        "a": artist,
        "al": album,
        "el": elapsed,
        "du": duration,
        "rp": repeat_mode,
        "sh": shuffle_enabled,
        "fav": favorite,
        "nt": next_title,
        "caps": {
            "vol": can_vol,
            "mute": can_mute,
            "seek": can_seek,
            "q": has_queue,
            "rp": has_queue,
            "sh": has_queue,
            "fav": can_fav,
            "grp": grouped,
        },
    }


def build_queue_list_item(item: Any, index: int, current_index: int | None) -> dict[str, Any]:
    """Project a QueueItem into a compact unified list item."""
    media_item = getattr(item, "media_item", None)
    title = (getattr(media_item, "name", None) if media_item is not None else None) or getattr(
        item, "name", ""
    )
    artist = _join_artists(getattr(media_item, "artists", None)) if media_item is not None else ""
    return {
        "k": str(index),
        "t": sanitize_text(title or f"Track {index + 1}", MAX_ITEM_TITLE),
        "sub": sanitize_text(artist, MAX_ITEM_SUB),
        "c": current_index is not None and index == current_index,
    }


def build_library_list_item(item: Any) -> dict[str, Any]:
    """Project a Playlist, Track, Album, or Radio item into a compact unified list item."""
    uri = str(getattr(item, "uri", "") or getattr(item, "item_id", ""))
    title = getattr(item, "name", "") or "Untitled"
    media_type = _enum_str(getattr(item, "media_type", None), "")
    sub = _join_artists(getattr(item, "artists", None)) or media_type.capitalize()
    return {
        "k": uri,
        "t": sanitize_text(title, MAX_ITEM_TITLE),
        "sub": sanitize_text(sub, MAX_ITEM_SUB),
        "c": False,
    }


def _compact_dumps(payload: dict[str, Any]) -> bytes:
    """Encode payload to minimal UTF-8 JSON bytes without extra whitespace."""
    return json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _shrink_scalar_payload(working: dict[str, Any], raw: bytes, budget: int) -> tuple[bytes, bool]:
    """Progressively truncate snapshot or error strings by UTF-8 bytes until within `budget`."""
    truncated = False
    if "p" in working and isinstance(working["p"], dict):
        snap = dict(working["p"])
        for max_bytes in (24, 12, 0):
            for field in ("al", "nt", "a", "t", "n"):
                if len(raw) <= budget:
                    return raw, truncated
                snap[field] = truncate_utf8(str(snap.get(field, "")), max_bytes)
                working["p"] = snap
                raw = _compact_dumps(working)
                truncated = True
    elif "error" in working and isinstance(working["error"], str):
        for max_bytes in (120, 64, 32):
            if len(raw) <= budget:
                break
            working["error"] = truncate_utf8(working["error"], max_bytes)
            raw = _compact_dumps(working)
            truncated = True
    return raw, truncated


def encode_bounded_json(
    payload: dict[str, Any], budget: int, list_key: str | None = None
) -> tuple[bytes, bool]:
    """
    Encode payload to UTF-8 JSON guaranteed to stay within `budget` bytes.

    Copies `payload` before any trimming so callers' dicts are never mutated.
    """
    working = dict(payload)
    raw = _compact_dumps(working)
    if len(raw) <= budget:
        return raw, False

    truncated = False
    if list_key and isinstance(working.get(list_key), list):
        items = list(working[list_key])
        while items and len(raw) > budget:
            items.pop()
            working[list_key] = items
            if "limit" in working:
                working["limit"] = max(1, len(items))
            raw = _compact_dumps(working)
            truncated = True
        if not items and "total" in working and "offset" in working:
            working["total"] = int(working["offset"])
            raw = _compact_dumps(working)
        if len(raw) <= budget:
            return raw, truncated

    raw, scalar_truncated = _shrink_scalar_payload(working, raw, budget)
    return raw, truncated or scalar_truncated


def build_error_payload(code: str, message: str, req_id: str) -> bytes:
    """Build a strictly bounded root JSON error envelope (<= BUDGET_ERROR bytes)."""
    payload: dict[str, Any] = {
        "ok": False,
        "code": sanitize_text(code, 32) or "error",
        "error": sanitize_text(message, MAX_ERROR_TEXT) or "Request failed",
        "req_id": sanitize_req_id(req_id, "0"),
    }
    raw, _ = encode_bounded_json(payload, BUDGET_ERROR)
    return raw
