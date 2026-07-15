"""Unit tests for aom.app.stream_detector.

Two surfaces are exercised:

* ``derive_stream_facts`` — the pure HDR/FPS/audio derivation (no dispatcher
  needed): echo guards, HLG normalization, the HLG-via-gamut sniff, FPS
  bucketing and the override collapse. These pin the "ported verbatim from
  legacy StreamInfo" contract the module docstring claims.
* ``StreamDetector`` — the probe/verify orchestration. Driven exactly like
  test_session_flow / test_dispatcher: a FakeClock plus run_pending() pumping,
  with recorders subscribed to the detector's OUTPUT events (ProfileChanged,
  StreamProbed, StreamStabilized) so behaviour is observed off the bus.

Timing facts the tests rely on: probe #1 is POSTED on PlaybackStarted (fires
on the next pump with no clock advance); later probes are scheduled at jittered
0.5s spacing, which collapses to EXACTLY 0.5s with ``rng=lambda: 0.5``; the
verify window is 1.0s; the probe budget is 20 attempts.
"""

import pytest

from resources.lib.aom.app import events
from resources.lib.aom.app.dispatcher import Dispatcher
from resources.lib.aom.app.session import SessionTracker
from resources.lib.aom.app.stream_detector import (
    StreamDetector,
    derive_stream_facts,
    INFOLABEL_FPS,
    INFOLABEL_HDR,
    INFOLABEL_GAMUT,
)
from resources.lib.aom.domain import formats
from resources.lib.aom.domain.stream_state import StreamState
from tests.fakes import FakeClock, FakeFacade, FakeGateway


# A gateway scripted to report a complete Dolby Vision / TrueHD stream. With
# the FPS override off the fps bucket collapses to 'all', so the profile keys
# to 'dolbyvision_all_truehd'.
COMPLETE_INFOLABELS = {
    INFOLABEL_FPS: '23.976',
    INFOLABEL_HDR: 'dolbyvision',
}


# --- pure-derivation helper --------------------------------------------------

def derive(raw_codec='truehd', raw_channels=8, raw_fps='23.976',
           raw_hdr='dolbyvision', raw_hdr_fallback='', raw_gamut='',
           fps_override=lambda hdr: False, player_id=1):
    """Call derive_stream_facts with readable defaults (a complete DV stream).

    ``fps_override`` is the ``hdr_type -> bool`` callable the real facade
    supplies; the default returns False, which collapses the fps bucket to
    'all' exactly as the production settings default does.
    """
    return derive_stream_facts(
        player_id=player_id, raw_codec=raw_codec, raw_channels=raw_channels,
        raw_fps=raw_fps, raw_hdr=raw_hdr, raw_hdr_fallback=raw_hdr_fallback,
        raw_gamut=raw_gamut, fps_override_enabled=fps_override)


# --- orchestration rig -------------------------------------------------------

class Rig:
    """The detector graph assembled on fakes; pump with start/advance/av_changed.

    Recorders capture the detector's output events. They are subscribed AFTER
    the detector on purpose: the detector consumes ProbeStream/VerifyStream/
    PlaybackStarted/AvChanged, never its own outputs, so recorder order is
    irrelevant to it.
    """

    def __init__(self, fps_override=False):
        self.clock = FakeClock()
        self.errors = []
        self.warnings = []
        self.debug = []
        self.dispatcher = Dispatcher(clock=self.clock,
                                     log_error=self.errors.append)
        # Tracker subscribes lifecycle FIRST so the detector always sees a live
        # session on PlaybackStarted (dispatch follows subscription order).
        self.tracker = SessionTracker(self.dispatcher)
        self.gateway = FakeGateway(infolabels=dict(COMPLETE_INFOLABELS))
        self.facade = FakeFacade(fps_override=fps_override)
        self.detector = StreamDetector(
            self.dispatcher, self.tracker, self.gateway, self.facade,
            log_debug=self.debug.append, log_warning=self.warnings.append,
            rng=lambda: 0.5)  # jittered spacing collapses to exactly 0.5s
        self.profiles = []
        self.probes = []
        self.stabilized = []
        self.dispatcher.subscribe(events.ProfileChanged, self.profiles.append)
        self.dispatcher.subscribe(events.StreamProbed, self.probes.append)
        self.dispatcher.subscribe(events.StreamStabilized,
                                  self.stabilized.append)

    @property
    def session(self):
        return self.tracker.current

    def start(self):
        self.dispatcher.post(events.PlaybackStarted())
        self.dispatcher.run_pending()

    def av_changed(self):
        self.dispatcher.post(events.AvChanged())
        self.dispatcher.run_pending()

    def advance(self, seconds=1.0):
        self.clock.advance(seconds)
        self.dispatcher.run_pending()


