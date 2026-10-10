from blackout.config import RoutingPolicy, ScenarioConfig, load_scenario
from blackout.events import EventType
from blackout.simulation import build_simulation


def direct_scenario(**updates: object) -> ScenarioConfig:
    raw: dict[str, object] = {
        "name": "direct-reliability",
        "seed": 3,
        "duration_seconds": 10,
        "routing_policy": "adaptive",
        "packet_loss_probability": 0,
        "ack_loss_probability": 0,
        "max_link_retries": 2,
        "ack_timeout_seconds": 1,
        "transfer_delay_seconds": 1,
        "nodes": [
            {
                "node_id": "A",
                "position": {"x": 0, "y": 0},
                "communication_range": 20,
                "buffer_capacity_bytes": 100,
            },
            {
                "node_id": "D",
                "position": {"x": 10, "y": 0},
                "communication_range": 20,
                "buffer_capacity_bytes": 100,
            },
        ],
        "messages": [
            {
                "message_id": "m1",
                "source": "A",
                "destination": "D",
                "size_bytes": 10,
                "ttl_seconds": 10,
            }
        ],
    }
    raw.update(updates)
    return ScenarioConfig.model_validate(raw)


def test_epidemic_creates_replicas_and_delivers() -> None:
    base = load_scenario("configs/presentation.yaml")
    scenario = base.model_copy(update={"routing_policy": RoutingPolicy.EPIDEMIC})
    simulation = build_simulation(scenario)

    simulation.run()
    events = simulation.engine.event_log

    assert any(event.event_type is EventType.MESSAGE_DELIVERED for event in events)
    assert sum(event.event_type is EventType.ROUTING_COPY_CREATED for event in events) >= 1
    assert len(simulation.messages) > 1


def test_binary_spray_splits_copy_budget_and_enters_wait_phase() -> None:
    base = load_scenario("configs/presentation.yaml")
    scenario = base.model_copy(update={"routing_policy": RoutingPolicy.SPRAY_AND_WAIT})
    simulation = build_simulation(scenario)

    simulation.run(until=7)
    decisions = [
        event
        for event in simulation.engine.event_log
        if event.event_type is EventType.FORWARD_DECISION
    ]

    assert any("binary spray 2 of 4" in str(event.payload["reason"]) for event in decisions)
    assert any("wait phase" in str(event.payload["reason"]) for event in decisions)
    copies = sum(
        event.event_type is EventType.ROUTING_COPY_CREATED
        for event in simulation.engine.event_log
    )
    assert copies == 2


def test_packet_loss_retries_then_retains_sender_copy() -> None:
    simulation = build_simulation(direct_scenario(packet_loss_probability=1))

    simulation.run()
    events = simulation.engine.event_log

    assert sum(event.event_type is EventType.PACKET_LOST for event in events) == 3
    assert sum(event.event_type is EventType.RETRANSMISSION for event in events) == 2
    assert sum(event.event_type is EventType.TRANSFER_FAILED for event in events) == 1
    assert not any(event.event_type is EventType.MESSAGE_DELIVERED for event in events)
    assert simulation.messages[("m1", "original")].last_custody_holder == "A"


def test_ack_loss_retries_without_duplicate_delivery() -> None:
    simulation = build_simulation(direct_scenario(ack_loss_probability=1))

    simulation.run()
    events = simulation.engine.event_log

    assert sum(event.event_type is EventType.PACKET_RECEIVED for event in events) == 3
    assert sum(event.event_type is EventType.ACK_LOST for event in events) == 3
    assert not any(event.event_type is EventType.MESSAGE_DELIVERED for event in events)


def test_zero_loss_stop_and_wait_delivers_once() -> None:
    simulation = build_simulation(direct_scenario())

    simulation.run()
    events = simulation.engine.event_log

    assert sum(event.event_type is EventType.PACKET_SENT for event in events) == 1
    assert sum(event.event_type is EventType.ACK_RECEIVED for event in events) == 1
    assert sum(event.event_type is EventType.MESSAGE_DELIVERED for event in events) == 1
