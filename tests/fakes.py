"""Shared test fakes for the Audio Offset Manager suite.

Phase 2 introduces the project's first shared fake: ``FakeClock``, the
deterministic clock every later phase reuses. The dispatcher — and every future
component that measures intervals — takes an injected ``clock`` callable that
defaults to ``time.monotonic``. Tests pass a ``FakeClock`` instead so time only
moves when the test says so, and timer-driven behaviour is driven with
``Dispatcher.run_pending()`` rather than real sleeps.

Keep this module tiny and dependency-free (no Kodi imports, no pytest) so every
test tier can share it. Later phases will add a fake Kodi gateway and a fake
settings store here as the components that need them land; until then this holds
only the clock.
"""


class FakeClock:
    """A deterministic stand-in for ``time.monotonic``.

    Instances are callable and return the current fake time in seconds as a
    float, exactly like ``time.monotonic()`` — so ``Dispatcher(clock=clock)``
    accepts one directly. Time never advances on its own; call
    :meth:`advance` to move it forward.

    The value is monotonic non-decreasing: advancing by a negative amount is
    rejected, preserving the one guarantee real interval math relies on.

    Example::

        clock = FakeClock()
        d = Dispatcher(clock=clock, log_error=errors.append)
        d.schedule(1.0, Tick())
        d.run_pending()      # nothing due yet
        clock.advance(1.0)
        d.run_pending()      # Tick fires
    """

    __slots__ = ("_now",)

    def __init__(self, start=0.0):
        self._now = float(start)

    def __call__(self):
        return self._now

    def advance(self, seconds):
        """Move the clock forward by ``seconds`` (must be >= 0); return the new time."""
        if seconds < 0:
            raise ValueError("FakeClock cannot move backwards")
        self._now += float(seconds)
        return self._now