@pytest.fixture
def rig():
    return Rig()


def _exhaust_discovery(rig):
    """Run the probe budget to exhaustion against an unresolved codec.

    Leaves the session STARTING with no profile and discovery given up. Probe
    #1 fires at start; the remaining attempts fire at exactly 0.5s spacing, so
    a handful of extra pumps past the budget are inert.
    """
    rig.gateway.codec = 'none'
    rig.start()
    for _ in range(StreamDetector.PROBE_BUDGET + 5):
        rig.clock.advance(StreamDetector.PROBE_SPACING_SECONDS)
        rig.dispatcher.run_pending()


# ============================================================================
# Pure derivation
# ============================================================================

class TestDeriveStreamFacts:

    def test_echo_guard_falls_back_and_sets_platform_hdr_full(self):
        # A primary reading equal to its own infolabel is Kodi's "no data"
        # signal: fall back to the secondary label and flag platform_hdr_full
        # False (the platform did not report a real HDR type).
        echoed = derive(raw_hdr=INFOLABEL_HDR, raw_hdr_fallback='dolbyvision')
        assert echoed.platform_hdr_full is False
        assert echoed.profile.hdr_type == 'dolbyvision'

        # A genuine primary reading: full HDR reported, flag True.
        real = derive(raw_hdr='dolbyvision')
        assert real.platform_hdr_full is True
        assert real.profile.hdr_type == 'dolbyvision'

    def test_empty_primary_and_fallback_is_sdr(self):
        facts = derive(raw_hdr='', raw_hdr_fallback='')
        assert facts.profile.hdr_type == 'sdr'
        assert facts.platform_hdr_full is False

    def test_hdr_string_normalization(self):
        # Space strip + lower + the 'hlghdr' -> 'hlg' mapping.
        assert derive(raw_hdr='HLG HDR').profile.hdr_type == 'hlg'
        # '+' is rewritten to 'plus' before vocabulary lookup.
        assert derive(raw_hdr='HDR10+').profile.hdr_type == 'hdr10plus'

    def test_unrecognized_hdr_is_unknown(self):
        assert derive(raw_hdr='banana').profile.hdr_type == formats.UNKNOWN

    def test_hlg_via_gamut(self):
        # HDR resolves SDR, but a valid gamut containing 'hlg' rewrites it to
        # HLG and marks advanced_hlg (the amlogic sniff).
        a = derive(raw_hdr='', raw_gamut='BT2020 HLG')
        assert a.profile.hdr_type == 'hlg'
        assert a.advanced_hlg is True
        assert a.gamut_info == 'BT2020 HLG'

        # A gamut echoing its own label is "no data": no rewrite, flag False,
        # gamut_info reads 'not available'.
        b = derive(raw_hdr='', raw_gamut=INFOLABEL_GAMUT)
        assert b.profile.hdr_type == 'sdr'
        assert b.advanced_hlg is False
        assert b.gamut_info == 'not available'

    def test_fps_bucketing_and_video_fps(self):
        keep = lambda hdr: True  # keep the detected bucket (no 'all' collapse)
        assert derive(raw_fps='23.976', fps_override=keep).profile.fps_type == 23
        assert derive(raw_fps='60', fps_override=keep).profile.fps_type == 60

        # Unparseable -> 'unknown' bucket AND video_fps None.
        for bad in ('', 'x'):
            facts = derive(raw_fps=bad, fps_override=keep)
            assert facts.profile.fps_type == formats.UNKNOWN
            assert facts.profile.video_fps is None

        # Parseable but not a defined bucket -> 'unknown' bucket, but the raw
        # integer is still carried on video_fps.
        facts = derive(raw_fps='48', fps_override=keep)
        assert facts.profile.fps_type == formats.UNKNOWN
        assert facts.profile.video_fps == 48

        # video_fps mirrors the parsed int even for a valid bucket.
        assert derive(raw_fps='23.976', fps_override=keep).profile.video_fps == 23

    def test_fps_override_collapse_and_unknown_hdr_skips_override(self):
        # Override OFF -> the specific bucket collapses to 'all'; the raw
        # video_fps is preserved regardless.
        off = derive(raw_fps='23.976', fps_override=lambda hdr: False).profile
        assert off.fps_type == formats.FPS_ALL
        assert off.video_fps == 23
        # Override ON -> the bucket is preserved.
        on = derive(raw_fps='23.976', fps_override=lambda hdr: True).profile
        assert on.fps_type == 23

        # HDR unknown short-circuits the collapse condition, so the override
        # callable is never consulted and the detected bucket is left as-is.
        consulted = []

        def spy(hdr):
            consulted.append(hdr)
            return False

        facts = derive(raw_hdr='banana', raw_fps='23.976', fps_override=spy)
        assert facts.profile.hdr_type == formats.UNKNOWN
        assert consulted == []               # not consulted for unknown HDR
        assert facts.profile.fps_type == 23  # detected bucket kept (no collapse)


