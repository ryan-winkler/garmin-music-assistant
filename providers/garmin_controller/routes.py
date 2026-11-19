"""Authenticated aiohttp route handlers for the Garmin Connect IQ controller plugin."""

from __future__ import annotations

import asyncio
import inspect
import json
import secrets
import time
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from aiohttp import web

from .domain import (
    API_PREFIX,
    API_VERSION,
    BUDGET_HEALTH,
    BUDGET_LIST,
    BUDGET_STATE,
    DEFAULT_SETTLE_TIMEOUT_MS,
    MAX_ITEMS_LIMIT,
    MAX_PLAYERS_LIMIT,
    PLUGIN_VERSION,
    ActionName,
    DomainError,
    ItemKind,
    build_error_payload,
    build_library_list_item,
    build_player_snapshot,
    build_player_summary,
    build_queue_list_item,
    effective_volume,
    encode_bounded_json,
    is_group_player,
    next_repeat_mode,
    normalize_playback_state,
    normalize_repeat_mode,
    sanitize_req_id,
    select_default_player,
    sort_players,
)

if TYPE_CHECKING:
    import logging

RouteDef = tuple[str, str, Callable[[web.Request], Awaitable[web.StreamResponse]]]


async def _maybe_await(value: Any) -> Any:
    """Await coroutines while passing through synchronous return values."""
    if inspect.isawaitable(value):
        return await value
    return value


def _load_ma_runtime() -> tuple[Any, Any, Any, Any, Any, Any]:
    """Import Music Assistant auth helpers and model enums lazily."""
    from music_assistant.controllers.webserver.helpers.auth_middleware import (  # noqa: PLC0415
        get_authenticated_user,
        has_scope,
        set_current_user,
    )
    from music_assistant_models.auth import Scope  # noqa: PLC0415
    from music_assistant_models.enums import EventType, RepeatMode  # noqa: PLC0415

    return get_authenticated_user, has_scope, set_current_user, Scope, EventType, RepeatMode


