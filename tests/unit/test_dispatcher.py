"""Behavioral tests for aom.app.dispatcher.Dispatcher.

The dispatcher is the spine of the redesign (DESIGN.md "Pillar A"): one thread
owns a queue and a timer heap, so every timer/debounce/retry becomes a
``schedule(...)`` call and all state runs serialized on one thread. These tests
pin that contract.

Time is driven by ``FakeClock`` and events are pumped with ``run_pending()`` —
no real sleeps anywhere except the single ``test_thread_mode_*`` case, which
exercises the production ``start()``/``stop()`` path against the real monotonic
clock with generous timeouts.
"""

import threading

import pytest

# ``_STOP`` is the module-private sentinel ``stop()`` enqueues. One test posts it
# directly to exercise the "sentinel consumed mid-drain" halt without spinning up
# a background thread; importing it keeps that test faithful to real behaviour.
from resources.lib.aom.app.dispatcher import Dispatcher, _STOP
from tests.fakes import FakeClock


# --- local event types -------------------------------------------------------
# The dispatcher routes purely on ``type(event)``, so plain distinct classes are
# enough; payloads carry an ``n`` so ordering assertions can tell instances apart.

class _Event:
    def __init__(self, n=0):
        self.n = n

    def __repr__(self):
        return "{}(n={})".format(type(self).__name__, self.n)


class Alpha(_Event):
    pass


class Beta(_Event):
    pass


class Gamma(_Event):
    pass


# --- helpers -----------------------------------------------------------------

def make_recorder():
    """Return ``(calls, handler)`` where ``handler`` appends each event it gets."""
    calls = []

    def handler(event):
        calls.append(event)

    return calls, handler


def make_dispatcher(clock=None, log_runtimes=False):
    """A Dispatcher wired to a FakeClock plus captured debug/error log sinks.

    Returns ``(dispatcher, clock, debug_lines, error_lines)``.
    """
    clock = FakeClock() if clock is None else clock
    debug = []
    errors = []
    dispatcher = Dispatcher(clock=clock, log_debug=debug.append,
                            log_error=errors.append, log_runtimes=log_runtimes)
    return dispatcher, clock, debug, errors


# --- dispatch & subscription -------------------------------------------------

def test_dispatch_by_event_type():
    d, _clock, _debug, errors = make_dispatcher()
    alpha_calls, alpha_handler = make_recorder()
    beta_calls, beta_handler = make_recorder()
    d.subscribe(Alpha, alpha_handler)
    d.subscribe(Beta, beta_handler)

    d.post(Alpha())
    d.post(Beta())
    d.run_pending()

    assert len(alpha_calls) == 1 and isinstance(alpha_calls[0], Alpha)
    assert len(beta_calls) == 1 and isinstance(beta_calls[0], Beta)
    assert errors == []


def test_events_with_no_subscribers_are_dropped_silently():
    d, clock, _debug, errors = make_dispatcher()

    d.post(Gamma())               # posted, no subscriber
    d.run_pending()               # must not raise
    assert errors == []

    d.schedule(1.0, Gamma())      # scheduled, no subscriber
    clock.advance(1.0)
    d.run_pending()               # must not raise
    assert errors == []


def test_fifo_order_across_posted_events():
    d, _clock, _debug, _errors = make_dispatcher()
    order = []
    d.subscribe(Alpha, lambda e: order.append(("A", e.n)))
    d.subscribe(Beta, lambda e: order.append(("B", e.n)))

    d.post(Alpha(1))
    d.post(Beta(2))
    d.post(Alpha(3))
    d.run_pending()

    assert order == [("A", 1), ("B", 2), ("A", 3)]


def test_subscriber_registration_order_within_one_event():
    d, _clock, _debug, _errors = make_dispatcher()
    order = []
    d.subscribe(Alpha, lambda e: order.append(1))
    d.subscribe(Alpha, lambda e: order.append(2))
    d.subscribe(Alpha, lambda e: order.append(3))

    d.post(Alpha())
    d.run_pending()

    assert order == [1, 2, 3]


# --- unsubscribe -------------------------------------------------------------

