"""Behavioral tests for aom.kodi.settings (Settings + OffsetTable).

Kodi is faked via Kodistubs: ``xbmcaddon.Addon(...).getSettings()`` yields a
stub ``Settings`` object whose ``getBool``/``getInt``/``setBool``/``setInt`` we
spy or monkeypatch per test. Log-sink calls are collected in a list of
``(message, level)`` tuples so assertions can pin both the message text and the
Kodi log level. No fixtures beyond ``monkeypatch``.
"""

import xbmc

from resources.lib.aom.kodi.settings import ADDON_ID, Settings, OffsetTable
from resources.lib.aom.domain.profile import StreamProfile


# --- helpers -----------------------------------------------------------------

def _make_settings():
    """Build a Settings with a list-collecting log sink. Returns (settings, logs)."""
    logs = []
    settings = Settings(log=lambda message, level=None: logs.append((message, level)))
    return settings, logs


def _profile(hdr='dolbyvision', fps='all', audio='truehd'):
    return StreamProfile(
        hdr_type=hdr,
        fps_type=fps,
        audio_format=audio,
        video_fps=24,
        player_id=1,
        audio_channels=8,
    )


class _Spy:
    """Records calls; returns ``result`` or raises ``raises`` when invoked."""

    def __init__(self, result=None, raises=None):
        self.result = result
        self.raises = raises
        self.calls = []

    def __call__(self, *args):
        self.calls.append(args)
        if self.raises is not None:
            raise self.raises
        return self.result


def test_addon_id_constant():
    assert ADDON_ID == 'script.audiooffsetmanager'


def test_settings_keeps_parent_addon_alive():
    """Regression pin for the 2.0.0~beta1 field bug (Kodi 21.2/Windows).

    ``xbmcaddon.Addon(...).getSettings()`` as a one-liner leaves the Addon a
    garbage-collected temporary, which orphans the Settings proxy: writes
    report success but never persist and dialog edits never arrive. The
    proxy is live only while its parent Addon is alive, so Settings must
    hold the Addon it derived ``_settings`` from.
    """
    import xbmcaddon

    settings, _ = _make_settings()
    assert isinstance(settings._addon, xbmcaddon.Addon)


# --- get_bool / get_int ------------------------------------------------------

class TestTypedReads:
    def test_get_bool_normal_read(self):
        settings, logs = _make_settings()
        settings._settings.getBool = _Spy(result=True)
        assert settings.get_bool('enable_notifications') is True
        assert logs == []

    def test_get_bool_exception_returns_default_and_warns(self):
        settings, logs = _make_settings()
        settings._settings.getBool = _Spy(raises=RuntimeError("boom"))
        assert settings.get_bool('enable_notifications', default=True) is True
        assert len(logs) == 1
        message, level = logs[0]
        assert level == xbmc.LOGWARNING
        assert "Error getting boolean setting 'enable_notifications'" in message
        assert "Using default: True" in message

    def test_get_bool_default_is_false(self):
        settings, logs = _make_settings()
        settings._settings.getBool = _Spy(raises=ValueError())
        assert settings.get_bool('missing') is False

    def test_get_int_normal_read(self):
        settings, logs = _make_settings()
        settings._settings.getInt = _Spy(result=7)
        assert settings.get_int('notification_seconds') == 7
        assert logs == []

    def test_get_int_exception_returns_default_and_warns(self):
        settings, logs = _make_settings()
        settings._settings.getInt = _Spy(raises=RuntimeError("boom"))
        assert settings.get_int('notification_seconds', default=3) == 3
        assert len(logs) == 1
        message, level = logs[0]
        assert level == xbmc.LOGWARNING
        assert "Error getting integer setting 'notification_seconds'" in message
        assert "Using default: 3" in message

    def test_get_int_default_is_zero(self):
        settings, logs = _make_settings()
        settings._settings.getInt = _Spy(raises=ValueError())
        assert settings.get_int('missing') == 0


# --- store_*_if_changed ------------------------------------------------------

class TestStoreBooleanIfChanged:
    def test_unchanged_skips_write_returns_true(self):
        settings, logs = _make_settings()
        settings._settings.getBool = _Spy(result=True)
        set_spy = _Spy()
        settings._settings.setBool = set_spy
        assert settings.store_boolean_if_changed('enable_notifications', True) is True
        assert set_spy.calls == []
        assert logs == []

    def test_changed_writes_returns_true_and_logs_debug(self):
        settings, logs = _make_settings()
        settings._settings.getBool = _Spy(result=False)
        set_spy = _Spy()
        settings._settings.setBool = set_spy
        assert settings.store_boolean_if_changed('enable_notifications', True) is True
        assert set_spy.calls == [('enable_notifications', True)]
        assert len(logs) == 1
        message, level = logs[0]
        assert level == xbmc.LOGDEBUG
        assert "Storing boolean setting enable_notifications: True" in message

    def test_write_raises_returns_false_and_warns(self):
        settings, logs = _make_settings()
        settings._settings.getBool = _Spy(result=False)
        settings._settings.setBool = _Spy(raises=RuntimeError("no dice"))
        assert settings.store_boolean_if_changed('enable_notifications', True) is False
        # LOGDEBUG "Storing" then LOGWARNING "Error storing".
        levels = [level for _, level in logs]
        assert levels == [xbmc.LOGDEBUG, xbmc.LOGWARNING]
        assert "Error storing boolean setting 'enable_notifications'" in logs[-1][0]

    def test_pre_read_raising_falls_through_to_write(self):
        settings, logs = _make_settings()
        # get_bool swallows the read error -> default False; value True differs,
        # so the store falls through to the write attempt (like legacy).
        settings._settings.getBool = _Spy(raises=RuntimeError("read down"))
        set_spy = _Spy()
        settings._settings.setBool = set_spy
        assert settings.store_boolean_if_changed('enable_notifications', True) is True
        assert set_spy.calls == [('enable_notifications', True)]


