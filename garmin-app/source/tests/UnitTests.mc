import Toybox.Lang;
import Toybox.Test;

// Connect IQ Run No Evil (:test) unit tests for domain models, URL hygiene, and error mapping.
(:test)
function testNormalizeUrlStripsWhitespaceAndSlashes(logger as Logger) as Boolean {
    var normalized = AppConfig.normalizeUrl("  https://ma.example.com///  ");
    Test.assertEqual(normalized, "https://ma.example.com");
    Test.assertEqual(AppConfig.trimString("\t token123 \n"), "token123");
    return true;
}

(:test)
function testPlaybackStateParsesCompactPayloadAndIgnoresUnknownKeys(logger as Logger) as Boolean {
    var raw = {
        "id" => "sendspin_phone_1",
        "n" => "Ryan Phone",
        "s" => "playing",
        "v" => 70,
        "m" => false,
        "t" => "Midnight City",
        "a" => "M83",
        "al" => "Hurry Up",
        "el" => 42,
        "du" => 240,
        "rp" => "all",
        "sh" => true,
        "fav" => false,
        "nt" => "Intro",
        "future_field" => "ignored",
        "caps" => {
            "vol" => true,
            "mute" => true,
            "seek" => true,
            "q" => true,
            "rp" => true,
            "sh" => true,
            "fav" => true,
            "grp" => false
        }
    };
    var ps = PlaybackState.fromDict(raw);
    Test.assertEqual(ps.playerId, "sendspin_phone_1");
    Test.assertEqual(ps.title, "Midnight City");
    Test.assertEqual(ps.volume, 70);
    Test.assertEqual(ps.repeatMode, "all");
    Test.assert(ps.shuffle);
    Test.assert(ps.canSeek);
    Test.assertEqual(PlaybackState.formatTime(65), "1:05");
    return true;
}

(:test)
function testOptimisticRepeatCycleAndVolumeClamp(logger as Logger) as Boolean {
    var ps = new PlaybackState();
    ps.repeatMode = "off";
    ps.applyOptimistic("repeat", "cycle");
    Test.assertEqual(ps.repeatMode, "all");
    ps.applyOptimistic("repeat", "cycle");
    Test.assertEqual(ps.repeatMode, "one");
    ps.applyOptimistic("repeat", "cycle");
    Test.assertEqual(ps.repeatMode, "off");

    ps.applyOptimistic("volume_set", 150);
    Test.assertEqual(ps.volume, 100);
    ps.applyOptimistic("volume_set", -20);
    Test.assertEqual(ps.volume, 0);
    return true;
}

(:test)
function testErrorMapperCoversCriticalConnectIqAndHttpCodes(logger as Logger) as Boolean {
    Test.assert(ErrorMapper.describe(-1001, null).find("HTTPS") != null);
    Test.assert(ErrorMapper.describe(-104, null).find("Bluetooth") != null);
    Test.assert(ErrorMapper.describe(401, null).find("401") != null);
    Test.assert(ErrorMapper.describe(404, null).find("404") != null);
    return true;
}