def test_unsubscribe_one_of_several_handlers():
    d, _clock, _debug, _errors = make_dispatcher()
    calls1, h1 = make_recorder()
    calls2, h2 = make_recorder()
    d.subscribe(Alpha, h1)
    d.subscribe(Alpha, h2)

    d.unsubscribe(Alpha, h1)
    d.post(Alpha())
    d.run_pending()

    assert calls1 == []
    assert len(calls2) == 1


def test_unsubscribe_unknown_handler_is_noop():
    d, _clock, _debug, errors = make_dispatcher()
    calls, h = make_recorder()
    _other_calls, other = make_recorder()
    d.subscribe(Alpha, h)

    d.unsubscribe(Alpha, other)   # 'other' was never subscribed
    d.post(Alpha())
    d.run_pending()

    assert len(calls) == 1        # the real subscriber is untouched
    assert errors == []


def test_unsubscribe_on_type_with_no_subscribers_is_noop():
    d, _clock, _debug, errors = make_dispatcher()
    _calls, h = make_recorder()

    d.unsubscribe(Beta, h)        # Beta has no subscribers at all
    d.post(Beta())
    d.run_pending()

    assert errors == []


# --- exception isolation -----------------------------------------------------

def test_raising_handler_is_logged_and_later_handlers_still_run():
    d, _clock, _debug, errors = make_dispatcher()
    after_calls, after_handler = make_recorder()

    def boom(event):
        raise RuntimeError("boom")

    d.subscribe(Alpha, boom)
    d.subscribe(Alpha, after_handler)   # registered after the raiser
    d.post(Alpha())
    d.run_pending()

    assert len(after_calls) == 1        # isolation: later handler still ran
    assert len(errors) == 1             # the failure was logged via log_error
    assert "boom" in errors[0] and "Alpha" in errors[0]


def test_raising_handler_does_not_block_later_events():
    d, _clock, _debug, errors = make_dispatcher()
    beta_calls, beta_handler = make_recorder()

    def boom(event):
        raise RuntimeError("kaboom")

    d.subscribe(Alpha, boom)
    d.subscribe(Beta, beta_handler)
    d.post(Alpha())               # raises
    d.post(Beta())                # must still be dispatched
    d.run_pending()

    assert len(beta_calls) == 1
    assert len(errors) == 1


# --- scheduling: deadlines ---------------------------------------------------

def test_schedule_fires_at_deadline_never_before():
    d, clock, _debug, _errors = make_dispatcher()
    fired, handler = make_recorder()
    d.subscribe(Alpha, handler)

    d.schedule(2.0, Alpha())
    d.run_pending()
    assert fired == []            # t=0.0, before deadline

    clock.advance(1.0)
    d.run_pending()
    assert fired == []            # t=1.0, still before deadline

    clock.advance(1.0)            # t=2.0, exactly at the deadline
    d.run_pending()
    assert len(fired) == 1        # fires at the boundary, not a tick later


def test_interleaved_timers_fire_in_deadline_order():
    d, clock, _debug, _errors = make_dispatcher()
    fired = []
    d.subscribe(Alpha, lambda e: fired.append(e.n))

    d.schedule(3.0, Alpha(3))     # scheduled out of deadline order on purpose
    d.schedule(1.0, Alpha(1))
    d.schedule(2.0, Alpha(2))

    clock.advance(3.0)
    d.run_pending()

    assert fired == [1, 2, 3]


# --- scheduling: key-replace supersede & cancel ------------------------------

def test_key_replace_drops_earlier_timer_even_after_its_deadline():
    # The debounce/supersede primitive: rescheduling under the same key must
    # drop the earlier timer, and must do so even once the earlier deadline has
    # already passed. (Regression guard for the AvChangeFilter replacement.)
    d, clock, _debug, _errors = make_dispatcher()
    fired, handler = make_recorder()
    d.subscribe(Alpha, handler)

    d.schedule(1.0, Alpha(1), key="k")   # earlier deadline
    d.schedule(2.0, Alpha(2), key="k")   # same key supersedes; later deadline

    clock.advance(1.5)                    # PAST the earlier (superseded) deadline
    d.run_pending()
    assert fired == []                    # earlier timer must NOT fire

    clock.advance(0.5)                     # now at t=2.0, the live deadline
    d.run_pending()
    assert [e.n for e in fired] == [2]    # only the superseding timer fired


