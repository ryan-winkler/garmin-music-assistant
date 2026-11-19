import Toybox.Graphics;
import Toybox.Lang;
import Toybox.Time;
import Toybox.WatchUi;

// Strictly offline GlanceView (< 24 KB RAM). Never imports Communications or menus.
// Named MusicAssistantGlanceView to avoid shadowing WatchUi.GlanceView.initialize().
(:glance)
class MusicAssistantGlanceView extends WatchUi.GlanceView {

    function initialize() {
        WatchUi.GlanceView.initialize();
    }

    function onUpdate(dc as Dc) as Void {
        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_BLACK);
        dc.clear();

        var h = dc.getHeight();
        var cache = StorageStore.loadCachedSnapshot();

        var header = "Music Assistant";
        var line2 = "Open to connect";
        var accentColor = Graphics.COLOR_LT_GRAY;

        if (cache != null) {
            var nameObj = cache.get("n");
            var stateObj = cache.get("s");
            var titleObj = cache.get("t");
            var artistObj = cache.get("a");
            var tsObj = cache.get("ts");

            var pName = (nameObj instanceof String && (nameObj as String).length() > 0)
                ? (nameObj as String)
                : "Music Assistant";
            var st = (stateObj instanceof String) ? (stateObj as String) : "idle";
            var badge = st.equals("playing") ? "> " : (st.equals("paused") ? "|| " : "");
            accentColor = st.equals("playing") ? Graphics.COLOR_BLUE : Graphics.COLOR_LT_GRAY;

            var age = formatAge(tsObj);
            header = badge + pName + (age.length() > 0 ? (" " + age) : "");

            var titleStr = (titleObj instanceof String) ? (titleObj as String) : "";
            var artistStr = (artistObj instanceof String) ? (artistObj as String) : "";
            if (titleStr.length() > 0 && artistStr.length() > 0) {
                line2 = titleStr + " - " + artistStr;
            } else if (titleStr.length() > 0) {
                line2 = titleStr;
            } else {
                line2 = st.equals("idle") ? "Idle" : "Ready";
            }
        }

        dc.setColor(accentColor, Graphics.COLOR_TRANSPARENT);
        dc.drawText(
            0,
            (h * 18) / 100,
            Graphics.FONT_GLANCE,
            truncateForGlance(header, 22),
            Graphics.TEXT_JUSTIFY_LEFT
        );

        dc.setColor(Graphics.COLOR_WHITE, Graphics.COLOR_TRANSPARENT);
        dc.drawText(
            0,
            (h * 56) / 100,
            Graphics.FONT_TINY,
            truncateForGlance(line2, 24),
            Graphics.TEXT_JUSTIFY_LEFT
        );
    }

    private function formatAge(tsObj as Object?) as String {
        if (!(tsObj instanceof Number)) {
            return "";
        }
        var diff = Time.now().value() - (tsObj as Number);
        if (diff < 60) {
            return "now";
        }
        var mins = diff / 60;
        if (mins < 60) {
            return mins.toString() + "m";
        }
        var hrs = mins / 60;
        return hrs.toString() + "h";
    }

    private function truncateForGlance(text as String, maxLen as Number) as String {
        if (maxLen < 3 || text.length() <= maxLen) {
            return text;
        }
        var prefix = text.substring(0, maxLen - 2);
        return prefix != null ? (prefix + "..") : text;
    }
}
