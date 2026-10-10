"""Runnable scenario state assembled from configuration and event handlers."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from blackout.config import MessageConfig, ScenarioConfig
from blackout.events import EventType, SimulationEvent
from blackout.models import Message, MessageState, Node, NodeState, Position
from blackout.simulation.engine import SimulationEngine
from blackout.simulation.scenario import schedule_scenario
from blackout.simulation.topology import Link, TopologyManager


@dataclass(frozen=True, slots=True)
class NodeSnapshot:
    """Read-only node state suitable for metrics and visualization."""

    node_id: str
    position: Position
    state: NodeState
    buffer_used_bytes: int
    buffer_capacity_bytes: int
    buffered_message_copies: tuple[tuple[str, str], ...]
    current_neighbors: frozenset[str]


@dataclass(frozen=True, slots=True)
class MessageSnapshot:
    """Read-only routing-message state at one simulated time."""

    message_id: str
    copy_id: str
    state: MessageState
    custody_holder: str
    hop_count: int
    remaining_ttl: float


@dataclass(frozen=True, slots=True)
class SimulationSnapshot:
    """Immutable view of the full domain state after an event or run boundary."""

    simulated_time: float
    nodes: tuple[NodeSnapshot, ...]
    messages: tuple[MessageSnapshot, ...]
    active_contacts: tuple[Link, ...]


class ScenarioSimulation:
    """Bind a validated scenario, domain state, and deterministic event engine."""

    def __init__(self, scenario: ScenarioConfig) -> None:
        self._scenario = scenario
        self._message_configs = {message.message_id: message for message in scenario.messages}
        self._nodes: dict[str, Node] = {}
        self._messages: dict[tuple[str, str], Message] = {}
        self._topology: TopologyManager = TopologyManager({})
        self._engine = SimulationEngine(seed=scenario.seed)
        self.reset()

    @property
    def scenario(self) -> ScenarioConfig:
        return self._scenario

    @property
    def engine(self) -> SimulationEngine:
        return self._engine

    @property
    def nodes(self) -> Mapping[str, Node]:
        return MappingProxyType(self._nodes)

    @property
    def messages(self) -> Mapping[tuple[str, str], Message]:
        return MappingProxyType(self._messages)

    @property
    def topology(self) -> TopologyManager:
        return self._topology

    def step(self) -> SimulationEvent | None:
        return self._engine.step()

    def run(self, until: float | None = None) -> tuple[SimulationEvent, ...]:
        return self._engine.run(until)

    def reset(self) -> None:
        """Rebuild pristine domain state and schedule the original trace again."""

        self._nodes = {
            config.node_id: Node(
                node_id=config.node_id,
                position=Position(config.position.x, config.position.y),
                communication_range=config.communication_range,
                buffer_capacity_bytes=config.buffer_capacity_bytes,
                state=NodeState(config.state),
            )
            for config in self._scenario.nodes
        }
        self._messages = {}
        initially_blocked = (
            (failure.node_a, failure.node_b)
            for failure in self._scenario.forced_link_failures
            if failure.start_time == 0
        )
        self._topology = TopologyManager(self._nodes, initially_blocked)
        self._engine = schedule_scenario(self._scenario)
        self._engine.register_handler(EventType.SIMULATION_STARTED, self._on_simulation_started)
        self._engine.register_handler(EventType.MESSAGE_CREATED, self._on_message_created)
        self._engine.register_handler(EventType.MESSAGE_EXPIRED, self._on_message_expired)
        self._engine.register_handler(EventType.NODE_MOVED, self._on_node_moved)
        self._engine.register_handler(EventType.LINK_FAILED, self._on_link_failed)
        self._engine.register_handler(EventType.LINK_RESTORED, self._on_link_restored)

    def snapshot(self) -> SimulationSnapshot:
        """Capture state without exposing mutable node or message objects."""

        node_snapshots = tuple(
            NodeSnapshot(
                node_id=node.node_id,
                position=node.position,
                state=node.state,
                buffer_used_bytes=node.buffer.used_bytes,
                buffer_capacity_bytes=node.buffer.capacity_bytes,
                buffered_message_copies=tuple(message.identity for message in node.buffer),
                current_neighbors=node.current_neighbors,
            )
            for node in sorted(self._nodes.values(), key=lambda item: item.node_id)
        )
        message_snapshots = tuple(
            MessageSnapshot(
                message_id=message.message_id,
                copy_id=message.copy_id,
                state=message.state,
                custody_holder=message.last_custody_holder,
                hop_count=message.hop_count,
                remaining_ttl=message.remaining_ttl(self._engine.current_time),
            )
            for message in sorted(self._messages.values(), key=lambda item: item.identity)
        )
        return SimulationSnapshot(
            simulated_time=self._engine.current_time,
            nodes=node_snapshots,
            messages=message_snapshots,
            active_contacts=tuple(sorted(self._topology.active_contacts)),
        )

    def _on_simulation_started(
        self, event: SimulationEvent, engine: SimulationEngine
    ) -> None:
        self._topology.reconcile(event.event_time, engine, reason="initial_range")

    def _on_message_created(
        self, event: SimulationEvent, engine: SimulationEngine
    ) -> None:
        message_id = str(event.payload["message_id"])
        config = self._message_configs[message_id]
        message = self._make_message(config)
        source = self._nodes[message.source]
        source.buffer.put(message, event.event_time)
        source.counters.messages_generated += 1
        self._messages[message.identity] = message
        engine.schedule(
            EventType.MESSAGE_BUFFERED,
            {
                "message_id": message.message_id,
                "copy_id": message.copy_id,
                "node_id": source.node_id,
                "used_bytes": source.buffer.used_bytes,
                "free_bytes": source.buffer.free_bytes,
            },
        )

    def _on_message_expired(
        self, event: SimulationEvent, _engine: SimulationEngine
    ) -> None:
        identity = (str(event.payload["message_id"]), str(event.payload["copy_id"]))
        message = self._messages.get(identity)
        if message is None or message.is_terminal:
            return
        holder = self._nodes[message.last_custody_holder]
        holder.buffer.expire(event.event_time)

    def _on_node_moved(self, event: SimulationEvent, engine: SimulationEngine) -> None:
        node_id = str(event.payload["node_id"])
        position = Position(float(event.payload["x"]), float(event.payload["y"]))
        if position.x > self._scenario.area.width or position.y > self._scenario.area.height:
            raise ValueError(f"node {node_id!r} moved outside the simulation area")
        self._nodes[node_id].set_position(position)
        self._topology.reconcile(event.event_time, engine, reason="node_moved")

    def _on_link_failed(self, event: SimulationEvent, engine: SimulationEngine) -> None:
        self._topology.fail_link(
            str(event.payload["node_a"]),
            str(event.payload["node_b"]),
            event.event_time,
            engine,
        )

    def _on_link_restored(self, event: SimulationEvent, engine: SimulationEngine) -> None:
        node_a = str(event.payload["node_a"])
        node_b = str(event.payload["node_b"])
        if event.event_time >= self._scenario.duration_seconds:
            self._topology.clear_failure(node_a, node_b)
            return
        self._topology.restore_link(node_a, node_b, event.event_time, engine)

    @staticmethod
    def _make_message(config: MessageConfig) -> Message:
        return Message(
            message_id=config.message_id,
            copy_id="original",
            source=config.source,
            destination=config.destination,
            creation_time=config.creation_time,
            size_bytes=config.size_bytes,
            ttl_seconds=config.ttl_seconds,
        )


def build_simulation(scenario: ScenarioConfig) -> ScenarioSimulation:
    """Build a ready-to-step simulation from a validated scenario."""

    return ScenarioSimulation(scenario)
