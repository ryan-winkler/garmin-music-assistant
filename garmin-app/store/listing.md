# Garmin Connect IQ Store Listing Copy

*(Excluded from `monkey.jungle` so store assets never consume watch binary RAM.)*

## App Name
**MA Remote (Music Assistant)**

## App Type
Watch App (with offline Glance preview)

## Short Description (Store Summary)
Control Music Assistant playback — including your phone's background Sendspin player and home speakers — right from your Garmin wrist.

## Full Description
**MA Remote** is a dedicated remote controller for **Music Assistant** servers. Control what is playing in the background on your phone (via Music Assistant Companion / Sendspin) or on any speaker in your home (Sonos, AirPlay, Chromecast, Squeezebox, Snapcast) without unlocking your phone.

**Key Controls:**
- Play / Pause / Resume idle queues / Stop
- Next & Previous Track
- Repeat Mode cycling (Off / All / One)
- Shuffle Toggle
- Dedicated Volume control with Mute (speaker-group aware)
- Seek Forward / Backward
- Favorite currently playing track
- Switch active player or speaker group (prioritizes phone background players)
- Browse Queue and jump directly to any track
- Quick-start Library Playlists and Favorite Tracks
- Offline Glance showing last-known track and player
- Built-in Diagnostics & Connection Tester

**Important Notes & Requirements:**
- This is a **remote controller** for Music Assistant, **not** an offline audio file player (it does not store MP3s on the watch or play audio inside recorded workout screens).
- Requires a paired smartphone in Bluetooth range running Garmin Connect.
- Requires your Music Assistant server to have the open-source **`garmin_controller`** plugin installed and reachable over **trusted HTTPS** (e.g., Let's Encrypt reverse proxy, Tailscale Serve/Funnel, or Cloudflare Tunnel).
- Configure your HTTPS URL and Music Assistant long-lived access token in the **Connect IQ Store** mobile app (or Garmin Express).

## Permissions Disclosure
- **Communications**: Sends authenticated HTTPS commands to your Music Assistant server via Garmin Connect on your paired phone.

## Store Upload Checklist
1. Generate and back up a permanent 4096-bit RSA DER developer key (never commit it to git).
2. Run `GARMIN_DEV_KEY=/path/to/key.der ./garmin-app/scripts/build.sh --package`.
3. Capture 1–5 screenshots on a `fenix7` simulator (Now Playing, Volume Arc, Controls Menu, Player Switcher, Diagnostics) with *Use Device HTTPS Requirements* enabled.
4. Upload `garmin-app/bin/ma-remote.iq` at `https://apps.garmin.com/en-US/developer/upload`.
