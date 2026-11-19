import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;

// Flat Actions Menu (stack depth <= 3) gating items on server-provided capability flags.
module ActionsMenuFactory {
    function build(ctrl as SessionController) as WatchUi.Menu2 {
        var menu = new WatchUi.Menu2({ :title => "Controls" });
        var ps = ctrl.state;

        if (ps == null || ps.canVol) {
            var volSub = (ps != null && ps.muted)
                ? "Muted"
                : (ps != null && ps.volume != null ? ((ps.volume as Number).toString() + "%") : "--");
            menu.addItem(new WatchUi.MenuItem("Volume", volSub, :volume, null));
        }
        if (ps == null || ps.canRepeat) {
            var rpLabel = ps != null ? formatRepeat(ps.repeatMode) : "Off";
            menu.addItem(new WatchUi.MenuItem("Repeat", rpLabel, :repeat, null));
        }
        if (ps == null || ps.canShuffle) {
            menu.addItem(new WatchUi.ToggleMenuItem("Shuffle", null, :shuffle, ps != null ? ps.shuffle : false, null));
        }
        if (ps != null && ps.canSeek) {
            var step = ctrl.config.seekStepSec.toString() + "s";
            menu.addItem(new WatchUi.MenuItem("Seek +" + step, null, :seek_fwd, null));
            menu.addItem(new WatchUi.MenuItem("Seek -" + step, null, :seek_back, null));
        }
        if (ps != null && ps.canFav) {
            menu.addItem(new WatchUi.MenuItem("Favorite Track", ps.favorite ? "Favorited" : null, :favorite, null));
        }

        menu.addItem(new WatchUi.MenuItem("Switch Player", ps != null ? ps.playerName : null, :players, null));
        if (ps == null || ps.hasQueue) {
            menu.addItem(new WatchUi.MenuItem("Queue", ps != null && ps.nextTitle.length() > 0 ? ("Next: " + ps.nextTitle) : null, :queue, null));
        }
        menu.addItem(new WatchUi.MenuItem("Playlists", null, :playlists, null));
        menu.addItem(new WatchUi.MenuItem("Favorites", null, :favorites, null));
        menu.addItem(new WatchUi.MenuItem("Stop", null, :stop, null));
        menu.addItem(new WatchUi.MenuItem("Refresh Now", null, :refresh, null));
        menu.addItem(new WatchUi.MenuItem("Diagnostics", null, :diagnostics, null));
        return menu;
    }

    function formatRepeat(mode as String) as String {
        if (mode.equals("all")) {
            return "All";
        }
        if (mode.equals("one")) {
            return "One";
        }
        return "Off";
    }
}

class ActionsMenuDelegate extends WatchUi.Menu2InputDelegate {
    private var _ctrl as SessionController;

    function initialize(ctrl as SessionController) {
        Menu2InputDelegate.initialize();
        _ctrl = ctrl;
    }

    function onSelect(item as WatchUi.MenuItem) as Void {
        var id = item.getId();
        if (id == :volume) {
            WatchUi.pushView(new VolumeView(_ctrl), new VolumeDelegate(_ctrl), WatchUi.SLIDE_LEFT);
        } else if (id == :repeat) {
            _ctrl.sendAction("repeat", "cycle");
            if (_ctrl.state != null) {
                item.setSubLabel(ActionsMenuFactory.formatRepeat((_ctrl.state as PlaybackState).repeatMode));
            }
        } else if (id == :shuffle) {
            var enabled = (item instanceof WatchUi.ToggleMenuItem) ? (item as WatchUi.ToggleMenuItem).isEnabled() : true;
            _ctrl.sendAction("shuffle", enabled);
        } else if (id == :seek_fwd) {
            _ctrl.adjustSeek(1);
        } else if (id == :seek_back) {
            _ctrl.adjustSeek(-1);
        } else if (id == :favorite) {
            _ctrl.sendAction("favorite", null);
            item.setSubLabel("Saving...");
        } else if (id == :players) {
            ItemListMenuFactory.open(_ctrl, "players", true);
        } else if (id == :queue) {
            ItemListMenuFactory.open(_ctrl, "queue", true);
        } else if (id == :playlists) {
            ItemListMenuFactory.open(_ctrl, "playlists", true);
        } else if (id == :favorites) {
            ItemListMenuFactory.open(_ctrl, "favorites", true);
        } else if (id == :stop) {
            _ctrl.sendAction("stop", null);
            WatchUi.popView(WatchUi.SLIDE_RIGHT);
        } else if (id == :refresh) {
            _ctrl.refreshState(true);
            WatchUi.popView(WatchUi.SLIDE_RIGHT);
        } else if (id == :diagnostics) {
            var diagView = new DiagnosticsView(_ctrl);
            WatchUi.pushView(diagView, new DiagnosticsDelegate(diagView), WatchUi.SLIDE_LEFT);
        }
    }

