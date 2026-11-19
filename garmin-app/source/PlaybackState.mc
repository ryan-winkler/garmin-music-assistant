import Toybox.Application.Storage;
import Toybox.Lang;
import Toybox.Time;

// Compact schema-versioned persistence shared with the offline (:glance) scope.
(:glance)
module StorageStore {
    const STORAGE_SCHEMA_VERSION = 1;
    const KEY_SCHEMA = "schema_v";
    const KEY_PLAYER_ID = "player_id";
    const KEY_CACHE = "glance_cache";

    function ensureSchema() as Void {
        try {
            var current = Storage.getValue(KEY_SCHEMA);
            if (current == null || !(current instanceof Number) || (current as Number) != STORAGE_SCHEMA_VERSION) {
                Storage.clearValues();
                Storage.setValue(KEY_SCHEMA, STORAGE_SCHEMA_VERSION);
            }
        } catch (ex) {
            // Safe fallback if flash storage is temporarily unavailable.
        }
    }

    function getSelectedPlayerId() as String? {
        ensureSchema();
        try {
            var val = Storage.getValue(KEY_PLAYER_ID);
            if (val instanceof String && (val as String).length() > 0) {
                return val as String;
            }
        } catch (ex) {
        }
        return null;
    }

    function setSelectedPlayerId(playerId as String?) as Void {
        ensureSchema();
        try {
            if (playerId != null && playerId.length() > 0) {
                Storage.setValue(KEY_PLAYER_ID, playerId);
            } else {
                Storage.deleteValue(KEY_PLAYER_ID);
            }
        } catch (ex) {
        }
    }

    function loadCachedSnapshot() as Dictionary? {
        ensureSchema();
        try {
            var val = Storage.getValue(KEY_CACHE);
            if (val instanceof Dictionary) {
                return val as Dictionary;
            }
        } catch (ex) {
        }
        return null;
    }

    function saveCachedSnapshot(cache as Dictionary) as Void {
        ensureSchema();
        try {
            Storage.setValue(KEY_CACHE, cache);
        } catch (ex) {
        }
    }
}

// Domain aggregate representing the active player's playback state.
class PlaybackState {
    public var playerId as String = "";
    public var playerName as String = "";
    public var state as String = "idle";
    public var volume as Number? = null;
    public var muted as Boolean = false;
    public var title as String = "";
    public var artist as String = "";
    public var album as String = "";
    public var elapsedSec as Number = 0;
    public var durationSec as Number = 0;
    public var repeatMode as String = "off";
    public var shuffle as Boolean = false;
    public var favorite as Boolean = false;
    public var nextTitle as String = "";
    public var fetchedAtEpoch as Number = 0;

    // Capability flags computed server-side from MA PlayerFeature + active queue.
    public var canVol as Boolean = true;
    public var canMute as Boolean = true;
    public var canSeek as Boolean = false;
    public var hasQueue as Boolean = false;
    public var canRepeat as Boolean = false;
    public var canShuffle as Boolean = false;
    public var canFav as Boolean = false;
    public var isGroup as Boolean = false;

    function initialize() {
    }

    function isPlaying() as Boolean {
        return state.equals("playing");
    }

    function displayElapsedSec() as Number {
        if (!isPlaying() || fetchedAtEpoch <= 0) {
            return elapsedSec;
        }
        var now = Time.now().value();
        var delta = now - fetchedAtEpoch;
        if (delta < 0) {
            delta = 0;
        }
        var current = elapsedSec + delta;
        if (durationSec > 0 && current > durationSec) {
            return durationSec;
        }
        return current;
    }

    function remainingSec() as Number {
        if (durationSec <= 0) {
            return 0;
        }
        var rem = durationSec - displayElapsedSec();
        return rem > 0 ? rem : 0;
    }

    // Optimistic local mutations give instant feedback while BLE HTTP is in flight.
    function applyOptimistic(action as String, value as Object?) as Void {
        if (action.equals("play_pause")) {
            if (isPlaying()) {
                elapsedSec = displayElapsedSec();
                state = "paused";
            } else {
                state = "playing";
                fetchedAtEpoch = Time.now().value();
            }
        } else if (action.equals("play")) {
            state = "playing";
            fetchedAtEpoch = Time.now().value();
        } else if (action.equals("pause")) {
            elapsedSec = displayElapsedSec();
            state = "paused";
        } else if (action.equals("stop")) {
            state = "idle";
            elapsedSec = 0;
        } else if (action.equals("repeat")) {
            if (value instanceof String && !((value as String).equals("cycle"))) {
                repeatMode = value as String;
            } else if (repeatMode.equals("off")) {
                repeatMode = "all";
            } else if (repeatMode.equals("all")) {
                repeatMode = "one";
            } else {
                repeatMode = "off";
            }
        } else if (action.equals("shuffle")) {
            shuffle = (value instanceof Boolean) ? (value as Boolean) : !shuffle;
        } else if (action.equals("mute")) {
            muted = (value instanceof Boolean) ? (value as Boolean) : !muted;
        } else if (action.equals("volume_set") && value instanceof Number) {
            volume = clampInt(value as Number, 0, 100);
        } else if (action.equals("favorite")) {
            favorite = true;
        }
    }

