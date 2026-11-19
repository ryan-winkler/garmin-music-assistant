"""Shared test fixtures simulating Music Assistant core controllers and dynamic webserver."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from providers.garmin_controller.routes import GarminApiHandler


@dataclass
class FakeArtist:
    """Minimal artist model."""

    name: str


@dataclass
class FakeAlbum:
    """Minimal album model."""

    name: str


@dataclass
class FakeMediaItem:
    """Minimal media item model."""

    item_id: str
    uri: str
    name: str
    media_type: str = "track"
    artists: list[FakeArtist] = field(default_factory=list)
    album: FakeAlbum | None = None
    duration: int = 210
    favorite: bool = False


@dataclass
class FakeQueueItem:
    """Minimal queue item model."""

    queue_item_id: str
    name: str
    duration: int = 210
    media_item: FakeMediaItem | None = None


@dataclass
class FakePlayerMedia:
    """Minimal external player media model (for non-queue sources like AirPlay)."""

    uri: str
    title: str = ""
    artist: str = ""
    album: str = ""
    duration: int = 0
    elapsed_time: float = 0.0
    elapsed_time_last_updated: float = field(default_factory=time.time)


@dataclass
class FakePlayer:
    """Minimal Music Assistant Player state model."""

    player_id: str
    display_name: str
    provider: str = "sonos"
    type: str = "player"
    available: bool = True
    enabled: bool = True
    playback_state: str = "idle"
    volume_level: int | None = 50
    volume_muted: bool = False
    group_volume: int | None = None
    group_volume_muted: bool | None = None
    group_members: list[str] = field(default_factory=list)
    supported_features: set[str] = field(
        default_factory=lambda: {"volume_set", "volume_mute", "seek"}
    )
    current_media: FakePlayerMedia | None = None


@dataclass
class FakeQueue:
    """Minimal Music Assistant PlayerQueue model."""

    queue_id: str
    display_name: str
    items_list: list[FakeQueueItem] = field(default_factory=list)
    current_index: int | None = 0
    repeat_mode: str = "off"
    shuffle_enabled: bool = False
    elapsed_time: float = 15.0
    elapsed_time_last_updated: float = field(default_factory=time.time)
    playback_speed: float = 1.0

    @property
    def items(self) -> int:
        """Return queue item count."""
        return len(self.items_list)

    @property
    def current_item(self) -> FakeQueueItem | None:
        """Return currently playing QueueItem."""
        if self.current_index is None or not (0 <= self.current_index < len(self.items_list)):
            return None
        return self.items_list[self.current_index]

    @property
    def next_item(self) -> FakeQueueItem | None:
        """Return upcoming QueueItem."""
        if self.current_index is None:
            return None
        nxt = self.current_index + 1
        return self.items_list[nxt] if 0 <= nxt < len(self.items_list) else None


@dataclass
class FakeEvent:
    """Minimal Music Assistant Event payload."""

    event: str
    object_id: str


@dataclass
class FakeUser:
    """Minimal authenticated Music Assistant user."""

    user_id: str
    username: str
    scopes: set[str]


class FakeDynamicWebserver:
    """Real aiohttp dynamic route dispatcher matching Music Assistant's Webserver helper."""

    def __init__(self, fail_on_path: str | None = None) -> None:
        """Initialize the dynamic route table."""
        self.routes: dict[
            tuple[str, str], Callable[[web.Request], Awaitable[web.StreamResponse]]
        ] = {}
        self.fail_on_path = fail_on_path

    def register_dynamic_route(
        self,
        path: str,
        handler: Callable[[web.Request], Awaitable[web.StreamResponse]],
        method: str = "*",
    ) -> Callable[[], None]:
        """Register a dynamic route."""
        if self.fail_on_path and path == self.fail_on_path:
            raise RuntimeError(f"Simulated registration failure on {path}")
        key = (method, path)
        if key in self.routes:
            raise RuntimeError(f"Route {path} already registered.")
        self.routes[key] = handler

        def _unreg() -> None:
            self.unregister_dynamic_route(path, method)

        return _unreg

    def unregister_dynamic_route(self, path: str, method: str = "*") -> None:
        """Unregister a dynamic route."""
        self.routes.pop((method, path), None)

    def build_app(self) -> web.Application:
        """Create an aiohttp application dispatching all registered dynamic routes."""
        app = web.Application()

        async def _dispatch(request: web.Request) -> web.StreamResponse:
            handler = self.routes.get((request.method, request.path))
            if handler is None:
                return web.Response(status=404, text="Not found")
            return await handler(request)

        app.router.add_route("*", "/{tail:.*}", _dispatch)
        return app


