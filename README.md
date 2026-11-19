# Garmin Connect IQ Controller for Music Assistant

> [!WARNING]
> **Experimental / Work in Progress — Not Finished.**
> This project is under active early development. The Python Music Assistant plugin (`providers/garmin_controller/`) has passing automated unit and contract tests against a mocked Music Assistant runtime, while the Garmin Connect IQ Monkey C watch app (`garmin-app/`) has **not yet been compiled with `monkeyc` or verified on physical Fenix 7 hardware**. Expect breaking changes until a tagged `v1.0.0` release.

Control **Music Assistant** playback — including background playback on your phone (via Music Assistant Companion / Sendspin) and multi-room home speakers (Sonos, AirPlay, Chromecast, Squeezebox, Snapcast) — directly from a **Garmin Fenix 7** (or other Connect IQ 4.0+ watches).

---

## Status

| Component | Path | Status | Verification |
| :--- | :--- | :--- | :--- |
| **Music Assistant Plugin** | `providers/garmin_controller/` | Alpha / Experimental | 23 pytest unit & schema contract tests, `ruff`, `mypy`, `codespell` pass |
| **Garmin Watch App (Fenix 7+)** | `garmin-app/` | Uncompiled / Experimental | Static XML, PNG, schema-parity, and Monkey C checks pass; awaiting `monkeyc` & on-watch testing |

---

## What This App Is (and Is Not)

* **Remote Controller:** Sends authenticated HTTPS commands over Bluetooth through Garmin Connect on your paired phone to Music Assistant. Controls background Music Assistant playback on your phone (Sendspin / Companion player) as well as any home speaker or speaker group managed by Music Assistant.
* **Not an Offline Audio Player:** Unlike `SubMusic` or `YuMusic` (Garmin Audio Content Providers for Subsonic), this app does **not** download or store audio files on watch flash storage (exporting audio files violates Music Assistant Community Catalog rules), and it cannot replace Garmin's built-in workout Music widget.
* **Phone Background Apps:** Controls Music Assistant's Sendspin / mobile background player (including waking and resuming idle queues without unlocking your phone). Connect IQ Watch Apps have no OS API to send raw Bluetooth AVRCP commands to arbitrary non-Music-Assistant phone apps — Garmin's built-in "Control Phone" widget handles raw AVRCP.

---

## Features

* **Full Wrist Listening Controls:** Play, Pause, Resume idle queue, Stop, Next Track, Previous Track, Repeat cycle (`Off` / `All` / `One`), Shuffle toggle, Volume Up/Down/Mute (group-volume aware), Seek (`+15s` / `-15s`), Favorite current track.
* **Player & Library Control:** Switch active player or speaker group (prioritizes active & phone/Sendspin players), browse Queue and jump directly to any track, quick-start Library Playlists and Favorite Tracks.
* **Fenix 7 First-Class Ergonomics:** 100% operable via the 5 physical buttons when touch is off, plus additive touchscreen tap zones when touch is on, rendered in high-contrast 64-color MIP layout.
* **Offline-Only Glance (`< 24 KB` RAM):** Reads cached playback state from `Application.Storage` with zero network calls or battery-draining background polling; pressing launches the live controller.
* **Built-In Diagnostics:** Staged connection test (Settings/HTTPS -> Phone BLE -> `/api/garmin/v1/health`) and 8-entry error log mapping Connect IQ and HTTP status codes to plain-English fixes.
* **Watch-Safe Wire Protocol (`/api/garmin/v1/*`):** Every response is a flat root JSON object under strict UTF-8 byte caps (`<= 512 B` health, `<= 1024 B` state/action, `<= 3072 B` paginated lists, `<= 384 B` errors) with server-side emoji/glyph stripping and 500 ms event-bus convergence so actions return fresh state in one BLE round-trip.

---

## Architecture

```text
Garmin Fenix 7 (Connect IQ Watch App + Offline Glance)
  │  BLE (single-flight JSON <= 3 KB, 350ms volume/seek debounce)
  ▼
Paired Phone (Garmin Connect BLE proxy + Connect IQ Store settings)
  │  Trusted HTTPS (Authorization: Bearer <MA long-lived token>)
  ▼
HTTPS Reverse Proxy (Tailscale Serve/Funnel, Caddy/Nginx Let's Encrypt, Cloudflare Tunnel)
  │  LAN HTTP :8095
  ▼
Music Assistant Server ──▶ providers/garmin_controller (/api/garmin/v1/*)
  │  Auth + Scope Check + 500ms Event Convergence
  ▼
Music Assistant Core Controllers & Speakers (Phone Sendspin, Sonos, AirPlay, Cast, etc.)
```

### Repository Layout

* `providers/garmin_controller/` — Self-contained Music Assistant plugin (`__init__.py`, `domain.py`, `routes.py`, `manifest.json`, `icon.svg`, `strings.json`). Zero symlinks, zero tests or dev tooling inside the runtime package.
* `garmin-app/` — Connect IQ Monkey C watch app (`manifest.xml`, `monkey.jungle`, `source/`, `resources/`, `scripts/build.sh`, `store/listing.md`).
* `docs/protocol/` — Versioned wire protocol spec ([v1.md](docs/protocol/v1.md)) and JSON Schemas ([v1_schemas.json](docs/protocol/v1_schemas.json)).
* `docs/user/` — End-user setup guides ([music-assistant-setup.md](docs/user/music-assistant-setup.md), [garmin-setup.md](docs/user/garmin-setup.md)).
* `docs/design/` — EGM brainstorm brief and technical design document.
* `tests/` — Python provider lifecycle, API, and schema/byte-budget contract tests.

