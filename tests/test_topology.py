from blackout.config import ScenarioConfig
from blackout.events import EventType
from blackout.models import Node, NodeState, Position
from blackout.simulation import SimulationEngine, TopologyManager, build_simulation


def make_node(
    node_id: str,
    x: float,
    *,
    communication_range: float = 10,
    state: NodeState = NodeState.HEALTHY,
) -> Node:
    return Node(
        node_id,
        Position(x, 0),
        communication_range=communication_range,
        buffer_capacity_bytes=100,
        state=state,
    )


def test_reconcile_starts_only_mutual_range_contacts_deterministically() -> None:
    nodes = {
        "C": make_node("C", 25),
        "A": make_node("A", 0),
        "B": make_node("B", 10),
    }
    engine = SimulationEngine(seed=1)
    topology = TopologyManager(nodes)

    topology.reconcile(0, engine)
    events = engine.run()

    assert topology.active_contacts == frozenset({("A", "B")})
    assert nodes["A"].current_neighbors == frozenset({"B"})
    assert nodes["B"].current_neighbors == frozenset({"A"})
    assert events[0].event_type is EventType.CONTACT_STARTED
    assert events[0].payload["node_a"] == "A"
    assert events[0].payload["node_b"] == "B"


def test_smaller_radio_range_limits_bidirectional_contact() -> None:
    nodes = {
        "A": make_node("A", 0, communication_range=10),
        "B": make_node("B", 15, communication_range=20),
    }
    engine = SimulationEngine(seed=1)
    topology = TopologyManager(nodes)

    topology.reconcile(0, engine)

    assert topology.active_contacts == frozenset()
    assert engine.pending_event_count == 0


def test_unavailable_node_is_excluded_from_contacts() -> None:
    nodes = {
        "A": make_node("A", 0),
        "B": make_node("B", 5, state=NodeState.UNAVAILABLE),
    }
    engine = SimulationEngine(seed=1)
    topology = TopologyManager(nodes)

    topology.reconcile(0, engine)

    assert topology.active_contacts == frozenset()


def test_forced_failure_ends_and_restoration_restarts_contact() -> None:
    nodes = {"A": make_node("A", 0), "B": make_node("B", 5)}
    engine = SimulationEngine(seed=1)
    topology = TopologyManager(nodes)
    topology.reconcile(0, engine)
    engine.run()

    topology.fail_link("B", "A", 2, engine)
    failed = engine.run()
    topology.restore_link("A", "B", 4, engine)
    restored = engine.run()

    assert failed[0].event_type is EventType.CONTACT_ENDED
    assert failed[0].payload["reason"] == "forced_failure"
    assert failed[0].payload["duration_seconds"] == 2
    assert restored[0].event_type is EventType.CONTACT_STARTED
    assert topology.active_contacts == frozenset({("A", "B")})
    assert nodes["A"].contact_history[0].started_at == 0
    assert nodes["A"].contact_history[0].ended_at == 2


def test_node_movement_event_reconciles_runtime_contacts() -> None:
    scenario = ScenarioConfig.model_validate(
        {
            "name": "movement-contact",
            "seed": 1,
            "duration_seconds": 5,
            "area": {"width": 100, "height": 100},
            "nodes": [
                {
                    "node_id": "A",
                    "position": {"x": 0, "y": 0},
                    "communication_range": 10,
                },
                {
                    "node_id": "B",
                    "position": {"x": 5, "y": 0},
                    "communication_range": 10,
                },
            ],
            "messages": [
                {
                    "message_id": "m1",
                    "source": "A",
                    "destination": "B",
                    "size_bytes": 10,
                    "ttl_seconds": 10,
                }
            ],
        }
    )
    simulation = build_simulation(scenario)
    simulation.engine.schedule_at(
        1,
        EventType.NODE_MOVED,
        {"node_id": "B", "x": 20, "y": 0},
    )

    simulation.run()
    contact_events = [
        event
        for event in simulation.engine.event_log
        if event.event_type in {EventType.CONTACT_STARTED, EventType.CONTACT_ENDED}
    ]

    assert [event.event_type for event in contact_events] == [
        EventType.CONTACT_STARTED,
        EventType.CONTACT_ENDED,
    ]
    assert contact_events[-1].event_time == 1
    assert simulation.topology.active_contacts == frozenset()
    assert simulation.nodes["B"].position == Position(20, 0)

