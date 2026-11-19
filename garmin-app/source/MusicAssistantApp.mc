import Toybox.Application;
import Toybox.Lang;
import Toybox.WatchUi;

// App entry point shared by Glance and full Watch App.
// Kept free of non-(:glance) type references in initialize/onStart/onStop/getGlanceView
// so Fenix 7 Glance compilation stays under 24 KB RAM under monkeyc -l 3.
class MusicAssistantApp extends Application.AppBase {
    private var _controller as Object? = null;

    function initialize() {
        AppBase.initialize();
    }

    function onStart(state as Dictionary?) as Void {
        AppBase.onStart(state);
    }

    function onStop(state as Dictionary?) as Void {
        if (_controller != null && _controller has :onAppStop) {
            (_controller as SessionController).onAppStop();
        }
        AppBase.onStop(state);
    }

    function onSettingsChanged() as Void {
        if (_controller != null && _controller has :reloadConfigAndRefresh) {
            (_controller as SessionController).reloadConfigAndRefresh();
        }
        WatchUi.requestUpdate();
    }

    (:glance)
    function getGlanceView() as [WatchUi.GlanceView] or [WatchUi.GlanceView, WatchUi.GlanceViewDelegate] or Null {
        return [ new MusicAssistantGlanceView() ];
    }

    function getInitialView() as [WatchUi.Views] or [WatchUi.Views, WatchUi.InputDelegates] {
        var ctrl = new SessionController();
        _controller = ctrl;
        ctrl.onAppStart();
        var view = new NowPlayingView(ctrl);
        var delegate = new NowPlayingDelegate(ctrl);
        return [ view, delegate ];
    }
}
