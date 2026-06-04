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
  **tracked without** `export-ignore`. Dev tooling (this file, CI, git config)
  must be listed in `.gitattributes` as `export-ignore`.
- Requires `xbmc.python` **3.0.1**; submitted to the **`nexus`** branch of
  `xbmc/repo-scripts`.
- Submission is automated: push a git tag → `.github/workflows/submit.yml`
  runs `kodi-addon-submitter`, which packages via `git archive` and opens the
  PR. Do not hand-copy files into repo-scripts.
- Verify what will ship at any time:
  `git archive --format=zip -o /tmp/pkg.zip HEAD` and inspect the zip.

## Architecture

Two entry points defined in `addon.xml`:

- `service.py` → `AddonManager` — the background service (`xbmc.service`).
- `script.py` → `script_handler.handle_script_call` — the user-invoked helper
  (`xbmc.python.script`).

`AddonManager` ([resources/lib/addon_manager.py](resources/lib/addon_manager.py))
wires up shared dependencies and starts the components:

- `SettingsManager` / `SettingsFacade` — settings access.
- `StreamInfo` — detects HDR type, audio format, FPS type of current playback.
- `EventManager` — playback/AV-change event detection, built on the
  `EventBus`.
- `OffsetManager` — applies audio offsets in response to events.
- `SeekBacks` — seek-back behaviour.
- `NotificationHandler` — user-facing notifications.

Communication is via a lightweight **event bus**
([resources/lib/event_bus.py](resources/lib/event_bus.py)): components
`subscribe(event_name, callback)` and `EventManager` `publish()`es events.
The bus can log per-callback runtimes when `log_runtimes=True` (handler name +
ms), useful for debugging slow handlers.

Logging goes through [resources/lib/logger.py](resources/lib/logger.py)
(`log()`); messages are prefixed with `AOM_`.

## Conventions

- Match the existing style: module docstrings, explicit dependency injection
  through constructors (see `AddonManager`), no global state.
- Keep new runtime files inside `resources/lib/`.
- Bump `version` in `addon.xml` and add a `<news>` entry for each release.
