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

    assert [event.event_type for event in processed] == [
        EventType.SIMULATION_STARTED,
        EventType.MESSAGE_CREATED,
        EventType.MESSAGE_BUFFERED,
    ]
    assert message.state is MessageState.BUFFERED
    assert message.last_custody_holder == "A"
    assert simulation.nodes["A"].buffer.get("demo") is message
    assert simulation.nodes["A"].buffer.used_bytes == 1024
    assert processed[-1].payload["free_bytes"] == 7168


def test_ttl_event_expires_message_and_reclaims_source_buffer() -> None:
    scenario = load_scenario(PROJECT_ROOT / "configs" / "broken_route.yaml")
    simulation = build_simulation(scenario)

    simulation.run()
    message = simulation.messages[("demo", "original")]

    assert message.state is MessageState.EXPIRED
    assert not simulation.nodes["A"].buffer.contains("demo")
    assert simulation.nodes["A"].buffer.used_bytes == 0
    assert EventType.MESSAGE_EXPIRED in [event.event_type for event in simulation.engine.event_log]


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