# ============================================================================
# Discovery: the budgeted probe chain
# ============================================================================

class TestDiscovery:

    def test_complete_stream_adopts_on_first_probe(self, rig):
        rig.start()
        session = rig.session
        # Probe #1 completed at once: profile written, STARTING -> STABILIZING,
        # both ProfileChanged and StreamProbed posted.
        assert session.profile.setting_id() == 'dolbyvision_all_truehd'
        assert session.stream_state is StreamState.STABILIZING
        assert len(rig.profiles) == 1
        assert rig.profiles[0].session_id == session.session_id
        assert len(rig.probes) == 1
        assert rig.stabilized == []          # verify not due yet

        rig.advance(1.0)                     # verify window elapses
        assert session.stream_state is StreamState.STABLE
        assert len(rig.stabilized) == 1
        assert len(rig.probes) == 2          # the verify gather posts a probe too
        assert rig.errors == []

    def test_late_codec_is_adopted_when_it_resolves(self, rig):
        # The legacy blocking retry loop, expressed as scheduled probes: the
        # chain keeps gathering until the codec negotiates in.
        rig.gateway.codec = 'none'
        rig.start()
        assert rig.session.profile is None
        assert rig.session.stream_state is StreamState.STARTING
        assert rig.profiles == []            # nothing adopted while incomplete

        rig.advance(0.5)                     # probe #2: codec still 'none'
        assert rig.session.profile is None
        assert rig.session.stream_state is StreamState.STARTING
        assert rig.profiles == []            # still no ProfileChanged before adoption

        rig.gateway.codec = 'truehd'         # negotiation finishes
        rig.advance(0.5)                     # probe #3: resolves -> adopt
        assert len(rig.profiles) == 1
        assert rig.session.profile.setting_id() == 'dolbyvision_all_truehd'
        assert rig.session.stream_state is StreamState.STABILIZING
        assert rig.errors == []

    def test_budget_exhaustion_warns_and_stops_probing(self, rig):
        _exhaust_discovery(rig)
        assert len(rig.warnings) == 1        # gave up exactly once
        assert rig.profiles == []            # never adopted
        assert rig.session.profile is None
        assert rig.session.stream_state is StreamState.STARTING
        # One gather (one StreamProbed) per attempt, budget attempts total.
        assert len(rig.probes) == StreamDetector.PROBE_BUDGET

        probes_after = len(rig.probes)
        rig.advance(10.0)                    # no timer remains after exhaustion
        assert len(rig.probes) == probes_after   # no further probe fires
        assert rig.errors == []

    def test_av_change_after_exhaustion_restarts_and_adopts(self, rig):
        _exhaust_discovery(rig)
        assert rig.session.profile is None

        # A change while still incomplete restarts the probe budget rather than
        # adopting (the profile gathered is still incomplete).
        rig.av_changed()
        assert rig.session.profile is None
        assert rig.session.stream_state is StreamState.STARTING
        assert rig.profiles == []
        assert any('restarting probes' in line for line in rig.debug)

        # Once the codec resolves, the restarted chain adopts on its next probe.
        rig.gateway.codec = 'truehd'
        rig.advance(0.5)
        assert len(rig.profiles) == 1
        assert rig.session.profile.setting_id() == 'dolbyvision_all_truehd'
        assert rig.session.stream_state is StreamState.STABILIZING
        assert rig.errors == []

    def test_reopen_stale_probe_never_adopts_into_new_session(self, rig):
        # In-place reopen: a probe scheduled/stamped for the OLD session must
        # never write the new session's profile — the is_alive guard drops it.
        rig.gateway.codec = 'none'
        rig.start()
        first = rig.session

        rig.dispatcher.post(events.PlaybackStarted())   # reopen without a stop
        rig.dispatcher.run_pending()
        second = rig.session
        assert second.session_id != first.session_id
        assert rig.tracker.is_alive(first.session_id) is False

        # Complete the stream, then fire a probe stamped with the DEAD session:
        # it is dropped before _gather, so no StreamProbed and no adoption.
        rig.gateway.codec = 'truehd'
        probes_before = len(rig.probes)
        rig.dispatcher.post(
            events.ProbeStream(session_id=first.session_id, attempt=2))
        rig.dispatcher.run_pending()
        assert len(rig.probes) == probes_before
        assert rig.profiles == []
        assert second.profile is None

        # The NEW session's own chain still proceeds to adoption.
        rig.advance(0.5)
        assert len(rig.profiles) == 1
        assert second.profile.setting_id() == 'dolbyvision_all_truehd'
        assert rig.errors == []

    def test_playback_stopped_cancels_pending_probes(self, rig):
        rig.gateway.codec = 'none'
        rig.start()
        assert len(rig.probes) == 1          # probe #1 fired; probe #2 scheduled

        rig.dispatcher.post(events.PlaybackStopped())
        rig.dispatcher.run_pending()
        assert rig.tracker.current is None

        # The scheduled probe was cancelled on stop: advancing never fires it.
        rig.advance(5.0)
        assert len(rig.probes) == 1
        assert rig.profiles == []
        assert rig.errors == []