---

## Fenix 7 Controls

| Physical Button (Touch OFF / ON) | Touch Zone (Touch ON) | Action |
| :--- | :--- | :--- |
| **START / STOP** (`KEY_ENTER`) | Middle-center | Play / Pause (resumes idle queue) |
| **DOWN** | Middle-right | Next Track |
| **UP** | Middle-left | Previous Track |
| **Hold UP** (`MENU`) | Bottom-right | Controls Menu (Volume, Repeat, Shuffle, Seek, Favorite, Players, Queue, Playlists, Favorites, Stop, Refresh, Diagnostics) |
| — | Top strip (Player Name) | Switch Player / Group |
| — | Bottom-left | Dedicated Volume Screen (`UP`/`DOWN` +/-, `START` Mute, `BACK` Close) |
| **BACK** | — | Back / Exit |

---

## Setup

1. **Install the Music Assistant Plugin & Expose HTTPS:** Follow [docs/user/music-assistant-setup.md](docs/user/music-assistant-setup.md).
   * Requires publicly trusted HTTPS targeting Music Assistant port `8095` directly (Tailscale Serve/Funnel, Let's Encrypt reverse proxy, or Cloudflare Tunnel without a browser login wall). Plain `http://` and Home Assistant Ingress URLs do not work on physical Garmin watches.
   * Create a long-lived access token in Music Assistant (**Settings -> Profile**).
2. **Install & Configure on Fenix 7:** Follow [docs/user/garmin-setup.md](docs/user/garmin-setup.md).
   * Enter your HTTPS URL and token in the **Connect IQ Store** mobile app (or Garmin Express).

---

## How to Test

### 1. Run Python Plugin & Protocol Contract Tests (Runs Immediately)
```bash
uv sync
uv run pytest -v
uv run ruff format --check .
uv run ruff check .
uv run mypy
uv run codespell
```

### 2. Test the Plugin Live Against Your Music Assistant Server
Copy `providers/garmin_controller/` into your Music Assistant custom providers folder, restart Music Assistant, enable **Garmin Connect IQ Controller**, and verify with `curl`:
```bash
export MA_URL="https://your-ma-host.example.com"
export MA_TOKEN="your-long-lived-token"

curl -sS -H "Authorization: Bearer $MA_TOKEN" "$MA_URL/api/garmin/v1/health"
curl -sS -H "Authorization: Bearer $MA_TOKEN" "$MA_URL/api/garmin/v1/players"
curl -sS -H "Authorization: Bearer $MA_TOKEN" "$MA_URL/api/garmin/v1/state"
curl -sS -X POST -H "Authorization: Bearer $MA_TOKEN" -H "Content-Type: application/json" \
  -d '{"action":"repeat","value":"cycle"}' "$MA_URL/api/garmin/v1/action"
```

### 3. Compile & Test in the Garmin Connect IQ Simulator (No Watch Required)
Install the headless Connect IQ SDK CLI (requires Go, Java 21, and a free Garmin Developer account):
```bash
go install github.com/lindell/connect-iq-sdk-manager-cli@latest
export PATH="$HOME/go/bin:$PATH"
connect-iq-sdk-manager-cli agreement accept
connect-iq-sdk-manager-cli login
connect-iq-sdk-manager-cli sdk set latest
connect-iq-sdk-manager-cli device download --manifest=garmin-app/manifest.xml
export CIQ_SDK_HOME="$(connect-iq-sdk-manager-cli sdk current-path)"

# Compile strict (-l 3 -O 2 -w) for Fenix 7
./garmin-app/scripts/build.sh fenix7

# Start simulator, then run Run No Evil (:test) unit tests
"$CIQ_SDK_HOME/bin/connectiq" &
./garmin-app/scripts/build.sh --test fenix7

# Launch interactive Fenix 7 simulator (edit settings via File -> Edit Persistent Storage -> Edit Application.Properties)
"$CIQ_SDK_HOME/bin/monkeydo" garmin-app/bin/ma-remote-fenix7.prg fenix7
```
In the simulator, enable **Settings -> Use Device HTTPS Requirements** and check **File -> View Memory** while viewing the Glance to verify Glance RAM stays under 24 KB.

### 4. Test on a Real Garmin Fenix 7
* **Recommended (enables Connect IQ Store mobile app settings):** Export a `.iq` bundle (`GARMIN_DEV_KEY=/path/to/key.der ./garmin-app/scripts/build.sh --package`) and upload it as a **Beta App** on the [Garmin Connect IQ Developer Dashboard](https://apps.garmin.com/en-US/developer/upload). Beta apps are private to your own Garmin account and let you configure `serverUrl` and `accessToken` normally on your phone.
* **Quick USB Sideload:** Copy `garmin-app/bin/ma-remote-fenix7.prg` to `GARMIN/APPS/` over USB *(note: USB-sideloaded `.prg` files do not show up in the Connect IQ Store phone settings UI, so use a Beta App upload for full end-to-end testing)*.

---

## Release Tags

This monorepo uses independent component release tags:
* **Music Assistant Plugin:** `provider-vMAJOR.MINOR.PATCH` (`tag_prefix: "provider-"`)
* **Garmin Watch App:** `watch-vMAJOR.MINOR.PATCH`

## License

Apache-2.0 — see [LICENSE](LICENSE).