def test_cancel_prevents_firing():
    d, clock, _debug, _errors = make_dispatcher()
    fired, handler = make_recorder()
    d.subscribe(Alpha, handler)

    d.schedule(1.0, Alpha(), key="k")
    d.cancel("k")
    clock.advance(2.0)
    d.run_pending()

    assert fired == []


def test_cancel_unknown_key_is_noop():
    d, _clock, _debug, errors = make_dispatcher()
    d.cancel("never-scheduled")   # must not raise
    assert errors == []


def test_cancel_already_fired_key_is_noop():
    d, clock, _debug, _errors = make_dispatcher()
    fired, handler = make_recorder()
    d.subscribe(Alpha, handler)

    d.schedule(1.0, Alpha(), key="k")
    clock.advance(1.0)
    d.run_pending()
    assert len(fired) == 1

    d.cancel("k")                 # already fired -> no-op
    clock.advance(1.0)
    d.run_pending()
    assert len(fired) == 1        # no resurrection / double fire


def test_generated_key_returned_by_schedule_is_cancelable():
    d, clock, _debug, _errors = make_dispatcher()
    fired, handler = make_recorder()
    d.subscribe(Alpha, handler)

    key = d.schedule(1.0, Alpha())   # key=None -> a generated key is returned
    assert key is not None
    d.cancel(key)
    clock.advance(2.0)
    d.run_pending()

    assert fired == []


# --- cascades ----------------------------------------------------------------

def test_cascade_of_posts_drains_in_one_run_pending():
    d, _clock, _debug, errors = make_dispatcher()
    beta_calls, beta_handler = make_recorder()

    def alpha_handler(event):
        d.post(Beta(event.n + 1))   # a handler that posts another event

    d.subscribe(Alpha, alpha_handler)
    d.subscribe(Beta, beta_handler)

    d.post(Alpha(1))
    d.run_pending()                 # a single pump call

    assert [b.n for b in beta_calls] == [2]
    assert errors == []


def test_cascade_of_due_schedule_drains_in_one_run_pending():
    d, _clock, _debug, errors = make_dispatcher()
    gamma_calls, gamma_handler = make_recorder()

    def alpha_handler(event):
        d.schedule(0.0, Gamma(), key="g")   # a handler that schedules a due timer

    d.subscribe(Alpha, alpha_handler)
    d.subscribe(Gamma, gamma_handler)

    d.post(Alpha())
    d.run_pending()                 # single pump call must process the due timer too

    assert len(gamma_calls) == 1
    assert errors == []


def test_reschedule_same_key_from_inside_fired_handler_recurs():
    # The recurring-tick pattern later phases rely on (WatchTick): the handler,
    # while it is being dispatched, reschedules itself under the same key.
    d, clock, _debug, errors = make_dispatcher()
    fired = []

    def tick(event):
        fired.append(clock())
        if len(fired) < 3:
            d.schedule(1.0, event, key="tick")   # reschedule from inside the handler

    d.subscribe(Alpha, tick)
    d.schedule(1.0, Alpha(), key="tick")

    d.run_pending()
    assert fired == []            # nothing before the first deadline

    for expected in (1, 2, 3):
        clock.advance(1.0)
        d.run_pending()
        assert len(fired) == expected

    clock.advance(5.0)            # it stopped rescheduling at the 3rd tick
    d.run_pending()
    assert len(fired) == 3
    assert errors == []


# --- log_runtimes ------------------------------------------------------------

def test_log_runtimes_off_by_default_emits_no_debug_lines():
    d, _clock, debug, errors = make_dispatcher()   # log_runtimes defaults False
    calls, handler = make_recorder()
    d.subscribe(Alpha, handler)

    d.post(Alpha())
    d.run_pending()

    assert len(calls) == 1
    assert debug == []            # no per-handler runtime logging
    assert errors == []


