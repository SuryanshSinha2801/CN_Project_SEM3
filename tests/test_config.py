import math
from itertools import pairwise
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


def test_presentation_scenario_has_scripted_alternate_route() -> None:
    scenario = load_scenario(PROJECT_ROOT / "configs" / "presentation.yaml")

    assert len(scenario.nodes) == 12
    assert scenario.movements == ()
    failure = scenario.forced_link_failures[0]
    assert (failure.node_a, failure.node_b) == ("B", "F")
    assert (failure.start_time, failure.end_time) == (1.5, 12)


def test_presentation_mesh_has_independent_upper_and_lower_paths() -> None:
    scenario = load_scenario(PROJECT_ROOT / "configs" / "presentation.yaml")
    nodes = {node.node_id: node for node in scenario.nodes}
    paths = (
        ("A", "B", "E", "H", "K", "D"),
        ("A", "C", "G", "I", "L", "D"),
    )

    for path in paths:
        for node_a_id, node_b_id in pairwise(path):
            node_a = nodes[node_a_id]
            node_b = nodes[node_b_id]
            distance = math.hypot(
                node_a.position.x - node_b.position.x,
                node_a.position.y - node_b.position.y,
            )
            assert distance <= min(
                node_a.communication_range, node_b.communication_range
            )


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

    with pytest.raises(ValidationError, match=r"must sum to 1\.0"):
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
