"""Contract tests for aom.app.events — the typed event catalog.

Events are dispatched by ``type`` and parked on a queue / timer heap, so each
must be an immutable value object: a frozen dataclass with equality by payload.
This suite pins that for the whole catalog and asserts the player/monitor group
Phase 2 posts and consumes exists by name.
"""

from dataclasses import FrozenInstanceError, is_dataclass

import pytest

from resources.lib.aom.app import events


# The player/monitor group Phase 2 wires up (posted by the Kodi bridges).
PHASE2_GROUP = [
    "PlaybackStarted", "AvChanged", "PlaybackStopped", "PlaybackEnded",
    "Paused", "Resumed", "SeekOccurred", "SeekChapter", "SpeedChanged",
    "SettingsChanged",
]

# Every catalog class, paired with sample kwargs to construct an instance.
CATALOG = {
    events.PlaybackStarted: {},
    events.AvChanged: {},
    events.PlaybackStopped: {},
    events.PlaybackEnded: {},
    events.Paused: {},
    events.Resumed: {},
    events.SeekOccurred: {"time_ms": 1000, "offset_ms": -50},
    events.SeekChapter: {"chapter": 3},
    events.SpeedChanged: {"speed": 2},
    events.SettingsChanged: {},
    events.ProbeStream: {"session_id": 1, "attempt": 0},
    events.VerifyStream: {"session_id": 1, "seq": 7},
    events.StreamStabilized: {"session_id": 1},
    events.ProfileChanged: {"session_id": 1},
    events.OffsetApplied: {"session_id": 1, "profile": object(),
                           "ms": 75, "provisional": True,
                           "user_initiated": False},
    events.UserOffsetSaved: {"session_id": 1, "profile": object(), "ms": -25},
    events.ExecuteSeek: {"session_id": 1, "reason": "resume", "requested_at": 0.0},
    events.WatchTick: {"session_id": 1},
}


@pytest.mark.parametrize("cls", list(CATALOG), ids=lambda c: c.__name__)
def test_every_catalog_class_is_a_frozen_dataclass(cls):
    assert is_dataclass(cls)
    assert cls.__dataclass_params__.frozen is True


@pytest.mark.parametrize("cls, kwargs", list(CATALOG.items()),
                         ids=lambda v: getattr(v, "__name__", None))
def test_instances_reject_attribute_assignment(cls, kwargs):
    event = cls(**kwargs)
    with pytest.raises(FrozenInstanceError):
        event.injected = 1


@pytest.mark.parametrize("cls, kwargs", list(CATALOG.items()),
                         ids=lambda v: getattr(v, "__name__", None))
def test_payload_equality_by_value(cls, kwargs):
    # Same type + same field values compare equal (dataclass value semantics).
    assert cls(**kwargs) == cls(**kwargs)


def test_payload_inequality_when_a_field_differs():
    assert events.SeekOccurred(1000, -50) != events.SeekOccurred(1000, -51)
    assert events.SeekChapter(3) != events.SeekChapter(4)
    assert events.WatchTick(1) != events.WatchTick(2)


def test_distinct_types_are_not_equal():
    assert events.PlaybackStarted() != events.PlaybackEnded()
    assert events.Paused() != events.Resumed()


@pytest.mark.parametrize("name", PHASE2_GROUP)
def test_phase2_player_monitor_group_exists(name):
    cls = getattr(events, name, None)
    assert cls is not None, "missing Phase 2 event: {}".format(name)
    assert is_dataclass(cls) and cls.__dataclass_params__.frozen is True
