from blackout.cli import build_parser
from blackout.events import EventType, SimulationEvent
from blackout.gui import event_summary


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
