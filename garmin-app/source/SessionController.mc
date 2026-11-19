import Toybox.Attention;
import Toybox.Lang;
import Toybox.Timer;
import Toybox.WatchUi;

// Coordinates domain PlaybackState, single-flight ApiClient, debouncing, and adaptive polling.
class SessionController {
    private const DEBOUNCE_MS = 350;
    private const SETTLE_FOLLOWUP_MS = 1500;

    public var config as AppConfig;
    public var diag as DiagnosticsLog;
    public var api as ApiClient;
    public var state as PlaybackState? = null;
    public var selectedPlayerId as String? = null;
    public var statusMessage as String = "";
    public var isLoading as Boolean = false;

    private var _pollTimer as Timer.Timer = new Timer.Timer();
    private var _tickTimer as Timer.Timer = new Timer.Timer();
    private var _debounceTimer as Timer.Timer = new Timer.Timer();
    private var _settleTimer as Timer.Timer = new Timer.Timer();

    private var _appActive as Boolean = false;
    private var _nowPlayingVisible as Boolean = false;
    private var _commandEpoch as Number = 0;
    private var _inflightStateEpoch as Number = -1;
    private var _inflightActionEpoch as Number = -1;

    private var _pendingVolTarget as Number? = null;
    private var _pendingSeekDelta as Number = 0;

    function initialize() {
        config = new AppConfig();
        diag = new DiagnosticsLog();
        api = new ApiClient(config, diag);
        selectedPlayerId = StorageStore.getSelectedPlayerId();
        if (selectedPlayerId == null && config.preferredPlayerId.length() > 0) {
            selectedPlayerId = config.preferredPlayerId;
        }
    }

    function onAppStart() as Void {
        _appActive = true;
    }

    function onAppStop() as Void {
        _appActive = false;
        _nowPlayingVisible = false;
        _pollTimer.stop();
        _tickTimer.stop();
        _debounceTimer.stop();
        _settleTimer.stop();
    }

    function onNowPlayingShow() as Void {
        _nowPlayingVisible = true;
        _tickTimer.stop();
        _tickTimer.start(method(:onProgressTick), 1000, true);
        if (_pendingVolTarget == null && _pendingSeekDelta == 0) {
            refreshState(false);
        }
    }

    function onNowPlayingHide() as Void {
        // Only pause 1s UI progress redraws; keep poll/debounce/settle timers alive for Volume/Menus.
        _nowPlayingVisible = false;
        _tickTimer.stop();
    }

    function reloadConfigAndRefresh() as Void {
        config.reload();
        if (config.preferredPlayerId.length() > 0) {
            selectedPlayerId = config.preferredPlayerId;
            StorageStore.setSelectedPlayerId(selectedPlayerId);
        }
        statusMessage = "";
        _commandEpoch++;
        refreshState(true);
    }

    function vibrateShort() as Void {
        if (config.vibrateFeedback && Attention has :vibrate) {
            Attention.vibrate([ new Attention.VibeProfile(40, 45) ]);
        }
    }

    function selectPlayer(playerId as String) as Void {
        selectedPlayerId = playerId;
        StorageStore.setSelectedPlayerId(playerId);
        _commandEpoch++;
        refreshState(true);
    }

    function refreshState(force as Boolean) as Void {
        if (!config.isConfigured()) {
            statusMessage = "";
            WatchUi.requestUpdate();
            return;
        }
        var epochAtDispatch = _commandEpoch;
        if (api.getState(selectedPlayerId, method(:onStateResponse), force)) {
            _inflightStateEpoch = epochAtDispatch;
            isLoading = (state == null);
            WatchUi.requestUpdate();
        } else {
            scheduleAdaptivePoll();
        }
    }

    function sendAction(action as String, value as Object?) as Void {
        if (!config.isConfigured()) {
            return;
        }
        vibrateShort();
        _commandEpoch++;
        var epoch = _commandEpoch;
        _pollTimer.stop();
        _settleTimer.stop();

        if (state != null) {
            (state as PlaybackState).applyOptimistic(action, value);
            WatchUi.requestUpdate();
        }

        var pid = (state != null && (state as PlaybackState).playerId.length() > 0)
            ? (state as PlaybackState).playerId
            : selectedPlayerId;
        if (api.postAction(pid, action, value, method(:onActionResponse))) {
            _inflightActionEpoch = epoch;
        }
    }

