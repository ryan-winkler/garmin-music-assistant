"""Protocol schema contract and worst-case UTF-8 byte-budget tests."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import jsonschema
from aiohttp.test_utils import TestClient, TestServer

from providers.garmin_controller.domain import (
    BUDGET_ERROR,
    BUDGET_HEALTH,
    BUDGET_LIST,
    BUDGET_STATE,
    sanitize_text,
)
from providers.garmin_controller.routes import GarminApiHandler
from tests.conftest import (
    FakeAlbum,
    FakeArtist,
    FakeMass,
    FakeMediaItem,
    FakePlayer,
    FakeQueue,
    FakeQueueItem,
    build_auth_overrides,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA = json.loads((REPO_ROOT / "docs" / "protocol" / "v1_schemas.json").read_text("utf-8"))
HEADERS = {"Authorization": "Bearer valid-admin-token", "X-Garmin-Req-Id": "contract-1"}


def _validate(def_name: str, payload: Any) -> None:
    """Validate payload against a named definition in docs/protocol/v1_schemas.json."""
    assert isinstance(payload, dict), "Connect IQ requires root JSON objects on every response"
    validator = jsonschema.Draft202012Validator(
        {"$ref": f"#/$defs/{def_name}", "$defs": SCHEMA["$defs"]}
    )
    validator.validate(payload)


def test_sanitize_text_strips_emoji_and_truncates_codepoints() -> None:
    """Verify 4-byte emoji removal and multi-byte UTF-8 code-point safe truncation."""
    assert sanitize_text("  Hello 🎵🔥\tWorld\n ", 40) == "Hello World"
    long_cjk = "音楽" * 40
    truncated = sanitize_text(long_cjk, 12)
    assert len(truncated) == 12
    assert truncated.endswith("...")
    truncated.encode("utf-8")


async def test_all_endpoints_conform_to_schema_and_worst_case_byte_budgets(
    default_tokens: dict[str, Any],
) -> None:
    """Stress-test every endpoint with 50 players and 200-char Unicode/emoji metadata."""
    huge_text = ("Symphony No. 9 in D Minor — Beethoven 音楽 🎼🎻🔥 " * 6)[:200]
    players = [
        FakePlayer(
            player_id=f"very_long_player_identifier_room_{i:02d}_speaker_group_master",
            display_name=f"Room {i:02d} {huge_text}",
            provider="sendspin" if i == 0 else "sonos",
            playback_state="playing" if i == 0 else "idle",
            volume_level=i % 100,
        )
        for i in range(50)
    ]
    queue_items = [
        FakeQueueItem(
            queue_item_id=f"q_{i}",
            name=huge_text,
            duration=3600,
            media_item=FakeMediaItem(
                item_id=f"t_{i}",
                uri=f"library://track/{'x' * 60}_{i}",
                name=huge_text,
                artists=[FakeArtist(huge_text)],
                album=FakeAlbum(huge_text),
                duration=3600,
                favorite=True,
            ),
        )
        for i in range(40)
    ]
    queues = {
        players[0].player_id: FakeQueue(
            queue_id=players[0].player_id,
            display_name=players[0].display_name,
            items_list=queue_items,
            current_index=0,
            repeat_mode="all",
            shuffle_enabled=True,
        )
    }
    playlists = [
        FakeMediaItem(
            item_id=f"pl_{i}",
            uri=f"library://playlist/{'p' * 80}_{i}",
            name=f"Playlist {i} {huge_text}",
            media_type="playlist",
        )
        for i in range(30)
    ]
    mass = FakeMass(
        players=players,
        queues=queues,
        playlists=playlists,
        tracks=[qi.media_item for qi in queue_items if qi.media_item is not None],
    )
    auth, has_scope, set_user, _ = build_auth_overrides(default_tokens)
    handler = GarminApiHandler(
        mass,
        mass.logger,
        settle_timeout_ms=100,
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
        checks: list[tuple[str, str, str, int, dict[str, Any] | None]] = [
            ("GET", "/api/garmin/v1/health", "healthResponse", BUDGET_HEALTH, None),
            ("GET", "/api/garmin/v1/players?limit=15", "playersResponse", BUDGET_LIST, None),
            ("GET", "/api/garmin/v1/state", "stateResponse", BUDGET_STATE, None),
            (
                "POST",
                "/api/garmin/v1/action",
                "actionResponse",
                BUDGET_STATE,
                {"player_id": players[0].player_id, "action": "repeat", "value": "cycle"},
            ),
            (
                "GET",
                f"/api/garmin/v1/items?kind=queue&player_id={players[0].player_id}&limit=12",
                "itemsResponse",
                BUDGET_LIST,
                None,
            ),
            (
                "GET",
                "/api/garmin/v1/items?kind=playlists&limit=12",
                "itemsResponse",
                BUDGET_LIST,
                None,
            ),
            (
                "GET",
                "/api/garmin/v1/items?kind=favorites&limit=12",
                "itemsResponse",
                BUDGET_LIST,
                None,
            ),
        ]
        for method, path, schema_def, budget, body in checks:
            resp = await client.request(method, path, headers=HEADERS, json=body)
            assert resp.status == 200, f"{method} {path} -> {resp.status}"
            raw = await resp.read()
            assert len(raw) <= budget, f"{path} exceeded budget: {len(raw)} > {budget}"
            parsed = json.loads(raw.decode("utf-8"))
            _validate(schema_def, parsed)

        # Error envelope check (including 3-byte UTF-8 CJK characters).
        cjk_id = "音楽" * 80
        err_resp = await client.get(f"/api/garmin/v1/state?player_id={cjk_id}", headers=HEADERS)
        err_raw = await err_resp.read()
        assert err_resp.status == 404
        assert len(err_raw) <= BUDGET_ERROR
        _validate("errorResponse", json.loads(err_raw.decode("utf-8")))
    finally:
        await client.close()
