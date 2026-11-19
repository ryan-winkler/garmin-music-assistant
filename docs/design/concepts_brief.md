# Garmin Connect IQ Controller for Music Assistant

* **Author:** Ryan Winkler
* **Date:** 2026-11-19
* **Status:** Approved (Autonomous `/goal` synthesis incorporating 7 Goldfish reviews)

## Overview

This project builds a Garmin Connect IQ Watch App (with a lightweight offline Glance) and an accompanying Music Assistant Community Catalog plugin (`garmin_controller`) so a user wearing a Garmin Fenix 7 (and other Connect IQ 4.0+ watches) can control Music Assistant speakers directly from their wrist.

The watch app acts as a **remote controller** for speakers managed by Music Assistant (Sonos, AirPlay, Chromecast, Squeezebox, Snapcast, Sendspin, etc.). It is **not** a Garmin Audio Content Provider that downloads MP3 files onto the watch for offline headphone listening. Music Assistant's Community Catalog rules forbid downloading, exporting, or exposing audio stream URLs outside the server, and Garmin's Audio Content Provider API is restricted to local encrypted playback.

## Analysis

Seven independent review lenses (`egm-design`, `egm-zoom-out`, `egm-inventive-catalyst`, `egm-codebase-details`, `egm-implementation-readiness`, `egm-comprehension`, and `egm-structural`) evaluated the initial hypothesis and surfaced critical platform constraints and trade-offs.

### 1. Root Contradictions & Inventive Resolutions

1. **Rich Music Assistant Payloads vs. Watch Heap & BLE Buffer Ceilings**
   * *Problem:* Music Assistant's built-in `POST /api` returns full `Player`, `PlayerQueue`, and `QueueItem` dataclasses (often 15–150 KB for `players/all` or queue listings). Connect IQ's `Communications.makeWebRequest` inflates JSON 3x–5x in heap memory, rejects responses above ~16–32 KB (`-402 NETWORK_RESPONSE_TOO_LARGE` / `-403 NETWORK_RESPONSE_OUT_OF_MEMORY`), and rejects valid JSON `null` bodies (which MA returns for void commands like `players/cmd/play_pause`) with `-400 INVALID_HTTP_BODY_IN_NETWORK_RESPONSE`. Root JSON arrays (`[...]`) also behave inconsistently across iOS and Android Garmin Connect Mobile (GCM).
   * *Resolution:* Ship one lightweight, zero-dependency Music Assistant Community Catalog plugin (`garmin_controller`) that registers 5 authenticated `/api/garmin/v1/*` routes (`/health`, `/players`, `/state`, `/action`, `/items?kind=queue|playlists|favorites`) returning strictly flat, root-object JSON (`<= 1 KB` for state/actions, `<= 3 KB` for paginated lists), stripping emoji/unsupported glyphs and truncating strings server-side. Per YAGNI and DRY, drop Direct Native `POST /api` fallback from v1 instead of maintaining two incompatible transports inside watch RAM.

2. **BLE Proxy Latency & Asynchronous Speaker Convergence vs. Instant Wrist Feedback**
   * *Problem:* Standard `Communications.makeWebRequest` always routes over Bluetooth through the paired phone's Garmin Connect app (not watch Wi-Fi). Round-trips take 0.8–2.5 seconds, Garmin's outbound BLE queue holds only 1–3 requests (overflow causes `-101 BLE_QUEUE_FULL`), and downstream MA speakers (Sonos, AirPlay, Cast) apply commands asynchronously, so reading state immediately after dispatching a command can return stale pre-command state.
   * *Resolution:*
     * Watch side: Enforce a strict single-flight request coordinator with a monotonic generation counter (preventing stale polls from overwriting newer commands), apply optimistic UI updates immediately on button press, coalesce rapid volume/seek clicks over a 350 ms debounce window into a single `volume_set` / `seek` call, interpolate elapsed playback seconds locally on a 1s timer, and use adaptive polling (10s playing, 30s paused/idle, zero polling when hidden).
     * Server side: On `POST /api/garmin/v1/action`, wait up to 500 ms on MA's event bus (`PLAYER_UPDATED` / `QUEUE_UPDATED` for that `player_id`) before serializing the updated state, and include `"settled": true|false` so the watch knows whether to schedule one delayed 1.5s follow-up poll.

