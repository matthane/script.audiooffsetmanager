"""Behavioral tests for aom.kodi.gateway.KodiGateway.

The gateway is the redesign's single-shot boundary to Kodi: exactly one
JSON-RPC round-trip per call, zero retries, zero sleeps — patience now lives in
the app-layer scheduler, not here. These tests pin that contract by asserting
the executeJSONRPC call count is 1 in every case (success, empty, and failure
alike) and by capturing the request payload to prove the JSON-RPC methods and
params are ported verbatim from the legacy ``rpc_client``.

Kodi is faked via Kodistubs: ``xbmc.executeJSONRPC`` is monkeypatched with a
recorder that returns canned JSON and counts calls; ``xbmc.getInfoLabel`` and
``xbmcgui.Window`` are stubbed where a test needs them. No fixtures beyond
``monkeypatch``.
"""

import json

import xbmc
import xbmcgui

from resources.lib.aom.kodi.gateway import KodiGateway


# --- fakes / helpers ---------------------------------------------------------

class _RpcRecorder:
    """Callable stand-in for ``xbmc.executeJSONRPC``.

    Records each request (decoded from the JSON string the gateway serializes)
    so tests can assert the single-shot contract via :attr:`call_count` and
    inspect the exact payload via :attr:`last_request`. Returns ``response``
    serialized back to JSON, unless ``raises`` is set — then the call raises,
    exercising the gateway's exception path.
    """

    def __init__(self, response=None, raises=None):
        self._response = {} if response is None else response
        self._raises = raises
        self.requests = []

    def __call__(self, payload):
        self.requests.append(json.loads(payload))
        if self._raises is not None:
            raise self._raises
        return json.dumps(self._response)

    @property
    def call_count(self):
        return len(self.requests)

    @property
    def last_request(self):
        return self.requests[-1]


class _FakeWindow:
    """Minimal stand-in for ``xbmcgui.Window`` recording its id and props."""

    def __init__(self, window_id=-1):
        self.window_id = window_id
        self.props = {}

    def getProperty(self, name):
        return self.props.get(name, "")

    def setProperty(self, name, value):
        self.props[name] = value

    def clearProperty(self, name):
        self.props.pop(name, None)


def _noop_log(message, level=None):
    return None


def _make_gateway(monkeypatch, response=None, raises=None):
    """Install an ``_RpcRecorder`` on ``xbmc.executeJSONRPC`` and build a gateway.

    Returns ``(gateway, recorder)``.
    """
    recorder = _RpcRecorder(response=response, raises=raises)
    monkeypatch.setattr(xbmc, "executeJSONRPC", recorder)
    return KodiGateway(log=_noop_log), recorder


# --- active_player_id --------------------------------------------------------

class TestActivePlayerId:
    def test_happy_path_returns_first_playerid(self, monkeypatch):
        gw, rec = _make_gateway(
            monkeypatch,
            response={"result": [{"playerid": 1, "type": "video"}]})
        assert gw.active_player_id() == 1
        assert rec.call_count == 1

    def test_empty_result_list_returns_minus_one(self, monkeypatch):
        gw, rec = _make_gateway(monkeypatch, response={"result": []})
        assert gw.active_player_id() == -1
        assert rec.call_count == 1

    def test_missing_result_key_returns_minus_one(self, monkeypatch):
        gw, rec = _make_gateway(monkeypatch, response={"jsonrpc": "2.0", "id": 1})
        assert gw.active_player_id() == -1
        assert rec.call_count == 1

    def test_playerid_minus_one_in_payload_returns_minus_one(self, monkeypatch):
        gw, rec = _make_gateway(monkeypatch, response={"result": [{"playerid": -1}]})
        assert gw.active_player_id() == -1
        assert rec.call_count == 1

    def test_exception_returns_minus_one_single_shot(self, monkeypatch):
        gw, rec = _make_gateway(monkeypatch, raises=RuntimeError("rpc down"))
        assert gw.active_player_id() == -1
        assert rec.call_count == 1   # single-shot: one attempt even on failure

    def test_request_uses_get_active_players(self, monkeypatch):
        gw, rec = _make_gateway(monkeypatch, response={"result": [{"playerid": 2}]})
        gw.active_player_id()
        assert rec.last_request["method"] == "Player.GetActivePlayers"


# --- audio_info --------------------------------------------------------------