# ============================================================================
# Change detection
# ============================================================================

class TestChangeDetection:

    def test_av_change_with_no_session_is_ignored(self, rig):
        # No PlaybackStarted yet: nothing to gather for; returns before _gather.
        rig.dispatcher.post(events.AvChanged())
        rig.dispatcher.run_pending()
        assert rig.profiles == []
        assert rig.probes == []
        assert any('no session' in line for line in rig.debug)
        assert rig.errors == []

    def test_unchanged_av_change_is_ignored(self, rig):
        rig.start()
        rig.advance(1.0)                     # settle -> STABLE
        assert rig.session.stream_state is StreamState.STABLE
        profiles_before = len(rig.profiles)

        rig.av_changed()                     # gateway unchanged
        assert len(rig.profiles) == profiles_before   # no new adoption
        assert rig.session.stream_state is StreamState.STABLE  # never regressed
        assert any('unchanged profile' in line for line in rig.debug)
        assert rig.errors == []

    def test_av_change_storm_collapses_to_one_adoption(self, rig):
        rig.start()
        rig.advance(1.0)
        assert len(rig.profiles) == 1
        assert len(rig.stabilized) == 1

        # One real codec switch, three onAVChange notifications around it: only
        # the first re-gather sees a change; the rest match and are ignored.
        rig.gateway.codec = 'eac3'
        rig.dispatcher.post(events.AvChanged())
        rig.dispatcher.post(events.AvChanged())
        rig.dispatcher.post(events.AvChanged())
        rig.dispatcher.run_pending()
        assert len(rig.profiles) == 2        # exactly one new adoption
        assert rig.session.stream_state is StreamState.STABILIZING
        assert len(rig.stabilized) == 1      # not stable again until re-verify

        rig.advance(1.0)
        assert rig.session.stream_state is StreamState.STABLE
        assert len(rig.stabilized) == 2
        assert rig.session.profile.setting_id() == 'dolbyvision_all_eac3'
        assert rig.errors == []

    def test_av_change_during_discovery_is_ignored(self, rig):
        # Mid-discovery the probe chain already re-reads facts every attempt,
        # so an AvChanged does no immediate gather-adopt; it just gets logged.
        rig.gateway.codec = 'none'
        rig.start()
        probes_before = len(rig.probes)

        rig.av_changed()
        assert len(rig.probes) == probes_before   # no extra gather here
        assert rig.profiles == []
        assert rig.session.profile is None
        assert any('during discovery' in line for line in rig.debug)

        # The probe chain itself picks the change up on its next attempt.
        rig.gateway.codec = 'truehd'
        rig.advance(0.5)
        assert len(rig.profiles) == 1
        assert rig.errors == []


