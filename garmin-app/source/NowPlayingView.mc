import Toybox.Graphics;
import Toybox.Lang;
import Toybox.System;
import Toybox.WatchUi;

// High-contrast 64-color MIP Now Playing screen with proportional round-display layout.
class NowPlayingView extends WatchUi.View {
    private var _ctrl as SessionController;

    function initialize(ctrl as SessionController) {
        View.initialize();
        _ctrl = ctrl;
    }

    function onShow() as Void {
        _ctrl.onNowPlayingShow();
    }

    function onHide() as Void {
        _ctrl.onNowPlayingHide();
    }

    function onUpdate(dc as Dc) as Void {
        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;

        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();

        if (!_ctrl.config.isConfigured()) {
            drawCenteredNotice(dc, w, h, "Setup Required", "Set HTTPS URL & token\nin Connect IQ Store");
            return;
        }

        if (_ctrl.state == null) {
            var body = _ctrl.statusMessage.length() > 0
                ? _ctrl.statusMessage
                : (_ctrl.isLoading ? "Connecting..." : "Hold UP for menu");
            drawCenteredNotice(dc, w, h, "Music Assistant", body);
            return;
        }

        var ps = _ctrl.state as PlaybackState;

        // Top: Active Player Name (tap zone -> Switch Player).
        dc.setColor(Graphics.COLOR_BLUE, Graphics.COLOR_TRANSPARENT);
        var playerLabel = ps.playerName.length() > 0 ? ps.playerName : "Player";
        dc.drawText(cx, (h * 9) / 100, Graphics.FONT_XTINY, PlaybackState.truncateText(playerLabel, 18), Graphics.TEXT_JUSTIFY_CENTER);

        // Status error banner (non-blocking) if latest request failed.
        if (_ctrl.statusMessage.length() > 0) {
            dc.setColor(Graphics.COLOR_ORANGE, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 19) / 100, Graphics.FONT_XTINY, PlaybackState.truncateText(firstLine(_ctrl.statusMessage), 22), Graphics.TEXT_JUSTIFY_CENTER);
        }

        // Center: Track Title & Artist.
        var titleText = ps.title.length() > 0 ? ps.title : (ps.isPlaying() ? "Playing" : "Idle");
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 30) / 100, Graphics.FONT_SMALL, PlaybackState.truncateText(titleText, 20), Graphics.TEXT_JUSTIFY_CENTER);

        if (ps.artist.length() > 0) {
            dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 44) / 100, Graphics.FONT_XTINY, PlaybackState.truncateText(ps.artist, 24), Graphics.TEXT_JUSTIFY_CENTER);
        }

        // Playback transport glyph bar: |<   PLAY/PAUSE   >|
        var transportY = (h * 58) / 100;
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText((w * 18) / 100, transportY, Graphics.FONT_TINY, "|<", Graphics.TEXT_JUSTIFY_CENTER);
        dc.drawText((w * 82) / 100, transportY, Graphics.FONT_TINY, ">|", Graphics.TEXT_JUSTIFY_CENTER);

        dc.setColor(ps.isPlaying() ? Graphics.COLOR_GREEN : Graphics.COLOR_BLUE, Graphics.COLOR_TRANSPARENT);
        var playText = ps.isPlaying() ? "PAUSE" : "PLAY";
        dc.drawText(cx, transportY, Graphics.FONT_SMALL, playText, Graphics.TEXT_JUSTIFY_CENTER);

        // Progress bar + elapsed/duration.
        var barX = (w * 16) / 100;
        var barW = (w * 68) / 100;
        var barY = (h * 72) / 100;
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.fillRectangle(barX, barY, barW, 4);

        var el = ps.displayElapsedSec();
        if (ps.durationSec > 0) {
            var fillW = (barW * el) / ps.durationSec;
            if (fillW > barW) {
                fillW = barW;
            }
            dc.setColor(Graphics.COLOR_BLUE, Graphics.COLOR_TRANSPARENT);
            dc.fillRectangle(barX, barY, fillW, 4);

            var timeStr = PlaybackState.formatTime(el) + " / " + PlaybackState.formatTime(ps.durationSec);
            dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
            dc.drawText(cx, (h * 75) / 100, Graphics.FONT_XTINY, timeStr, Graphics.TEXT_JUSTIFY_CENTER);
        }

        // Bottom strip: Volume, Repeat, Shuffle, Favorite badges.
        var volStr = ps.muted ? "MUTE" : (ps.volume != null ? ("V" + (ps.volume as Number).toString()) : "V--");
        var rpStr = ps.repeatMode.equals("all") ? "R:ALL" : (ps.repeatMode.equals("one") ? "R:1" : "R:OFF");
        var shStr = ps.shuffle ? " SHF" : "";
        var favStr = ps.favorite ? " *" : "";
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 84) / 100, Graphics.FONT_XTINY, volStr + " " + rpStr + shStr + favStr, Graphics.TEXT_JUSTIFY_CENTER);
    }

    private function drawCenteredNotice(dc as Dc, w as Number, h as Number, title as String, body as String) as Void {
        var cx = w / 2;
        dc.setColor(Graphics.COLOR_BLUE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 26) / 100, Graphics.FONT_SMALL, title, Graphics.TEXT_JUSTIFY_CENTER);
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 45) / 100, Graphics.FONT_XTINY, body, Graphics.TEXT_JUSTIFY_CENTER);
        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 78) / 100, Graphics.FONT_XTINY, "Hold UP: Menu", Graphics.TEXT_JUSTIFY_CENTER);
    }

    private function firstLine(text as String) as String {
        var idx = text.find("\n");
        if (idx != null) {
            var line = text.substring(0, idx);
            return line != null ? line : text;
        }
        return text;
    }
}

