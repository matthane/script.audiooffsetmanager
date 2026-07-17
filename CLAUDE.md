# CLAUDE.md

Guidance for working in this repo. This file is **dev-only**: it is marked
`export-ignore` in `.gitattributes`, so `git archive` / the Kodi submitter
strip it from every submission package. It will never reach repo-scripts.

## What this is

`script.audiooffsetmanager` ("Audio Offset Manager") — a Kodi add-on that
dynamically adjusts the audio offset during playback based on detected HDR
type, audio format, and FPS type, per user-configured settings. It also
provides seek-back behaviour and playback notifications.

The repo root **is** the addon folder (no wrapping subdirectory): `addon.xml`,
`service.py`, and `script.py` sit at the top level. Everything tracked here is
part of the shipped addon unless `export-ignore`'d.

Version 2.0.0 is a ground-up rebuild of the runtime on a single-threaded
dispatcher (the `redesign/2.0` branch, merged in one deliberate merge). The
design rationale and the phase-by-phase build log live in `DESIGN.md` and
`IMPLEMENTATION.md` at the repo root — both **git-ignored, local-only** files
that exist only in the primary working copy.

## Kodi packaging constraints (important)

- Keep the package clean. Only files that belong in the addon should be
  **tracked without** `export-ignore`. Dev tooling (this file, CI, git config,
  `.claude/`, `tests/`, `tools/`) must be listed in `.gitattributes` as
  `export-ignore`.
- Requires `xbmc.python` **3.0.1** (Kodi v20 "Nexus"; Python 3.8 syntax only);
  submitted to the **`nexus`** branch of `xbmc/repo-scripts`.
- Submission is automated by `.github/workflows/submit.yml`, which runs
  `kodi-addon-submitter` (packages via `git archive` and opens the PR). It
  triggers **only on `release: [released]`** — i.e. publishing a *stable*
  (non-prerelease) GitHub Release. Pushing a tag alone does nothing; a
  pre-release (beta) fires `prereleased`/`published`, not `released`, so betas
  stay as pre-release tags and are never submitted. As a hard backstop the
  workflow refuses any addon.xml version containing `~`. The package version
  comes from `addon.xml`, not the release/tag name. Do not hand-copy files
  into repo-scripts.
- Verify what will ship at any time:
  `git archive --format=zip -o /tmp/pkg.zip HEAD` and inspect the zip.

## Entry points

Two extension points defined in `addon.xml`, running as **separate
processes**:

- `service.py` → [aom/runtime.py](resources/lib/aom/runtime.py)
  `ServiceRuntime` — the background service (`xbmc.service`). The composition
  root: builds the dispatcher, the Kodi adapters, and every app component
  with explicit constructor injection, subscribes them **in a load-bearing
  order** (documented in the runtime module docstring), starts the dispatcher
  thread, then blocks on the monitor until Kodi aborts.
- `script.py` → [aom/onboarding.py](resources/lib/aom/onboarding.py)
  `handle_script_call` — the user-invoked helper (`xbmc.python.script`).
  Routes the `RunScript` argument: `play_test_video`, `bypass_test_video`, or
  (no/unknown arg) opens addon settings.

## Architecture

The `resources/lib/aom/` package is layered, and **the module docstrings are
the architecture documentation** — this section is the map, not the
territory:

- [aom/domain/](resources/lib/aom/domain/) — pure vocabulary and policy:
  `formats` (the HDR/audio/FPS vocabulary that generates `settings.xml`),
  `profile` (the frozen `StreamProfile`), `stream_state` (the state machine
  enum), `policies` (pure decision functions, e.g. seek decisions).
- [aom/app/](resources/lib/aom/app/) — the runtime components, all driven by
  typed events on one dispatcher thread (below).
- [aom/kodi/](resources/lib/aom/kodi/) — the only layer allowed to import
  `xbmc*`: `gateway` (single-shot JSON-RPC/InfoLabel calls), `settings`,
  `gui` (toasts), `log`, and the `player_bridge`/`monitor_bridge` that turn
  Kodi callbacks into posted events.

`domain` and `app` are **pure** (stdlib + `resources.lib.aom` only) — the
contract test [tests/contract/test_architecture.py](tests/contract/test_architecture.py)
enforces it by AST; there are no exemptions.

### The dispatcher owns all state

