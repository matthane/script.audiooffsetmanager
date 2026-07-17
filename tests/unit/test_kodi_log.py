"""Behavioral tests for aom.kodi.log.KodiLogger.

``xbmc.log`` is monkeypatched with a recorder capturing ``(message, level)``
tuples, so tests pin both the emitted text (prefix rules) and the escalated
level. No fixtures beyond ``monkeypatch``.
"""

import xbmc

from resources.lib.aom.kodi.log import KodiLogger


def _install_recorder(monkeypatch):
    calls = []
    monkeypatch.setattr(xbmc, "log", lambda message, level: calls.append((message, level)))
    return calls


# --- debug escalation --------------------------------------------------------

class TestDebugEscalation:
    def test_debug_escalates_to_info_when_flag_on(self, monkeypatch):
        calls = _install_recorder(monkeypatch)
        KodiLogger(debug_escalation=True)("hello", xbmc.LOGDEBUG)
        assert calls == [("[AOM] hello", xbmc.LOGINFO)]

    def test_debug_stays_debug_when_flag_off(self, monkeypatch):
        calls = _install_recorder(monkeypatch)
        KodiLogger(debug_escalation=False)("hello", xbmc.LOGDEBUG)
        assert calls == [("[AOM] hello", xbmc.LOGDEBUG)]

    def test_default_flag_is_off(self, monkeypatch):
        calls = _install_recorder(monkeypatch)
        KodiLogger()("hello", xbmc.LOGDEBUG)
        assert calls == [("[AOM] hello", xbmc.LOGDEBUG)]

    def test_default_level_is_debug(self, monkeypatch):
        calls = _install_recorder(monkeypatch)
        KodiLogger(debug_escalation=True)("hello")
        assert calls == [("[AOM] hello", xbmc.LOGINFO)]

    def test_flag_refresh_between_calls(self, monkeypatch):
        calls = _install_recorder(monkeypatch)
        logger = KodiLogger(debug_escalation=False)
        logger("first", xbmc.LOGDEBUG)
        logger.debug_escalation = True
        logger("second", xbmc.LOGDEBUG)
        assert calls == [
            ("[AOM] first", xbmc.LOGDEBUG),
            ("[AOM] second", xbmc.LOGINFO),
        ]


# --- non-debug levels are never escalated ------------------------------------

class TestNonDebugLevelsPassThrough:
    def test_warning_not_escalated_regardless_of_flag(self, monkeypatch):
        calls = _install_recorder(monkeypatch)
        KodiLogger(debug_escalation=True)("careful", xbmc.LOGWARNING)
        assert calls == [("[AOM] careful", xbmc.LOGWARNING)]

    def test_error_not_escalated_regardless_of_flag(self, monkeypatch):
        calls = _install_recorder(monkeypatch)
        KodiLogger(debug_escalation=True)("bad", xbmc.LOGERROR)
        assert calls == [("[AOM] bad", xbmc.LOGERROR)]

    def test_info_not_touched(self, monkeypatch):
        calls = _install_recorder(monkeypatch)
        KodiLogger(debug_escalation=True)("fyi", xbmc.LOGINFO)
        assert calls == [("[AOM] fyi", xbmc.LOGINFO)]


# --- prefix rules ------------------------------------------------------------

class TestPrefixRules:
    def test_bare_message_is_prefixed(self, monkeypatch):
        calls = _install_recorder(monkeypatch)
        KodiLogger()("plain message", xbmc.LOGINFO)
        assert calls == [("[AOM] plain message", xbmc.LOGINFO)]

    def test_aom_underscore_prefix_not_double_tagged(self, monkeypatch):
        calls = _install_recorder(monkeypatch)
        KodiLogger()("AOM_Settings: stored", xbmc.LOGINFO)
        assert calls == [("AOM_Settings: stored", xbmc.LOGINFO)]

    def test_bracket_aom_prefix_not_double_tagged(self, monkeypatch):
        calls = _install_recorder(monkeypatch)
        KodiLogger()("[AOM] already tagged", xbmc.LOGINFO)
        assert calls == [("[AOM] already tagged", xbmc.LOGINFO)]


# --- convenience sinks -------------------------------------------------------

class TestConvenienceSinks:
    def test_debug_sink_uses_logdebug(self, monkeypatch):
        calls = _install_recorder(monkeypatch)
        KodiLogger(debug_escalation=False).debug("d")
        assert calls == [("[AOM] d", xbmc.LOGDEBUG)]

    def test_debug_sink_escalates_when_flag_on(self, monkeypatch):
        calls = _install_recorder(monkeypatch)
        KodiLogger(debug_escalation=True).debug("d")
        assert calls == [("[AOM] d", xbmc.LOGINFO)]

    def test_warning_sink_uses_logwarning(self, monkeypatch):
        calls = _install_recorder(monkeypatch)
        KodiLogger(debug_escalation=True).warning("w")
        assert calls == [("[AOM] w", xbmc.LOGWARNING)]

    def test_error_sink_uses_logerror(self, monkeypatch):
        calls = _install_recorder(monkeypatch)
        KodiLogger(debug_escalation=True).error("e")
        assert calls == [("[AOM] e", xbmc.LOGERROR)]