    // Coalesces rapid UP/DOWN clicks over 350ms into a single absolute volume_set RPC.
    function adjustVolume(deltaSteps as Number) as Void {
        if (state == null) {
            return;
        }
        var ps = state as PlaybackState;
        var baseVol = _pendingVolTarget != null
            ? (_pendingVolTarget as Number)
            : (ps.volume != null ? (ps.volume as Number) : 50);
        var nextVol = PlaybackState.clampInt(baseVol + (deltaSteps * config.volumeStep), 0, 100);
        _pendingVolTarget = nextVol;
        ps.volume = nextVol;
        ps.muted = false;
        vibrateShort();
        WatchUi.requestUpdate();

        _debounceTimer.stop();
        _debounceTimer.start(method(:onDebounceFire), DEBOUNCE_MS, false);
    }

    // Coalesces rapid seek steps over 350ms into one relative seek RPC.
    function adjustSeek(direction as Number) as Void {
        _pendingSeekDelta += direction * config.seekStepSec;
        vibrateShort();
        _debounceTimer.stop();
        _debounceTimer.start(method(:onDebounceFire), DEBOUNCE_MS, false);
    }

    function flushPendingAdjustments() as Void {
        _debounceTimer.stop();
        onDebounceFire();
    }

    function onDebounceFire() as Void {
        if (_pendingVolTarget != null) {
            var target = _pendingVolTarget as Number;
            _pendingVolTarget = null;
            sendAction("volume_set", target);
        }
        if (_pendingSeekDelta != 0) {
            var delta = _pendingSeekDelta;
            _pendingSeekDelta = 0;
            sendAction("seek", { "delta" => delta });
        }
    }

    function onStateResponse(ok as Boolean, code as Number, data as Dictionary?, errMsg as String) as Void {
        isLoading = false;
        // Ignore stale poll responses that finished after a newer command or player switch.
        if (_inflightStateEpoch != _commandEpoch) {
            scheduleAdaptivePoll();
            return;
        }
        if (ok && data != null) {
            applyServerSnapshot(data);
        } else {
            handleError(code, errMsg);
        }
        scheduleAdaptivePoll();
        WatchUi.requestUpdate();
    }

    function onActionResponse(ok as Boolean, code as Number, data as Dictionary?, errMsg as String) as Void {
        isLoading = false;
        if (ok && data != null) {
            // Only apply snapshot if no newer user command/volume edit superseded this action.
            if (_inflightActionEpoch == _commandEpoch && _pendingVolTarget == null) {
                applyServerSnapshot(data);
                var settled = PlaybackState.readBool(data, "settled", true);
                if (!settled && _appActive) {
                    _settleTimer.stop();
                    _settleTimer.start(method(:onSettleFollowup), SETTLE_FOLLOWUP_MS, false);
                }
            }
        } else {
            handleError(code, errMsg);
            // Roll back failed optimistic UI by scheduling a clean server refresh.
            if (_appActive && code != 401 && code != 403 && code != -104 && code != -1001) {
                _settleTimer.stop();
                _settleTimer.start(method(:onSettleFollowup), SETTLE_FOLLOWUP_MS, false);
            }
        }
        scheduleAdaptivePoll();
        WatchUi.requestUpdate();
    }

    function onSettleFollowup() as Void {
        if (_appActive && _pendingVolTarget == null && _pendingSeekDelta == 0) {
            refreshState(false);
        }
    }

    private function applyServerSnapshot(data as Dictionary) as Void {
        var pObj = data.get("p");
        if (pObj instanceof Dictionary) {
            var ps = PlaybackState.fromDict(pObj as Dictionary);
            state = ps;
            statusMessage = "";
            if (ps.playerId.length() > 0) {
                selectedPlayerId = ps.playerId;
                StorageStore.setSelectedPlayerId(ps.playerId);
            }
            StorageStore.saveCachedSnapshot(ps.toCacheDict());
        }
    }

    private function handleError(code as Number, errMsg as String) as Void {
        if (code == 404 && selectedPlayerId != null) {
            selectedPlayerId = null;
            StorageStore.setSelectedPlayerId(null);
        }
        statusMessage = errMsg;
    }

    private function scheduleAdaptivePoll() as Void {
        _pollTimer.stop();
        if (!_appActive || !config.isConfigured()) {
            return;
        }
        var intervalSec = 30;
        if (state != null && (state as PlaybackState).isPlaying()) {
            intervalSec = config.pollIntervalSec;
            var rem = (state as PlaybackState).remainingSec();
            if (rem > 0 && rem + 2 < intervalSec) {
                intervalSec = rem + 2;
            }
        }
        if (intervalSec < 3) {
            intervalSec = 3;
        }
        _pollTimer.start(method(:onPollTimer), intervalSec * 1000, false);
    }

    function onPollTimer() as Void {
        if (_appActive && _pendingVolTarget == null && _pendingSeekDelta == 0) {
            refreshState(false);
        }
    }

    function onProgressTick() as Void {
        if (_nowPlayingVisible && state != null && (state as PlaybackState).isPlaying()) {
            WatchUi.requestUpdate();
        }
    }
}