[aom/app/dispatcher.py](resources/lib/aom/app/dispatcher.py) is a
single-threaded event loop with a monotonic timer scheduler. Kodi bridges
(and any other thread) only ever call `post()`; handlers, timers, and every
state mutation run serialized on the dispatcher thread — **no locks exist
above this module**. Timers support keyed supersede (`schedule(..., key=)`
replaces the pending timer with the same key) — the debounce/defer primitive
used by the detector, seek scheduler, adjustment watcher, and notifier.

### Sessions and the stream-state machine

[aom/app/session.py](resources/lib/aom/app/session.py) — `SessionTracker`
owns one `PlaybackSession` per playback. All per-playback state
(profile, stream state, applied offset, pending notification, pause flag) is
**session-borne**, so state reset is structural: a new session starts clean,
and stale-session events are dropped by their `session_id` stamp. The stream
state machine is STARTING → STABILIZING → STABLE, with re-verification edges
on stream changes.

### Components (subscription order = dispatch order, see runtime.py)

- `SessionTracker` — session lifecycle; always first.
- `StreamDetector` ([stream_detector.py](resources/lib/aom/app/stream_detector.py))
  — scheduled budgeted probes at startup, whole-profile 1s verification
  windows, sole writer of `session.profile`; posts `ProfileChanged` /
  `StreamStabilized`.
- `PlatformRecorder` — persists platform capability flags observed on every
  probe (`platform_hdr_full`, `advanced_hlg`).
- `OffsetApplier` ([offset_applier.py](resources/lib/aom/app/offset_applier.py))
  — applies the stored offset on `ProfileChanged` (provisional) and retries
  on `StreamStabilized`; records `session.applied` BEFORE the JSON-RPC call
  (the applied-before-RPC rule the watcher's self-echo suppression depends
  on).
- `Notifier` ([notifier.py](resources/lib/aom/app/notifier.py)) — all toasts:
  deferral-until-stable, a 1s dedupe window, and the fade guard (defers a
  toast that would ride the previous toast's fade-out animation — the module
  docstring is the authoritative account of the Kodi toast mechanics).
- `SeekScheduler` / `ExternalSeekCoordinator`
  ([seek_scheduler.py](resources/lib/aom/app/seek_scheduler.py)) — seek-backs
  with STABLE-preferring deferral, the external-seek quiet window, and PM4K
  coordination via the `script.audiooffsetmanager.seeking` window property.
- `AdjustmentWatcher` ([adjustment_watcher.py](resources/lib/aom/app/adjustment_watcher.py))
  — polls `Player.AudioDelay` on dispatcher ticks (1.0s idle / 0.25s active
  cadences, 2.0s quiescence), so manual adjustments are caught from **any**
  input method (GUI slider, keymaps, remotes, JSON-RPC). The sole writer of
  offset values into settings. Posts `UserOffsetSaved`.

Events are frozen dataclasses in [events.py](resources/lib/aom/app/events.py),
dispatched by type; payloads are explicit fields, session-stamped where a
stale delivery must be inert.

### Stream profile (the lookup key)

`StreamProfile` ([aom/domain/profile.py](resources/lib/aom/domain/profile.py))
is a frozen dataclass. Its `setting_id()` is the single source of truth for
which settings key a stream maps to:

```
<hdr_type>_<fps_key>_<audio_format>     e.g. "dolbyvision_all_truehd"
```

- `hdr_type` ∈ `dolbyvision, hdr10, hdr10plus, hlg, sdr` (else `unknown`).
- `audio_format` ∈ `truehd, eac3, ac3, dtshd_ma, dtshd_hra, dca, pcm` (else
  `unknown`).
- `fps_key` is a specific bucket (`23,24,25,29,30,50,59,60`) or `all` when
  the per-HDR FPS override is off.

`resources/settings.xml` (one integer offset setting per valid combination)
is **generated** by [tools/generate_settings.py](tools/generate_settings.py)
from `aom.domain.formats`; the contract tests enforce lockstep. **Setting ids
are FROZEN for user-data compatibility** — users upgrading keep their stored
offsets. Never change the `setting_id()` format or the vocabulary without
regenerating and consciously accepting the migration consequences.

## Settings state management (read this before touching settings)

