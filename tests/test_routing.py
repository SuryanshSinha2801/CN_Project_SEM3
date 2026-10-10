from blackout.config import ScenarioConfig
from blackout.events import EventType
from blackout.models import Message, MessageState, Node, Position
from blackout.routing import ForwardAction, GreedySingleCopyRouter
from blackout.simulation import build_simulation


def scenario_with_line_nodes(*, failure: bool = False) -> ScenarioConfig:
    raw: dict[str, object] = {
        "name": "single-copy-line",
        "seed": 7,
        "duration_seconds": 5,
        "area": {"width": 100, "height": 100},
        "transfer_delay_seconds": 1,
        "nodes": [
            {
                "node_id": "A",
                "position": {"x": 0, "y": 0},
                "communication_range": 6,
                "buffer_capacity_bytes": 100,
            },
            {
                "node_id": "B",
                "position": {"x": 5, "y": 0},
                "communication_range": 6,
                "buffer_capacity_bytes": 100,
            },
            {
                "node_id": "D",
                "position": {"x": 10, "y": 0},
                "communication_range": 6,
                "buffer_capacity_bytes": 100,
            },
        ],
        "messages": [
            {
                "message_id": "m1",
                "source": "A",
                "destination": "D",
                "size_bytes": 10,
                "ttl_seconds": 5,
            }
        ],
    }
    if failure:
        raw["forced_link_failures"] = [
            {"node_a": "B", "node_b": "D", "start_time": 1.5, "end_time": 5}
        ]
    return ScenarioConfig.model_validate(raw)


def test_single_copy_is_delivered_over_two_contacts() -> None:
    simulation = build_simulation(scenario_with_line_nodes())

    simulation.run()
    message = simulation.messages[("m1", "original")]
    event_types = [event.event_type for event in simulation.engine.event_log]

    assert message.state is MessageState.DELIVERED
    assert message.hop_count == 2
    assert [(hop.from_node, hop.to_node) for hop in message.hop_history] == [
        ("A", "B"),
        ("B", "D"),
    ]
    assert message.delivery_time == 2
    assert EventType.TRANSFER_COMPLETED in event_types
    assert EventType.MESSAGE_DELIVERED in event_types
    assert all(len(node.buffer) == 0 for node in simulation.nodes.values())


def test_failed_transfer_retains_custody_during_partition() -> None:
    simulation = build_simulation(scenario_with_line_nodes(failure=True))

    simulation.run()
    message = simulation.messages[("m1", "original")]
    failures = [
        event
        for event in simulation.engine.event_log
        if event.event_type is EventType.TRANSFER_FAILED
    ]

    assert message.state is MessageState.EXPIRED
    assert message.hop_count == 1
    assert message.last_custody_holder == "B"
    assert len(failures) == 1
    assert failures[0].event_time == 2
    assert failures[0].payload["reason"] == "contact ended before transfer completion"
    assert simulation.nodes["A"].counters.messages_forwarded == 1
    assert simulation.nodes["B"].counters.messages_forwarded == 0


def test_router_holds_when_no_neighbor_makes_progress() -> None:
    holder = Node("B", Position(5, 0), 10, 100)
    behind = Node("A", Position(0, 0), 10, 100)
    destination = Node("D", Position(10, 0), 10, 100)
    holder.start_contact("A", 0)
    message = Message("m1", "A", "D", 0, 10, 10)
    message.mark_buffered("B", 0)
    router = GreedySingleCopyRouter()

    decision = router.decide(
        holder,
        message,
        {"A": behind, "B": holder, "D": destination},
        0,
    )

    assert decision.action is ForwardAction.HOLD
    assert decision.to_node is None


def test_router_prioritizes_destination_over_other_relays() -> None:
    holder = Node("A", Position(0, 0), 20, 100)
    relay = Node("B", Position(8, 0), 20, 100)
    destination = Node("D", Position(10, 0), 20, 100)
    holder.start_contact("B", 0)
    holder.start_contact("D", 0)
    message = Message("m1", "A", "D", 0, 10, 10)
    message.mark_buffered("A", 0)

    decision = GreedySingleCopyRouter().decide(
        holder,
        message,
        {"A": holder, "B": relay, "D": destination},
        0,
    )

    assert decision.action is ForwardAction.FORWARD
    assert decision.to_node == "D"
    assert decision.reason == "destination is in direct contact"


def test_runtime_does_not_complete_transfer_after_simulation_end() -> None:
    scenario = ScenarioConfig.model_validate(
        {
            "name": "late-message",
            "seed": 1,
            "duration_seconds": 5,
            "transfer_delay_seconds": 1,
            "nodes": [
                {
                    "node_id": "A",
                    "position": {"x": 0, "y": 0},
                    "communication_range": 10,
                },
                {
                    "node_id": "D",
                    "position": {"x": 5, "y": 0},
                    "communication_range": 10,
                },
            ],
            "messages": [
                {
                    "message_id": "late",
                    "source": "A",
                    "destination": "D",
                    "size_bytes": 10,
                    "creation_time": 4.5,
                    "ttl_seconds": 10,
                }
            ],
        }
    )
    simulation = build_simulation(scenario)

    simulation.run()
    message = simulation.messages[("late", "original")]
    attempts = [
        event
        for event in simulation.engine.event_log
        if event.event_type is EventType.TRANSFER_ATTEMPT
    ]

    assert message.state is MessageState.BUFFERED
    assert message.last_custody_holder == "A"
    assert attempts == []
    assert simulation.engine.current_time == 5