    function onBack() as Void {
        _ctrl.flushPendingAdjustments();
        WatchUi.popView(WatchUi.SLIDE_RIGHT);
    }
}

// Single DRY paginated Menu2 serving Players, Queue, Playlists, and Favorites.
module ItemListMenuFactory {
    function open(ctrl as SessionController, kind as String, replaceTop as Boolean) as Void {
        var title = "Players";
        if (kind.equals("queue")) {
            title = "Queue";
        } else if (kind.equals("playlists")) {
            title = "Playlists";
        } else if (kind.equals("favorites")) {
            title = "Favorites";
        }
        var menu = new WatchUi.Menu2({ :title => title });
        menu.addItem(new WatchUi.MenuItem("Loading...", null, :loading, null));
        var delegate = new ItemListMenuDelegate(ctrl, kind, menu);
        if (replaceTop) {
            WatchUi.switchToView(menu, delegate, WatchUi.SLIDE_LEFT);
        } else {
            WatchUi.pushView(menu, delegate, WatchUi.SLIDE_LEFT);
        }
        delegate.loadPage(0);
    }
}

class ItemListMenuDelegate extends WatchUi.Menu2InputDelegate {
    private const PAGE_SIZE = 10;

    private var _ctrl as SessionController;
    private var _kind as String;
    private var _menu as WatchUi.Menu2;
    private var _offset as Number = 0;
    private var _total as Number = 0;
    private var _items as Array<ListItem> = [] as Array<ListItem>;

    function initialize(ctrl as SessionController, kind as String, menu as WatchUi.Menu2) {
        Menu2InputDelegate.initialize();
        _ctrl = ctrl;
        _kind = kind;
        _menu = menu;
    }

    function loadPage(offset as Number) as Void {
        _offset = offset;
        if (_kind.equals("players")) {
            _ctrl.api.getPlayers(offset, PAGE_SIZE, method(:onPageLoaded));
        } else {
            _ctrl.api.getItems(_kind, _ctrl.selectedPlayerId, offset, PAGE_SIZE, method(:onPageLoaded));
        }
    }

    function onPageLoaded(ok as Boolean, code as Number, data as Dictionary?, errMsg as String) as Void {
        if (!ok || data == null) {
            if (_items.size() == 0) {
                clearMenu();
            }
            _menu.addItem(new WatchUi.MenuItem("Retry Load", ErrorMapper.singleLine(errMsg), :retry, null));
            WatchUi.requestUpdate();
            return;
        }

        _total = PlaybackState.readInt(data, "total", 0);
        if (_offset == 0) {
            _items = [] as Array<ListItem>;
        }

        var added = 0;
        var rawItems = data.get("items");
        if (rawItems instanceof Array) {
            var arr = rawItems as Array;
            for (var i = 0; i < arr.size(); i++) {
                if (arr[i] instanceof Dictionary) {
                    var entry = _kind.equals("players")
                        ? ListItem.fromPlayerDict(arr[i] as Dictionary)
                        : ListItem.fromItemDict(arr[i] as Dictionary);
                    _items.add(entry);
                    added++;
                }
            }
        }

        clearMenu();
        if (_items.size() == 0) {
            _menu.addItem(new WatchUi.MenuItem("Empty", "No items found", :noop, null));
        } else {
            for (var j = 0; j < _items.size(); j++) {
                var li = _items[j];
                var label = li.isCurrent ? ("> " + li.title) : li.title;
                _menu.addItem(new WatchUi.MenuItem(label, li.subtitle.length() > 0 ? li.subtitle : null, j, null));
            }
            if (added > 0 && _items.size() < _total) {
                _menu.addItem(new WatchUi.MenuItem("Load More...", _items.size().toString() + "/" + _total.toString(), :load_more, null));
            }
        }
        WatchUi.requestUpdate();
    }