class FakePlayersController:
    """In-memory Music Assistant PlayersController stub."""

    def __init__(self, mass: FakeMass, players: list[FakePlayer]) -> None:
        """Initialize with a player list."""
        self._mass = mass
        self._players = {p.player_id: p for p in players}
        self.commands: list[tuple[str, Any]] = []

    def all_player_states(self, *, return_unavailable: bool = True) -> list[FakePlayer]:
        """Return all players."""
        if return_unavailable:
            return list(self._players.values())
        return [p for p in self._players.values() if p.available]

    def get_player_state(self, player_id: str) -> FakePlayer | None:
        """Return player by ID."""
        return self._players.get(player_id)

    async def cmd_play(self, player_id: str) -> None:
        """Set player to playing."""
        self.commands.append(("play", player_id))
        self._players[player_id].playback_state = "playing"
        self._mass.emit("player_updated", player_id)

    async def cmd_pause(self, player_id: str) -> None:
        """Set player to paused."""
        self.commands.append(("pause", player_id))
        self._players[player_id].playback_state = "paused"
        self._mass.emit("player_updated", player_id)

    async def cmd_play_pause(self, player_id: str) -> None:
        """Toggle play/pause."""
        self.commands.append(("play_pause", player_id))
        p = self._players[player_id]
        p.playback_state = "paused" if p.playback_state == "playing" else "playing"
        self._mass.emit("player_updated", player_id)

    async def cmd_stop(self, player_id: str) -> None:
        """Stop playback."""
        self.commands.append(("stop", player_id))
        self._players[player_id].playback_state = "idle"
        self._mass.emit("player_updated", player_id)

    async def cmd_next_track(self, player_id: str) -> None:
        """Advance queue index."""
        self.commands.append(("next", player_id))
        q = self._mass.player_queues.get_active_queue(player_id)
        if (
            q is not None
            and q.current_index is not None
            and q.current_index + 1 < len(q.items_list)
        ):
            q.current_index += 1
            q.elapsed_time = 0.0
        self._mass.emit("queue_updated", player_id)

    async def cmd_previous_track(self, player_id: str) -> None:
        """Move to previous queue index."""
        self.commands.append(("previous", player_id))
        q = self._mass.player_queues.get_active_queue(player_id)
        if q is not None and q.current_index is not None and q.current_index > 0:
            q.current_index -= 1
            q.elapsed_time = 0.0
        self._mass.emit("queue_updated", player_id)

    async def cmd_volume_set(self, player_id: str, level: int) -> None:
        """Set single-player volume."""
        self.commands.append(("volume_set", (player_id, level)))
        self._players[player_id].volume_level = level
        self._mass.emit("player_updated", player_id)

    async def cmd_volume_up(self, player_id: str) -> None:
        """Increment single-player volume."""
        self.commands.append(("volume_up", player_id))
        p = self._players[player_id]
        p.volume_level = min(100, (p.volume_level or 0) + 5)
        self._mass.emit("player_updated", player_id)

    async def cmd_volume_down(self, player_id: str) -> None:
        """Decrement single-player volume."""
        self.commands.append(("volume_down", player_id))
        p = self._players[player_id]
        p.volume_level = max(0, (p.volume_level or 0) - 5)
        self._mass.emit("player_updated", player_id)

    async def cmd_volume_mute(self, player_id: str, muted: bool) -> None:  # noqa: FBT001
        """Mute/unmute single player."""
        self.commands.append(("volume_mute", (player_id, muted)))
        self._players[player_id].volume_muted = muted
        self._mass.emit("player_updated", player_id)

    async def cmd_group_volume(self, player_id: str, level: int) -> None:
        """Set speaker group volume."""
        self.commands.append(("group_volume", (player_id, level)))
        self._players[player_id].group_volume = level
        self._mass.emit("player_updated", player_id)

    async def cmd_group_volume_up(self, player_id: str) -> None:
        """Increment group volume."""
        self.commands.append(("group_volume_up", player_id))
        p = self._players[player_id]
        p.group_volume = min(100, (p.group_volume or 0) + 5)
        self._mass.emit("player_updated", player_id)

    async def cmd_group_volume_down(self, player_id: str) -> None:
        """Decrement group volume."""
        self.commands.append(("group_volume_down", player_id))
        p = self._players[player_id]
        p.group_volume = max(0, (p.group_volume or 0) - 5)
        self._mass.emit("player_updated", player_id)

    async def cmd_group_volume_mute(self, player_id: str, muted: bool) -> None:  # noqa: FBT001
        """Mute/unmute speaker group."""
        self.commands.append(("group_volume_mute", (player_id, muted)))
        self._players[player_id].group_volume_muted = muted
        self._mass.emit("player_updated", player_id)

    async def cmd_seek(self, player_id: str, position: int) -> None:
        """Seek to position."""
        self.commands.append(("seek", (player_id, position)))
        q = self._mass.player_queues.get_active_queue(player_id)
        if q is not None:
            q.elapsed_time = float(position)
            q.elapsed_time_last_updated = time.time()
        self._mass.emit("queue_updated", player_id)

    async def add_currently_playing_to_favorites(self, player_id: str) -> None:
        """Favorite the current track."""
        self.commands.append(("favorite", player_id))
        q = self._mass.player_queues.get_active_queue(player_id)
        if q is not None and q.current_item and q.current_item.media_item:
            q.current_item.media_item.favorite = True
        self._mass.emit("queue_updated", player_id)