3. **Glance Freshness vs. 28–32 KB Glance RAM & Battery Life**
   * *Problem:* Fenix 7 Glances are capped at ~28–32 KB RAM (far below the ~1 MB watch-app cap). Making live BLE network calls inside `GlanceView` stalls scrolling and risks OOM; Connect IQ `Background` temporal events are hard-capped at 5-minute intervals (longer than most songs) and wake BLE ~288 times/day.
   * *Resolution:* Keep `(:glance)` strictly offline and read-only from `Application.Storage` (no `Communications`, no menus, no transport code imported into `:glance` scope). The Glance displays the cached player name, playback state, track/artist, and staleness age (e.g., `2m ago`) and opens the full Watch App on press to fetch live state immediately.

4. **Full Listening Action Breadth vs. Fenix 7 5-Button & Touch-Off Ergonomics**
   * *Problem:* Fenix 7 users frequently disable touch (wet hands, gloves, workouts). Additionally, in Connect IQ `BehaviorDelegate`, a screen tap triggers `onSelect()` and returning `true` suppresses `onTap(clickEvent)`.
   * *Resolution:* Guarantee 100% control via the 5 physical buttons alone, with touch zones strictly additive:
     * Now Playing primary screen: `KEY_ENTER` (START/STOP) = Play/Pause; `UP` = Previous Track; `DOWN` = Next Track; hold `UP` (`onMenu`) = Actions Menu; `BACK` = Exit. When touch is enabled, `onSelect()` returns `false` while `onKey(KEY_ENTER)` handles the physical button, allowing clean `onTap(clickEvent)` zones (center = Play/Pause, left = Previous, right = Next, top = Switch Player, bottom-left = Volume, bottom-right = Menu/Repeat/Shuffle).
     * Dedicated Volume View (1 press from Actions Menu or bottom-left touch): `UP` = Vol+, `DOWN` = Vol-, `SELECT` = Mute/Unmute, `BACK` = Return (eliminates accidental track skips and mode confusion).
     * Flat Actions Menu (`WatchUi.Menu2`, max view stack depth <= 4): Volume, Repeat cycle (`off` -> `all` -> `one`), Shuffle toggle, Seek (`+15s` / `-15s`), Favorite Current Track, Switch Player/Group, Queue (paginated jump-to-track), Library (Playlists & Favorites), Stop, Refresh, Diagnostics.

