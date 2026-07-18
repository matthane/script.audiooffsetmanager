"""Unit tests for aom.app.platform_recorder.PlatformRecorder.

The recorder is a pure event consumer: on every StreamProbed it writes the two
platform-capability flags through the settings adapter's store-if-changed
helper (the dedupe is the ADAPTER's job — the recorder always calls). Writes
defer while the addon settings dialog is open (doctrine) — the gateway
answers that question.

Driven like the other app-layer tests: a real Dispatcher (no timers needed
here) pumped with run_pending(), and a recording settings double capturing
every store_boolean_if_changed call in order.
"""

from resources.lib.aom.app import events
from resources.lib.aom.app.dispatcher import Dispatcher
from resources.lib.aom.app.platform_recorder import PlatformRecorder
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


def _probe(session_id=1, platform_hdr_full=True, advanced_hlg=False):
    return events.StreamProbed(session_id=session_id,
                               platform_hdr_full=platform_hdr_full,
                               advanced_hlg=advanced_hlg)


def test_stores_platform_facts_on_every_probe():
    dispatcher, _gateway, facade, _debug, errors = make_rig()

    dispatcher.post(_probe(platform_hdr_full=True, advanced_hlg=False))
    dispatcher.run_pending()
    assert facade.stored == [('platform_hdr_full', True),
                             ('advanced_hlg', False)]

    # A second probe records again with the new values: the recorder ALWAYS
    # calls store-if-changed (whether the value actually changed is the
    # facade's concern, not the recorder's).
    dispatcher.post(_probe(platform_hdr_full=False, advanced_hlg=True))
    dispatcher.run_pending()
    assert facade.stored == [
        ('platform_hdr_full', True), ('advanced_hlg', False),
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
                             ('advanced_hlg', False)]
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
                             ('advanced_hlg', True)]
    assert errors == []
