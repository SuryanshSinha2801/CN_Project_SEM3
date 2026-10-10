from pathlib import Path

from blackout.config import load_scenario
from blackout.events import EventType
from blackout.models import MessageState
from blackout.simulation import build_simulation

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_presentation_scenario_routes_around_failed_link() -> None:
    simulation = build_simulation(
        load_scenario(PROJECT_ROOT / "configs" / "presentation.yaml")
    )

    simulation.run()
    message = simulation.messages[("demo", "original")]
    failed_links = [
        event
        for event in simulation.engine.event_log
        if event.event_type is EventType.TRANSFER_FAILED
    ]

    assert message.state is MessageState.DELIVERED
    assert [(hop.from_node, hop.to_node) for hop in message.hop_history] == [
        ("A", "B"),
        ("B", "E"),
        ("E", "F"),
        ("F", "D"),
    ]
    assert message.delivery_time == 11
    assert any(
        event.payload["from_node"] == "B" and event.payload["to_node"] == "C"
        for event in failed_links
    )

