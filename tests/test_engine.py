from pathlib import Path

import pytest

from blackout.config import load_scenario
from blackout.events import EventType
from blackout.simulation import SimulationEngine, schedule_scenario

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_events_run_in_chronological_order() -> None:
    engine = SimulationEngine(seed=1)
    engine.schedule_at(5, EventType.CONTACT_ENDED)
    engine.schedule_at(1, EventType.CONTACT_STARTED)
    engine.schedule_at(3, EventType.NODE_MOVED)

    processed = engine.run()

    assert [event.event_time for event in processed] == [1, 3, 5]
    assert engine.current_time == 5


def test_equal_time_events_preserve_insertion_order() -> None:
    engine = SimulationEngine(seed=1)
    engine.schedule_at(2, EventType.MESSAGE_CREATED, {"order": "first"})
    engine.schedule_at(2, EventType.MESSAGE_CREATED, {"order": "second"})

    processed = engine.run()

    assert [event.payload["order"] for event in processed] == ["first", "second"]


def test_step_processes_one_event() -> None:
    engine = SimulationEngine(seed=1)
    engine.schedule_at(1, EventType.NODE_MOVED)
    engine.schedule_at(2, EventType.NODE_MOVED)

    event = engine.step()

    assert event is not None
    assert event.event_time == 1
    assert engine.pending_event_count == 1


def test_schedule_uses_current_time() -> None:
    engine = SimulationEngine(seed=1)
    engine.run(until=3)

    event = engine.schedule(EventType.NODE_MOVED)

    assert event.event_time == 3


def test_run_until_is_inclusive_and_advances_clock() -> None:
    engine = SimulationEngine(seed=1)
    engine.schedule_at(2, EventType.NODE_MOVED)
    engine.schedule_at(4, EventType.NODE_MOVED)

    processed = engine.run(until=2)

    assert len(processed) == 1
    assert engine.current_time == 2
    assert engine.pending_event_count == 1


def test_past_events_are_rejected() -> None:
    engine = SimulationEngine(seed=1)
    engine.run(until=2)

    with pytest.raises(ValueError, match="simulated past"):
        engine.schedule_at(1, EventType.NODE_MOVED)


def test_handler_can_schedule_another_event() -> None:
    engine = SimulationEngine(seed=1)

    def follow_up(_event: object, active_engine: SimulationEngine) -> None:
        active_engine.schedule_after(1, EventType.TRANSFER_COMPLETED)

    engine.register_handler(EventType.FORWARD_DECISION, follow_up)
    engine.schedule_at(3, EventType.FORWARD_DECISION)

    processed = engine.run()

    assert [event.event_type for event in processed] == [
        EventType.FORWARD_DECISION,
        EventType.TRANSFER_COMPLETED,
    ]
    assert processed[-1].event_time == 4


def test_cancel_scheduled_removes_only_matching_future_events() -> None:
    engine = SimulationEngine(seed=1)
    engine.schedule_at(3, EventType.MESSAGE_EXPIRED, {"message_id": "keep"})
    engine.schedule_at(4, EventType.MESSAGE_EXPIRED, {"message_id": "cancel"})
    engine.schedule_at(5, EventType.SIMULATION_ENDED)

    removed = engine.cancel_scheduled(
        EventType.MESSAGE_EXPIRED,
        lambda event: event.payload["message_id"] == "cancel",
    )
    processed = engine.run()

    assert removed == 1
    assert [event.event_type for event in processed] == [
        EventType.MESSAGE_EXPIRED,
        EventType.SIMULATION_ENDED,
    ]


def test_reset_replays_seeded_randomness() -> None:
    engine = SimulationEngine(seed=42)
    first_sequence = [engine.random.random() for _ in range(3)]

    engine.reset()

    assert [engine.random.random() for _ in range(3)] == first_sequence
    assert engine.current_time == 0
    assert engine.event_log == ()


def test_seed_controls_random_sequence() -> None:
    first = SimulationEngine(seed=42)
    second = SimulationEngine(seed=42)
    different = SimulationEngine(seed=43)

    first_values = [first.random.random() for _ in range(3)]
    assert [second.random.random() for _ in range(3)] == first_values
    assert [different.random.random() for _ in range(3)] != first_values


def test_broken_route_scenario_builds_expected_timeline() -> None:
    scenario = load_scenario(PROJECT_ROOT / "configs" / "broken_route.yaml")
    engine = schedule_scenario(scenario)

    processed = engine.run()

    assert [
        (event.event_time, event.event_type)
        for event in processed
    ] == [
        (0, EventType.SIMULATION_STARTED),
        (0, EventType.MESSAGE_CREATED),
        (2, EventType.LINK_FAILED),
        (15, EventType.MESSAGE_EXPIRED),
        (15, EventType.LINK_RESTORED),
        (15, EventType.SIMULATION_ENDED),
    ]
    assert engine.current_time == scenario.duration_seconds