The addon both reads configuration *and* writes runtime/user state back into
`settings.xml` (offset values from the adjustment watcher,
`platform_hdr_full`, `advanced_hlg`, `new_install`). The store itself is
consistent; the hazards are the proxy's lifetime, the dialog's working copy,
and stale *derived* state.

### Kodi's settings object is a live, shared proxy (confirmed)

`xbmcaddon.Addon().getSettings()` does **not** return a frozen snapshot — it
is a live view onto Kodi's in-process settings store. Confirmed empirically,
in both directions, with no Kodi restart: GUI edits take effect in the
running service immediately, and service writes show up in the GUI
immediately. There is **no "force reload"** — re-fetching the proxy reloads
nothing.

**LIFETIME RULE (learned the hard way in the 2.0 beta cycle):** the proxy is
live only while its **parent `Addon` object is alive**. Building it as
`xbmcaddon.Addon(ID).getSettings()` orphans the proxy when the temporary
`Addon` is garbage-collected — writes then report success but never persist.
Keep the `Addon` on `self` for the proxy's whole lifetime
([aom/kodi/settings.py](resources/lib/aom/kodi/settings.py) documents this).

### Writes don't "stick" if the settings dialog is open

While the addon settings dialog is open, Kodi holds values in a dialog
buffer and **writes that buffer back on close** — a programmatic
`setBool`/`setInt` made while the dialog is open can be clobbered when the
dialog saves. Correct **write ordering** fixes this, not reloads: action
buttons that lead to writes use `<close>true</close>` so the dialog is
closed before the write, and the write settles before settings reopen
(`bypass_test_video` in [aom/onboarding.py](resources/lib/aom/onboarding.py)
is the worked example). The watcher additionally defers its store while
`gateway.settings_dialog_open()` reports the dialog up.

### The real hazard: stale derived state

Past offset-overwrite bugs came from a component acting on cached derived
state that no longer matched the live stream/settings, then writing or
applying against the wrong key or an outdated value. The 2.0 architecture
makes most of this structural — per-session state dies with the session, and
events carry session stamps — but the rules remain binding:

- **Always derive `setting_id()` from the current `session.profile`** at the
  moment you read or write — never from a profile captured during an earlier
  event. (The notifier's stabilization release re-derives and drops the toast
  if the key changed; follow that pattern.)
- Applying an offset automatically is a **JSON-RPC player call**
  (`gateway.set_audio_delay`), not a settings write — automatic application
  can never overwrite a stored value. The **only** writer of offset values is
  `AdjustmentWatcher._store` (manual user change), and it re-checks player
  liveness at store time (teardown-phantom guard) and captures the
  profile/value it stored on the `UserOffsetSaved` event so consumers act on
  exactly what was stored.
- Settings writes happen **only on the dispatcher thread**.
- The service (`service.py`) and helper (`script.py`) run as separate
  processes and don't share Python state; script-side writes reach the
  service through the live store with no manual reload.

## Tests and tooling (dev-only, never shipped)

- `python -m pytest -q` from the repo root (project venv:
  `.venv/Scripts/python.exe`; deps in `requirements-dev.txt`). The full suite
  must be green before every commit.
- `tests/contract/` pins the architecture purity, the generated
  `settings.xml` lockstep, and the strings table; `tests/unit/` drives
  components on a manually pumped dispatcher with a fake clock
  (`tests/fakes.py`).
- CI (`.github/workflows/ci.yml`) runs pytest on 3.8 + 3.12 and
  `kodi-addon-checker` (nexus) against the `git archive` output on every
  push.

## Conventions

- Match the existing style: module docstrings (they ARE the docs), explicit
  constructor dependency injection (see `ServiceRuntime`), no globals, no
  locks above the dispatcher.
- Python 3.8 syntax only; new runtime files go under `resources/lib/aom/` in
  the layer that matches their imports.
- Kodi I/O goes through the `aom/kodi` adapters; logging through the
  injected sinks with `AOM_`-prefixed messages (`LOGDEBUG` escalates to
  `LOGINFO` when `enable_debug_logging` is on).
- Small imperative commits with the
  `Co-authored-by: Claude <noreply@anthropic.com>` trailer; annotated tags
  only (repo config rejects lightweight tags).
- Bump `version` in `addon.xml` and add a `<news>` entry for each release;
  betas carry `~` versions and are never promoted to stable Releases.
