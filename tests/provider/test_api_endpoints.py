"""HTTP integration tests for all 5 /api/garmin/v1/* endpoints and listening actions."""

from __future__ import annotations

from typing import Any

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from providers.garmin_controller.routes import GarminApiHandler
from tests.conftest import FakeMass, build_auth_overrides, make_default_mass

ApiFixture = tuple[TestClient[web.Request, web.Application], FakeMass, list[Any]]

ADMIN_HEADERS = {"Authorization": "Bearer valid-admin-token", "X-Garmin-Req-Id": "req-1"}
READONLY_HEADERS = {"Authorization": "Bearer readonly-token", "X-Garmin-Req-Id": "req-ro"}


async def test_auth_required_on_all_endpoints(api_client: ApiFixture) -> None:
    """Missing or invalid Bearer token returns structured JSON 401 with req_id."""
    client, _, _ = api_client
    for method, path in (
        ("GET", "/api/garmin/v1/health"),
        ("GET", "/api/garmin/v1/players"),
        ("GET", "/api/garmin/v1/state"),
        ("POST", "/api/garmin/v1/action"),
        ("GET", "/api/garmin/v1/items?kind=playlists"),
    ):
        resp = await client.request(method, path, headers={"X-Garmin-Req-Id": "unauth-7"})
        assert resp.status == 401
        data = await resp.json()
        assert data["ok"] is False
        assert data["code"] == "auth_required"
        assert data["req_id"] == "unauth-7"


async def test_scope_enforcement_blocks_readonly_actions(
    api_client: ApiFixture,
) -> None:
    """Read-only token can fetch state/players/items but gets 403 on write actions."""
    client, _, _ = api_client
    assert (await client.get("/api/garmin/v1/health", headers=READONLY_HEADERS)).status == 200
    assert (await client.get("/api/garmin/v1/players", headers=READONLY_HEADERS)).status == 200
    assert (
        await client.get("/api/garmin/v1/items?kind=playlists", headers=READONLY_HEADERS)
    ).status == 200

    resp = await client.post(
        "/api/garmin/v1/action",
        headers=READONLY_HEADERS,
        json={"player_id": "sendspin_phone_1", "action": "play_pause"},
    )
    assert resp.status == 403
    data = await resp.json()
    assert data["ok"] is False
    assert data["code"] == "forbidden"


async def test_players_prioritize_playing_and_mobile_background_player(
    api_client: ApiFixture,
) -> None:
    """Playing mobile/Sendspin player ranks first, offline speakers are excluded."""
    client, _, _ = api_client
    resp = await client.get("/api/garmin/v1/players", headers=ADMIN_HEADERS)
    assert resp.status == 200
    data = await resp.json()
    ids = [p["id"] for p in data["items"]]
    assert "offline_bed" not in ids
    assert ids[0] == "sendspin_phone_1"
    assert data["items"][0]["ph"] is True
    assert data["items"][0]["s"] == "playing"


async def test_state_default_and_non_queue_airplay_caps(
    api_client: ApiFixture,
) -> None:
    """State selects playing mobile player by default and accurately gates non-queue caps."""
    client, _, seen_users = api_client
    resp = await client.get("/api/garmin/v1/state", headers=ADMIN_HEADERS)
    assert resp.status == 200
    snap = (await resp.json())["p"]
    assert snap["id"] == "sendspin_phone_1"
    # Emoji stripped cleanly for Garmin MIP fonts.
    assert snap["t"] == "Midnight City"
    assert snap["a"] == "M83"
    assert snap["nt"] == "Intro"
    assert snap["caps"]["q"] is True
    assert snap["caps"]["rp"] is True
    assert snap["caps"]["sh"] is True
    assert len(seen_users) >= 1

    # Non-queue AirPlay source must report q/rp/sh/fav as False.
    ap_resp = await client.get(
        "/api/garmin/v1/state?player_id=airplay_office", headers=ADMIN_HEADERS
    )
    ap_snap = (await ap_resp.json())["p"]
    assert ap_snap["t"] == "Live Radio Stream"
    assert ap_snap["a"] == "KEXP 90.3"
    assert ap_snap["caps"]["q"] is False
    assert ap_snap["caps"]["rp"] is False
    assert ap_snap["caps"]["sh"] is False
    assert ap_snap["caps"]["fav"] is False


