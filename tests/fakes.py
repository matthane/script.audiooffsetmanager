"""Shared test fakes for the Audio Offset Manager suite.

Intentionally empty in Phase 0 — placeholder only.

The Phase 2+ dispatcher/session redesign (see DESIGN.md, "Testing
architecture") introduces fake collaborators that unit and integration tests
will share from here: a FakeClock/waiter pair for deterministic, instant
timer tests, a fake Kodi gateway, and a fake settings store. They arrive with
the components that need them; until then this module holds no fakes.
"""