class FakeQueuesController:
    """In-memory Music Assistant PlayerQueuesController stub."""

    def __init__(self, mass: FakeMass, queues: dict[str, FakeQueue]) -> None:
        """Initialize with queue mapping."""
        self._mass = mass
        self._queues = queues
        self.commands: list[tuple[str, Any]] = []

    def get_active_queue(self, player_id: str) -> FakeQueue | None:
        """Return active queue for player_id."""
        return self._queues.get(player_id)

    def items(self, queue_id: str, limit: int = 500, offset: int = 0) -> list[FakeQueueItem]:
        """Return paginated queue items."""
        q = self._queues[queue_id]
        return q.items_list[offset : offset + limit]

    async def resume(self, queue_id: str) -> None:
        """Resume an idle queue."""
        self.commands.append(("resume", queue_id))
        p = self._mass.players.get_player_state(queue_id)
        if p is not None:
            p.playback_state = "playing"
        self._mass.emit("player_updated", queue_id)

    async def set_repeat(self, queue_id: str, mode: str) -> None:
        """Set repeat mode."""
        self.commands.append(("repeat", (queue_id, mode)))
        self._queues[queue_id].repeat_mode = mode
        self._mass.emit("queue_updated", queue_id)

    async def set_shuffle(self, queue_id: str, enabled: bool) -> None:  # noqa: FBT001
        """Set shuffle flag."""
        self.commands.append(("shuffle", (queue_id, enabled)))
        self._queues[queue_id].shuffle_enabled = enabled
        self._mass.emit("queue_updated", queue_id)

    async def play_index(self, queue_id: str, index: int) -> None:
        """Jump to queue index."""
        self.commands.append(("play_index", (queue_id, index)))
        self._queues[queue_id].current_index = index
        self._queues[queue_id].elapsed_time = 0.0
        p = self._mass.players.get_player_state(queue_id)
        if p is not None:
            p.playback_state = "playing"
        self._mass.emit("queue_updated", queue_id)

    async def play_media(self, queue_id: str, media: str) -> None:
        """Start playing a playlist or track URI."""
        self.commands.append(("play_media", (queue_id, media)))
        p = self._mass.players.get_player_state(queue_id)
        if p is not None:
            p.playback_state = "playing"
        self._mass.emit("queue_updated", queue_id)


