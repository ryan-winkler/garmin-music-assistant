import Toybox.Application.Properties;
import Toybox.Communications;
import Toybox.Lang;
import Toybox.PersistedContent;
import Toybox.System;
import Toybox.Time;

typedef ApiCallback as Method(ok as Boolean, code as Number, data as Dictionary?, errMsg as String) as Void;

// Safe settings loader and URL/token sanitizer.
class AppConfig {
    public var serverUrl as String = "";
    public var accessToken as String = "";
    public var preferredPlayerId as String = "";
    public var pollIntervalSec as Number = 10;
    public var seekStepSec as Number = 15;
    public var volumeStep as Number = 5;
    public var vibrateFeedback as Boolean = true;

    function initialize() {
        reload();
    }

    function reload() as Void {
        serverUrl = normalizeUrl(safeGetString("serverUrl"));
        accessToken = trimString(safeGetString("accessToken"));
        preferredPlayerId = trimString(safeGetString("preferredPlayerId"));
        pollIntervalSec = PlaybackState.clampInt(safeGetNumber("pollIntervalSec", 10), 5, 60);
        seekStepSec = PlaybackState.clampInt(safeGetNumber("seekStepSec", 15), 5, 60);
        volumeStep = PlaybackState.clampInt(safeGetNumber("volumeStep", 5), 1, 20);
        vibrateFeedback = safeGetBool("vibrateFeedback", true);
    }

    function isConfigured() as Boolean {
        return serverUrl.length() > 0 && accessToken.length() > 0;
    }

    function isHttps() as Boolean {
        if (serverUrl.length() < 8) {
            return false;
        }
        var prefix = serverUrl.substring(0, 8);
        return prefix != null && prefix.toLower().equals("https://");
    }

    static function normalizeUrl(raw as String) as String {
        var trimmed = trimString(raw);
        if (trimmed.length() >= 8) {
            var scheme = trimmed.substring(0, 8);
            var rest = trimmed.substring(8, trimmed.length());
            if (scheme != null && rest != null && scheme.toLower().equals("https://")) {
                trimmed = "https://" + rest;
            }
        }
        while (trimmed.length() > 0) {
            var tail = trimmed.substring(trimmed.length() - 1, trimmed.length());
            if (tail == null || !tail.equals("/")) {
                break;
            }
            var shortened = trimmed.substring(0, trimmed.length() - 1);
            trimmed = shortened != null ? shortened : "";
        }
        return trimmed;
    }

    static function trimString(value as String) as String {
        var start = 0;
        var end = value.length();
        while (start < end) {
            var ch = value.substring(start, start + 1);
            if (ch != null && isWhitespace(ch)) {
                start++;
            } else {
                break;
            }
        }
        while (end > start) {
            var ch = value.substring(end - 1, end);
            if (ch != null && isWhitespace(ch)) {
                end--;
            } else {
                break;
            }
        }
        if (start >= end) {
            return "";
        }
        var out = value.substring(start, end);
        return out != null ? out : "";
    }

    private static function isWhitespace(ch as String) as Boolean {
        return ch.equals(" ") || ch.equals("\t") || ch.equals("\n") || ch.equals("\r");
    }

    private function safeGetProperty(key as String) as PropertyValueType {
        try {
            return Properties.getValue(key);
        } catch (ex) {
            return null;
        }
    }

    private function safeGetString(key as String) as String {
        var val = safeGetProperty(key);
        return (val instanceof String) ? (val as String) : "";
    }

    private function safeGetNumber(key as String, fallback as Number) as Number {
        var val = safeGetProperty(key);
        return (val instanceof Number) ? (val as Number) : fallback;
    }

    private function safeGetBool(key as String, fallback as Boolean) as Boolean {
        var val = safeGetProperty(key);
        return (val instanceof Boolean) ? (val as Boolean) : fallback;
    }
}

module ErrorMapper {
    function describe(code as Number, serverMsg as String?) as String {
        if (code == Communications.BLE_CONNECTION_UNAVAILABLE || code == -104) {
            return "Phone disconnected\nCheck Bluetooth";
        }
        if (code == Communications.BLE_HOST_TIMEOUT || code == -2) {
            return "Phone timeout\nOpen Garmin Connect";
        }
        if (code == Communications.BLE_QUEUE_FULL || code == -101) {
            return "BLE busy\nTry again";
        }
        if (code == Communications.SECURE_CONNECTION_REQUIRED || code == -1001) {
            return "HTTPS required\nUse trusted TLS URL";
        }
        if (code == Communications.NETWORK_REQUEST_TIMED_OUT || code == -300) {
            return "Server timeout\nCheck URL & TLS";
        }
        if (code == Communications.INVALID_HTTP_BODY_IN_NETWORK_RESPONSE || code == -400) {
            return "Bad JSON response\nCheck proxy / auth";
        }
        if (code == Communications.NETWORK_RESPONSE_TOO_LARGE || code == -402) {
            return "Response too large\nUpdate MA plugin";
        }
        if (code == Communications.NETWORK_RESPONSE_OUT_OF_MEMORY || code == -403) {
            return "Watch low memory\nRetry action";
        }
        if (code == 401) {
            return "Auth failed (401)\nCheck MA token";
        }
        if (code == 403) {
            return "Forbidden (403)\nCheck token scopes";
        }
        if (code == 404) {
            if (serverMsg != null && serverMsg.find("Player") != null) {
                return "Player offline\nPick another speaker";
            }
            return "Plugin not found (404)\nInstall MA plugin";
        }
        if (code >= 500) {
            return "Server error (" + code.toString() + ")\nCheck MA logs";
        }
        if (serverMsg != null && serverMsg.length() > 0) {
            return serverMsg;
        }
        return "Error " + code.toString();
    }

