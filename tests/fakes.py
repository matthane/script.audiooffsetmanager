"""Shared test fakes for the Audio Offset Manager suite.

``FakeClock`` (Phase 2) is the deterministic clock every phase reuses: the
dispatcher — and every component that measures intervals — takes an injected
``clock`` callable that defaults to ``time.monotonic``. Tests pass a
``FakeClock`` instead so time only moves when the test says so, and
timer-driven behaviour is driven with ``Dispatcher.run_pending()`` rather
than real sleeps.

``FakeGateway`` (Phase 4) is the scriptable stand-in for
``aom.kodi.gateway.KodiGateway``: tests mutate its attributes between pumps
to script what the "platform" reports, mirroring how the real single-shot
gateway reads live Kodi state on every call.

``FakeFacade`` (Phase 5) is the shared settings-facade double covering the
methods app components read (detector: fps_override_enabled; scheduler:
seek_back_config) — one fake, so the facade contract cannot drift between
suites.

``FakeGui`` (Phase 7) is the stand-in for ``aom.kodi.gui.Gui``: it records
toasts and returns a deterministic ``localized()`` marker so the Notifier's
message assembly is asserted without a real string table.

Keep this module tiny and dependency-free (no Kodi imports, no pytest) so
every test tier can share it.
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


class FakeGateway:
    """Scriptable stand-in for ``aom.kodi.gateway.KodiGateway``.

    Mirrors the real gateway's single-shot semantics: every read reflects the
    CURRENT attribute values, so tests script a stream by mutating
    ``player_id`` / ``codec`` / ``channels`` / ``infolabels`` between pumps
    (exactly how the real gateway sees live Kodi state change under it).
    Write-side calls are recorded for assertions and report success.
    """

    def __init__(self, player_id=1, codec='truehd', channels=8,
                 infolabels=None):
        self.player_id = player_id
        self.codec = codec
        self.channels = channels
        self.infolabels = dict(infolabels or {})
        # 9999 is Kodi's "no dialog open" answer from getCurrentWindowDialogId.
        self.dialog_id = 9999
        self.applied = []            # (player_id, delay_seconds)
        self.seeks = []              # (seconds, player_id)
        self.window_properties = {}

    # -- reads ------------------------------------------------------------------

    def active_player_id(self):
        return self.player_id

    def audio_info(self, player_id):
        return self.codec, self.channels

    def infolabel(self, label):
        return self.infolabels.get(label, '')

    def current_dialog_id(self):
        return self.dialog_id

    def window_property(self, name):
        return self.window_properties.get(name, '')

    # -- writes -----------------------------------------------------------------

    def set_audio_delay(self, player_id, delay_seconds):
        self.applied.append((player_id, delay_seconds))
        return True

    def seek_back(self, seconds, player_id=None):
        self.seeks.append((seconds, player_id))
        return True

    def set_window_property(self, name, value):
        self.window_properties[name] = value

    def clear_window_property(self, name):
        self.window_properties.pop(name, None)


class FakeFacade:
    """Scriptable settings facade covering the app components' read surface.

    ``fps_override`` drives the detector's fps-bucket collapse; ``seek_configs``
    maps a seek reason to its (enabled, seconds) pair, defaulting every reason
    to (True, 4). The adjustment-watcher surface: ``active_monitoring`` /
    ``hdr_enabled`` gate eligibility; ``offsets`` (setting_id -> ms) backs
    ``get_offset_ms``; ``store_integer_if_changed`` appends to ``stored`` and
    writes ``offsets`` (unless ``store_ok`` is False, when it reports failure).
    """

    def __init__(self, fps_override=False):
        self.fps_override = fps_override
        self.seek_configs = {}
        self.active_monitoring = True
        self.hdr_enabled = True
        self.offsets = {}            # setting_id -> ms
        self.stored = []             # (setting_id, ms), in store order
        self.store_ok = True

    def fps_override_enabled(self, hdr_type):
        return self.fps_override

    def seek_back_config(self, reason):
        return self.seek_configs.get(reason, (True, 4))

    def active_monitoring_enabled(self):
        return self.active_monitoring

    def is_hdr_enabled(self, hdr_type):
        return self.hdr_enabled

    def get_offset_ms(self, profile):
        return self.offsets.get(profile.setting_id(), 0)

    def store_integer_if_changed(self, setting_id, value):
        if not self.store_ok:
            return False
        self.stored.append((setting_id, value))
        self.offsets[setting_id] = value
        return True


class FakeGui:
    """Records toasts; localized() returns a deterministic marker."""

    def __init__(self):
        self.notifications = []          # (message, duration_ms)
        self.localized_strings = {}      # optional overrides: id -> str

    def localized(self, string_id):
        return self.localized_strings.get(string_id, f"#{string_id}")

    def notification(self, message, duration_ms):
        self.notifications.append((message, duration_ms))
