"""Unit tests for aom.app.platform_recorder.PlatformRecorder.

The recorder is a pure event consumer: on every StreamProbed it writes the
platform-capability flags through the settings adapter's store-if-changed
helper (the dedupe is the ADAPTER's job — the recorder always calls), plus
the sticky platform_hdr10plus latch (only ever written True, from the full
HDR label or a native 'hdr10plus' report). Writes defer while the addon
settings dialog is open (doctrine) — the gateway answers that question.

Driven like the other app-layer tests: a real Dispatcher (no timers needed
here) pumped with run_pending(), and a recording settings double capturing
every store_boolean_if_changed call in order.
"""

import pytest

from resources.lib.aom.app import events
from resources.lib.aom.app.dispatcher import Dispatcher
from resources.lib.aom.app.platform_recorder import (
    INFOLABEL_BUILD_VERSION,
    PlatformRecorder,
    parse_kodi_major,
)
from tests.fakes import FakeClock, FakeGateway


class RecordingFacade:
    """Records store_boolean_if_changed calls in order (the recorder never
    consumes the return value, so recording the calls is the whole surface)."""

    def __init__(self):
        self.stored = []   # (setting_id, value), in call order

    def store_boolean_if_changed(self, setting_id, value):
        self.stored.append((setting_id, value))
        return True


def make_rig():
    """Return (dispatcher, gateway, facade, debug, errors), recorder wired."""
    errors = []
    debug = []
    dispatcher = Dispatcher(clock=FakeClock(), log_error=errors.append)
    gateway = FakeGateway()
    facade = RecordingFacade()
    PlatformRecorder(dispatcher, gateway, facade, log_debug=debug.append)
    return dispatcher, gateway, facade, debug, errors


def _probe(session_id=1, platform_hdr_full=True, advanced_hlg=False,
           hdr_type='sdr'):
    return events.StreamProbed(session_id=session_id,
                               platform_hdr_full=platform_hdr_full,
                               advanced_hlg=advanced_hlg,
                               hdr_type=hdr_type)


def test_stores_platform_facts_on_every_probe():
    dispatcher, _gateway, facade, _debug, errors = make_rig()

    dispatcher.post(_probe(platform_hdr_full=True, advanced_hlg=False))
    dispatcher.run_pending()
    # The full HDR label implies HDR10+ capability, so the latch rides along.
    assert facade.stored == [('platform_hdr_full', True),
                             ('advanced_hlg', False),
                             ('platform_hdr10plus', True)]

    # A second probe records again with the new values: the recorder ALWAYS
    # calls store-if-changed (whether the value actually changed is the
    # facade's concern, not the recorder's). No capability evidence -> the
    # latch is NOT called (it is sticky, never written False).
    dispatcher.post(_probe(platform_hdr_full=False, advanced_hlg=True))
    dispatcher.run_pending()
    assert facade.stored == [
        ('platform_hdr_full', True), ('advanced_hlg', False),
        ('platform_hdr10plus', True),
        ('platform_hdr_full', False), ('advanced_hlg', True),
    ]
    assert errors == []


def test_writes_defer_while_settings_dialog_open():
    # Settings-state doctrine: a write under an open addon-settings dialog is
    # clobbered by its save-on-close. The recorder skips the probe's writes;
    # the next probe (dialog closed) records everything.
    dispatcher, gateway, facade, debug, errors = make_rig()

    gateway.settings_dialog = True
    dispatcher.post(_probe())
    dispatcher.run_pending()
    assert facade.stored == []                       # nothing written
    assert any('deferring platform writes' in line for line in debug)

    gateway.settings_dialog = False
    dispatcher.post(_probe())
    dispatcher.run_pending()
    assert facade.stored == [('platform_hdr_full', True),
                             ('advanced_hlg', False),
                             ('platform_hdr10plus', True)]
    assert errors == []