    function singleLine(msg as String) as String {
        var idx = msg.find("\n");
        if (idx == null) {
            return msg;
        }
        var head = msg.substring(0, idx);
        var tail = msg.substring(idx + 1, msg.length());
        return (head != null ? head : "") + " - " + (tail != null ? tail : "");
    }
}

class DiagnosticsLog {
    private const MAX_ENTRIES = 8;
    private var _entries as Array<String> = [] as Array<String>;
    public var lastStatus as Number = 0;
    public var lastRttMs as Number = 0;
    public var lastSyncEpoch as Number = 0;
    public var lastError as String = "";

    function initialize() {
    }

    function record(route as String, status as Number, rttMs as Number, reqId as String, detail as String) as Void {
        lastStatus = status;
        lastRttMs = rttMs;
        if (status == 200) {
            lastSyncEpoch = Time.now().value();
            lastError = "";
            return;
        }
        lastError = detail;
        var line = route + " " + status.toString() + " #" + reqId;
        _entries.add(line);
        while (_entries.size() > MAX_ENTRIES) {
            _entries = _entries.slice(1, null);
        }
    }

    function getEntries() as Array<String> {
        return _entries;
    }
}

// Single-flight BLE HTTPS client with 1-slot coalesced pending queue and HTTPS enforcement.
class ApiClient {
    const APP_VERSION = "0.1.0";
    const API_PREFIX = "/api/garmin/v1";

    public var config as AppConfig;
    public var diag as DiagnosticsLog;

    private var _inFlight as Boolean = false;
    private var _reqSeq as Number = 0;
    private var _activeRoute as String = "";
    private var _activeReqId as String = "";
    private var _activeStartMs as Number = 0;
    private var _activeCallback as ApiCallback? = null;

    // Single-slot pending queue so menu/diagnostics/forced calls never stall when BLE is busy.
    private var _hasQueued as Boolean = false;
    private var _qMethod as Communications.HttpRequestMethod = Communications.HTTP_REQUEST_METHOD_GET;
    private var _qPath as String = "";
    private var _qParams as Dictionary<Object, Object>? = null;
    private var _qCallback as ApiCallback? = null;

    function initialize(cfg as AppConfig, dlog as DiagnosticsLog) {
        config = cfg;
        diag = dlog;
    }

    function isBusy() as Boolean {
        return _inFlight;
    }

    function getHealth(cb as ApiCallback) as Boolean {
        return enqueueOrSend(Communications.HTTP_REQUEST_METHOD_GET, "/health", null, cb, true);
    }

    function getPlayers(offset as Number, limit as Number, cb as ApiCallback) as Boolean {
        var params = {
            "offset" => offset.toString(),
            "limit" => limit.toString()
        } as Dictionary<Object, Object>;
        return enqueueOrSend(Communications.HTTP_REQUEST_METHOD_GET, "/players", params, cb, true);
    }

    function getState(playerId as String?, cb as ApiCallback, queueIfBusy as Boolean) as Boolean {
        var params = null as Dictionary<Object, Object>?;
        if (playerId != null && playerId.length() > 0) {
            params = { "player_id" => playerId } as Dictionary<Object, Object>;
        }
        return enqueueOrSend(Communications.HTTP_REQUEST_METHOD_GET, "/state", params, cb, queueIfBusy);
    }

    function postAction(playerId as String?, action as String, value as Object?, cb as ApiCallback) as Boolean {
        var body = {
            "action" => action
        } as Dictionary<Object, Object>;
        if (playerId != null && playerId.length() > 0) {
            body["player_id"] = playerId;
        }
        if (value != null) {
            body["value"] = value;
        }
        return enqueueOrSend(Communications.HTTP_REQUEST_METHOD_POST, "/action", body, cb, true);
    }

    function getItems(kind as String, playerId as String?, offset as Number, limit as Number, cb as ApiCallback) as Boolean {
        var params = {
            "kind" => kind,
            "offset" => offset.toString(),
            "limit" => limit.toString()
        } as Dictionary<Object, Object>;
        if (playerId != null && playerId.length() > 0) {
            params["player_id"] = playerId;
        }
        return enqueueOrSend(Communications.HTTP_REQUEST_METHOD_GET, "/items", params, cb, true);
    }

