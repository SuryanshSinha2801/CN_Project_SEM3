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