class TestAudioInfo:
    def test_returns_codec_and_channels(self, monkeypatch):
        gw, rec = _make_gateway(monkeypatch, response={
            "result": {"currentaudiostream": {"codec": "truehd", "channels": 8}}})
        assert gw.audio_info(1) == ("truehd", 8)
        assert rec.call_count == 1

    def test_strips_pt_prefix_from_codec(self, monkeypatch):
        gw, rec = _make_gateway(monkeypatch, response={
            "result": {"currentaudiostream": {"codec": "pt-truehd", "channels": 6}}})
        assert gw.audio_info(1) == ("truehd", 6)
        assert rec.call_count == 1

    def test_codec_none_passes_through_unchanged(self, monkeypatch):
        # Single-shot contract: legacy retried while codec == 'none'; the
        # gateway reports it as-is and lets the caller own the patience.
        gw, rec = _make_gateway(monkeypatch, response={
            "result": {"currentaudiostream": {"codec": "none", "channels": 2}}})
        assert gw.audio_info(1) == ("none", 2)
        assert rec.call_count == 1

    def test_missing_currentaudiostream_returns_unknown(self, monkeypatch):
        gw, rec = _make_gateway(monkeypatch, response={"result": {}})
        assert gw.audio_info(1) == ("unknown", "unknown")
        assert rec.call_count == 1

    def test_missing_result_key_returns_unknown(self, monkeypatch):
        gw, rec = _make_gateway(monkeypatch, response={"jsonrpc": "2.0", "id": 1})
        assert gw.audio_info(1) == ("unknown", "unknown")
        assert rec.call_count == 1

    def test_missing_codec_and_channels_default_to_unknown(self, monkeypatch):
        gw, rec = _make_gateway(monkeypatch, response={
            "result": {"currentaudiostream": {}}})
        assert gw.audio_info(1) == ("unknown", "unknown")
        assert rec.call_count == 1

    def test_exception_returns_unknown_single_shot(self, monkeypatch):
        gw, rec = _make_gateway(monkeypatch, raises=ValueError("boom"))
        assert gw.audio_info(1) == ("unknown", "unknown")
        assert rec.call_count == 1

    def test_request_carries_player_id_and_property(self, monkeypatch):
        gw, rec = _make_gateway(monkeypatch, response={
            "result": {"currentaudiostream": {"codec": "ac3", "channels": 6}}})
        gw.audio_info(7)
        req = rec.last_request
        assert req["method"] == "Player.GetProperties"
        assert req["params"]["playerid"] == 7
        assert req["params"]["properties"] == ["currentaudiostream"]


# --- set_audio_delay ---------------------------------------------------------

class TestSetAudioDelay:
    def test_success_returns_true_and_sends_correct_request(self, monkeypatch):
        gw, rec = _make_gateway(monkeypatch, response={"result": "OK"})
        assert gw.set_audio_delay(1, 0.25) is True
        req = rec.last_request
        assert req["method"] == "Player.SetAudioDelay"
        assert req["params"]["playerid"] == 1
        assert req["params"]["offset"] == 0.25
        assert rec.call_count == 1

    def test_error_response_returns_false(self, monkeypatch):
        gw, rec = _make_gateway(monkeypatch, response={
            "error": {"code": -32602, "message": "Invalid params"}})
        assert gw.set_audio_delay(1, 0.1) is False
        assert rec.call_count == 1

    def test_exception_returns_false(self, monkeypatch):
        gw, rec = _make_gateway(monkeypatch, raises=RuntimeError("no player"))
        assert gw.set_audio_delay(1, 0.1) is False
        assert rec.call_count == 1


# --- seek_back ---------------------------------------------------------------

class TestSeekBack:
    def test_request_negates_seconds(self, monkeypatch):
        gw, rec = _make_gateway(monkeypatch, response={"result": "OK"})
        assert gw.seek_back(10, player_id=1) is True
        req = rec.last_request
        assert req["method"] == "Player.Seek"
        assert req["params"]["value"] == {"seconds": -10}
        assert rec.call_count == 1

    def test_none_player_id_falls_back_to_one(self, monkeypatch):
        gw, rec = _make_gateway(monkeypatch, response={"result": "OK"})
        gw.seek_back(5)
        assert rec.last_request["params"]["playerid"] == 1

    def test_explicit_player_id_is_honored(self, monkeypatch):
        gw, rec = _make_gateway(monkeypatch, response={"result": "OK"})
        gw.seek_back(5, player_id=2)
        assert rec.last_request["params"]["playerid"] == 2

    def test_error_response_returns_false(self, monkeypatch):
        gw, rec = _make_gateway(monkeypatch, response={"error": {"message": "bad"}})
        assert gw.seek_back(5, player_id=1) is False
        assert rec.call_count == 1

    def test_exception_returns_false(self, monkeypatch):
        gw, rec = _make_gateway(monkeypatch, raises=RuntimeError("boom"))
        assert gw.seek_back(5, player_id=1) is False
        assert rec.call_count == 1


# --- infolabel ---------------------------------------------------------------

class TestInfolabel:
    def test_passthrough_of_get_info_label(self, monkeypatch):
        captured = {}

        def fake_get_info_label(label):
            captured["label"] = label
            return "3840x2160"

        monkeypatch.setattr(xbmc, "getInfoLabel", fake_get_info_label)
        gw = KodiGateway(log=_noop_log)
        assert gw.infolabel("Player.Process(video.width)") == "3840x2160"
        assert captured["label"] == "Player.Process(video.width)"


# --- window properties -------------------------------------------------------

class TestWindowProperties:
    def test_caches_home_window_10000(self, monkeypatch):
        monkeypatch.setattr(xbmcgui, "Window", _FakeWindow)
        gw = KodiGateway(log=_noop_log)
        assert isinstance(gw._home_window, _FakeWindow)
        assert gw._home_window.window_id == 10000

    def test_set_then_get_round_trips(self, monkeypatch):
        monkeypatch.setattr(xbmcgui, "Window", _FakeWindow)
        gw = KodiGateway(log=_noop_log)
        assert gw.window_property("AOM.Signal") == ""   # unset -> empty string
        gw.set_window_property("AOM.Signal", "active")
        assert gw.window_property("AOM.Signal") == "active"
        assert gw._home_window.props["AOM.Signal"] == "active"

    def test_clear_removes_property(self, monkeypatch):
        monkeypatch.setattr(xbmcgui, "Window", _FakeWindow)
        gw = KodiGateway(log=_noop_log)
        gw.set_window_property("AOM.Signal", "active")
        gw.clear_window_property("AOM.Signal")
        assert gw.window_property("AOM.Signal") == ""
        assert "AOM.Signal" not in gw._home_window.props
