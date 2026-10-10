import pytest

from blackout.cli import build_parser
from blackout.config import load_scenario
from blackout.events import EventType, SimulationEvent
from blackout.gui import build_interactive_scenario, event_summary
from blackout.models import MessageState
from blackout.simulation import build_simulation


def test_gui_command_defaults_to_presentation_scenario() -> None:
    args = build_parser().parse_args(["gui"])

    assert args.command == "gui"
    assert args.scenario.as_posix() == "configs/presentation.yaml"


def test_forward_decision_summary_is_explainable() -> None:
    event = SimulationEvent(
        event_time=1,
        sequence_number=1,
        event_type=EventType.FORWARD_DECISION,
        payload={
            "action": "forward",
            "from_node": "A",
            "to_node": "B",
            "reason": "candidate meets hysteresis",
        },
    )

    assert event_summary(event) == "forward: A → B — candidate meets hysteresis"


def test_copy_event_summary_identifies_the_replica_route() -> None:
    event = SimulationEvent(
        event_time=2,
        sequence_number=2,
        event_type=EventType.ROUTING_COPY_CREATED,
        payload={
            "message_id": "m1",
            "copy_id": "m1-copy-0001",
            "from_node": "A",
            "to_node": "B",
        },
    )

    assert event_summary(event) == "copy m1-copy-0001: A → B"


def test_interactive_scenario_uses_message_text_and_selected_endpoints() -> None:
    base = load_scenario("configs/presentation.yaml")

    scenario = build_interactive_scenario(base, "  Help is required  ", "B", "F")

    message = scenario.messages[0]
    assert message.source == "B"
    assert message.destination == "F"
    assert message.content == "Help is required"
    assert message.size_bytes == 1024
    assert len(scenario.forced_link_failures) == 1
    background_failure = scenario.forced_link_failures[0]
    assert {background_failure.node_a, background_failure.node_b} == {"C", "E"}


def test_interactive_scenario_rejects_same_endpoint() -> None:
    base = load_scenario("configs/presentation.yaml")

    with pytest.raises(ValueError, match="different"):
        build_interactive_scenario(base, "hello", "A", "A")


def test_interactive_message_reroutes_after_seeded_random_failure() -> None:
    scenario = build_interactive_scenario(
        load_scenario("configs/presentation.yaml"),
        "Professor demonstration message",
        "A",
        "D",
    )
    simulation = build_simulation(scenario)
    simulation.run(until=0)

    failed_link = simulation.break_random_active_link(duration_seconds=8)
    simulation.run()

    message = simulation.messages[("interactive-message", "original")]
    assert failed_link == ("B", "C")
    assert message.state is MessageState.DELIVERED
    assert [hop.to_node for hop in message.hop_history] == ["B", "E", "F", "D"]