5. **Local Plain-HTTP Music Assistant Default vs. Mandatory Trusted HTTPS**
   * *Problem:* Physical Garmin watches route `makeWebRequest` through Garmin Connect Mobile on iOS/Android, which rejects plain `http://` and self-signed/user-installed custom CAs (Android 7+ blocks user CAs for third-party apps; Home Assistant Ingress uses HA session auth rather than MA Bearer tokens).
   * *Resolution:* Document publicly trusted HTTPS (Let's Encrypt reverse proxy, Tailscale Serve/Funnel, or Cloudflare Tunnel targeting MA port `8095` directly, not HA Ingress) and paired phone in BLE range as explicit prerequisites. Ship an on-watch Diagnostics & Connection Test screen mapping exact Connect IQ codes (`-1001`, `-104`, `-2`, `-101`, `-300`, `-400`, `-402`, `-403`) and HTTP statuses (`401`, `403`, `404`, `5xx`) into plain-English instructions.

6. **Monorepo Packaging Across Two Distribution Channels**
   * *Problem:* Music Assistant Community Catalog validates `providers/<domain>/` strictly (no symlinks, no tests/tooling inside the provider folder, wheel-only requirements, `multi_instance: false` to prevent route collisions) and tracks GitHub release tags, while Garmin Connect IQ publishes signed `.iq` packages independently.
   * *Resolution:* Use a decoupled monorepo layout: `providers/garmin_controller/` holds runtime-only plugin files; `pyproject.toml` and `tests/` sit at repo root; `garmin-app/` holds the Connect IQ app with `garmin-app/store/` excluded from `monkey.jungle`; `docs/protocol/` holds versioned wire schemas; release tags are independent (`provider-vMAJOR.MINOR.PATCH` with `tag_prefix: "provider-"` and `watch-vMAJOR.MINOR.PATCH`).

### Secondary Trade-Offs Accepted

* **Phone BLE dependency:** The watch requires a paired phone running Garmin Connect in Bluetooth range; standalone watch Wi-Fi remote control is not possible without Garmin's full-screen `SyncDelegate` UI.
* **Settings via Connect IQ Store app:** Credentials (`serverUrl`, `accessToken`) are entered in the Connect IQ Store phone app (or Garmin Express) and transit Garmin's settings sync service; `settings.xml` cannot mask password fields, so users should create a least-privilege MA token and avoid reverse-proxy login walls (like Cloudflare Access) on `/api/garmin/v1/*`.
* **Degraded Direct `/api` fallback:** Without the `garmin_controller` plugin, large player lists (`players/all`) can still hit `-402`/`-403` on big setups; Direct Mode is positioned strictly as an emergency/zero-install fallback for basic transport on a configured or small player list.

## Goals vs. Non-Goals

### In-Scope Goals
* **Full Wrist Listening Controls on Fenix 7 (and Connect IQ 4.0+ watches):** Play/Pause, Stop, Next Track, Previous Track, Repeat mode cycling (`off` / `all` / `one`), Shuffle toggle, Volume Up/Down/Mute (group-volume aware), Seek (`+15s` / `-15s`), Favorite current track, Switch Player/Group, View & jump in Queue, Quick-play Library Playlists & Favorites.
* **First-Class Fenix 7 Ergonomics:** 100% physical 5-button operability (Touch-OFF safe), additive touchscreen tap zones (Touch-ON), 64-color high-contrast MIP rendering, proportional geometry for 240x240–454x454 round displays.
* **Music Assistant Community Catalog Plugin (`garmin_controller`):** Compliant with `music-assistant/community-provider-template` and Community Catalog rules (zero PyPI dependencies, zero audio exporting, native MA Bearer auth + scope enforcement, clean route unregister on `unload()`, hard UTF-8 byte caps, structured logging with `X-Garmin-Req-Id`).
* **Direct Native `/api` Fallback:** Auto-detected fallback (`404` on `/api/garmin/v1/health` only; never on `401`/`403` or network timeout) supporting basic single-player transport with zero server plugin install.
* **Offline-Safe Glance View:** `< 24 KB` peak RAM, reads cached state from `Application.Storage`, zero network calls in Glance scope.
* **On-Watch Diagnostics & Connection Tester:** Staged check (settings/HTTPS validation -> `phoneConnected` -> `/api/garmin/v1/health` -> authenticated state) with ring buffer of recent errors.
* **Store & Catalog Packaging Readiness:** Connect IQ Store listing assets, developer key & `.iq`/`.prg` build scripts, separated path-scoped CI workflows, and full Python + contract test suite.

### Out-of-Scope Non-Goals
* **Offline Audio Sync / Watch-Local Playback (`audio-content-provider-app`):** Excluded because Garmin's Audio Content Provider API cannot control remote speakers and Music Assistant's Community Catalog rules strictly prohibit exporting/downloading audio files or exposing stream URLs outside the server.
* **Running Concurrently Inside Active Workout Recording Screens:** Connect IQ Watch Apps cannot replace the native Music widget inside a running workout activity (Glance access depends on watch firmware widget-loop behavior).
* **Plain HTTP / Self-Signed CA Workarounds:** Excluded because real Garmin hardware and Android/iOS Garmin Connect Mobile reject untrusted certificates and cleartext HTTP.
* **Album Art Bitmaps on Watch:** Excluded in v1 to avoid multi-kilobyte BLE image transfers, `-402`/`-403` memory spikes, and slow screen updates.
* **Free-Text Music Search & Queue Reordering/Deletion:** Excluded in v1 due to watch text-entry friction; users browse existing Playlists, Favorites, and Queue items.
* **2-Button / Rectangular Watch Layout Optimization (Phase 1):** Primary focus is Fenix 7 and 5-button round watches; 2-button touch watches inherit `BehaviorDelegate` + `Menu2` support as best-effort.

## Alternatives Weighed

1. **Garmin Audio Content Provider (`type="audio-content-provider-app"`) like SubMusic / YuMusic**
   * *Rejected by author:* Audio Content Providers only download encrypted audio files onto watch flash for local Bluetooth headphone playback. They cannot send remote-control commands to Music Assistant home speakers, and exporting audio files violates Music Assistant Community Catalog rules.
2. **Direct Native Music Assistant `POST /api` Only (No Server Plugin)**
   * *Rejected by author:* Raw MA JSON-RPC responses for `players/all` and `player_queues/items` routinely reach 20–150 KB (triggering Connect IQ `-402`/`-403` OOM errors), void commands return JSON `null` (triggering Connect IQ `-400` JSON parse failures), and every action requires 2–3 sequential BLE round-trips. Keeping Direct `/api` only as a degraded fallback while making the lightweight `garmin_controller` plugin the primary path resolves all three constraints cleanly.
3. **Home Assistant `media_player` Proxy Only (via Nabu Casa / `GarminHomeAssistant`)**
   * *Rejected by author:* Requires Home Assistant as a mandatory dependency, lacks Music Assistant-native queue browsing/jumping and MA-specific repeat/shuffle/favorite semantics, and forces users to rely on generic smart-home dashboards instead of a dedicated wrist music controller.
4. **Live Network Polling or `Toybox.Background` Temporal Events in Glance**
   * *Rejected by author:* Live `makeWebRequest` in `GlanceView` stalls scrolling over BLE and risks OOM in Fenix 7's 28–32 KB Glance heap; `Toybox.Background` enforces a 5-minute minimum interval that leaves song metadata permanently stale while waking BLE ~288 times/day.
5. **Two Separate Git Repositories vs. Decoupled Monorepo**
   * *Rejected by author:* Two separate repositories complicate atomic wire-protocol updates and contract testing. Music Assistant Community Catalog explicitly supports `providers/<domain>/` with `tag_prefix`, allowing a clean monorepo with strictly separated runtime folders, path-scoped CI, and independent `provider-v*` / `watch-v*` release tags.

## Key Decisions & Staging for Next Steps

1. **Wire Protocol Namespace:** `/api/garmin/v1/` with additive-only compatibility, root JSON objects on every response (including lists and errors), and explicit `api_version: 1` handshake in `GET /api/garmin/v1/health`.
2. **Authentication:** Reuse Music Assistant's native `Authorization: Bearer <long-lived-token>` verified via `await get_authenticated_user(request)` + `has_scope(user, Scope.*)` + `set_current_user(user)` on every route (including `/health`). Never log tokens; never pass tokens in query params.
3. **Minimum Connect IQ API Level:** `minApiLevel="4.0.0"` (supports all Fenix 7 firmware revisions and modern round Garmin watches), `storage_schema_version = 1`, `settings.xml` `maxLength="512"`.
4. **Hard UTF-8 Byte Budgets:** `/health <= 512 B`, `/state <= 1024 B`, `/action <= 1024 B`, `/players <= 3072 B`, `/queue <= 3072 B`, `/playlists <= 3072 B`, `/favorites <= 3072 B`, error envelope `<= 384 B`.
5. **Action Convergence:** `POST /api/garmin/v1/action` awaits matching `PLAYER_UPDATED`/`QUEUE_UPDATED` event for up to 500 ms and returns updated compact state plus `"settled": bool`.
6. **Build & Verification Strategy:** Python plugin & contract tests run 100% locally via `uv run pytest`, `ruff`, `mypy`, `codespell`; Garmin Connect IQ `.prg`/`.iq` build scripts and CI workflows target `monkeyc -l 3 -O 2 -w` with documented Garmin Developer SDK bootstrap.