    function onSelect(item as WatchUi.MenuItem) as Void {
        var id = item.getId();
        if (id == :retry) {
            loadPage(_offset);
            return;
        }
        if (id == :load_more) {
            loadPage(_items.size());
            return;
        }
        if (!(id instanceof Number)) {
            return;
        }
        var idx = id as Number;
        if (idx < 0 || idx >= _items.size()) {
            return;
        }
        var chosen = _items[idx];
        if (_kind.equals("players")) {
            _ctrl.selectPlayer(chosen.key);
        } else if (_kind.equals("queue")) {
            var qIdx = chosen.key.toNumber();
            if (qIdx != null) {
                _ctrl.sendAction("play_index", qIdx);
            }
        } else {
            _ctrl.sendAction("play_media", chosen.key);
        }
        WatchUi.popView(WatchUi.SLIDE_RIGHT);
    }

    function onBack() as Void {
        WatchUi.popView(WatchUi.SLIDE_RIGHT);
    }

    private function clearMenu() as Void {
        while (_menu.deleteItem(0) == true) {
        }
    }
}

// On-watch staged connection tester & failure ring-buffer viewer.
class DiagnosticsView extends WatchUi.View {
    private var _ctrl as SessionController;
    private var _testResult as String = "Press START to test";

    function initialize(ctrl as SessionController) {
        View.initialize();
        _ctrl = ctrl;
    }

    function runConnectionTest() as Void {
        if (!_ctrl.config.isConfigured()) {
            _testResult = "Missing URL or token";
            WatchUi.requestUpdate();
            return;
        }
        if (!_ctrl.config.isHttps()) {
            _testResult = "FAIL: URL must be https://";
            WatchUi.requestUpdate();
            return;
        }
        if (!System.getDeviceSettings().phoneConnected) {
            _testResult = "FAIL: Phone BLE offline";
            WatchUi.requestUpdate();
            return;
        }
        _testResult = "Testing /health...";
        WatchUi.requestUpdate();
        _ctrl.api.getHealth(method(:onHealthTested));
    }

    function onHealthTested(ok as Boolean, code as Number, data as Dictionary?, errMsg as String) as Void {
        if (ok && data != null) {
            var apiVer = PlaybackState.readInt(data, "api_version", 0);
            var maVer = PlaybackState.readStr(data, "ma_version", "?");
            _testResult = "OK v" + apiVer.toString() + " MA " + maVer + " (" + _ctrl.diag.lastRttMs.toString() + "ms)";
        } else {
            _testResult = "FAIL " + code.toString() + ": " + ErrorMapper.singleLine(errMsg);
        }
        WatchUi.requestUpdate();
    }

    function onUpdate(dc as Dc) as Void {
        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;

        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();

        dc.setColor(Graphics.COLOR_BLUE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 10) / 100, Graphics.FONT_TINY, "Diagnostics", Graphics.TEXT_JUSTIFY_CENTER);

        var ble = System.getDeviceSettings().phoneConnected ? "BLE: OK" : "BLE: OFF";
        var httpsStr = _ctrl.config.isHttps() ? "TLS: HTTPS" : "TLS: NON-HTTPS";
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 24) / 100, Graphics.FONT_XTINY, ble + "  " + httpsStr, Graphics.TEXT_JUSTIFY_CENTER);
        dc.drawText(cx, (h * 35) / 100, Graphics.FONT_XTINY, PlaybackState.truncateText(_testResult, 28), Graphics.TEXT_JUSTIFY_CENTER);

        var lastLine = "Last: " + _ctrl.diag.lastStatus.toString() + " (" + _ctrl.diag.lastRttMs.toString() + "ms)";
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 52) / 100, Graphics.FONT_XTINY, lastLine, Graphics.TEXT_JUSTIFY_CENTER);

        var entries = _ctrl.diag.getEntries();
        if (entries.size() > 0) {
            var recent = entries[entries.size() - 1];
            dc.setColor(Graphics.COLOR_ORANGE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 64) / 100, Graphics.FONT_XTINY, PlaybackState.truncateText(recent, 26), Graphics.TEXT_JUSTIFY_CENTER);
        }

        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 80) / 100, Graphics.FONT_XTINY, "START: Test  BACK: Close", Graphics.TEXT_JUSTIFY_CENTER);
    }
}

class DiagnosticsDelegate extends WatchUi.BehaviorDelegate {
    private var _view as DiagnosticsView;

    function initialize(view as DiagnosticsView) {
        BehaviorDelegate.initialize();
        _view = view;
    }

    function onSelect() as Boolean {
        _view.runConnectionTest();
        return true;
    }

    function onBack() as Boolean {
        WatchUi.popView(WatchUi.SLIDE_RIGHT);
        return true;
    }
}
