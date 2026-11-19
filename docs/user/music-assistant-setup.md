# Music Assistant Setup (`garmin_controller` Plugin)

The `garmin_controller` plugin runs inside your Music Assistant server and exposes 5 compact, authenticated endpoints under `/api/garmin/v1/*` sized for Garmin Connect IQ memory and Bluetooth transfer limits.

## 1. Install the Plugin

### Option A: Music Assistant Community Catalog (Recommended once admitted)
1. In Music Assistant, open **Settings -> Marketplace** and enable the **Community Catalog** (requires admin role).
2. Search for **Garmin Connect IQ Controller** (`garmin_controller`) and install it.
3. Add the plugin under **Settings -> Providers -> Add Provider -> Plugin -> Garmin Connect IQ Controller**.

### Option B: Local / Development Install
Copy `providers/garmin_controller/` into your Music Assistant server's custom providers folder (or mount it in Docker) and restart Music Assistant. The folder is self-contained with zero extra Python packages (`requirements: []`).

## 2. Optional Plugin Settings
* **Action state settle timeout (ms)** (default `500`, range `100`–`1500`): How long `/api/garmin/v1/action` waits for Music Assistant's event bus (`PLAYER_UPDATED` / `QUEUE_UPDATED`) before returning the updated state.
* **Preferred player (optional)**: Player ID or display-name substring (for example, your phone's Sendspin player name) to prioritize whenever no explicit player is chosen on the watch.

## 3. Generate a Long-Lived Access Token
1. In the Music Assistant web UI, open **Settings -> Profile**.
2. Create a **Long-Lived Access Token** (for example, named `Garmin Fenix 7`).
3. Ensure the user account has scopes `players.read`, `players.control`, `queues.read`, `queues.control`, `library.read`, and `library.write` (standard user or admin role).
4. Copy the token — you will paste it into the **Connect IQ Store** mobile app.

## 4. Expose Music Assistant Over Trusted HTTPS

Physical Garmin watches route `makeWebRequest` calls over Bluetooth through Garmin Connect on your phone. Android and iOS reject plain `http://192.168.x.x:8095` and self-signed/user-installed certificates.

Use one of these publicly trusted HTTPS options targeting Music Assistant's webserver port (`8095`) **directly** (do **not** use a Home Assistant Ingress URL, which requires Home Assistant session cookies instead of a Music Assistant Bearer token):

* **Tailscale Serve / Funnel:** `tailscale serve --bg http://127.0.0.1:8095` -> gives you a valid `https://<host>.ts.net` URL with a publicly trusted Let's Encrypt certificate (requires Tailscale active on your phone when using private `serve`).
* **Reverse Proxy (Caddy / Nginx / Traefik) + Let's Encrypt:** Proxy `https://ma.yourdomain.com` -> `http://<ma-lan-ip>:8095`.
* **Cloudflare Tunnel:** Route `https://ma.yourdomain.com` -> `http://<ma-lan-ip>:8095`. Do **not** place a browser login gate (Cloudflare Access / Authelia / HTTP Basic Auth) in front of `/api/garmin/v1/*`, or requests carrying `Authorization: Bearer <token>` will be intercepted.

Verify from your phone or terminal:

```bash
curl -H "Authorization: Bearer YOUR_TOKEN" https://ma.yourdomain.com/api/garmin/v1/health
# Expected: {"ok":true,"api_version":1,"plugin_version":"0.1.0","ma_version":"..."}
```
