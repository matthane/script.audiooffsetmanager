"""Unit tests for aom.app.platform_recorder.PlatformRecorder.

The recorder is a pure event consumer: on every StreamProbed it writes the two
platform-capability flags through the settings adapter's store-if-changed
helper (the dedupe is the ADAPTER's job — the recorder always calls), and it
clears the ``new_install`` flag exactly once, on the first probe whose store
succeeds. Writes defer while the addon settings dialog is open (doctrine)
— the gateway answers that question.

Driven like the other app-layer tests: a real Dispatcher (no timers needed
here) pumped with run_pending(), and a recording settings double capturing
every store_boolean_if_changed call in order.
"""

from resources.lib.aom.app import events
from resources.lib.aom.app.dispatcher import Dispatcher
from resources.lib.aom.app.platform_recorder import PlatformRecorder
from tests.fakes import FakeClock, FakeGateway


class RecordingFacade:
    """Records store_boolean_if_changed calls; answers is_new_install().

    Honors the adapter's return contract — True on success-or-skip, False
    when the underlying write raised — with failures scripted per setting
    id via ``fail_ids``.
    """

    def __init__(self, new_install=False):
        self._new_install = new_install
        self.stored = []   # (setting_id, value), in call order
        self.fail_ids = set()

    def is_new_install(self):
        return self._new_install

    def store_boolean_if_changed(self, setting_id, value):
        self.stored.append((setting_id, value))
        return setting_id not in self.fail_ids


def make_rig(new_install=False):
    """Return (dispatcher, gateway, facade, debug, errors), recorder wired."""
    errors = []
    debug = []
    dispatcher = Dispatcher(clock=FakeClock(), log_error=errors.append)
    gateway = FakeGateway()
    facade = RecordingFacade(new_install=new_install)
    PlatformRecorder(dispatcher, gateway, facade, log_debug=debug.append)
    return dispatcher, gateway, facade, debug, errors


def _probe(session_id=1, platform_hdr_full=True, advanced_hlg=False):
    return events.StreamProbed(session_id=session_id,
                               platform_hdr_full=platform_hdr_full,
                               advanced_hlg=advanced_hlg)


def test_stores_platform_facts_on_every_probe():
    dispatcher, _gateway, facade, _debug, errors = make_rig(new_install=False)

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


def test_new_install_cleared_once_on_first_probe():
    dispatcher, _gateway, facade, debug, errors = make_rig(new_install=True)

    dispatcher.post(_probe())
    dispatcher.run_pending()
    # First probe stores the two facts AND clears new_install (after them),
    # and logs the clear.
    assert facade.stored[-1] == ('new_install', False)
    assert len(debug) == 1

    dispatcher.post(_probe())
    dispatcher.run_pending()
    # The SECOND probe must not clear new_install again.
    new_install_writes = [s for s in facade.stored if s[0] == 'new_install']
    assert new_install_writes == [('new_install', False)]   # exactly one, ever
    assert len(debug) == 1                                   # logged once only
    assert errors == []


def test_failed_new_install_store_keeps_latch_armed():
    # The latch is consumed only after a SUCCESSFUL store: a raised write
    # (adapter returns False) must leave it armed so the next probe retries
    # the clear — consuming it on the attempt would leave new_install true,
    # and with it every offset apply gated off, for the whole service
    # lifetime.
    dispatcher, _gateway, facade, debug, errors = make_rig(new_install=True)

    facade.fail_ids = {'new_install'}
    dispatcher.post(_probe())
    dispatcher.run_pending()
    assert facade.stored[-1] == ('new_install', False)   # the attempt ran
    assert debug == []                                   # but not logged as cleared

    facade.fail_ids = set()
    dispatcher.post(_probe())
    dispatcher.run_pending()
    new_install_writes = [s for s in facade.stored if s[0] == 'new_install']
    assert new_install_writes == [('new_install', False),
                                  ('new_install', False)]  # retried, succeeded
    assert len(debug) == 1                                 # cleared logged once

    dispatcher.post(_probe())
    dispatcher.run_pending()
    # Consumed now: no further clear attempts.
    assert len([s for s in facade.stored if s[0] == 'new_install']) == 2
    assert errors == []


def test_new_install_never_stored_when_flag_already_false():
    dispatcher, _gateway, facade, debug, errors = make_rig(new_install=False)

    dispatcher.post(_probe())
    dispatcher.post(_probe())
    dispatcher.run_pending()
    assert all(s[0] != 'new_install' for s in facade.stored)
    assert debug == []
    assert errors == []


def test_writes_defer_while_settings_dialog_open():
    # Settings-state doctrine: a write under an open addon-settings dialog is
    # clobbered by its save-on-close. The recorder skips the probe's writes —
    # including the new_install clear, whose latch must stay armed — and the
    # next probe (dialog closed) records everything.
    dispatcher, gateway, facade, debug, errors = make_rig(new_install=True)

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
                             ('new_install', False)]  # latch survived the defer
    assert errors == []


def test_records_regardless_of_session_id():
    # No session guard by design: platform facts are session-independent — a
    # probe stamped with a superseded (or never-live) session id still observed
    # the real platform, so the recorder records it unconditionally. The
    # recorder never consults the SessionTracker at all.
    dispatcher, _gateway, facade, _debug, errors = make_rig(new_install=False)

    dispatcher.post(_probe(session_id=999999, platform_hdr_full=True,
                           advanced_hlg=True))
    dispatcher.run_pending()
    assert facade.stored == [('platform_hdr_full', True),
                             ('advanced_hlg', True)]
    assert errors == []
