# Garmin Connect IQ Controller for Music Assistant

Control Music Assistant playback — including your phone's background Sendspin player and home speakers — directly from a Garmin Fenix 7 (or any Connect IQ 4.0+ watch).

This repository contains two decoupled, independently released components sharing one compact wire protocol (`docs/protocol/v1.md`):

| Component | Path | Setup Guide | Release Tag |
| :--- | :--- | :--- | :--- |
| **Music Assistant Plugin** | `providers/garmin_controller/` | [Music Assistant Setup](docs/user/music-assistant-setup.md) | `provider-v*` |
| **Garmin Watch App (Fenix 7+)** | `garmin-app/` | [Garmin Watch Setup](docs/user/garmin-setup.md) | `watch-v*` |

## What This App Is (and Is Not)

* **Remote Controller:** Sends authenticated HTTPS commands over Bluetooth through your paired phone's Garmin Connect app to Music Assistant. Controls background Music Assistant playback on your phone (Sendspin / Companion app) as well as any speaker or group managed by Music Assistant (Sonos, AirPlay, Chromecast, Squeezebox, Snapcast).
* **Not an Offline Audio Player:** Does not download MP3s onto watch flash storage (which violates Music Assistant Community Catalog rules) and does not replace Garmin's built-in workout Music widget.

## Architecture & Design Docs

* [Wire Protocol v1](docs/protocol/v1.md) & [JSON Schemas](docs/protocol/v1_schemas.json)
* [EGM Concepts Brief](docs/design/concepts_brief.md)
* [EGM Technical Design Document](docs/design/garmin-music-assistant-controller.md)

## Local Development

```bash
# Python plugin tests, schema contract checks, and linters
uv sync
uv run pytest -v
uv run ruff check .
uv run mypy
uv run codespell

# Garmin Fenix 7 build (requires Connect IQ SDK installed & logged in)
./garmin-app/scripts/build.sh fenix7
./garmin-app/scripts/build.sh --package
```
