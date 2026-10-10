from pathlib import Path

import pytest
from pydantic import ValidationError

from blackout.config import ScenarioConfig, load_scenario

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_default_scenario_loads() -> None:
    scenario = load_scenario(PROJECT_ROOT / "configs" / "default.yaml")

    assert scenario.seed == 2801
    assert len(scenario.nodes) == 6
    assert scenario.messages[0].source == "A"
    assert scenario.messages[0].destination == "D"


def test_broken_route_scenario_is_deterministic() -> None:
    first = load_scenario(PROJECT_ROOT / "configs" / "broken_route.yaml")
    second = load_scenario(PROJECT_ROOT / "configs" / "broken_route.yaml")

    assert first == second
    assert first.forced_link_failures[0].node_a == "B"
    assert first.forced_link_failures[0].node_b == "C"


def test_duplicate_node_ids_are_rejected() -> None:
    raw = {
        "name": "invalid-duplicate-nodes",
        "seed": 1,
        "duration_seconds": 10,
        "nodes": [
            {"node_id": "A", "position": {"x": 0, "y": 0}},
            {"node_id": "A", "position": {"x": 10, "y": 10}},
        ],
        "messages": [
            {
                "message_id": "m1",
                "source": "A",
                "destination": "B",
                "size_bytes": 10,
            }
        ],
    }

    with pytest.raises(ValidationError, match="node IDs must be unique"):
        ScenarioConfig.model_validate(raw)


def test_adaptive_weights_must_sum_to_one() -> None:
    raw = {
        "name": "invalid-weights",
        "seed": 1,
        "duration_seconds": 10,
        "adaptive_weights": {
            "connectivity": 0.5,
            "proximity": 0.5,
            "buffer_availability": 0.5,
            "node_state": 0.5,
        },
        "nodes": [
            {"node_id": "A", "position": {"x": 0, "y": 0}},
            {"node_id": "B", "position": {"x": 10, "y": 10}},
        ],
        "messages": [
            {
                "message_id": "m1",
                "source": "A",
                "destination": "B",
                "size_bytes": 10,
            }
        ],
    }

    with pytest.raises(ValidationError, match="must sum to 1.0"):
        ScenarioConfig.model_validate(raw)


def test_link_failure_cannot_outlive_simulation() -> None:
    raw = {
        "name": "invalid-failure-end",
        "seed": 1,
        "duration_seconds": 10,
        "nodes": [
            {"node_id": "A", "position": {"x": 0, "y": 0}},
            {"node_id": "B", "position": {"x": 10, "y": 10}},
        ],
        "messages": [
            {
                "message_id": "m1",
                "source": "A",
                "destination": "B",
                "size_bytes": 10,
            }
        ],
        "forced_link_failures": [
            {"node_a": "A", "node_b": "B", "start_time": 2, "end_time": 11}
        ],
    }

    with pytest.raises(ValidationError, match="ends after the simulation"):
        ScenarioConfig.model_validate(raw)
