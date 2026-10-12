import pytest

from blackout.cli import build_parser
from blackout.config import load_scenario
from blackout.events import EventType, SimulationEvent
from blackout.gui import build_interactive_scenario, event_summary, format_link, parse_link
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


def test_contact_summary_calls_out_physical_contact() -> None:
    event = SimulationEvent(
        event_time=8,
        sequence_number=3,
        event_type=EventType.CONTACT_STARTED,
        payload={"node_a": "E", "node_b": "F"},
    )

    assert event_summary(event) == "topology only: E ↔ F (no message sent)"


def test_link_selector_round_trips_node_ids() -> None:
    assert format_link(("F", "H")) == "F — H"
    assert parse_link("F — H") == ("F", "H")


def test_selected_failure_is_identified_in_event_trace() -> None:
    event = SimulationEvent(
        event_time=2,
        sequence_number=4,
        event_type=EventType.LINK_FAILED,
        payload={"node_a": "F", "node_b": "H", "manual_failure": True},
    )

    assert event_summary(event) == "F-H (selected)"


def test_interactive_scenario_uses_message_text_and_selected_endpoints() -> None:
    base = load_scenario("configs/presentation.yaml")

    scenario = build_interactive_scenario(base, "  Help is required  ", "B", "F")

    message = scenario.messages[0]
    assert message.source == "B"
    assert message.destination == "F"
    assert message.content == "Help is required"
    assert message.size_bytes == 1024
    assert scenario.forced_link_failures == ()


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
    assert failed_link == ("G", "I")
    assert message.state is MessageState.DELIVERED
    assert [hop.to_node for hop in message.hop_history] == ["B", "F", "H", "J", "D"]


def test_destination_delivery_cancels_expiry_and_prevents_further_forwarding() -> None:
    scenario = build_interactive_scenario(
        load_scenario("configs/presentation.yaml"),
        "Deliver only to E",
        "A",
        "E",
    )
    simulation = build_simulation(scenario)
    simulation.run(until=0)
    simulation.break_random_active_link(duration_seconds=8)
    simulation.run()

    message = simulation.messages[("interactive-message", "original")]
    message_events = [
        event
        for event in simulation.engine.event_log
        if event.payload.get("message_id") == "interactive-message"
    ]
    assert message.state is MessageState.DELIVERED
    assert message.last_custody_holder == "E"
    assert [hop.to_node for hop in message.hop_history] == ["B", "E"]
    assert EventType.MESSAGE_EXPIRED not in {
        event.event_type for event in message_events
    }
    delivery_index = next(
        index
        for index, event in enumerate(message_events)
        if event.event_type is EventType.MESSAGE_DELIVERED
    )
    assert not any(
        event.event_type is EventType.TRANSFER_COMPLETED
        for event in message_events[delivery_index + 1 :]
    )


def test_low_score_detour_reaches_destination_after_direct_link_removal() -> None:
    scenario = build_interactive_scenario(
        load_scenario("configs/presentation.yaml"),
        "Route through a lower-scoring relay",
        "A",
        "L",
    )
    simulation = build_simulation(scenario)

    assert simulation.break_link("I", "L") == ("I", "L")
    simulation.run()

    message = simulation.messages[("interactive-message", "original")]
    assert message.state is MessageState.DELIVERED
    assert [hop.to_node for hop in message.hop_history] == ["C", "F", "I", "J", "L"]
    assert any(
        event.event_type is EventType.FORWARD_DECISION
        and event.payload.get("from_node") == "I"
        and event.payload.get("to_node") == "J"
        and "detour" in str(event.payload.get("reason"))
        for event in simulation.engine.event_log
    )