def test_records_regardless_of_session_id():
    # No session guard by design: platform facts are session-independent — a
    # probe stamped with a superseded (or never-live) session id still observed
    # the real platform, so the recorder records it unconditionally. The
    # recorder never consults the SessionTracker at all.
    dispatcher, _gateway, facade, _debug, errors = make_rig()

    dispatcher.post(_probe(session_id=999999, platform_hdr_full=True,
                           advanced_hlg=True))
    dispatcher.run_pending()
    assert facade.stored == [('platform_hdr_full', True),
                             ('advanced_hlg', True),
                             ('platform_hdr10plus', True)]
    assert errors == []


def test_hdr10plus_latches_from_native_report():
    # Kodi 22 presents 'hdr10plus' through VideoPlayer.HdrType without the
    # full HDR infolabel: the observation alone proves the capability.
    dispatcher, _gateway, facade, _debug, errors = make_rig()

    dispatcher.post(_probe(platform_hdr_full=False, hdr_type='hdr10plus'))
    dispatcher.run_pending()
    assert facade.stored == [('platform_hdr_full', False),
                             ('advanced_hlg', False),
                             ('platform_hdr10plus', True)]
    assert errors == []


def test_hdr10plus_latch_is_never_written_false():
    # Streams that are not HDR10+ say nothing about the capability: on a
    # platform with no full HDR label the latch is simply not called, so a
    # previously stored True can never be knocked back down.
    dispatcher, _gateway, facade, _debug, errors = make_rig()

    for hdr_type in ('sdr', 'hdr10', 'dolbyvision', 'unknown'):
        dispatcher.post(_probe(platform_hdr_full=False, hdr_type=hdr_type))
    dispatcher.run_pending()
    assert all(setting != 'platform_hdr10plus'
               for setting, _value in facade.stored)
    assert errors == []


def test_hdr10plus_latches_from_build_version_at_startup():
    # Kodi 22+ reports 'hdr10plus' natively, so the capability is known from
    # the build version alone: ServiceStarted latches it with no playback.
    dispatcher, gateway, facade, _debug, errors = make_rig()

    gateway.infolabels[INFOLABEL_BUILD_VERSION] = '22.0 (22.0.0) Git:20260101-abcdef'
    dispatcher.post(events.ServiceStarted())
    dispatcher.run_pending()
    assert facade.stored == [('platform_hdr10plus', True)]
    assert errors == []


def test_older_build_version_does_not_latch():
    dispatcher, gateway, facade, _debug, errors = make_rig()

    gateway.infolabels[INFOLABEL_BUILD_VERSION] = '21.2 (21.2.0) Git:20241122-abc'
    dispatcher.post(events.ServiceStarted())
    dispatcher.run_pending()
    assert facade.stored == []
    assert errors == []


def test_unparseable_build_version_is_inert():
    # The fake's unresolved InfoLabel answer is '' (the real gateway can also
    # hand back a label echo); neither parses, neither latches, no error.
    dispatcher, _gateway, facade, _debug, errors = make_rig()

    dispatcher.post(events.ServiceStarted())
    dispatcher.run_pending()
    assert facade.stored == []
    assert errors == []


def test_startup_check_defers_while_settings_dialog_open():
    dispatcher, gateway, facade, debug, errors = make_rig()

    gateway.infolabels[INFOLABEL_BUILD_VERSION] = '22.0 (22.0.0)'
    gateway.settings_dialog = True
    dispatcher.post(events.ServiceStarted())
    dispatcher.run_pending()
    assert facade.stored == []
    assert any('deferring startup capability check' in line for line in debug)
    assert errors == []


@pytest.mark.parametrize("raw,expected", [
    ('22.0 (22.0.0) Git:20260101-abcdef', 22),
    ('21.2 (21.2.0)', 21),
    ('  20.5', 20),
    ('', None),
    (None, None),
    ('System.BuildVersion', None),   # label echo = unresolved
])
def test_parse_kodi_major(raw, expected):
    assert parse_kodi_major(raw) == expected
