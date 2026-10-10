import pytest

from blackout.config import AdaptiveWeights
from blackout.models import Message, Node, NodeState, Position
from blackout.routing import AdaptiveRouter, ForwardAction


def make_router(**weight_overrides: float) -> AdaptiveRouter:
    weights = AdaptiveWeights.model_validate(weight_overrides)
    return AdaptiveRouter(weights, area_width=100, area_height=100)


def make_message() -> Message:
    message = Message("m1", "A", "D", 0, 1, 100)
    message.mark_buffered("A", 0)
    return message


def test_adaptive_score_uses_all_four_normalized_factors() -> None:
    router = make_router()
    candidate = Node(
        "B", Position(50, 0), 100, 100, state=NodeState.DEGRADED
    )
    destination = Node("D", Position(100, 0), 100, 100)
    candidate.start_contact("D", 10)
    candidate.end_contact("D", 11)
    candidate.start_contact("D", 20)
    candidate.end_contact("D", 21)
    candidate.start_contact("A", 22)

    score = router.score_node(candidate, destination, node_count=3, at_time=25)

    expected_connectivity = 0.7 * (2 / 3) + 0.3 * (1 / 2)
    expected_proximity = 1 - 50 / (100**2 + 100**2) ** 0.5
    expected_total = (
        0.35 * expected_connectivity
        + 0.35 * expected_proximity
        + 0.20 * 1.0
        + 0.10 * 0.5
    )
    assert score.connectivity == pytest.approx(expected_connectivity)
    assert score.proximity == pytest.approx(expected_proximity)
    assert score.buffer_availability == 1
    assert score.node_state == 0.5
    assert score.total == pytest.approx(expected_total)


def test_hysteresis_holds_when_candidate_improvement_is_too_small() -> None:
    holder = Node("A", Position(0, 0), 100, 100)
    candidate = Node("B", Position(0, 0), 100, 100)
    destination = Node("D", Position(100, 0), 100, 100)
    holder.start_contact("B", 0)
    candidate.start_contact("A", 0)
    message = make_message()
    holder.buffer.put(message, 0)

    decision = make_router().decide(
        holder,
        message,
        {"A": holder, "B": candidate, "D": destination},
        0,
    )

    assert decision.action is ForwardAction.HOLD
    assert decision.to_node == "B"
    assert "requires at least" in decision.reason
    assert decision.score_components["candidate_total"] < (
        decision.score_components["holder_total"]
        + decision.score_components["minimum_improvement"]
    )


def test_destination_bypasses_adaptive_threshold() -> None:
    holder = Node("A", Position(0, 0), 100, 100)
    destination = Node("D", Position(90, 0), 100, 100)
    holder.start_contact("D", 0)
    message = make_message()
    holder.buffer.put(message, 0)

    decision = make_router().decide(
        holder, message, {"A": holder, "D": destination}, 0
    )

    assert decision.action is ForwardAction.FORWARD
    assert decision.to_node == "D"
    assert "bypassed" in decision.reason


def test_equal_candidate_scores_use_lexicographic_node_id() -> None:
    holder = Node("A", Position(0, 0), 100, 100)
    candidate_b = Node("B", Position(60, 0), 100, 100)
    candidate_c = Node("C", Position(60, 0), 100, 100)
    destination = Node("D", Position(100, 0), 100, 100)
    holder.start_contact("C", 0)
    holder.start_contact("B", 0)
    message = make_message()
    holder.buffer.put(message, 0)
    router = make_router(minimum_improvement=0)

    decision = router.decide(
        holder,
        message,
        {"A": holder, "B": candidate_b, "C": candidate_c, "D": destination},
        0,
    )

    assert decision.action is ForwardAction.FORWARD
    assert decision.to_node == "B"