async def test_all_listening_actions_and_idle_queue_resume(
    api_client: ApiFixture,
) -> None:
    """Exercise Play, Pause, Resume-from-idle, Next, Prev, Repeat, Shuffle, Seek, Vol, Mute, Fav."""
    client, mass, _ = api_client

    async def act(player_id: str, action: str, value: Any = None) -> dict[str, Any]:
        resp = await client.post(
            "/api/garmin/v1/action",
            headers=ADMIN_HEADERS,
            json={"player_id": player_id, "action": action, "value": value},
        )
        assert resp.status == 200, await resp.text()
        payload: dict[str, Any] = await resp.json()
        return payload

    # Play/Pause toggles playing -> paused.
    res = await act("sendspin_phone_1", "play_pause")
    assert res["settled"] is True
    assert res["p"]["s"] == "paused"

    # Stop -> idle, then play_pause resumes idle queue via player_queues.resume (background phone wake).
    await act("sendspin_phone_1", "stop")
    res = await act("sendspin_phone_1", "play_pause")
    assert res["p"]["s"] == "playing"
    assert ("resume", "sendspin_phone_1") in mass.player_queues.commands

    # Next & Previous track.
    res = await act("sendspin_phone_1", "next")
    assert res["p"]["t"] == "Intro"
    res = await act("sendspin_phone_1", "previous")
    assert res["p"]["t"] == "Midnight City"

    # Repeat cycle: off -> all -> one -> off.
    assert (await act("sendspin_phone_1", "repeat", "cycle"))["p"]["rp"] == "all"
    assert (await act("sendspin_phone_1", "repeat", "cycle"))["p"]["rp"] == "one"
    assert (await act("sendspin_phone_1", "repeat", "cycle"))["p"]["rp"] == "off"

    # Shuffle toggle.
    assert (await act("sendspin_phone_1", "shuffle", "toggle"))["p"]["sh"] is True
    assert (await act("sendspin_phone_1", "shuffle", value=False))["p"]["sh"] is False

    # Volume set / up / down / mute.
    assert (await act("sendspin_phone_1", "volume_set", 80))["p"]["v"] == 80
    assert (await act("sendspin_phone_1", "volume_up"))["p"]["v"] == 85
    assert (await act("sendspin_phone_1", "volume_down"))["p"]["v"] == 80
    assert (await act("sendspin_phone_1", "mute", "toggle"))["p"]["m"] is True

    # Seek relative and absolute.
    res = await act("sendspin_phone_1", "seek", {"position": 100})
    assert res["p"]["el"] >= 100
    res = await act("sendspin_phone_1", "seek", {"delta": -15})
    assert 80 <= res["p"]["el"] <= 90

    # Favorite current track.
    res = await act("sendspin_phone_1", "favorite")
    assert res["p"]["fav"] is True

    # Jump in queue & play playlist URI.
    res = await act("sendspin_phone_1", "play_index", 2)
    assert res["p"]["t"] == "Time"
    res = await act("sendspin_phone_1", "play_media", "library://playlist/1")
    assert (
        "play_media",
        ("sendspin_phone_1", "library://playlist/1"),
    ) in mass.player_queues.commands


