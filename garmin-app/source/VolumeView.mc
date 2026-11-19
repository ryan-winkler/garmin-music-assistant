import Toybox.Graphics;
import Toybox.Lang;
import Toybox.WatchUi;

// Dedicated Volume screen: UP/DOWN debounce volume_set (350ms), START toggles mute, BACK pops.
class VolumeView extends WatchUi.View {
    private var _ctrl as SessionController;

    function initialize(ctrl as SessionController) {
        View.initialize();
        _ctrl = ctrl;
    }

    function onUpdate(dc as Dc) as Void {
        var w = dc.getWidth();
        var h = dc.getHeight();
        var cx = w / 2;
        var cy = h / 2;
        var radius = (w < h ? w : h) / 2 - 10;

        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();

        var vol = 0;
        var muted = false;
        var label = "Volume";
        if (_ctrl.state != null) {
            var ps = _ctrl.state as PlaybackState;
            vol = ps.volume != null ? (ps.volume as Number) : 0;
            muted = ps.muted;
            label = ps.isGroup ? "Group Vol" : "Volume";
        }

        // Background track arc.
        dc.setPenWidth(8);
        dc.setColor(Graphics.COLOR_DK_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawArc(cx, cy, radius, Graphics.ARC_CLOCKWISE, 225, 315);

        // Filled volume arc (270-degree sweep from 225 deg clockwise).
        if (vol > 0 && !muted) {
            var sweep = (270 * vol) / 100;
            var endDeg = (225 - sweep + 360) % 360;
            dc.setColor(Graphics.COLOR_BLUE, Graphics.COLOR_TRANSPARENT);
            dc.drawArc(cx, cy, radius, Graphics.ARC_CLOCKWISE, 225, endDeg);
        }
        dc.setPenWidth(1);

        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 24) / 100, Graphics.FONT_XTINY, label, Graphics.TEXT_JUSTIFY_CENTER);

        // Use FONT_LARGE / FONT_MEDIUM (not FONT_NUMBER_MEDIUM) so "MUTED" and "%" render on Fenix 7 MIP.
        dc.setColor(muted ? Graphics.COLOR_ORANGE : Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        var valText = muted ? "MUTED" : (vol.toString() + "%");
        var valFont = muted ? Graphics.FONT_MEDIUM : Graphics.FONT_LARGE;
        dc.drawText(cx, (h * 42) / 100, valFont, valText, Graphics.TEXT_JUSTIFY_CENTER);

        dc.setColor(Graphics.COLOR_LT_GRAY, Graphics.COLOR_TRANSPARENT);
        dc.drawText(cx, (h * 74) / 100, Graphics.FONT_XTINY, "UP/DN +/-  START Mute", Graphics.TEXT_JUSTIFY_CENTER);
    }
}

class VolumeDelegate extends WatchUi.BehaviorDelegate {
    private var _ctrl as SessionController;

    function initialize(ctrl as SessionController) {
        BehaviorDelegate.initialize();
        _ctrl = ctrl;
    }

    function onPreviousPage() as Boolean {
        _ctrl.adjustVolume(1);
        return true;
    }

    function onNextPage() as Boolean {
        _ctrl.adjustVolume(-1);
        return true;
    }

    function onSelect() as Boolean {
        _ctrl.flushPendingAdjustments();
        _ctrl.sendAction("mute", "toggle");
        return true;
    }

    function onBack() as Boolean {
        _ctrl.flushPendingAdjustments();
        WatchUi.popView(WatchUi.SLIDE_DOWN);
        return true;
    }
}