// Hybrid 5-button + additive touch delegate for Fenix 7.
// Physical START/STOP is handled in onKey(KEY_ENTER) so onSelect() returns false and onTap() receives coordinates.
class NowPlayingDelegate extends WatchUi.BehaviorDelegate {
    private var _ctrl as SessionController;

    function initialize(ctrl as SessionController) {
        BehaviorDelegate.initialize();
        _ctrl = ctrl;
    }

    function onKey(keyEvent as KeyEvent) as Boolean {
        var key = keyEvent.getKey();
        if (key == WatchUi.KEY_ENTER) {
            if (_ctrl.state == null) {
                _ctrl.refreshState(true);
            } else {
                _ctrl.sendAction("play_pause", null);
            }
            return true;
        }
        return false;
    }

    function onSelect() as Boolean {
        // Defer screen taps to onTap(clickEvent); physical START/STOP is handled by onKey(KEY_ENTER).
        return false;
    }

    function onNextPage() as Boolean {
        _ctrl.sendAction("next", null);
        return true;
    }

    function onPreviousPage() as Boolean {
        _ctrl.sendAction("previous", null);
        return true;
    }

    function onMenu() as Boolean {
        WatchUi.pushView(
            ActionsMenuFactory.build(_ctrl),
            new ActionsMenuDelegate(_ctrl),
            WatchUi.SLIDE_LEFT
        );
        return true;
    }

    function onTap(clickEvent as ClickEvent) as Boolean {
        var coords = clickEvent.getCoordinates();
        var x = coords[0];
        var y = coords[1];
        var settings = System.getDeviceSettings();
        var w = settings.screenWidth;
        var h = settings.screenHeight;

        if (_ctrl.state == null) {
            _ctrl.refreshState(true);
            return true;
        }
        // Top strip -> Player Switcher.
        if (y < (h * 24) / 100) {
            ItemListMenuFactory.open(_ctrl, "players", false);
            return true;
        }
        // Bottom strip -> left = Volume, right = Actions Menu.
        if (y > (h * 76) / 100) {
            if (x < w / 2) {
                WatchUi.pushView(new VolumeView(_ctrl), new VolumeDelegate(_ctrl), WatchUi.SLIDE_UP);
            } else {
                onMenu();
            }
            return true;
        }
        // Middle band -> left = Previous, center = Play/Pause, right = Next.
        if (x < (w * 28) / 100) {
            _ctrl.sendAction("previous", null);
        } else if (x > (w * 72) / 100) {
            _ctrl.sendAction("next", null);
        } else {
            _ctrl.sendAction("play_pause", null);
        }
        return true;
    }
}