class FakeLibraryDomain:
    """In-memory Music Assistant library sub-controller."""

    def __init__(self, items: list[FakeMediaItem]) -> None:
        """Initialize with items."""
        self._items = items

    async def library_items(
        self, *, favorite: bool | None = None, limit: int = 50, offset: int = 0
    ) -> list[FakeMediaItem]:
        """Return paginated items."""
        filtered = (
            [item for item in self._items if item.favorite] if favorite else list(self._items)
        )
        return filtered[offset : offset + limit]

    async def library_count(self, *, favorite_only: bool = False) -> int:
        """Return total count."""
        if favorite_only:
            return sum(1 for item in self._items if item.favorite)
        return len(self._items)


class FakeMusicController:
    """In-memory Music Assistant MusicController stub."""

    def __init__(self, playlists: list[FakeMediaItem], tracks: list[FakeMediaItem]) -> None:
        """Initialize playlists and tracks."""
        self.playlists = FakeLibraryDomain(playlists)
        self.tracks = FakeLibraryDomain(tracks)


class FakeMass:
    """In-memory MusicAssistant server stub for unit and HTTP integration tests."""

    def __init__(  # noqa: PLR0913
        self,
        players: list[FakePlayer],
        queues: dict[str, FakeQueue],
        playlists: list[FakeMediaItem],
        tracks: list[FakeMediaItem],
        *,
        emit_events: bool = True,
        fail_on_path: str | None = None,
    ) -> None:
        """Initialize the mock server."""
        self.version = "2.11.0-test"
        self.logger = logging.getLogger("test.garmin_controller")
        self.emit_events = emit_events
        self.webserver = FakeDynamicWebserver(fail_on_path=fail_on_path)
        self.players = FakePlayersController(self, players)
        self.player_queues = FakeQueuesController(self, queues)
        self.music = FakeMusicController(playlists, tracks)
        self._listeners: list[tuple[Callable[[FakeEvent], None], tuple[str, ...]]] = []

    def subscribe(
        self, callback: Callable[[FakeEvent], None], event_filter: tuple[str, ...]
    ) -> Callable[[], None]:
        """Subscribe to fake server events."""
        entry = (callback, event_filter)
        self._listeners.append(entry)

        def _unsub() -> None:
            if entry in self._listeners:
                self._listeners.remove(entry)

        return _unsub

    def emit(self, event_name: str, object_id: str) -> None:
        """Emit an event to registered listeners if enabled."""
        if not self.emit_events:
            return
        evt = FakeEvent(event=event_name, object_id=object_id)
        for cb, filt in list(self._listeners):
            if event_name in filt:
                cb(evt)


