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

## Kodi packaging constraints (important)

- Keep the package clean. Only files that belong in the addon should be
  **tracked without** `export-ignore`. Dev tooling (this file, CI, git config,
  `.claude/`) must be listed in `.gitattributes` as `export-ignore`.
- Requires `xbmc.python` **3.0.1**; submitted to the **`nexus`** branch of
  `xbmc/repo-scripts`.
- Submission is automated by `.github/workflows/submit.yml`, which runs
  `kodi-addon-submitter` (packages via `git archive` and opens the PR). It
  triggers **only on `release: [released]`** — i.e. publishing a *stable*
  (non-prerelease) GitHub Release. Pushing a tag alone does nothing; a
  pre-release (beta) fires `prereleased`/`published`, not `released`, so betas
  stay as pre-release tags and are never submitted. The package version comes
  from `addon.xml`, not the release/tag name. Do not hand-copy files into
  repo-scripts.
- Verify what will ship at any time:
  `git archive --format=zip -o /tmp/pkg.zip HEAD` and inspect the zip.

## MIGRATION IN PROGRESS (branch `redesign/2.0`)

The service is being rebuilt on a single-threaded dispatcher with
per-playback `PlaybackSession` state and a STARTING/STABILIZING/STABLE
stream-state machine (see `resources/lib/aom/` module docstrings). On that
branch, the sections below describing `AddonManager`, `EventManager`, the
`playback_state` dict, `_last_applied`, the 2.0s startup grace window, and
the `last_audio_codec` mirror flow are **superseded** — trust the code and
the `aom` docstrings over this file until the scheduled end-of-migration
rewrite. The **settings-state doctrine** (live proxy, dialog write ordering,
fresh-`setting_id()` derivation) remains fully accurate and binding.

## Entry points

Two extension points defined in `addon.xml`:

- `service.py` → `AddonManager` — the background service (`xbmc.service`).
  Builds all components, `start()`s them, then blocks on
  `xbmc.Monitor().waitForAbort()` until Kodi shuts down, then `stop()`s.
- `script.py` → `script_handler.handle_script_call` — the user-invoked helper
  (`xbmc.python.script`). Routes the `RunScript` argument: `play_test_video`,
  `bypass_test_video`, or (no/unknown arg) just opens addon settings.

## Architecture

`AddonManager` ([resources/lib/addon_manager.py](resources/lib/addon_manager.py))
constructs the shared dependencies **once** and injects them into every
component via constructors (no globals, no per-module re-instantiation of
shared state):

