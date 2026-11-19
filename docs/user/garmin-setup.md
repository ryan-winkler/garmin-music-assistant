# Garmin Fenix 7 Setup & Usage Guide

## Prerequisites
1. Music Assistant with the `garmin_controller` plugin enabled and reachable over publicly trusted HTTPS ([Music Assistant Setup](music-assistant-setup.md)).
2. Paired smartphone within Bluetooth range running **Garmin Connect** (acts as the Bluetooth-to-HTTPS bridge).
3. **Connect IQ Store** mobile app (or Garmin Express on desktop) to configure settings.

> **Controlling Phone Background Playback:** When you listen to Music Assistant in the background on your phone (via the Music Assistant Companion app / Sendspin web player), your phone appears as a Music Assistant player. The plugin automatically prioritizes playing/mobile Sendspin players and resumes idle queues when you press Play on your Fenix 7 — keeping your phone locked in your pocket while giving you full Repeat, Shuffle, Queue, Volume, Seek, and Favorite controls (unlike basic Bluetooth AVRCP).

## 1. Install on Your Fenix 7

### Sideload Over USB (Development / Immediate Testing)
1. Install the Garmin Connect IQ SDK and Fenix 7 device profile:
   ```bash
   mkdir -p ~/.Garmin/ConnectIQ/Sdks ~/.Garmin/ConnectIQ/Devices
   go install github.com/lindell/connect-iq-sdk-manager-cli@latest
   connect-iq-sdk-manager-cli agreement accept
   connect-iq-sdk-manager-cli login
   connect-iq-sdk-manager-cli sdk set ">=9.0.0"
   connect-iq-sdk-manager-cli device download -d fenix7 -F
   export CIQ_SDK_HOME="$(connect-iq-sdk-manager-cli sdk current-path)"
   ```
2. Build for Fenix 7:
   ```bash
   ./garmin-app/scripts/build.sh fenix7
   ```
3. Connect your Fenix 7 over USB and copy `garmin-app/bin/ma-remote-fenix7.prg` into `GARMIN/APPS/`.

### Install from Garmin Connect IQ Store
Once published, install **MA Remote (Music Assistant)** directly from the **Connect IQ Store** app.

## 2. Configure Settings
Open the **Connect IQ Store** mobile app -> **My Device -> My Watch Apps -> MA Remote -> Settings**:
* **Server URL (HTTPS):** e.g. `https://ma.yourdomain.com` (no trailing slash needed; whitespace is trimmed automatically).
* **Access Token:** Your Music Assistant long-lived Bearer token. *(Note: Connect IQ app settings sync through Garmin's settings service and are unmasked in the mobile settings form.)*
* **Preferred Player ID (optional):** Leave blank to auto-select your active/phone player, or enter a specific `player_id`.
* **Poll Interval / Seek Step / Volume Step / Vibrate:** Defaults (`10s`, `15s`, `5%`, `On`) are tuned for Fenix 7 battery life and BLE responsiveness.

## 3. Fenix 7 Controls (100% 5-Button + Additive Touch)

### Now Playing Screen
| Physical Button (Touch OFF/ON) | Touch Zone (when Touch ON) | Action |
| :--- | :--- | :--- |
| **START/STOP** (`KEY_ENTER`) | Center band | Play / Pause (or Resume idle queue) |
| **DOWN** | Middle-right | Next Track |
| **UP** | Middle-left | Previous Track |
| **Hold UP** (`MENU`) | Bottom-right | Open Controls Menu |
| — | Top strip (Player Name) | Switch Player / Group |
| — | Bottom-left | Open Dedicated Volume Screen |
| **BACK** | — | Exit App |

### Dedicated Volume Screen
* **UP / DOWN:** Increase / decrease volume (rapid presses coalesce over 350 ms into a single `volume_set` call; speaker groups adjust group volume automatically).
* **START/STOP:** Toggle Mute.
* **BACK:** Return to Now Playing.

### Controls Menu (`Hold UP`)
* **Volume**, **Repeat** (cycles `Off` -> `All` -> `One` in place), **Shuffle** (toggle in place), **Seek +15s / -15s**, **Favorite Track**, **Switch Player**, **Queue** (jump directly to any track), **Playlists**, **Favorites**, **Stop**, **Refresh Now**, **Diagnostics**.

### Glance View
Add **MA Remote** to your Fenix 7 Glance loop. The Glance renders cached track/player info offline (`< 24 KB` RAM, zero battery drain) and opens the live controller when pressed.

## 4. Troubleshooting (Built-In Diagnostics)
Open **Controls Menu -> Diagnostics** and press **START/STOP** to run a staged check:

| Watch Message | Cause & Fix |
| :--- | :--- |
| `Phone disconnected` (`-104`) | Phone is out of Bluetooth range or Bluetooth is off. |
| `Phone timeout` (`-2`) | Open Garmin Connect on your phone so iOS/Android wakes background BLE proxy. |
| `HTTPS required` (`-1001`) | URL uses `http://`. Switch to a trusted `https://` URL. |
| `Server timeout` (`-300`) | Server unreachable, firewall blocked, or self-signed/untrusted TLS cert. |
| `Bad JSON response` (`-400`) | Reverse proxy returned HTML (e.g., Cloudflare Access login page or 502). |
| `Auth failed (401)` | Token invalid or expired. Generate a fresh token in MA Settings -> Profile. |
| `Forbidden (403)` | Token's Music Assistant user lacks required scopes. |
| `Plugin not found (404)` | `garmin_controller` plugin is not installed or enabled on Music Assistant. |