# ============================================================================
# Verification recovery edges
# ============================================================================

class TestVerificationRecovery:

    def test_blip_and_revert_restabilizes(self, rig):
        # Recovery edge A: a STABLE stream blips incomplete, then reverts to the
        # original profile before the verify fires -> STABLE again, no adoption.
        rig.start()
        rig.advance(1.0)
        assert rig.session.stream_state is StreamState.STABLE
        original_setting = rig.session.profile.setting_id()

        rig.gateway.codec = 'none'           # codec blip: profile goes incomplete
        rig.av_changed()
        assert rig.session.stream_state is StreamState.STABILIZING  # regressed
        assert len(rig.profiles) == 1        # no adoption (incomplete profile)
        assert any('profile lost' in line for line in rig.debug)

        rig.gateway.codec = 'truehd'         # reverts before the window fires
        rig.advance(1.0)
        assert rig.session.stream_state is StreamState.STABLE
        assert rig.session.profile.setting_id() == original_setting
        assert len(rig.profiles) == 1        # never re-adopted -> no stranding
        assert len(rig.stabilized) == 2
        # The re-confirmation announces NO change (no adoption in between):
        # the router suppresses the legacy ON_AV_CHANGE for it, so a pure
        # blip can never fire a spurious 'adjust' seek-back.
        assert rig.stabilized[0].profile_changed is True    # startup settle
        assert rig.stabilized[1].profile_changed is False   # blip re-confirm
        assert rig.errors == []

    def test_incidental_field_wiggle_still_stabilizes(self, rig):
        # Stability is judged on the OFFSET-RELEVANT identity (setting_id
        # axes), not raw dataclass equality: a channel count that flickers
        # between gathers (passthrough sync) must not strand the session in
        # a perpetual re-adopt loop — it stabilizes, and the fresher
        # incidental fields are refreshed silently (no extra ProfileChanged).
        rig.start()
        assert rig.session.profile.audio_channels == 8

        rig.gateway.channels = 6             # wiggles before the verify fires
        rig.advance(1.0)
        assert rig.session.stream_state is StreamState.STABLE
        assert len(rig.stabilized) == 1
        assert rig.stabilized[0].profile_changed is True
        assert len(rig.profiles) == 1        # no re-adoption for the wiggle
        assert rig.session.profile.audio_channels == 6   # silently refreshed

        # Same for a mid-play AvChanged that only wiggles incidental fields.
        rig.gateway.channels = 8
        rig.av_changed()
        assert rig.session.stream_state is StreamState.STABLE  # not regressed
        assert len(rig.profiles) == 1
        assert rig.session.profile.audio_channels == 8
        assert rig.errors == []

    def test_change_during_verification_readopts(self, rig):
        # Recovery edge B: profile A adopted; it becomes B before A's verify
        # fires -> verify re-adopts B (second ProfileChanged), STILL verifying;
        # the next verify settles B.
        rig.start()
        assert rig.session.profile.setting_id() == 'dolbyvision_all_truehd'
        assert len(rig.profiles) == 1

        rig.gateway.codec = 'eac3'           # A -> B before the 1s verify
        rig.advance(1.0)
        assert rig.session.profile.setting_id() == 'dolbyvision_all_eac3'
        assert len(rig.profiles) == 2        # re-adopted
        assert rig.session.stream_state is StreamState.STABILIZING  # still verifying
        assert rig.stabilized == []

        rig.advance(1.0)                     # next verify: B held -> STABLE
        assert rig.session.stream_state is StreamState.STABLE
        assert len(rig.stabilized) == 1
        assert rig.errors == []