def make_default_mass(*, emit_events: bool = True) -> FakeMass:
    """Build a realistic multi-room + background phone Sendspin test server."""
    track1 = FakeMediaItem(
        item_id="t1",
        uri="library://track/1",
        name="Midnight City 🎧🔥",
        artists=[FakeArtist("M83")],
        album=FakeAlbum("Hurry Up, We're Dreaming"),
        duration=243,
        favorite=False,
    )
    track2 = FakeMediaItem(
        item_id="t2",
        uri="library://track/2",
        name="Intro",
        artists=[FakeArtist("The xx")],
        album=FakeAlbum("xx"),
        duration=127,
        favorite=True,
    )
    track3 = FakeMediaItem(
        item_id="t3",
        uri="library://track/3",
        name="Time",
        artists=[FakeArtist("Hans Zimmer")],
        album=FakeAlbum("Inception"),
        duration=275,
        favorite=True,
    )
    phone_player = FakePlayer(
        player_id="sendspin_phone_1",
        display_name="Ryan's Phone",
        provider="sendspin",
        playback_state="playing",
        volume_level=70,
        volume_muted=False,
    )
    living_room = FakePlayer(
        player_id="sonos_living",
        display_name="Living Room",
        provider="sonos",
        playback_state="paused",
        volume_level=35,
    )
    all_home_group = FakePlayer(
        player_id="group_home",
        display_name="Whole Home",
        provider="player_group",
        type="group",
        playback_state="idle",
        volume_level=40,
        group_volume=55,
        group_volume_muted=False,
        group_members=["sonos_living", "sonos_kitchen"],
    )
    airplay_no_queue = FakePlayer(
        player_id="airplay_office",
        display_name="Office AirPlay",
        provider="airplay",
        playback_state="playing",
        volume_level=50,
        current_media=FakePlayerMedia(
            uri="airplay://stream",
            title="Live Radio Stream",
            artist="KEXP 90.3",
            duration=0,
        ),
    )
    offline_speaker = FakePlayer(
        player_id="offline_bed",
        display_name="Bedroom",
        available=False,
        playback_state="idle",
    )

    queues = {
        "sendspin_phone_1": FakeQueue(
            queue_id="sendspin_phone_1",
            display_name="Ryan's Phone",
            items_list=[
                FakeQueueItem("q1", track1.name, track1.duration, track1),
                FakeQueueItem("q2", track2.name, track2.duration, track2),
                FakeQueueItem("q3", track3.name, track3.duration, track3),
            ],
            current_index=0,
            repeat_mode="off",
            shuffle_enabled=False,
            elapsed_time=30.0,
        ),
        "sonos_living": FakeQueue(
            queue_id="sonos_living",
            display_name="Living Room",
            items_list=[FakeQueueItem("ql1", track2.name, track2.duration, track2)],
            current_index=0,
        ),
        "group_home": FakeQueue(
            queue_id="group_home",
            display_name="Whole Home",
            items_list=[FakeQueueItem("qg1", track3.name, track3.duration, track3)],
            current_index=0,
        ),
    }
    playlists = [
        FakeMediaItem("p1", "library://playlist/1", "Morning Run 🏃", media_type="playlist"),
        FakeMediaItem("p2", "library://playlist/2", "Deep Focus", media_type="playlist"),
    ]
    return FakeMass(
        players=[phone_player, living_room, all_home_group, airplay_no_queue, offline_speaker],
        queues=queues,
        playlists=playlists,
        tracks=[track1, track2, track3],
        emit_events=emit_events,
    )


def build_auth_overrides(
    tokens: dict[str, FakeUser],
) -> tuple[
    Callable[[web.Request], Awaitable[FakeUser | None]],
    Callable[[Any, Any], bool],
    Callable[[Any], None],
    list[FakeUser],
]:
    """Build deterministic Bearer auth overrides for HTTP tests."""
    seen_users: list[FakeUser] = []

    async def _auth(request: web.Request) -> FakeUser | None:
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return None
        return tokens.get(header[7:].strip())

    def _has_scope(user: FakeUser, scope: Any) -> bool:
        return "*" in user.scopes or str(scope) in user.scopes

    def _set_user(user: FakeUser) -> None:
        seen_users.append(user)

    return _auth, _has_scope, _set_user, seen_users


@pytest.fixture
def default_tokens() -> dict[str, FakeUser]:
    """Return full-access and read-only test tokens."""
    return {
        "valid-admin-token": FakeUser(user_id="u1", username="ryan", scopes={"*"}),
        "readonly-token": FakeUser(
            user_id="u2",
            username="guest",
            scopes={"PLAYERS_READ", "QUEUES_READ", "LIBRARY_READ"},
        ),
    }


@pytest.fixture
async def api_client(
    default_tokens: dict[str, FakeUser],
) -> Any:
    """Yield `(TestClient, FakeMass, seen_users)` wired to GarminApiHandler."""
    mass = make_default_mass()
    auth, has_scope, set_user, seen_users = build_auth_overrides(default_tokens)
    handler = GarminApiHandler(
        mass,
        mass.logger,
        settle_timeout_ms=200,
        auth_resolver=auth,
        scope_checker=has_scope,
        user_setter=set_user,
    )
    for method, path, fn in handler.route_definitions():
        mass.webserver.register_dynamic_route(path, fn, method)

    server = TestServer(mass.webserver.build_app())
    client = TestClient(server)
    await client.start_server()
    try:
        yield client, mass, seen_users
    finally:
        await client.close()