    function toCacheDict() as Dictionary {
        return {
            "id" => playerId,
            "n" => playerName,
            "s" => state,
            "t" => title,
            "a" => artist,
            "ts" => Time.now().value()
        };
    }

    static function fromDict(raw as Dictionary) as PlaybackState {
        var ps = new PlaybackState();
        ps.playerId = readStr(raw, "id", "");
        ps.playerName = readStr(raw, "n", "Player");
        ps.state = readStr(raw, "s", "idle");
        ps.volume = readNullableInt(raw, "v");
        ps.muted = readBool(raw, "m", false);
        ps.title = readStr(raw, "t", "");
        ps.artist = readStr(raw, "a", "");
        ps.album = readStr(raw, "al", "");
        ps.elapsedSec = readInt(raw, "el", 0);
        ps.durationSec = readInt(raw, "du", 0);
        ps.repeatMode = readStr(raw, "rp", "off");
        ps.shuffle = readBool(raw, "sh", false);
        ps.favorite = readBool(raw, "fav", false);
        ps.nextTitle = readStr(raw, "nt", "");
        ps.fetchedAtEpoch = Time.now().value();

        var capsVal = raw.get("caps");
        if (capsVal instanceof Dictionary) {
            var caps = capsVal as Dictionary;
            ps.canVol = readBool(caps, "vol", true);
            ps.canMute = readBool(caps, "mute", true);
            ps.canSeek = readBool(caps, "seek", false);
            ps.hasQueue = readBool(caps, "q", false);
            ps.canRepeat = readBool(caps, "rp", false);
            ps.canShuffle = readBool(caps, "sh", false);
            ps.canFav = readBool(caps, "fav", false);
            ps.isGroup = readBool(caps, "grp", false);
        }
        return ps;
    }

    static function clampInt(val as Number, minVal as Number, maxVal as Number) as Number {
        if (val < minVal) {
            return minVal;
        }
        if (val > maxVal) {
            return maxVal;
        }
        return val;
    }

    static function formatTime(seconds as Number) as String {
        var s = seconds < 0 ? 0 : seconds;
        var mins = s / 60;
        var rem = s % 60;
        var secStr = rem < 10 ? ("0" + rem.toString()) : rem.toString();
        return mins.toString() + ":" + secStr;
    }

    static function truncateText(text as String, maxLen as Number) as String {
        if (maxLen < 3 || text.length() <= maxLen) {
            return text;
        }
        var prefix = text.substring(0, maxLen - 2);
        return prefix != null ? (prefix + "..") : text;
    }

    static function readStr(d as Dictionary, key as String, fallback as String) as String {
        var v = d.get(key);
        if (v instanceof String) {
            return v as String;
        }
        return fallback;
    }

    static function readInt(d as Dictionary, key as String, fallback as Number) as Number {
        var v = d.get(key);
        if (v instanceof Number) {
            return v as Number;
        }
        if (v instanceof Float) {
            return (v as Float).toNumber();
        }
        if (v instanceof Double) {
            return (v as Double).toNumber();
        }
        return fallback;
    }

    static function readNullableInt(d as Dictionary, key as String) as Number? {
        var v = d.get(key);
        if (v == null) {
            return null;
        }
        if (v instanceof Number) {
            return v as Number;
        }
        if (v instanceof Float) {
            return (v as Float).toNumber();
        }
        return null;
    }

    static function readBool(d as Dictionary, key as String, fallback as Boolean) as Boolean {
        var v = d.get(key);
        if (v instanceof Boolean) {
            return v as Boolean;
        }
        return fallback;
    }
}

// Unified item model shared by Players, Queue, Playlists, and Favorites menus.
class ListItem {
    public var key as String;
    public var title as String;
    public var subtitle as String;
    public var isCurrent as Boolean;

    function initialize(k as String, t as String, sub as String, cur as Boolean) {
        key = k;
        title = t;
        subtitle = sub;
        isCurrent = cur;
    }

    static function fromPlayerDict(d as Dictionary) as ListItem {
        var id = PlaybackState.readStr(d, "id", "");
        var name = PlaybackState.readStr(d, "n", "Player");
        var st = PlaybackState.readStr(d, "s", "idle");
        var vol = PlaybackState.readNullableInt(d, "v");
        var isPhone = PlaybackState.readBool(d, "ph", false);
        var isGroup = PlaybackState.readBool(d, "g", false);
        var tag = isPhone ? "Phone" : (isGroup ? "Group" : "Speaker");
        var volStr = vol != null ? (" " + vol.toString() + "%") : "";
        var sub = tag + " - " + st + volStr;
        return new ListItem(id, name, sub, st.equals("playing"));
    }

    static function fromItemDict(d as Dictionary) as ListItem {
        return new ListItem(
            PlaybackState.readStr(d, "k", ""),
            PlaybackState.readStr(d, "t", "Untitled"),
            PlaybackState.readStr(d, "sub", ""),
            PlaybackState.readBool(d, "c", false)
        );
    }
}
