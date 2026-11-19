"""Lifecycle, packaging, and Music Assistant Community Catalog compliance tests."""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

import pytest
from aiohttp.test_utils import TestClient, TestServer

from providers.garmin_controller import GarminControllerPlugin
from tests.conftest import FakeMass, build_auth_overrides, make_default_mass

REPO_ROOT = Path(__file__).resolve().parents[2]
PROVIDER_DIR = REPO_ROOT / "providers" / "garmin_controller"


def test_provider_directory_has_no_symlinks_or_test_pollution() -> None:
    """Community Catalog forbids symlinks and non-runtime tooling inside provider folder."""
    assert PROVIDER_DIR.is_dir()
    for path in PROVIDER_DIR.rglob("*"):
        assert not path.is_symlink(), f"Forbidden symlink inside provider dir: {path}"
        assert path.name not in {"pyproject.toml", "tests"}, f"Non-runtime artifact: {path}"


def test_manifest_meets_community_catalog_rules() -> None:
    """Validate manifest.json structure, size, domain, and multi_instance flag."""
    manifest_path = PROVIDER_DIR / "manifest.json"
    raw = manifest_path.read_bytes()
    assert len(raw) <= 16 * 1024
    manifest = json.loads(raw.decode("utf-8"))
    assert manifest["type"] == "plugin"
    assert manifest["domain"] == "garmin_controller"
    assert manifest["multi_instance"] is False
    assert manifest["requirements"] == []
    assert isinstance(manifest["codeowners"], list)
    assert 1 <= len(manifest["codeowners"]) <= 10
    assert manifest["documentation"].startswith("https://")


def test_icon_svg_is_valid_and_within_5kb() -> None:
    """Community Catalog limits icon.svg to 5 KB of safe drawing primitives."""
    icon_path = PROVIDER_DIR / "icon.svg"
    raw = icon_path.read_bytes()
    assert len(raw) <= 5 * 1024
    root = ET.fromstring(raw.decode("utf-8"))  # noqa: S314 - parsing our own repository SVG asset
    assert root.tag.endswith("svg")
    for elem in root.iter():
        tag = elem.tag.split("}")[-1].lower()
        assert tag not in {"script", "foreignobject", "image", "iframe"}


async def test_plugin_load_unload_reload_lifecycle(default_tokens: dict[str, Any]) -> None:
    """Verify routes return 200 after load, 404 after unload, and 200 again after reload."""
    mass = make_default_mass()
    plugin = GarminControllerPlugin(
        mass,
        manifest={"domain": "garmin_controller"},
        config={"settle_timeout_ms": 250, "preferred_player": "sendspin"},
    )
    await plugin.loaded_in_mass()
    assert len(mass.webserver.routes) == 5

    # Patch auth overrides onto created handler so HTTP requests work without full MA server.
    auth, has_scope, set_user, _ = build_auth_overrides(default_tokens)
    assert plugin._api_handler is not None  # noqa: SLF001
    plugin._api_handler._auth_resolver = auth  # noqa: SLF001
    plugin._api_handler._scope_checker = has_scope  # noqa: SLF001
    plugin._api_handler._user_setter = set_user  # noqa: SLF001

    server = TestServer(mass.webserver.build_app())
    client = TestClient(server)
    await client.start_server()
    try:
        headers = {"Authorization": "Bearer valid-admin-token"}
        resp = await client.get("/api/garmin/v1/health", headers=headers)
        assert resp.status == 200

        await plugin.unload()
        assert len(mass.webserver.routes) == 0
        resp_after_unload = await client.get("/api/garmin/v1/health", headers=headers)
        assert resp_after_unload.status == 404

        # Second unload must be a safe no-op.
        await plugin.unload()

        # Reload cleanly.
        await plugin.loaded_in_mass()
        assert len(mass.webserver.routes) == 5
        assert plugin._api_handler is not None  # noqa: SLF001
        plugin._api_handler._auth_resolver = auth  # noqa: SLF001
        plugin._api_handler._scope_checker = has_scope  # noqa: SLF001
        plugin._api_handler._user_setter = set_user  # noqa: SLF001
        resp_reloaded = await client.get("/api/garmin/v1/health", headers=headers)
        assert resp_reloaded.status == 200
    finally:
        await client.close()


async def test_partial_route_registration_rolls_back_cleanly() -> None:
    """Failure mid-registration must unregister any previously registered routes."""
    mass = FakeMass(
        players=[],
        queues={},
        playlists=[],
        tracks=[],
        fail_on_path="/api/garmin/v1/action",
    )
    plugin = GarminControllerPlugin(mass, manifest={}, config={})
    with pytest.raises(RuntimeError, match="Simulated registration failure"):
        await plugin.loaded_in_mass()
    assert mass.webserver.routes == {}
