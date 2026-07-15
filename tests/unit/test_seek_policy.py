"""Unit tests for aom.domain.policies.seek_decision — the seek quiet-window
policy stated as one pure function.

These are pure table tests (no dispatcher, no clock, no fakes): the caller
resolves every timestamp and the function only decides 'seek' | 'defer' |
'abandon'. The scheduler-side enforcement (rescheduling, deadline bounding,
cross-type suppression as it actually plays out on the bus) is pinned in
test_seek_scheduler.py; here we pin the decision math and, crucially, its
DOCUMENTED ORDERING: served-check, then deadline, then quietness.

All timestamps are monotonic floats; only their differences matter, so the
tables use small readable numbers.
"""

import pytest

from resources.lib.aom.domain import policies


# The decision is evaluated in a fixed order (served -> deadline -> quiet);
# each row names which rule it is meant to exercise so a regression points at
# the guard it broke.
@pytest.mark.parametrize("case, now, requested_at, last_activity, last_own_seek, expected", [
    # -- quietness (the happy path) ------------------------------------------
    # No activity for >= quiet_window and inside the deadline -> seek.
    ("quiet_window_elapsed_seeks", 10.0, 8.0, 5.0, None, 'seek'),
    # Activity landed inside the quiet window -> defer (wait for calm).
    ("activity_inside_window_defers", 10.0, 9.0, 9.0, None, 'defer'),
    # Activity just shy of the window (1.5s < 2.0s) -> still defer.
    ("activity_just_inside_window_defers", 10.0, 9.0, 8.5, None, 'defer'),

    # -- deadline ------------------------------------------------------------
    # Aged past the deadline with recent activity -> abandon (gave up).
    ("aged_past_deadline_abandons", 20.0, 10.0, 19.0, None, 'abandon'),
    # DOCUMENTED ORDERING: past the deadline but the window is quiet NOW ->
    # still abandon. Deadline is checked before quietness (legacy parity:
    # the PM4K idle wait was skipped after its timeout regardless of calm).
    ("quiet_now_but_past_deadline_abandons", 20.0, 10.0, 1.0, None, 'abandon'),

    # -- served (our own later seek already replayed the glitch) -------------
    # A seek WE executed AFTER this request was made serves it -> abandon.
    ("own_seek_after_request_is_served", 10.0, 8.0, 8.0, 9.0, 'abandon'),
    # Served is checked FIRST: it abandons even when the window is quiet and
    # the deadline is far off (the request's purpose is already fulfilled).
    ("served_wins_even_when_quiet", 10.0, 5.0, 1.0, 6.0, 'abandon'),
    # A seek executed BEFORE the request does NOT serve it: an earlier rewind
    # can't have replayed seconds that hadn't glitched yet -> proceeds to seek.
    ("own_seek_before_request_not_served", 10.0, 5.0, 3.0, 4.0, 'seek'),
    # Equal timestamps are NOT "after" (strict >): not served -> seek.
    ("own_seek_equal_to_request_not_served", 10.0, 8.0, 1.0, 8.0, 'seek'),
    # last_own_seek None (we have never seeked this session) is handled.
    ("no_prior_own_seek_handled", 10.0, 5.0, 3.0, None, 'seek'),

    # -- boundaries (>= vs <) ------------------------------------------------
    # now - requested_at == deadline abandons (the guard is >=, not >).
    ("deadline_boundary_abandons", 18.0, 10.0, 0.0, None, 'abandon'),
    # now - last_activity == quiet_window seeks (the guard is <, so equality
    # is "quiet enough").
    ("quiet_boundary_seeks", 10.0, 9.0, 8.0, None, 'seek'),
])
def test_seek_decision(case, now, requested_at, last_activity, last_own_seek,
                       expected):
    assert policies.seek_decision(
        now=now,
        requested_at=requested_at,
        last_activity=last_activity,
        last_own_seek=last_own_seek,
        quiet_window=2.0,
        deadline=8.0) == expected, case


def test_served_and_deadline_both_true_still_abandons():
    # Both the served rule and the deadline rule fire; the result is abandon
    # either way, but this pins that a served request past its deadline is
    # never mistaken for anything else.
    assert policies.seek_decision(
        now=30.0, requested_at=10.0, last_activity=1.0, last_own_seek=25.0,
        quiet_window=2.0, deadline=8.0) == 'abandon'
