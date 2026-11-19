"""Static parity, XML resource, and (:glance) isolation checks for garmin-app/."""

from __future__ import annotations

import json
import re
import struct
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
GARMIN_DIR = REPO_ROOT / "garmin-app"
SCHEMA = json.loads((REPO_ROOT / "docs" / "protocol" / "v1_schemas.json").read_text("utf-8"))


def test_garmin_xml_files_are_valid_and_target_fenix7() -> None:
    """Verify manifest.xml and all resource XMLs parse cleanly and include fenix7."""
    manifest_path = GARMIN_DIR / "manifest.xml"
    tree = ET.parse(manifest_path)  # noqa: S314 - local repository asset
    root = tree.getroot()
    ns = {"iq": "http://www.garmin.com/xml/connectiq"}
    app = root.find("iq:application", ns)
    assert app is not None
    assert app.attrib["type"] == "watch-app"
    assert app.attrib["minApiLevel"] == "4.0.0"

    products = {el.attrib["id"] for el in app.findall("iq:products/iq:product", ns)}
    assert {"fenix7", "fenix7s", "fenix7x", "fenix7pro"}.issubset(products)

    perms = {el.attrib["id"] for el in app.findall("iq:permissions/iq:uses-permission", ns)}
    assert perms == {"Communications"}

    for xml_path in (GARMIN_DIR / "resources").rglob("*.xml"):
        ET.parse(xml_path)  # noqa: S314 - local repository asset


def test_settings_enforce_safe_token_and_url_max_lengths() -> None:
    """Settings must set maxLength >= 512 on serverUrl and accessToken to prevent truncation."""
    settings_tree = ET.parse(GARMIN_DIR / "resources" / "settings" / "settings.xml")  # noqa: S314
    props_tree = ET.parse(GARMIN_DIR / "resources" / "settings" / "properties.xml")  # noqa: S314
    prop_ids = {el.attrib["id"] for el in props_tree.getroot().findall("property")}
    assert {"serverUrl", "accessToken", "preferredPlayerId", "pollIntervalSec"}.issubset(prop_ids)

    configs: dict[str, dict[str, str]] = {}
    for setting in settings_tree.getroot().findall("setting"):
        key = setting.attrib["propertyKey"].replace("@Properties.", "")
        cfg = setting.find("settingConfig")
        assert cfg is not None
        configs[key] = dict(cfg.attrib)

    assert int(configs["serverUrl"]["maxLength"]) >= 512
    assert int(configs["accessToken"]["maxLength"]) >= 512
    assert int(configs["pollIntervalSec"]["min"]) >= 5


def test_launcher_icon_is_valid_40x40_png() -> None:
    """Verify launcher_icon.png header and dimensions."""
    raw = (GARMIN_DIR / "resources" / "drawables" / "launcher_icon.png").read_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    width, height = struct.unpack(">II", raw[16:24])
    assert (width, height) == (40, 40)


def test_glance_scope_never_imports_communications() -> None:
    """GlanceView and MusicAssistantApp must stay free of Communications to stay < 24 KB RAM."""
    for name in ("GlanceView.mc", "MusicAssistantApp.mc"):
        src = (GARMIN_DIR / "source" / name).read_text("utf-8")
        assert "Toybox.Communications" not in src


def test_monkey_c_protocol_keys_match_v1_schema() -> None:
    """Ensure every PlayerSnapshot and Capability field in v1_schemas.json is parsed in Monkey C."""
    mc_src = (GARMIN_DIR / "source" / "PlaybackState.mc").read_text("utf-8")
    snapshot_keys = set(SCHEMA["$defs"]["playerSnapshot"]["required"])
    cap_keys = set(SCHEMA["$defs"]["capabilities"]["required"])
    for key in snapshot_keys | cap_keys:
        assert f'"{key}"' in mc_src, f"Protocol field {key!r} missing from PlaybackState.mc"

    api_src = (GARMIN_DIR / "source" / "ApiClient.mc").read_text("utf-8")
    for endpoint in ("/health", "/players", "/state", "/action", "/items"):
        assert endpoint in api_src, f"Endpoint {endpoint!r} missing from ApiClient.mc"


def test_monkey_c_files_have_balanced_braces_and_valid_build_script() -> None:
    """Static Monkey C -l 3 / Fenix 7 regression checks and bash -n check on build.sh."""
    for mc_path in (GARMIN_DIR / "source").rglob("*.mc"):
        text = mc_path.read_text("utf-8")
        # Strip quoted strings first (they may contain "https://"), then line comments.
        cleaned = re.sub(r'"(?:\\.|[^"\\])*"', '""', text)
        cleaned = re.sub(r"//.*", "", cleaned)
        assert cleaned.count("{") == cleaned.count("}"), f"Unbalanced braces in {mc_path.name}"
        assert cleaned.count("(") == cleaned.count(")"), f"Unbalanced parens in {mc_path.name}"
        # Monkey C const declarations forbid `as <Type>`.
        assert not re.search(r"\bconst\s+\w+\s+as\s+", cleaned), (
            f"Illegal `const ... as <Type>` in {mc_path.name}"
        )

    menus_src = (GARMIN_DIR / "source" / "Menus.mc").read_text("utf-8")
    assert "deleteItem(0) != null" not in menus_src
    assert "deleteItem(0) == true" in menus_src
    assert "MenuItem(" in menus_src
    assert ", {})" not in menus_src

    glance_src = (GARMIN_DIR / "source" / "GlanceView.mc").read_text("utf-8")
    assert "class MusicAssistantGlanceView extends WatchUi.GlanceView" in glance_src
    assert "WatchUi.GlanceView.initialize();" in glance_src

    vol_src = (GARMIN_DIR / "source" / "VolumeView.mc").read_text("utf-8")
    assert "Graphics.FONT_NUMBER_MEDIUM" not in vol_src

    api_src = (GARMIN_DIR / "source" / "ApiClient.mc").read_text("utf-8")
    assert "PersistedContent.Iterator" in api_src
    assert "typedef ApiCallback" in api_src

    result = subprocess.run(  # noqa: S603
        ["bash", "-n", str(GARMIN_DIR / "scripts" / "build.sh")],  # noqa: S607
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
