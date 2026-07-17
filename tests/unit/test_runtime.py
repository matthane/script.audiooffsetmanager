"""Composition-root tests: graph wiring and the load-bearing dispatch order.

Constructs the REAL ServiceRuntime under Kodistubs (replacing the deleted
legacy-router suite's wiring pins). Dispatch follows subscription order per
event type, so the order pins here are behavioral guarantees, not style.
"""

import pytest

from resources.lib.aom.app import events
from resources.lib.aom.app.stream_detector import StreamDetector
from resources.lib.aom.runtime import ServiceRuntime


@pytest.fixture
def runtime():
    return ServiceRuntime()


def test_service_runtime_graph_wiring(runtime):
    # One instance of each adapter, shared by every consumer: the settings
    # doctrine's "single live proxy" and the single-gateway reconciliation.
    assert runtime.detector._gateway is runtime.gateway
    assert runtime.offset_applier._gateway is runtime.gateway
    assert runtime.seek_coordinator._gateway is runtime.gateway
    assert runtime.adjustment_watcher._gateway is runtime.gateway
    assert runtime.platform_recorder._gateway is runtime.gateway

    assert runtime.detector._settings is runtime.settings
    assert runtime.platform_recorder._settings is runtime.settings
    assert runtime.offset_applier._settings is runtime.settings
    assert runtime.notifier._settings is runtime.settings
    assert runtime.seek_scheduler._settings is runtime.settings
    assert runtime.adjustment_watcher._settings is runtime.settings

    assert runtime.offset_applier._offsets is runtime.offsets
    assert runtime.adjustment_watcher._offsets is runtime.offsets
    assert runtime.offsets._settings is runtime.settings
    assert runtime.notifier._gui is runtime.gui

    for component in (runtime.detector, runtime.offset_applier,
                      runtime.notifier, runtime.seek_scheduler,
                      runtime.adjustment_watcher):
        assert component._sessions is runtime.session_tracker

    # UserOffsetSaved fans out to the seek scheduler ('change' replay) and
    # the notifier (manual-offset toast) — both typed, both session-stamped.
    saved_handlers = runtime.dispatcher._subscribers[events.UserOffsetSaved]
    assert runtime.seek_scheduler._on_user_offset_saved in saved_handlers
    assert runtime.notifier._on_user_offset_saved in saved_handlers


def test_runtime_subscription_order_is_pinned(runtime):
    subs = runtime.dispatcher._subscribers

    def owners(event_type):
        return [getattr(h, '__self__', None) for h in subs[event_type]]

    # Lifecycle AND pause state: the tracker runs FIRST — the session exists
    # (or is torn down) and session.paused is current before any other
    # handler of the same event reads them (session.py states this
    # guarantee for Paused/Resumed explicitly).
    for event_type in (events.PlaybackStarted, events.PlaybackStopped,
                       events.PlaybackEnded, events.Paused, events.Resumed):
        assert owners(event_type)[0] is runtime.session_tracker, (
            f"{event_type.__name__}: SessionTracker must be the first "
            f"subscriber")

    # PlaybackStarted: detector (probe chain) before the seek scheduler
    # (resume request) — detection work is planned before seek work.
    started = owners(events.PlaybackStarted)
    assert started.index(runtime.detector) < started.index(
        runtime.seek_scheduler)

    # ProfileChanged: the applier records session.applied before the watcher
    # evaluates eligibility for the same adoption.
    profile_changed = owners(events.ProfileChanged)
    assert profile_changed.index(runtime.offset_applier) < \
        profile_changed.index(runtime.adjustment_watcher)

    # StreamStabilized: applier (retry pass) -> notifier (pending release)
    # -> seek scheduler (adjust request): offset work strictly precedes
    # seek planning for the same stabilization.
    stabilized = owners(events.StreamStabilized)
    assert (stabilized.index(runtime.offset_applier)
            < stabilized.index(runtime.notifier)
            < stabilized.index(runtime.seek_scheduler))

    # Detection events are the detector's alone.
    assert all(isinstance(owner, StreamDetector)
               for owner in owners(events.ProbeStream))
    assert all(isinstance(owner, StreamDetector)
               for owner in owners(events.VerifyStream))


def test_settings_changed_refreshes_cached_debug_flags(runtime, monkeypatch):
    monkeypatch.setattr(runtime.settings, 'debug_logging_enabled',
                        lambda: True)
    runtime.dispatcher.post(events.SettingsChanged())
    runtime.dispatcher.run_pending()
    assert runtime.logger.debug_escalation is True
    assert runtime.dispatcher.log_runtimes is True

    monkeypatch.setattr(runtime.settings, 'debug_logging_enabled',
                        lambda: False)
    runtime.dispatcher.post(events.SettingsChanged())
    runtime.dispatcher.run_pending()
    assert runtime.logger.debug_escalation is False
    assert runtime.dispatcher.log_runtimes is False