def test_log_runtimes_on_emits_one_line_per_handler():
    d, _clock, debug, errors = make_dispatcher(log_runtimes=True)
    _calls1, h1 = make_recorder()
    _calls2, h2 = make_recorder()
    d.subscribe(Alpha, h1)
    d.subscribe(Alpha, h2)

    d.post(Alpha())
    d.run_pending()

    runtime_lines = [line for line in debug if "handled by" in line]
    assert len(runtime_lines) == 2                       # one per handler
    assert all("Alpha" in line and "ms" in line for line in runtime_lines)
    assert errors == []


def test_log_runtimes_toggled_mid_run_takes_effect():
    # The flag is a plain attribute so the runtime can flip it on SettingsChanged;
    # flipping it mid-dispatch must change logging for subsequent handlers.
    d, _clock, debug, errors = make_dispatcher(log_runtimes=False)

    def before_flip(event):
        pass

    def flip_on(event):
        d.log_runtimes = True

    def after_flip(event):
        pass

    d.subscribe(Alpha, before_flip)   # runs while the flag is still off
    d.subscribe(Alpha, flip_on)       # turns the flag on
    d.subscribe(Beta, after_flip)     # a later event, flag now on

    d.post(Alpha())
    d.post(Beta())
    d.run_pending()

    joined = "\n".join(debug)
    assert "before_flip" not in joined   # logged nothing while flag was off
    assert "flip_on" in joined           # flag on by the time its line is emitted
    assert "after_flip" in joined        # later event logged under the on flag
    assert errors == []


# --- thread mode (real clock, real threading) --------------------------------

def test_thread_mode_start_post_schedule_stop():
    # The one test that uses production start()/stop() with the real monotonic
    # clock and a background thread. Waits are event-driven with generous
    # timeouts, so total added wall time is a few tens of milliseconds.
    errors = []
    d = Dispatcher(log_error=errors.append)   # default clock = time.monotonic
    started = threading.Event()
    changed = threading.Event()
    never_fired = []
    d.subscribe(Alpha, lambda e: started.set())
    d.subscribe(Beta, lambda e: changed.set())
    d.subscribe(Gamma, lambda e: never_fired.append(e))

    try:
        d.start()
        first_thread = d._thread
        d.start()                          # double start(): no-op, same thread
        assert d._thread is first_thread

        d.post(Alpha())                    # delivered via the queue
        d.schedule(0.02, Beta(), key="b")  # delivered via the timer heap
        d.schedule(5.0, Gamma(), key="never")  # pending; must be dropped by stop()

        assert started.wait(1.5), "posted event was not handled by the thread"
        assert changed.wait(1.5), "scheduled event was not handled by the thread"
    finally:
        d.stop()                           # joins the thread; drops the 5s timer

    assert d._thread is None
    d.stop()                               # double stop(): no-op, must not raise
    assert never_fired == []               # pending work was dropped by stop()
    assert errors == []


# --- stop() in pump mode -----------------------------------------------------

def test_pump_mode_stop_halts_run_pending():
    d, _clock, _debug, _errors = make_dispatcher()
    calls, handler = make_recorder()
    d.subscribe(Alpha, handler)

    d.post(Alpha())
    d.stop()                      # pump mode (no thread): flags stopped, drops queue
    d.run_pending()               # must dispatch nothing
    assert calls == []

    d.run_pending()               # still nothing on a second pump
    assert calls == []


def test_stop_sentinel_consumed_dispatches_nothing_further():
    d, _clock, _debug, _errors = make_dispatcher()
    calls, handler = make_recorder()
    d.subscribe(Alpha, handler)

    d.post(Alpha(1))              # dispatched before the sentinel
    d.post(_STOP)                 # halts the pump the moment it is consumed
    d.post(Alpha(2))              # queued after the sentinel -> must NOT dispatch
    d.run_pending()

    assert [e.n for e in calls] == [1]
    assert d._stopped is True

    d.run_pending()               # stopped stays stopped
    assert [e.n for e in calls] == [1]