# ============================================================================
# Post ordering, sole-writer freshness, and stale-event guards
# ============================================================================

class TestOrderingAndGuards:

    def test_stream_state_is_stable_when_stabilized_delivered(self, rig):
        # The detector marks the session STABLE BEFORE posting StreamStabilized,
        # so any consumer reading session state on delivery sees STABLE.
        rig.start()
        observed = []
        rig.dispatcher.subscribe(
            events.StreamStabilized,
            lambda e: observed.append(rig.tracker.current.stream_state))
        rig.advance(1.0)
        assert observed == [StreamState.STABLE]

    def test_setting_id_tracks_current_gateway_after_each_adoption(self, rig):
        # Sole-writer + freshness: every adoption derives setting_id() from the
        # gateway's CURRENT readings, never a carried-over profile.
        rig.start()
        assert rig.session.profile.setting_id() == 'dolbyvision_all_truehd'

        rig.gateway.codec = 'eac3'
        rig.av_changed()
        assert rig.session.profile.setting_id() == 'dolbyvision_all_eac3'

        rig.gateway.infolabels[INFOLABEL_HDR] = 'hdr10'
        rig.av_changed()
        assert rig.session.profile.setting_id() == 'hdr10_all_eac3'
        assert rig.errors == []

    def test_stale_verify_for_dead_session_is_dropped(self, rig):
        # Guard 1: is_alive. A verification for a session that has since ended
        # must be dropped without touching the (now None) current session.
        rig.start()
        dead_id = rig.session.session_id
        rig.dispatcher.post(events.PlaybackStopped())
        rig.dispatcher.run_pending()
        assert rig.tracker.current is None

        rig.dispatcher.post(events.VerifyStream(session_id=dead_id, seq=1))
        rig.dispatcher.run_pending()
        assert rig.stabilized == []
        assert rig.errors == []

    def test_stale_verify_with_wrong_seq_is_dropped(self, rig):
        # Guard 2: seq. A VerifyStream carrying a superseded seq for the LIVE
        # session is dropped, and the real scheduled verify still settles it.
        rig.start()
        rig.dispatcher.post(
            events.VerifyStream(session_id=rig.session.session_id, seq=999))
        rig.dispatcher.run_pending()
        assert rig.session.stream_state is StreamState.STABILIZING
        assert rig.stabilized == []

        rig.advance(1.0)                     # the real verify (correct seq) fires
        assert rig.session.stream_state is StreamState.STABLE
        assert len(rig.stabilized) == 1
        assert rig.errors == []


# ============================================================================
# Platform-facts emission
# ============================================================================

class TestPlatformFactsEmission:

    def test_every_gather_posts_exactly_one_stream_probed(self, rig):
        # Wrap _gather to count invocations; StreamProbed is posted once per
        # gather, so the counts must stay equal across startup, settle, an
        # AV-change re-probe and a second settle (4 gathers total).
        gathers = []
        original = rig.detector._gather

        def counting(session_id):
            gathers.append(session_id)
            return original(session_id)

        rig.detector._gather = counting

        rig.start()          # gather #1: discovery probe
        rig.advance(1.0)     # gather #2: verify
        rig.gateway.codec = 'eac3'
        rig.av_changed()     # gather #3: AV-change re-probe
        rig.advance(1.0)     # gather #4: verify

        assert len(gathers) == 4
        assert len(rig.probes) == len(gathers)   # one StreamProbed per gather
        assert rig.errors == []