class TestStoreIntegerIfChanged:
    def test_unchanged_skips_write_returns_true(self):
        settings, logs = _make_settings()
        settings._settings.getInt = _Spy(result=250)
        set_spy = _Spy()
        settings._settings.setInt = set_spy
        assert settings.store_integer_if_changed('dolbyvision_all_truehd', 250) is True
        assert set_spy.calls == []
        assert logs == []

    def test_changed_writes_returns_true_and_logs_debug(self):
        settings, logs = _make_settings()
        settings._settings.getInt = _Spy(result=100)
        set_spy = _Spy()
        settings._settings.setInt = set_spy
        assert settings.store_integer_if_changed('dolbyvision_all_truehd', 250) is True
        assert set_spy.calls == [('dolbyvision_all_truehd', 250)]
        assert len(logs) == 1
        message, level = logs[0]
        assert level == xbmc.LOGDEBUG
        assert "Storing integer setting dolbyvision_all_truehd: 250" in message

    def test_write_raises_returns_false_and_warns(self):
        settings, logs = _make_settings()
        settings._settings.getInt = _Spy(result=100)
        settings._settings.setInt = _Spy(raises=RuntimeError("no dice"))
        assert settings.store_integer_if_changed('dolbyvision_all_truehd', 250) is False
        levels = [level for _, level in logs]
        assert levels == [xbmc.LOGDEBUG, xbmc.LOGWARNING]
        assert "Error storing integer setting 'dolbyvision_all_truehd'" in logs[-1][0]

    def test_pre_read_raising_falls_through_to_write(self):
        settings, logs = _make_settings()
        settings._settings.getInt = _Spy(raises=RuntimeError("read down"))
        set_spy = _Spy()
        settings._settings.setInt = set_spy
        assert settings.store_integer_if_changed('dolbyvision_all_truehd', 250) is True
        assert set_spy.calls == [('dolbyvision_all_truehd', 250)]


# --- intent-level reads ------------------------------------------------------

class TestIntentReads:
    def _spy_bool(self, settings):
        spy = _Spy(result=True)
        settings.get_bool = spy
        return spy

    def _spy_int(self, settings):
        spy = _Spy(result=5)
        settings.get_int = spy
        return spy

    def test_is_hdr_enabled(self):
        settings, _ = _make_settings()
        spy = self._spy_bool(settings)
        assert settings.is_hdr_enabled('dolbyvision') is True
        assert spy.calls == [('enable_dolbyvision',)]

    def test_fps_override_enabled(self):
        settings, _ = _make_settings()
        spy = self._spy_bool(settings)
        assert settings.fps_override_enabled('hdr10') is True
        assert spy.calls == [('enable_fps_hdr10',)]

    def test_active_monitoring_enabled(self):
        settings, _ = _make_settings()
        spy = self._spy_bool(settings)
        assert settings.active_monitoring_enabled() is True
        assert spy.calls == [('enable_active_monitoring',)]

    def test_notifications_enabled(self):
        settings, _ = _make_settings()
        spy = self._spy_bool(settings)
        assert settings.notifications_enabled() is True
        assert spy.calls == [('enable_notifications',)]

    def test_debug_logging_enabled(self):
        settings, _ = _make_settings()
        spy = self._spy_bool(settings)
        assert settings.debug_logging_enabled() is True
        assert spy.calls == [('enable_debug_logging',)]

    def test_seek_back_config_maps_ids(self):
        settings, _ = _make_settings()
        settings.get_bool = _Spy(result=True)
        settings.get_int = _Spy(result=8)
        enabled, seconds = settings.seek_back_config('unpause')
        assert enabled is True
        assert seconds == 8
        assert settings.get_bool.calls == [('enable_seek_back_unpause',)]
        assert settings.get_int.calls == [('seek_back_unpause_seconds',)]

    def test_seek_back_config_clamps_negative_seconds(self):
        settings, _ = _make_settings()
        settings.get_bool = _Spy(result=False)
        settings.get_int = _Spy(result=-4)
        enabled, seconds = settings.seek_back_config('resume')
        assert enabled is False
        assert seconds == 0

    def test_notification_duration_ms_multiplies_by_1000(self):
        settings, _ = _make_settings()
        settings.get_int = _Spy(result=6)
        assert settings.notification_duration_ms() == 6000
        assert settings.get_int.calls == [('notification_seconds',)]


# --- OffsetTable -------------------------------------------------------------

class TestOffsetTable:
    def test_get_derives_setting_id_at_call_time(self):
        settings, _ = _make_settings()
        get_int = _Spy(result=175)
        settings.get_int = get_int
        table = OffsetTable(settings)
        profile = _profile(hdr='hdr10', fps='all', audio='eac3')
        assert table.get(profile) == 175
        assert get_int.calls == [(profile.setting_id(),)]
        assert get_int.calls == [('hdr10_all_eac3',)]

    def test_store_derives_setting_id_at_call_time(self):
        settings, _ = _make_settings()
        store = _Spy(result=True)
        settings.store_integer_if_changed = store
        table = OffsetTable(settings)
        profile = _profile(hdr='sdr', fps='all', audio='ac3')
        assert table.store(profile, 120) is True
        assert store.calls == [(profile.setting_id(), 120)]
        assert store.calls == [('sdr_all_ac3', 120)]
