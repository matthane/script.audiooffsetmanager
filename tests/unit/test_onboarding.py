"""Unit tests for aom.onboarding's test-video stop guard.

The 5s stop in ``play_test_video`` fires on wall time, not on a playback
handle, so it must verify the bundled test video is still the playing item
before stopping (a blind ``Player().stop()`` could kill playback the user
started inside the window — the legacy behavior).

Kodi is faked via Kodistubs; ``xbmc.Player`` is monkeypatched with a
scriptable fake so the guard's decision is pinned without real playback.
"""

import pytest

import resources.lib.aom.onboarding as onboarding


class FakePlayer:
    """Scriptable xbmc.Player: what is playing (or a raise), and the stops."""

    def __init__(self):
        self.playing_file = None      # None = nothing playing
        self.raises = False           # getPlayingFile raises (stop race)
        self.played = []
        self.stopped = 0

    def play(self, path):
        self.played.append(path)
        self.playing_file = path

    def isPlaying(self):
        return self.raises or self.playing_file is not None

    def getPlayingFile(self):
        if self.raises:
            raise RuntimeError('XBMCAddon: no file playing')
        return self.playing_file

    def stop(self):
        self.stopped += 1
        self.playing_file = None


TEST_PATH = 'addons/script.audiooffsetmanager/resources/media/test-video.mp4'


@pytest.fixture
def rig(monkeypatch):
    """(onboarding instance, fake player): one shared player instance so the
    guard sees the same state play() produced."""
    player = FakePlayer()
    monkeypatch.setattr(onboarding.xbmc, 'Player', lambda: player)
    onb = onboarding._Onboarding()
    onb._test_video_path = TEST_PATH
    return onb, player


class TestStopGuard:

    def test_stops_while_test_video_still_playing(self, rig):
        onb, player = rig
        player.playing_file = TEST_PATH
        onb._stop_if_still_test_video()
        assert player.stopped == 1

    def test_path_comparison_is_separator_normalized(self, rig):
        # Kodi may report the path with redundant or mixed separators; the
        # comparison is normpath/normcase-based, not string equality.
        onb, player = rig
        player.playing_file = TEST_PATH.replace('/resources/',
                                                '//resources/./')
        onb._stop_if_still_test_video()
        assert player.stopped == 1

    def test_leaves_other_playback_alone(self, rig):
        # The user started something else inside the 5s window: never stop it.
        onb, player = rig
        player.playing_file = 'videodb://movies/titles/42'
        onb._stop_if_still_test_video()
        assert player.stopped == 0

    def test_no_stop_when_nothing_is_playing(self, rig):
        # The test video failed to open (or already ended): nothing to stop.
        onb, player = rig
        player.playing_file = None
        onb._stop_if_still_test_video()
        assert player.stopped == 0

    def test_raise_reads_as_not_ours(self, rig):
        # isPlaying/getPlayingFile can race a natural stop; a raise must be
        # treated as "not our video", never propagate out of the script.
        onb, player = rig
        player.raises = True
        onb._stop_if_still_test_video()
        assert player.stopped == 0


class TestPlayFlowWiring:

    def test_happy_path_plays_then_stops_the_test_video(self, rig, monkeypatch):
        # The full flow still stops the test video when it is (still) the
        # playing item — the guard replaced the blind stop, not the stop.
        onb, player = rig
        monkeypatch.setattr(onboarding.xbmcvfs, 'exists', lambda path: True)
        monkeypatch.setattr(onboarding.xbmc, 'sleep', lambda ms: None)
        monkeypatch.setattr(onboarding.xbmc, 'executebuiltin', lambda cmd: None)

        onb.play_test_video()

        assert player.played == [onb._test_video_path]
        assert player.stopped == 1

    def test_flow_spares_playback_started_inside_the_window(self, rig,
                                                            monkeypatch):
        # Regression pin for the review finding: the user starts a different
        # item during the 5s wait; the flow must not stop it.
        onb, player = rig
        monkeypatch.setattr(onboarding.xbmcvfs, 'exists', lambda path: True)
        monkeypatch.setattr(
            onboarding.xbmc, 'sleep',
            lambda ms: player.play('videodb://movies/titles/42'))
        monkeypatch.setattr(onboarding.xbmc, 'executebuiltin', lambda cmd: None)

        onb.play_test_video()

        assert player.stopped == 0
        assert player.playing_file == 'videodb://movies/titles/42'