    private function enqueueOrSend(
        httpMethod as Communications.HttpRequestMethod,
        path as String,
        params as Dictionary<Object, Object>?,
        cb as ApiCallback,
        queueIfBusy as Boolean
    ) as Boolean {
        if (!config.isConfigured()) {
            cb.invoke(false, 0, null, "Setup required\nCheck CIQ Store app");
            return false;
        }
        if (!config.isHttps()) {
            // Never transmit Bearer tokens over cleartext HTTP.
            var tlsMsg = ErrorMapper.describe(Communications.SECURE_CONNECTION_REQUIRED, null);
            diag.record(path, Communications.SECURE_CONNECTION_REQUIRED, 0, "tls", tlsMsg);
            cb.invoke(false, Communications.SECURE_CONNECTION_REQUIRED, null, tlsMsg);
            return false;
        }
        if (!System.getDeviceSettings().phoneConnected) {
            var bleMsg = ErrorMapper.describe(Communications.BLE_CONNECTION_UNAVAILABLE, null);
            diag.record(path, Communications.BLE_CONNECTION_UNAVAILABLE, 0, "ble", bleMsg);
            cb.invoke(false, Communications.BLE_CONNECTION_UNAVAILABLE, null, bleMsg);
            return false;
        }
        if (_inFlight) {
            if (!queueIfBusy) {
                return false;
            }
            _hasQueued = true;
            _qMethod = httpMethod;
            _qPath = path;
            _qParams = params;
            _qCallback = cb;
            return true;
        }
        dispatchNow(httpMethod, path, params, cb);
        return true;
    }

    private function dispatchNow(
        httpMethod as Communications.HttpRequestMethod,
        path as String,
        params as Dictionary<Object, Object>?,
        cb as ApiCallback
    ) as Void {
        _reqSeq++;
        _inFlight = true;
        _activeRoute = path;
        _activeReqId = _reqSeq.toString();
        _activeStartMs = System.getTimer();
        _activeCallback = cb;

        var url = config.serverUrl + API_PREFIX + path;
        var headers = {
            "Authorization" => "Bearer " + config.accessToken,
            "X-Garmin-Req-Id" => _activeReqId,
            "X-Garmin-App-Version" => APP_VERSION
        } as Dictionary<Object, Object>;

        var reqParams = params;
        if (httpMethod == Communications.HTTP_REQUEST_METHOD_POST) {
            headers["Content-Type"] = Communications.REQUEST_CONTENT_TYPE_JSON;
            // Always send a JSON object (never null) so aiohttp never sees an empty body.
            reqParams = (params != null) ? params : ({} as Dictionary<Object, Object>);
        }

        var options = {
            :method => httpMethod,
            :headers => headers,
            :responseType => Communications.HTTP_RESPONSE_CONTENT_TYPE_JSON
        };

        try {
            Communications.makeWebRequest(url, reqParams, options, method(:onHttpResponse));
        } catch (ex) {
            _inFlight = false;
            _activeCallback = null;
            var msg = "Request failed\nCheck server URL";
            diag.record(path, -1, 0, _activeReqId, msg);
            cb.invoke(false, -1, null, msg);
            flushQueued();
        }
    }

    function onHttpResponse(
        responseCode as Number,
        data as Dictionary or String or PersistedContent.Iterator or Null
    ) as Void {
        var rtt = System.getTimer() - _activeStartMs;
        if (rtt < 0) {
            rtt = 0;
        }
        var route = _activeRoute;
        var reqId = _activeReqId;
        var cb = _activeCallback;

        _inFlight = false;
        _activeCallback = null;

        var dict = (data instanceof Dictionary) ? (data as Dictionary) : null;
        var serverErr = (dict != null) ? PlaybackState.readStr(dict, "error", "") : "";

        if (responseCode == 200 && dict != null && PlaybackState.readBool(dict, "ok", true)) {
            diag.record(route, 200, rtt, reqId, "");
            if (cb != null) {
                cb.invoke(true, 200, dict, "");
            }
        } else {
            var friendly = ErrorMapper.describe(responseCode, serverErr.length() > 0 ? serverErr : null);
            diag.record(route, responseCode, rtt, reqId, friendly);
            if (cb != null) {
                cb.invoke(false, responseCode, dict, friendly);
            }
        }

        flushQueued();
    }

    private function flushQueued() as Void {
        if (!_inFlight && _hasQueued && _qCallback != null) {
            var m = _qMethod;
            var p = _qPath;
            var prm = _qParams;
            var cb = _qCallback as ApiCallback;
            _hasQueued = false;
            _qCallback = null;
            _qParams = null;
            dispatchNow(m, p, prm, cb);
        }
    }
}