async def test_group_volume_and_mute_routing(
    api_client: ApiFixture,
) -> None:
    """Speaker groups route volume and mute actions to cmd_group_volume*."""
    client, mass, _ = api_client
    resp = await client.post(
        "/api/garmin/v1/action",
        headers=ADMIN_HEADERS,
        json={"player_id": "group_home", "action": "volume_set", "value": 42},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["p"]["v"] == 42
    assert data["p"]["caps"]["grp"] is True
    assert ("group_volume", ("group_home", 42)) in mass.players.commands

    resp_mute = await client.post(
        "/api/garmin/v1/action",
        headers=ADMIN_HEADERS,
        json={"player_id": "group_home", "action": "mute", "value": True},
    )
    assert (await resp_mute.json())["p"]["m"] is True
    assert ("group_volume_mute", ("group_home", True)) in mass.players.commands


async def test_unsettled_action_returns_settled_false(default_tokens: dict[str, Any]) -> None:
    """When downstream speakers do not emit an event before timeout, settled is False."""
    mass = make_default_mass(emit_events=False)
    auth, has_scope, set_user, _ = build_auth_overrides(default_tokens)
    handler = GarminApiHandler(
        mass,
        mass.logger,
        settle_timeout_ms=50,
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
        resp = await client.post(
            "/api/garmin/v1/action",
            headers=ADMIN_HEADERS,
            json={"player_id": "sendspin_phone_1", "action": "next"},
        )
        assert resp.status == 200
        assert (await resp.json())["settled"] is False
    finally:
        await client.close()


async def test_unified_items_endpoint_queue_playlists_favorites(
    api_client: ApiFixture,
) -> None:
    """GET /items serves queue, playlists, and favorites through one uniform schema."""
    client, _, _ = api_client

    q_resp = await client.get(
        "/api/garmin/v1/items?kind=queue&player_id=sendspin_phone_1&limit=2&offset=0",
        headers=ADMIN_HEADERS,
    )
    q_data = await q_resp.json()
    assert q_data["kind"] == "queue"
    assert q_data["total"] == 3
    assert len(q_data["items"]) == 2
    assert q_data["items"][0]["c"] is True
    assert q_data["items"][0]["k"] == "0"

    p_resp = await client.get("/api/garmin/v1/items?kind=playlists", headers=ADMIN_HEADERS)
    p_data = await p_resp.json()
    assert p_data["kind"] == "playlists"
    assert p_data["items"][0]["t"] == "Morning Run"
    assert p_data["items"][0]["k"] == "library://playlist/1"

    f_resp = await client.get("/api/garmin/v1/items?kind=favorites", headers=ADMIN_HEADERS)
    f_data = await f_resp.json()
    assert f_data["kind"] == "favorites"
    assert len(f_data["items"]) == 2


async def test_malformed_requests_return_root_json_errors(
    api_client: ApiFixture,
) -> None:
    """Invalid JSON, unknown action, missing player, or bad kind never return HTML/plain text."""
    client, _, _ = api_client

    r1 = await client.post("/api/garmin/v1/action", headers=ADMIN_HEADERS, data=b"{not-json")
    assert r1.status == 400
    assert (await r1.json())["code"] == "invalid_json"

    r2 = await client.post("/api/garmin/v1/action", headers=ADMIN_HEADERS, data=b"")
    assert r2.status == 400
    assert (await r2.json())["code"] == "invalid_action"

    r3 = await client.get("/api/garmin/v1/state?player_id=does_not_exist", headers=ADMIN_HEADERS)
    assert r3.status == 404
    assert (await r3.json())["code"] == "player_not_found"

    r4 = await client.get("/api/garmin/v1/items?kind=bogus", headers=ADMIN_HEADERS)
    assert r4.status == 400
    assert (await r4.json())["code"] == "invalid_kind"

    # String "false" must be rejected with 400 instead of coerced to True.
    r5 = await client.post(
        "/api/garmin/v1/action",
        headers=ADMIN_HEADERS,
        json={"player_id": "sendspin_phone_1", "action": "mute", "value": "false"},
    )
    assert r5.status == 400
    assert (await r5.json())["code"] == "invalid_value"

    # Malicious / special-char X-Garmin-Req-Id must be sanitized cleanly without 500.
    r6 = await client.get(
        "/api/garmin/v1/health",
        headers={"Authorization": "Bearer valid-admin-token", "X-Garmin-Req-Id": "bad req!@#$%"},
    )
    assert r6.status == 200
    assert r6.headers["X-Garmin-Req-Id"] == "badreq"


async def test_write_only_token_and_group_mute_fallback(
    default_tokens: dict[str, Any],
) -> None:
    """Write-only PLAYERS_CONTROL token can run actions, and group mute falls back to volume_muted."""
    tokens = dict(default_tokens)
    tokens["write-only"] = type(default_tokens["readonly-token"])(
        user_id="u3", username="ctrl", scopes={"PLAYERS_CONTROL"}
    )
    mass = make_default_mass()
    grp = mass.players.get_player_state("group_home")
    assert grp is not None
    grp.group_volume_muted = None
    grp.volume_muted = True

    auth, has_scope, set_user, _ = build_auth_overrides(tokens)
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
        resp = await client.post(
            "/api/garmin/v1/action",
            headers={"Authorization": "Bearer write-only"},
            json={"player_id": "group_home", "action": "mute", "value": "toggle"},
        )
        assert resp.status == 200
        # Toggled True -> False using volume_muted fallback.
        assert (await resp.json())["p"]["m"] is False
    finally:
        await client.close()