class GarminApiHandler:
    """Handles all /api/garmin/v1/* routes for Garmin Connect IQ clients."""

    def __init__(  # noqa: PLR0913
        self,
        mass: Any,
        logger: logging.Logger,
        *,
        settle_timeout_ms: int = DEFAULT_SETTLE_TIMEOUT_MS,
        preferred_player: str = "",
        auth_resolver: Callable[[web.Request], Awaitable[Any]] | None = None,
        scope_checker: Callable[[Any, Any], bool] | None = None,
        user_setter: Callable[[Any], None] | None = None,
    ) -> None:
        """
        Initialize the route handler adapter.

        :param mass: MusicAssistant core server instance.
        :param logger: Provider logger.
        :param settle_timeout_ms: Max ms to await player/queue update events after actions.
        :param preferred_player: Optional player ID or name substring prioritized by default.
        :param auth_resolver: Optional auth callable override for tests.
        :param scope_checker: Optional scope predicate override for tests.
        :param user_setter: Optional current-user context setter override for tests.
        """
        self.mass = mass
        self.logger = logger
        self.settle_timeout_ms = settle_timeout_ms
        self.preferred_player = preferred_player
        self._auth_resolver = auth_resolver
        self._scope_checker = scope_checker
        self._user_setter = user_setter
        self._ma_runtime_cache: tuple[Any, Any, Any, Any, Any, Any] | None = None

    def route_definitions(self) -> list[RouteDef]:
        """Return `(method, path, handler)` tuples registered on MA's webserver."""
        return [
            ("GET", f"{API_PREFIX}/health", self.handle_health),
            ("GET", f"{API_PREFIX}/players", self.handle_players),
            ("GET", f"{API_PREFIX}/state", self.handle_state),
            ("POST", f"{API_PREFIX}/action", self.handle_action),
            ("GET", f"{API_PREFIX}/items", self.handle_items),
        ]

    def _resolve_runtime(self) -> tuple[Any, Any, Any, Any, Any, Any]:
        """Return cached auth helpers and MA enums, honoring test overrides."""
        if self._auth_resolver and self._scope_checker and self._user_setter:
            return (self._auth_resolver, self._scope_checker, self._user_setter, None, None, None)
        if self._ma_runtime_cache is None:
            self._ma_runtime_cache = _load_ma_runtime()
        return self._ma_runtime_cache

    def _check_scope(self, user: Any, scope_name: str) -> None:
        """Raise 403 DomainError if `user` lacks `scope_name`."""
        _, check_scope, _, scope_enum, _, _ = self._resolve_runtime()
        required = getattr(scope_enum, scope_name, scope_name) if scope_enum else scope_name
        if not check_scope(user, required):
            raise DomainError(403, "forbidden", f"Missing required scope: {scope_name}")

    async def _authenticate(self, request: web.Request, scope_name: str | None) -> Any:
        """Authenticate the request and enforce `scope_name` when provided."""
        get_user, _, set_user, _, _, _ = self._resolve_runtime()
        try:
            user = await get_user(request)
        except Exception as err:
            self.logger.warning("Garmin API authentication error: %s", err)
            raise DomainError(401, "auth_failed", "Authentication failed") from err

        if not user:
            raise DomainError(401, "auth_required", "Authentication required")

        if scope_name is not None:
            self._check_scope(user, scope_name)

        set_user(user)
        return user

    def _json_response(  # noqa: PLR0913
        self,
        body: bytes,
        status: int = 200,
        *,
        req_id: str,
        route: str,
        started: float,
        username: str = "-",
        player_id: str = "-",
        truncated: bool = False,
    ) -> web.Response:
        """Build an aiohttp JSON response and emit structured operational logs."""
        duration_ms = int((time.monotonic() - started) * 1000)
        if truncated:
            self.logger.warning(
                "Garmin API truncated response req_id=%s route=%s user=%s player=%s bytes=%d",
                req_id,
                route,
                username,
                player_id,
                len(body),
            )
        elif status >= 500:
            self.logger.error(
                "Garmin API error req_id=%s route=%s status=%d user=%s player=%s ms=%d",
                req_id,
                route,
                status,
                username,
                player_id,
                duration_ms,
            )
        elif status >= 400:
            self.logger.warning(
                "Garmin API rejected req_id=%s route=%s status=%d user=%s player=%s ms=%d",
                req_id,
                route,
                status,
                username,
                player_id,
                duration_ms,
            )
        else:
            self.logger.debug(
                "Garmin API ok req_id=%s route=%s status=%d user=%s player=%s bytes=%d ms=%d",
                req_id,
                route,
                status,
                username,
                player_id,
                len(body),
                duration_ms,
            )
        return web.Response(
            body=body,
            status=status,
            content_type="application/json",
            charset="utf-8",
            headers={"X-Garmin-Req-Id": req_id},
        )

    async def _run_wrapped(
        self,
        request: web.Request,
        route: str,
        scope_name: str | None,
        budget: int,
        handler: Callable[[Any], Awaitable[tuple[dict[str, Any], str | None, str]]],
    ) -> web.Response:
        """Execute a route handler with uniform auth, error JSON, byte budgeting, and logging."""
        started = time.monotonic()
        req_id = sanitize_req_id(request.headers.get("X-Garmin-Req-Id"), secrets.token_hex(4))
        username = "-"
        player_id = "-"
        user_bound = False
        try:
            user = await self._authenticate(request, scope_name)
            user_bound = True
            username = str(getattr(user, "username", getattr(user, "user_id", "-")))
            payload, list_key, resolved_pid = await handler(user)
            player_id = resolved_pid or "-"
            body, truncated = encode_bounded_json(payload, budget, list_key=list_key)
            return self._json_response(
                body,
                200,
                req_id=req_id,
                route=route,
                started=started,
                username=username,
                player_id=player_id,
                truncated=truncated,
            )
        except DomainError as err:
            body = build_error_payload(err.code, err.message, req_id)
            return self._json_response(
                body,
                err.status,
                req_id=req_id,
                route=route,
                started=started,
                username=username,
                player_id=player_id,
            )
        except Exception:
            self.logger.exception(
                "Unhandled Garmin API exception req_id=%s route=%s", req_id, route
            )
            body = build_error_payload("internal_error", "Internal server error", req_id)
            return self._json_response(
                body,
                500,
                req_id=req_id,
                route=route,
                started=started,
                username=username,
                player_id=player_id,
            )
        finally:
            if user_bound:
                _, _, set_user, _, _, _ = self._resolve_runtime()
                set_user(None)

    def _get_all_players(self) -> list[Any]:
        """Fetch all player states from Music Assistant's PlayersController."""
        if hasattr(self.mass.players, "all_player_states"):
            return list(self.mass.players.all_player_states(return_unavailable=True))
        return list(self.mass.players.all(return_unavailable=True))

    def _get_player(self, player_id: str | None) -> Any:
        """Resolve an explicit or default Music Assistant player."""
        if player_id:
            player = (
                self.mass.players.get_player_state(player_id)
                if hasattr(self.mass.players, "get_player_state")
                else self.mass.players.get(player_id)
            )
            if player is None:
                raise DomainError(404, "player_not_found", f"Player not found: {player_id}")
            return player

        selected = select_default_player(self._get_all_players(), preferred=self.preferred_player)
        if selected is None:
            raise DomainError(404, "no_players", "No available players")
        return selected

    def _get_active_queue(self, player_id: str) -> Any | None:
        """Return the active PlayerQueue for `player_id`, or None if non-queue source."""
        if hasattr(self.mass.player_queues, "get_active_queue"):
            return self.mass.player_queues.get_active_queue(player_id)
        return self.mass.player_queues.get(player_id)

    def _parse_pagination(
        self, request: web.Request, *, default_limit: int, max_limit: int
    ) -> tuple[int, int]:
        """Parse and clamp non-negative `offset` and bounded `limit` query parameters."""
        try:
            offset = max(0, int(request.query.get("offset", "0")))
            limit = int(request.query.get("limit", str(default_limit)))
        except ValueError as err:
            raise DomainError(
                400, "invalid_pagination", "offset and limit must be integers"
            ) from err
        return offset, max(1, min(max_limit, limit))

    async def handle_health(self, request: web.Request) -> web.Response:
        """Handle GET /api/garmin/v1/health."""

        async def _op(_user: Any) -> tuple[dict[str, Any], str | None, str]:
            return (
                {
                    "ok": True,
                    "api_version": API_VERSION,
                    "plugin_version": PLUGIN_VERSION,
                    "ma_version": str(getattr(self.mass, "version", "unknown")),
                },
                None,
                "-",
            )

        return await self._run_wrapped(request, "/health", "PLAYERS_READ", BUDGET_HEALTH, _op)

    async def handle_players(self, request: web.Request) -> web.Response:
        """Handle GET /api/garmin/v1/players."""

        async def _op(_user: Any) -> tuple[dict[str, Any], str | None, str]:
            offset, limit = self._parse_pagination(
                request, default_limit=MAX_PLAYERS_LIMIT, max_limit=MAX_PLAYERS_LIMIT
            )
            ranked = sort_players(self._get_all_players(), preferred=self.preferred_player)
            page = ranked[offset : offset + limit]
            items = [
                build_player_summary(
                    player, has_queue=self._get_active_queue(str(player.player_id)) is not None
                )
                for player in page
            ]
            return (
                {
                    "ok": True,
                    "total": len(ranked),
                    "offset": offset,
                    "limit": limit,
                    "items": items,
                },
                "items",
                "-",
            )

        return await self._run_wrapped(request, "/players", "PLAYERS_READ", BUDGET_LIST, _op)

    async def handle_state(self, request: web.Request) -> web.Response:
        """Handle GET /api/garmin/v1/state."""

        async def _op(_user: Any) -> tuple[dict[str, Any], str | None, str]:
            pid = request.query.get("player_id") or None
            player = self._get_player(pid)
            resolved_id = str(player.player_id)
            queue = self._get_active_queue(resolved_id)
            return ({"ok": True, "p": build_player_snapshot(player, queue)}, None, resolved_id)

        return await self._run_wrapped(request, "/state", "PLAYERS_READ", BUDGET_STATE, _op)

    async def handle_action(self, request: web.Request) -> web.Response:
        """Handle POST /api/garmin/v1/action with auth-first check and event convergence."""

        async def _op(user: Any) -> tuple[dict[str, Any], str | None, str]:
            raw_body = await request.read()
            try:
                body = json.loads(raw_body.decode("utf-8")) if raw_body.strip() else {}
            except (UnicodeDecodeError, json.JSONDecodeError) as err:
                raise DomainError(400, "invalid_json", "Request body must be valid JSON") from err

            if not isinstance(body, dict):
                raise DomainError(400, "invalid_json", "Request body must be a JSON object")

            action_raw = str(body.get("action") or "").strip().lower()
            try:
                action = ActionName(action_raw)
            except ValueError as err:
                raise DomainError(
                    400, "invalid_action", f"Unsupported action: {action_raw}"
                ) from err

            self._check_scope(user, self._scope_for_action(action))

            pid = body.get("player_id")
            if pid is not None and not isinstance(pid, str):
                raise DomainError(400, "invalid_player_id", "player_id must be a string")

            player = self._get_player(pid)
            resolved_id = str(player.player_id)
            queue = self._get_active_queue(resolved_id)
            value = body.get("value")

            settled = await self._execute_with_settle(player, queue, action, value)
            fresh_player = (
                self.mass.players.get_player_state(resolved_id)
                if hasattr(self.mass.players, "get_player_state")
                else self.mass.players.get(resolved_id)
            ) or player
            fresh_queue = self._get_active_queue(resolved_id)
            return (
                {
                    "ok": True,
                    "settled": settled,
                    "p": build_player_snapshot(fresh_player, fresh_queue),
                },
                None,
                resolved_id,
            )

        return await self._run_wrapped(request, "/action", None, BUDGET_STATE, _op)

    def _scope_for_action(self, action: ActionName) -> str:
        """Map an action name to the exact Music Assistant API scope required."""
        if action == ActionName.FAVORITE:
            return "LIBRARY_WRITE"
        if action in {
            ActionName.PLAY_INDEX,
            ActionName.PLAY_MEDIA,
            ActionName.REPEAT,
            ActionName.SHUFFLE,
        }:
            return "QUEUES_CONTROL"
        return "PLAYERS_CONTROL"

    async def _execute_with_settle(
        self, player: Any, queue: Any | None, action: ActionName, value: Any
    ) -> bool:
        """Dispatch an action and await matching player/queue update events up to timeout."""
        resolved_id = str(player.player_id)
        queue_id = (
            str(getattr(queue, "queue_id", resolved_id)) if queue is not None else resolved_id
        )
        changed = asyncio.Event()
        unsub: Callable[[], None] | None = None

        if hasattr(self.mass, "subscribe") and action != ActionName.FAVORITE:
            _, _, _, _, event_type, _ = self._resolve_runtime()
            watched_events = (
                (event_type.PLAYER_UPDATED, event_type.QUEUE_UPDATED)
                if event_type is not None
                else ("player_updated", "queue_updated")
            )

            def _on_event(event: Any) -> None:
                obj_id = str(getattr(event, "object_id", ""))
                if obj_id in {resolved_id, queue_id}:
                    changed.set()

            unsub = self.mass.subscribe(_on_event, watched_events)

        try:
            await self._dispatch_action(player, queue, action, value)
            if unsub is None:
                return True
            try:
                await asyncio.wait_for(changed.wait(), timeout=self.settle_timeout_ms / 1000.0)
            except TimeoutError:
                return False
            else:
                return True
        finally:
            if unsub is not None:
                unsub()

    async def _dispatch_action(
        self, player: Any, queue: Any | None, action: ActionName, value: Any
    ) -> None:
        """Execute the domain action against Music Assistant's core controllers."""
        pid = str(player.player_id)
        state = normalize_playback_state(
            getattr(player, "playback_state", None) or getattr(player, "state", None)
        )
        qid = str(getattr(queue, "queue_id", pid)) if queue is not None else None
        queue_items = int(getattr(queue, "items", 0) or 0) if queue is not None else 0

        if (
            action in {ActionName.PLAY, ActionName.PLAY_PAUSE}
            and state == "idle"
            and qid
            and queue_items > 0
            and hasattr(self.mass.player_queues, "resume")
        ):
            # Resumes idle queues on background phone (Sendspin) players without unlocking.
            await _maybe_await(self.mass.player_queues.resume(qid))
            return

        simple_cmds: dict[ActionName, str] = {
            ActionName.PLAY: "cmd_play",
            ActionName.PAUSE: "cmd_pause",
            ActionName.PLAY_PAUSE: "cmd_play_pause",
            ActionName.STOP: "cmd_stop",
            ActionName.NEXT: "cmd_next_track",
            ActionName.PREVIOUS: "cmd_previous_track",
        }
        if action in simple_cmds:
            await _maybe_await(getattr(self.mass.players, simple_cmds[action])(pid))
            return
        if action in {
            ActionName.VOLUME_SET,
            ActionName.VOLUME_UP,
            ActionName.VOLUME_DOWN,
            ActionName.MUTE,
        }:
            await self._dispatch_volume_action(player, action, value)
            return
        await self._dispatch_queue_or_media_action(player, queue, qid, action, value)

    def _parse_bool_or_toggle(self, value: Any, *, current: bool, label: str) -> bool:
        """Validate strict boolean or toggle value so strings like 'false' are never truthy."""
        if value in {None, "toggle"}:
            return not current
        if isinstance(value, bool):
            return value
        raise DomainError(400, "invalid_value", f"{label} must be a boolean or 'toggle'")

    async def _dispatch_volume_action(self, player: Any, action: ActionName, value: Any) -> None:
        """Execute volume and mute actions with automatic speaker-group routing."""
        pid = str(player.player_id)
        grouped = is_group_player(player)
        if action == ActionName.VOLUME_SET:
            level = self._parse_int(value, "volume_set value", minimum=0, maximum=100)
            fn = (
                self.mass.players.cmd_group_volume
                if grouped and hasattr(self.mass.players, "cmd_group_volume")
                else self.mass.players.cmd_volume_set
            )
            await _maybe_await(fn(pid, level))
        elif action == ActionName.VOLUME_UP:
            fn = (
                self.mass.players.cmd_group_volume_up
                if grouped and hasattr(self.mass.players, "cmd_group_volume_up")
                else self.mass.players.cmd_volume_up
            )
            await _maybe_await(fn(pid))
        elif action == ActionName.VOLUME_DOWN:
            fn = (
                self.mass.players.cmd_group_volume_down
                if grouped and hasattr(self.mass.players, "cmd_group_volume_down")
                else self.mass.players.cmd_volume_down
            )
            await _maybe_await(fn(pid))
        elif action == ActionName.MUTE:
            _, current_muted = effective_volume(player, grouped=grouped)
            target = self._parse_bool_or_toggle(value, current=current_muted, label="mute value")
            fn = (
                self.mass.players.cmd_group_volume_mute
                if grouped and hasattr(self.mass.players, "cmd_group_volume_mute")
                else self.mass.players.cmd_volume_mute
            )
            await _maybe_await(fn(pid, target))

    def _resolve_repeat_target(self, queue: Any, value: Any) -> Any:
        """Resolve repeat action value to RepeatMode enum (when available) or string."""
        current_rp = normalize_repeat_mode(getattr(queue, "repeat_mode", "off"))
        if value in {None, "cycle"}:
            target = next_repeat_mode(current_rp)
        else:
            candidate = str(value).lower()
            if candidate not in {"off", "one", "all"}:
                raise DomainError(400, "invalid_repeat", f"Invalid repeat mode: {value}")
            target = candidate
        _, _, _, _, _, repeat_enum = self._resolve_runtime()
        return repeat_enum(target) if repeat_enum is not None else target

    async def _dispatch_queue_or_media_action(
        self,
        player: Any,
        queue: Any | None,
        qid: str | None,
        action: ActionName,
        value: Any,
    ) -> None:
        """Execute repeat, shuffle, seek, favorite, queue-jump, and play-media actions."""
        pid = str(player.player_id)
        if action == ActionName.SEEK:
            await _maybe_await(
                self.mass.players.cmd_seek(pid, self._resolve_seek_position(player, queue, value))
            )
            return
        if action == ActionName.FAVORITE:
            if not hasattr(self.mass.players, "add_currently_playing_to_favorites"):
                raise DomainError(400, "unsupported_action", "Favorites not supported")
            await _maybe_await(self.mass.players.add_currently_playing_to_favorites(pid))
            return
        if action == ActionName.PLAY_MEDIA:
            if not isinstance(value, str) or not value.strip():
                raise DomainError(400, "invalid_media", "play_media requires a non-empty media URI")
            await _maybe_await(self.mass.player_queues.play_media(qid or pid, value.strip()))
            return
        if qid is None:
            raise DomainError(400, "no_active_queue", "Player has no active queue")
        if action == ActionName.REPEAT:
            await _maybe_await(
                self.mass.player_queues.set_repeat(qid, self._resolve_repeat_target(queue, value))
            )
        elif action == ActionName.SHUFFLE:
            current_sh = bool(getattr(queue, "shuffle_enabled", False))
            target_sh = self._parse_bool_or_toggle(value, current=current_sh, label="shuffle value")
            await _maybe_await(self.mass.player_queues.set_shuffle(qid, target_sh))
        elif action == ActionName.PLAY_INDEX:
            idx = self._parse_int(value, "play_index value", minimum=0, maximum=100000)
            await _maybe_await(self.mass.player_queues.play_index(qid, idx))

    def _parse_int(self, value: Any, label: str, *, minimum: int, maximum: int) -> int:
        """Parse and clamp an integer action value."""
        if isinstance(value, bool) or value is None:
            raise DomainError(400, "invalid_value", f"{label} must be an integer")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as err:
            raise DomainError(400, "invalid_value", f"{label} must be an integer") from err
        return max(minimum, min(maximum, parsed))

    def _resolve_seek_position(self, player: Any, queue: Any | None, value: Any) -> int:
        """Compute clamped target seek position in seconds from absolute or relative input."""
        snap = build_player_snapshot(player, queue)
        current_el = int(snap["el"])
        duration = int(snap["du"])
        if isinstance(value, dict):
            if "position" in value:
                target = self._parse_int(
                    value["position"], "seek position", minimum=0, maximum=86400
                )
            elif "delta" in value:
                delta = self._parse_int(value["delta"], "seek delta", minimum=-3600, maximum=3600)
                target = max(0, current_el + delta)
            else:
                raise DomainError(400, "invalid_value", "seek requires delta or position")
        else:
            delta = self._parse_int(value, "seek delta", minimum=-3600, maximum=3600)
            target = max(0, current_el + delta)
        return min(target, duration) if duration > 0 else target

    async def handle_items(self, request: web.Request) -> web.Response:
        """Handle GET /api/garmin/v1/items?kind=queue|playlists|favorites."""
        kind_raw = (request.query.get("kind") or "").strip().lower()
        scope_name = "QUEUES_READ" if kind_raw == ItemKind.QUEUE else "LIBRARY_READ"

        async def _op(_user: Any) -> tuple[dict[str, Any], str | None, str]:
            try:
                kind = ItemKind(kind_raw)
            except ValueError as err:
                raise DomainError(
                    400, "invalid_kind", "kind must be queue, playlists, or favorites"
                ) from err

            offset, limit = self._parse_pagination(
                request, default_limit=10, max_limit=MAX_ITEMS_LIMIT
            )
            if kind == ItemKind.QUEUE:
                pid = request.query.get("player_id") or None
                player = self._get_player(pid)
                resolved_id = str(player.player_id)
                queue = self._get_active_queue(resolved_id)
                if queue is None:
                    return (
                        {
                            "ok": True,
                            "kind": kind.value,
                            "total": 0,
                            "offset": offset,
                            "limit": limit,
                            "cur": None,
                            "items": [],
                        },
                        "items",
                        resolved_id,
                    )
                qid = str(getattr(queue, "queue_id", resolved_id))
                raw_items = await _maybe_await(
                    self.mass.player_queues.items(qid, limit=limit, offset=offset)
                )
                cur = getattr(queue, "current_index", None)
                total = int(getattr(queue, "items", len(raw_items)) or 0)
                projected = [
                    build_queue_list_item(item, offset + idx, cur)
                    for idx, item in enumerate(raw_items)
                ]
                return (
                    {
                        "ok": True,
                        "kind": kind.value,
                        "total": total,
                        "offset": offset,
                        "limit": limit,
                        "cur": cur,
                        "items": projected,
                    },
                    "items",
                    resolved_id,
                )

            if kind == ItemKind.PLAYLISTS:
                raw_playlists = await _maybe_await(
                    self.mass.music.playlists.library_items(limit=limit, offset=offset)
                )
                total = await self._library_count(self.mass.music.playlists, raw_playlists, offset)
                return (
                    {
                        "ok": True,
                        "kind": kind.value,
                        "total": total,
                        "offset": offset,
                        "limit": limit,
                        "cur": None,
                        "items": [build_library_list_item(p) for p in raw_playlists],
                    },
                    "items",
                    "-",
                )

            # ItemKind.FAVORITES: favorite tracks paged cleanly.
            raw_favs = await _maybe_await(
                self.mass.music.tracks.library_items(favorite=True, limit=limit, offset=offset)
            )
            total = await self._library_count(
                self.mass.music.tracks, raw_favs, offset, favorite_only=True
            )
            return (
                {
                    "ok": True,
                    "kind": kind.value,
                    "total": total,
                    "offset": offset,
                    "limit": limit,
                    "cur": None,
                    "items": [build_library_list_item(item) for item in raw_favs],
                },
                "items",
                "-",
            )

        return await self._run_wrapped(request, "/items", scope_name, BUDGET_LIST, _op)

    async def _library_count(
        self,
        controller: Any,
        page_items: list[Any],
        offset: int,
        *,
        favorite_only: bool = False,
    ) -> int:
        """Return total library item count without falling back to unfiltered totals for favorites."""
        if hasattr(controller, "library_count"):
            try:
                count = await _maybe_await(controller.library_count(favorite_only=favorite_only))
                return int(count)
            except TypeError:
                if not favorite_only:
                    count = await _maybe_await(controller.library_count())
                    return int(count)
        return offset + len(page_items)
