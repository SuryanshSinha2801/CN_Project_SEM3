from pathlib import Path

import pytest
from pydantic import ValidationError

from blackout.config import ScenarioConfig, load_scenario
from blackout.events import EventType
from blackout.models import MessageState
from blackout.simulation import build_simulation

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_runtime_builds_nodes_before_events_run() -> None:
    scenario = load_scenario(PROJECT_ROOT / "configs" / "broken_route.yaml")
    simulation = build_simulation(scenario)

    assert tuple(simulation.nodes) == ("A", "B", "C", "D", "E", "F")
    assert simulation.messages == {}
    assert simulation.nodes["A"].buffer.capacity_bytes == 8192


def test_message_created_is_buffered_at_source_and_emits_event() -> None:
    scenario = load_scenario(PROJECT_ROOT / "configs" / "broken_route.yaml")
    simulation = build_simulation(scenario)

    processed = simulation.run(until=0)
    message = simulation.messages[("demo", "original")]

    event_types = [event.event_type for event in processed]
    assert event_types[:2] == [EventType.SIMULATION_STARTED, EventType.MESSAGE_CREATED]
    assert event_types.count(EventType.CONTACT_STARTED) == 3
    assert EventType.MESSAGE_BUFFERED in event_types
    assert event_types[-1] is EventType.FORWARD_DECISION
    assert message.state is MessageState.BUFFERED
    assert message.last_custody_holder == "A"
    assert simulation.nodes["A"].buffer.get("demo") is message
    assert simulation.nodes["A"].buffer.used_bytes == 1024
    buffered = next(
        event for event in processed if event.event_type is EventType.MESSAGE_BUFFERED
    )
    assert buffered.payload["free_bytes"] == 7168


def test_random_active_link_failure_is_seeded_and_restored() -> None:
    scenario = load_scenario(PROJECT_ROOT / "configs" / "presentation.yaml")
    simulation = build_simulation(
        scenario.model_copy(update={"forced_link_failures": ()})
    )
    simulation.run(until=0)

    active_before = simulation.topology.active_contacts
    failed_link = simulation.break_random_active_link(duration_seconds=2)

    assert failed_link in active_before
    simulation.run(until=0)
    assert failed_link in simulation.topology.blocked_links
    simulation.run(until=2)
    assert failed_link not in simulation.topology.blocked_links
    failures = [
        event
        for event in simulation.engine.event_log
        if event.event_type is EventType.LINK_FAILED
        and event.payload.get("random_failure")
    ]
    assert len(failures) == 1


def test_ttl_event_expires_message_and_reclaims_source_buffer() -> None:
    scenario = load_scenario(PROJECT_ROOT / "configs" / "broken_route.yaml")
    simulation = build_simulation(scenario)

    simulation.run()
    message = simulation.messages[("demo", "original")]

    assert message.state is MessageState.EXPIRED
    assert not simulation.nodes["A"].buffer.contains("demo")
    assert simulation.nodes["A"].buffer.used_bytes == 0
    assert EventType.MESSAGE_EXPIRED in [event.event_type for event in simulation.engine.event_log]


def test_broken_route_failure_ends_the_b_c_contact() -> None:
    scenario = load_scenario(PROJECT_ROOT / "configs" / "broken_route.yaml")
    simulation = build_simulation(scenario)

    simulation.run()
    b_c_events = [
        event
        for event in simulation.engine.event_log
        if event.event_type in {EventType.CONTACT_STARTED, EventType.CONTACT_ENDED}
        and (event.payload["node_a"], event.payload["node_b"]) == ("B", "C")
    ]

    assert [(event.event_time, event.event_type) for event in b_c_events] == [
        (0, EventType.CONTACT_STARTED),
        (2, EventType.CONTACT_ENDED),
    ]
    assert b_c_events[-1].payload["reason"] == "forced_failure"
    assert "C" not in simulation.nodes["B"].current_neighbors


def test_snapshot_reflects_state_after_each_step() -> None:
    scenario = load_scenario(PROJECT_ROOT / "configs" / "broken_route.yaml")
    simulation = build_simulation(scenario)
    simulation.step()
    simulation.step()

    snapshot = simulation.snapshot()
    source = next(node for node in snapshot.nodes if node.node_id == "A")

    assert snapshot.simulated_time == 0
    assert snapshot.messages[0].state is MessageState.BUFFERED
    assert snapshot.messages[0].remaining_ttl == 15
    assert source.buffered_message_copies == (("demo", "original"),)
    assert snapshot.active_contacts == (("A", "B"), ("B", "C"), ("C", "E"))


def test_reset_restores_pristine_deterministic_state() -> None:
    scenario = load_scenario(PROJECT_ROOT / "configs" / "broken_route.yaml")
    simulation = build_simulation(scenario)
    first_trace = [(event.event_time, event.event_type) for event in simulation.run()]

    simulation.reset()
    second_trace = [(event.event_time, event.event_type) for event in simulation.run()]

    assert second_trace == first_trace
    assert simulation.messages[("demo", "original")].state is MessageState.EXPIRED


def test_config_rejects_message_larger_than_its_source_buffer() -> None:
    raw = {
        "name": "oversized-message",
        "seed": 1,
        "duration_seconds": 10,
        "nodes": [
            {
                "node_id": "A",
                "position": {"x": 0, "y": 0},
                "buffer_capacity_bytes": 10,
            },
            {"node_id": "B", "position": {"x": 10, "y": 10}},
        ],
        "messages": [
            {
                "message_id": "large",
                "source": "A",
                "destination": "B",
                "size_bytes": 11,
            }
        ],
    }

    with pytest.raises(ValidationError, match="exceeds source buffer"):
        ScenarioConfig.model_validate(raw)