- `SettingsManager` / `SettingsFacade` — settings access (see the dedicated
  section below — this is the heart of the addon's correctness).
- `StreamInfo` — detects HDR type, audio format, FPS type of current playback
  via JSON-RPC + InfoLabels; produces an immutable `StreamProfile`.
- `EventManager` — subclasses `xbmc.Player`; receives Kodi playback callbacks,
  filters them, and republishes them on the `EventBus`.
- `OffsetManager` — the consumer that actually applies audio offsets in
  response to events, and owns the `ActiveMonitor` lifecycle.
- `SeekBacks` — seek-back behaviour on resume/adjust/unpause/change events.
- `NotificationHandler` — user-facing GUI notifications.

Communication is via a lightweight **event bus**
([resources/lib/event_bus.py](resources/lib/event_bus.py)): components
`subscribe(event_name, callback)` and `EventManager` `publish()`es events.
The bus can log per-callback runtimes when `log_runtimes=True` (handler name +
ms), useful for debugging slow handlers; it is enabled when debug logging is on.

### Event flow

Kodi `xbmc.Player` callbacks land on `EventManager`, which maintains a
`playback_state` dict (`start_time`, `av_started`, `last_event`,
`last_audio_codec`) and publishes named events:

- `onAVStarted` → `AV_STARTED`
- `onAVChange` → debounced through `AvChangeFilter`, then `ON_AV_CHANGE`
- `onPlayBackStopped` / `onPlayBackEnded` → `PLAYBACK_STOPPED` /
  `PLAYBACK_ENDED`
- `onPlayBackPaused` / `onPlayBackResumed` → `PLAYBACK_PAUSED` /
  `PLAYBACK_RESUMED`
- `onPlayBackSeek` / `onPlayBackSeekChapter` / `onPlayBackSpeedChanged` →
  corresponding events
- `USER_ADJUSTMENT` — published by `ActiveMonitor` when the user manually
  changes the offset during playback.

`AvChangeFilter` ([resources/lib/av_change_filter.py](resources/lib/av_change_filter.py))
debounces noisy `onAVChange` storms: it waits 1s and only fires `ON_AV_CHANGE`
once the audio codec has held steady, using a sequence counter so a newer
change supersedes a pending one. This codec-stability signal is also surfaced
to `OffsetManager` (via `playback_state['last_audio_codec']`) to suppress
premature notifications during the startup grace period.

### Offset application pipeline

`OffsetManager._handle_av_event` is the core path on `AV_STARTED` /
`ON_AV_CHANGE`:

1. `StreamInfo.update_stream_info()` rebuilds the immutable `StreamProfile`.
2. `apply_audio_offset()` decides and applies via `_should_apply_offset()`
   gating (skips new installs, missing profile, any `unknown`
   HDR/audio/FPS, or disabled HDR type).
3. The offset value is looked up by `profile.setting_id()` and pushed through
   `rpc_client.set_audio_delay()`.
4. `manage_active_monitor()` starts/stops the `ActiveMonitor` thread.

`_last_applied = (setting_id, delay_ms)` guards against redundant re-application
of the same offset. Notifications are deferred (`_pending_notification`) while
the codec is still stabilizing within `_startup_grace_seconds` (2.0s).

### Stream profile (the lookup key)

`StreamProfile` ([resources/lib/stream_profile.py](resources/lib/stream_profile.py))
is a **frozen dataclass**. Its `setting_id()` is the single source of truth for
which settings key a given stream maps to:

```
<hdr_type>_<fps_key>_<audio_format>     e.g. "dolbyvision_all_truehd"
```

- `hdr_type` ∈ `dolbyvision, hdr10, hdr10plus, hlg, sdr` (else `unknown`).
- `audio_format` ∈ `truehd, eac3, ac3, dtshd_ma, dtshd_hra, dca, pcm` (else
  `unknown`).
- `fps_key` is either a specific bucket (`23,24,25,29,30,50,59,60`) or `all`
  when the per-HDR FPS override is off (`StreamInfo` collapses it to `all`,
  mirrored by `SettingsFacade.effective_fps_bucket`).

`settings.xml` contains one integer offset setting per valid
`<hdr>_<fps>_<audio>` combination (hundreds of them), grouped into per-HDR
categories. Keep the `setting_id()` format, the `valid_*` lists in `StreamInfo`,
and the settings IDs in `settings.xml` in lockstep — a mismatch silently means
"no offset found."

### Other components

- `ActiveMonitor` ([resources/lib/active_monitor.py](resources/lib/active_monitor.py))
  — a background thread (only running when `enable_active_monitoring` and the
  current HDR type are on). It watches the Kodi audio-settings/slider dialogs,
  and when the user manually changes the delay it **writes** the new value back
  into the profile's `setting_id()` and publishes `USER_ADJUSTMENT`. This is a
  primary writer of settings state during playback (see below).
- `SeekBacks` ([resources/lib/seek_backs.py](resources/lib/seek_backs.py)) —
  performs short backward seeks after resume/adjust/unpause/change events, with
  extensive guards (per-event 2s debounce, in-progress lock, paused check, and
  PM4K/Plexmod coordination so the two addons don't fight over seeks).
- `rpc_client` ([resources/lib/rpc_client.py](resources/lib/rpc_client.py)) —
  all Kodi JSON-RPC calls (active player id, audio info, set audio delay,
  seek), with jittered retries.
- `NotificationHandler` — GUI notifications with a 1s dedupe window.
- `logger.log()` ([resources/lib/logger.py](resources/lib/logger.py)) —
  messages prefixed `AOM_`; `LOGDEBUG` is escalated to `LOGINFO` when
  `enable_debug_logging` is on.
- `debug_snapshot.log_snapshot()` — one-line state dump (profile, offset,
  seek config) at key events when debug logging is enabled.
- `TestVideoManager` ([resources/lib/test_video.py](resources/lib/test_video.py))
  — onboarding test-video playback and the `new_install` bypass.

## Settings state management (read this before touching settings)

This addon is fundamentally a **state machine over `settings.xml`**: it both
reads configuration *and* writes runtime/user state back into the same file
(offset values from the active monitor, `platform_hdr_full`, `advanced_hlg`,
`new_install`). Keeping a consistent view of state across components and threads
is the hardest correctness problem in this codebase — but, importantly, **the
hazard is stale *derived* state in the components, not the settings store
itself.**

### Kodi's settings object is a live, shared proxy (confirmed)

`xbmcaddon.Addon().getSettings()` does **not** return a frozen snapshot — it is
a live view onto Kodi's in-process settings store. Confirmed empirically, in
both directions, with no Kodi restart:

- GUI settings edits take effect in the already-running service immediately.
- Active-monitor writes during playback show up in the settings GUI immediately.

So the `settings.xml`-backed values are a **single, consistent source of truth**
for the running service: every read sees current values and every write is
visible everywhere at once. The settings file cannot "drift out of sync with
itself."

Consequences for the existing machinery:

- **`SettingsManager` (singleton) is a convenience, not a correctness barrier.**
  ([resources/lib/settings_manager.py](resources/lib/settings_manager.py)) It
  gives one shared object for centralized logging and the store-if-changed
  guard. The single shared `getSettings()` proxy is what makes reads/writes
  consistent — the singleton just keeps it tidy.
- **There is no "force reload" of settings.** `getSettings()` returns a live
  proxy onto Kodi's in-memory store, not a snapshot, so re-fetching it reloads
  nothing — there is no Python API to re-read `settings.xml` from disk into the
  core. (A `reload_if_needed()` method used to exist for this; it was a no-op
  and has been removed.)

### Writes don't "stick" if the settings dialog is open

The one real way a write gets lost is the **settings dialog's working copy**.
While the addon settings dialog is open, Kodi holds the values in a dialog
buffer and **writes that buffer back on close** — so a programmatic
`setBool`/`setInt` made *while the dialog is open* can be clobbered when the
dialog saves. This is the actual cause of "the setting won't stick," and no
reload fixes it; correct **write ordering** does.

`TestVideoManager.bypass_test_video()` is the worked example: its action button
uses `<close>true</close>` so the dialog is already closed before the script
writes `new_install=False`, and a short `xbmc.sleep(500)` lets the write settle
before settings are reopened. The active-monitor write path is safe for the same
reason — it only runs during playback, when no settings dialog is open.

### The real hazard: stale *derived* state

Past offset-overwrite bugs did not come from the settings store drifting. They
came from a component acting on **cached derived state** that no longer matched
the live stream/settings, then writing or applying against the **wrong key or
an outdated value**. The file was fine; the decision feeding the write was
stale.

Key fact: **applying an offset automatically is a JSON-RPC player call**
(`rpc_client.set_audio_delay`), **not a settings write** — so automatic
application can never overwrite a stored value. The **only** writer of offset
*values* into `settings.xml` is `ActiveMonitor.process_audio_delay_change`
(manual user change → `store_setting_integer(profile.setting_id(), delay_ms)`).
An offset therefore gets "reverted to a prior state" only when that writer fires
with a **stale `setting_id` or a stale tracked value**.

Derived state that must be kept honest (these are the real drift sources):

- `stream_info.profile` — the immutable profile; `setting_id()` is derived from
  it. A writer/applier using an out-of-date profile reads/writes the **wrong**
  settings key (wrong HDR/FPS/audio bucket).
- `ActiveMonitor.state` — `last_stored_delay`, `last_processed_delay`,
  `last_audio_delay`.
- `OffsetManager._last_applied` — `(setting_id, delay_ms)` dedupe guard.
- `StreamInfo.new_install` — read once at `__init__`, flipped on first playback.
- `EventManager.playback_state['last_audio_codec']` and
  `AvChangeFilter.last_audio_codec` — codec-stability tracking.

### Rules when changing settings code

- **Always derive `setting_id()` from the *current* `stream_info.profile`** at
  the moment you read or write — never from a profile captured during an earlier
  event. Stale keys are how an offset lands on (or is read from) the wrong
  profile.
- Route reads/writes through the injected `SettingsManager` / `SettingsFacade`
  for consistent logging and the store-if-changed guard. (Correctness comes from
  the live proxy; the singleton just keeps access uniform.)
- Prefer the `store_*_if_changed` helpers; preserve the read-before-write skip.
- **Don't write a setting from Python while the settings dialog is open** — the
  dialog's save-on-close will overwrite you. Write with the dialog closed (e.g.
  via a `<close>true</close>` action button) and let it settle before reopening.
- When you add a writer, ask: *is the profile/key I'm writing under freshly
  derived, or carried over from an earlier event?* That — not settings-object
  caching — is the source of the past offset-overwrite bugs.
- The service (`service.py`) and helper (`script.py`) run as **separate
  processes** and don't share Python state. Script-side writes still reach the
  service through the live on-disk store with no manual reload (confirmed) — so
  there's nothing special to do, but don't assume in-memory objects are shared
  across the two.

## Conventions

- Match the existing style: module docstrings, explicit dependency injection
  through constructors (see `AddonManager`), no global state.
- Keep new runtime files inside `resources/lib/`.
- Route all Kodi JSON-RPC through `rpc_client`; route all logging through
  `logger.log()` with an `AOM_`-prefixed message.
- Bump `version` in `addon.xml` and add a `<news>` entry for each release.
