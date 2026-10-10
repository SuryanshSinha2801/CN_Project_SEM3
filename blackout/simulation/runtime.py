"""Runnable scenario state assembled from configuration and event handlers."""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from blackout.config import MessageConfig, ScenarioConfig
from blackout.events import EventType, SimulationEvent
from blackout.models import Message, MessageState, Node, NodeState, Position
from blackout.routing import ForwardAction, ForwardDecision, GreedySingleCopyRouter
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
        self._pending_transfers: dict[tuple[str, str], tuple[str, str]] = {}
        self._router = GreedySingleCopyRouter()
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
        self._pending_transfers = {}
        initially_blocked = (
            (failure.node_a, failure.node_b)
            for failure in self._scenario.forced_link_failures
            if failure.start_time == 0
        )
        self._topology = TopologyManager(self._nodes, initially_blocked)
        self._engine = schedule_scenario(self._scenario)
        self._engine.register_handler(EventType.SIMULATION_STARTED, self._on_simulation_started)
        self._engine.register_handler(EventType.MESSAGE_CREATED, self._on_message_created)
        self._engine.register_handler(EventType.MESSAGE_BUFFERED, self._on_message_buffered)
        self._engine.register_handler(EventType.MESSAGE_EXPIRED, self._on_message_expired)
        self._engine.register_handler(EventType.CONTACT_STARTED, self._on_contact_started)
        self._engine.register_handler(EventType.TRANSFER_ATTEMPT, self._on_transfer_attempt)
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
        self._schedule_buffered_event(message, source, engine)

    def _on_message_buffered(
        self, event: SimulationEvent, engine: SimulationEngine
    ) -> None:
        self._consider_forwarding(str(event.payload["node_id"]), engine)

    def _on_message_expired(
        self, event: SimulationEvent, _engine: SimulationEngine
    ) -> None:
        identity = (str(event.payload["message_id"]), str(event.payload["copy_id"]))
        message = self._messages.get(identity)
        if message is None or message.is_terminal:
            return
        holder = self._nodes[message.last_custody_holder]
        holder.buffer.expire(event.event_time)
        self._pending_transfers.pop(identity, None)

    def _on_contact_started(
        self, event: SimulationEvent, engine: SimulationEngine
    ) -> None:
        self._consider_forwarding(str(event.payload["node_a"]), engine)
        self._consider_forwarding(str(event.payload["node_b"]), engine)

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

    def _consider_forwarding(self, holder_id: str, engine: SimulationEngine) -> None:
        holder = self._nodes[holder_id]
        for message in sorted(holder.buffer.items(), key=lambda item: item.identity):
            if message.identity in self._pending_transfers or message.is_terminal:
                continue
            decision = self._router.decide(
                holder, message, self._nodes, engine.current_time
            )
            completion_time = engine.current_time + self._scenario.transfer_delay_seconds
            deadline = min(message.expires_at, self._scenario.duration_seconds)
            if decision.action is ForwardAction.FORWARD and completion_time >= deadline:
                decision = ForwardDecision(
                    action=ForwardAction.HOLD,
                    from_node=holder.node_id,
                    to_node=None,
                    message_id=message.message_id,
                    copy_id=message.copy_id,
                    reason="insufficient time before message or simulation deadline",
                    score_components=decision.score_components,
                    total_score=decision.total_score,
                )
            self._schedule_decision(decision, engine)
            if decision.action is ForwardAction.FORWARD:
                if decision.to_node is None:
                    raise RuntimeError("forward decision is missing its destination node")
                self._pending_transfers[message.identity] = (
                    decision.from_node,
                    decision.to_node,
                )
                engine.schedule_after(
                    self._scenario.transfer_delay_seconds,
                    EventType.TRANSFER_ATTEMPT,
                    {
                        "message_id": message.message_id,
                        "copy_id": message.copy_id,
                        "from_node": decision.from_node,
                        "to_node": decision.to_node,
                    },
                )

    def _on_transfer_attempt(
        self, event: SimulationEvent, engine: SimulationEngine
    ) -> None:
        identity = (str(event.payload["message_id"]), str(event.payload["copy_id"]))
        from_node_id = str(event.payload["from_node"])
        to_node_id = str(event.payload["to_node"])
        self._pending_transfers.pop(identity, None)
        message = self._messages.get(identity)
        source = self._nodes[from_node_id]
        receiver = self._nodes[to_node_id]

        failure_reason: str | None = None
        if message is None or message.is_terminal:
            failure_reason = "message is no longer active"
        elif not source.buffer.contains(*identity):
            failure_reason = "source no longer holds the message"
        elif not self._topology.is_link_active(from_node_id, to_node_id):
            failure_reason = "contact ended before transfer completion"
        elif not receiver.buffer.can_accept(message, event.event_time):
            failure_reason = "receiver buffer cannot accept the message"

        if failure_reason is not None:
            self._schedule_transfer_outcome(
                EventType.TRANSFER_FAILED,
                identity,
                from_node_id,
                to_node_id,
                engine,
                reason=failure_reason,
            )
            if message is not None and not message.is_terminal and source.buffer.contains(*identity):
                self._consider_forwarding(from_node_id, engine)
            return

        if message is None:
            raise RuntimeError("active transfer message unexpectedly disappeared")
        source.buffer.remove(*identity)
        message.record_hop(from_node_id, to_node_id, event.event_time)
        receiver.buffer.put(message, event.event_time)
        source.counters.messages_forwarded += 1
        receiver.counters.messages_received += 1
        self._schedule_transfer_outcome(
            EventType.TRANSFER_COMPLETED,
            identity,
            from_node_id,
            to_node_id,
            engine,
            reason="custody transferred after active-contact check",
        )

        if to_node_id == message.destination:
            receiver.buffer.remove(*identity)
            message.mark_delivered(event.event_time, to_node_id)
            receiver.counters.messages_delivered += 1
            engine.schedule(
                EventType.MESSAGE_DELIVERED,
                {
                    "message_id": message.message_id,
                    "copy_id": message.copy_id,
                    "node_id": to_node_id,
                    "delay_seconds": event.event_time - message.creation_time,
                    "hop_count": message.hop_count,
                },
            )
        else:
            self._schedule_buffered_event(message, receiver, engine)

    @staticmethod
    def _schedule_decision(decision: ForwardDecision, engine: SimulationEngine) -> None:
        engine.schedule(
            EventType.FORWARD_DECISION,
            {
                "action": decision.action.value,
                "from_node": decision.from_node,
                "to_node": decision.to_node,
                "message_id": decision.message_id,
                "copy_id": decision.copy_id,
                "reason": decision.reason,
                "score_components": dict(decision.score_components),
                "total_score": decision.total_score,
            },
        )

    @staticmethod
    def _schedule_buffered_event(
        message: Message, node: Node, engine: SimulationEngine
    ) -> None:
        engine.schedule(
            EventType.MESSAGE_BUFFERED,
            {
                "message_id": message.message_id,
                "copy_id": message.copy_id,
                "node_id": node.node_id,
                "used_bytes": node.buffer.used_bytes,
                "free_bytes": node.buffer.free_bytes,
            },
        )

    @staticmethod
    def _schedule_transfer_outcome(
        event_type: EventType,
        identity: tuple[str, str],
        from_node: str,
        to_node: str,
        engine: SimulationEngine,
        *,
        reason: str,
    ) -> None:
        engine.schedule(
            event_type,
            {
                "message_id": identity[0],
                "copy_id": identity[1],
                "from_node": from_node,
                "to_node": to_node,
                "reason": reason,
            },
        )

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
