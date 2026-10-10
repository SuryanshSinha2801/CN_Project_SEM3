"""Runnable scenario state assembled from configuration and event handlers."""

from __future__ import annotations

import random
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from blackout.config import MessageConfig, RoutingPolicy, ScenarioConfig
from blackout.events import EventType, SimulationEvent
from blackout.models import Message, MessageState, Node, NodeState, Position
from blackout.routing import AdaptiveRouter, ForwardAction, ForwardDecision
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
        self._pending_transfers: set[tuple[str, str, str]] = set()
        self._copy_budgets: dict[tuple[str, str], int] = {}
        self._delivered_message_ids: set[str] = set()
        self._copy_sequence = 0
        self._router = self._build_router()
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
        self._pending_transfers = set()
        self._copy_budgets = {}
        self._delivered_message_ids = set()
        self._copy_sequence = 0
        self._router = self._build_router()
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
        self._copy_budgets[message.identity] = self._scenario.spray_copy_budget
        self._schedule_buffered_event(message, source, engine)

    def _on_message_buffered(
        self, event: SimulationEvent, engine: SimulationEngine
    ) -> None:
        self._consider_forwarding(str(event.payload["node_id"]), engine)

    def _on_message_expired(
        self, event: SimulationEvent, _engine: SimulationEngine
    ) -> None:
        message_id = str(event.payload["message_id"])
        holders = {
            message.last_custody_holder
            for message in self._messages.values()
            if message.message_id == message_id and not message.is_terminal
        }
        for holder_id in holders:
            holder = self._nodes[holder_id]
            holder.buffer.expire(event.event_time)
            self._schedule_buffer_update(holder, _engine)
        self._pending_transfers = {
            pending for pending in self._pending_transfers if pending[0] != message_id
        }

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
        if self._scenario.routing_policy is RoutingPolicy.ADAPTIVE:
            self._consider_adaptive(holder_id, engine)
        elif self._scenario.routing_policy is RoutingPolicy.EPIDEMIC:
            self._consider_epidemic(holder_id, engine)
        else:
            self._consider_spray_and_wait(holder_id, engine)

    def _consider_adaptive(self, holder_id: str, engine: SimulationEngine) -> None:
        holder = self._nodes[holder_id]
        for message in sorted(holder.buffer.items(), key=lambda item: item.identity):
            if self._has_pending(message.identity) or self._skip_message(message):
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
                self._schedule_transfer(
                    message,
                    decision.from_node,
                    decision.to_node,
                    "custody",
                    engine,
                )

    def _consider_epidemic(self, holder_id: str, engine: SimulationEngine) -> None:
        holder = self._nodes[holder_id]
        for message in sorted(holder.buffer.items(), key=lambda item: item.identity):
            if self._skip_message(message):
                continue
            for peer_id in sorted(holder.current_neighbors):
                peer = self._nodes[peer_id]
                pending_key = (*message.identity, peer_id)
                if pending_key in self._pending_transfers or peer.buffer.contains(
                    message.message_id
                ):
                    continue
                if not peer.buffer.can_accept(message, engine.current_time):
                    continue
                self._schedule_baseline_decision(
                    message, holder_id, peer_id, "epidemic replica", engine
                )
                self._schedule_transfer(message, holder_id, peer_id, "replicate", engine)

    def _consider_spray_and_wait(self, holder_id: str, engine: SimulationEngine) -> None:
        holder = self._nodes[holder_id]
        for message in sorted(holder.buffer.items(), key=lambda item: item.identity):
            if self._skip_message(message) or self._has_pending(message.identity):
                continue
            budget = self._copy_budgets.get(message.identity, 1)
            peers = [self._nodes[node_id] for node_id in sorted(holder.current_neighbors)]
            destination = next(
                (peer for peer in peers if peer.node_id == message.destination), None
            )
            if destination is not None and not destination.buffer.contains(message.message_id):
                self._schedule_baseline_decision(
                    message, holder_id, destination.node_id, "destination in contact", engine
                )
                self._schedule_transfer(
                    message, holder_id, destination.node_id, "replicate", engine
                )
                continue
            if budget <= 1:
                self._schedule_baseline_hold(message, holder_id, "wait phase", engine)
                continue
            peer = next(
                (
                    candidate
                    for candidate in peers
                    if not candidate.buffer.contains(message.message_id)
                    and candidate.buffer.can_accept(message, engine.current_time)
                ),
                None,
            )
            if peer is None:
                self._schedule_baseline_hold(message, holder_id, "no relay can accept copy", engine)
                continue
            transfer_budget = budget // 2
            self._schedule_baseline_decision(
                message,
                holder_id,
                peer.node_id,
                f"binary spray {transfer_budget} of {budget} copy tokens",
                engine,
            )
            self._schedule_transfer(
                message,
                holder_id,
                peer.node_id,
                "spray",
                engine,
                transfer_budget=transfer_budget,
            )

    def _on_transfer_attempt(
        self, event: SimulationEvent, engine: SimulationEngine
    ) -> None:
        identity = (str(event.payload["message_id"]), str(event.payload["copy_id"]))
        from_node_id = str(event.payload["from_node"])
        to_node_id = str(event.payload["to_node"])
        mode = str(event.payload["mode"])
        retry_count = int(event.payload.get("retry_count", 0))
        transfer_budget = int(event.payload.get("transfer_budget", 0))
        pending_key = (*identity, to_node_id)
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
        elif receiver.buffer.contains(message.message_id):
            failure_reason = "receiver already has this logical message"
        elif not receiver.buffer.can_accept(message, event.event_time):
            failure_reason = "receiver buffer cannot accept the message"

        if failure_reason is not None:
            self._pending_transfers.discard(pending_key)
            self._schedule_transfer_outcome(
                EventType.TRANSFER_FAILED,
                identity,
                from_node_id,
                to_node_id,
                engine,
                reason=failure_reason,
            )
            if (
                message is not None
                and not message.is_terminal
                and source.buffer.contains(*identity)
            ):
                self._consider_forwarding(from_node_id, engine)
            return

        if message is None:
            raise RuntimeError("active transfer message unexpectedly disappeared")
        self._schedule_link_event(EventType.PACKET_SENT, event.payload, engine)
        packet_draw = self._channel_draw(
            "packet",
            message.message_id,
            from_node_id,
            to_node_id,
            retry_count,
            event.event_time,
        )
        if packet_draw < self._scenario.packet_loss_probability:
            self._schedule_link_event(EventType.PACKET_LOST, event.payload, engine)
            self._retry_or_fail(
                message,
                from_node_id,
                to_node_id,
                mode,
                retry_count,
                transfer_budget,
                engine,
                "data packet lost",
            )
            return

        self._schedule_link_event(EventType.PACKET_RECEIVED, event.payload, engine)
        self._schedule_link_event(EventType.ACK_SENT, event.payload, engine)
        ack_draw = self._channel_draw(
            "ack",
            message.message_id,
            from_node_id,
            to_node_id,
            retry_count,
            event.event_time,
        )
        if ack_draw < self._scenario.ack_loss_probability:
            self._schedule_link_event(EventType.ACK_LOST, event.payload, engine)
            self._retry_or_fail(
                message,
                from_node_id,
                to_node_id,
                mode,
                retry_count,
                transfer_budget,
                engine,
                "acknowledgement lost",
            )
            return

        self._schedule_link_event(EventType.ACK_RECEIVED, event.payload, engine)
        self._pending_transfers.discard(pending_key)
        self._complete_transfer(
            message,
            source,
            receiver,
            mode,
            transfer_budget,
            event.event_time,
            engine,
        )

    def _complete_transfer(
        self,
        message: Message,
        source: Node,
        receiver: Node,
        mode: str,
        transfer_budget: int,
        at_time: float,
        engine: SimulationEngine,
    ) -> None:
        if mode == "custody":
            source.buffer.remove(*message.identity)
            self._schedule_buffer_update(source, engine)
            message.record_hop(source.node_id, receiver.node_id, at_time)
            receiver.buffer.put(message, at_time)
            received = message
            self._router.record_transfer(message, source.node_id, receiver.node_id, at_time)
        else:
            received = message.replicate(
                self._next_copy_id(message.message_id), receiver.node_id, at_time
            )
            receiver.buffer.put(received, at_time)
            self._messages[received.identity] = received
            if mode == "spray":
                current_budget = self._copy_budgets.get(message.identity, 1)
                self._copy_budgets[message.identity] = current_budget - transfer_budget
                self._copy_budgets[received.identity] = transfer_budget
            engine.schedule(
                EventType.ROUTING_COPY_CREATED,
                {
                    "message_id": received.message_id,
                    "copy_id": received.copy_id,
                    "from_node": source.node_id,
                    "to_node": receiver.node_id,
                    "policy": self._scenario.routing_policy.value,
                },
            )

        source.counters.messages_forwarded += 1
        receiver.counters.messages_received += 1
        self._schedule_transfer_outcome(
            EventType.TRANSFER_COMPLETED,
            received.identity,
            source.node_id,
            receiver.node_id,
            engine,
            reason="Stop-and-Wait transfer acknowledged",
        )

        if receiver.node_id == received.destination:
            receiver.buffer.remove(*received.identity)
            self._schedule_buffer_update(receiver, engine)
            received.mark_delivered(at_time, receiver.node_id)
            if received.message_id not in self._delivered_message_ids:
                self._delivered_message_ids.add(received.message_id)
                receiver.counters.messages_delivered += 1
                engine.schedule(
                    EventType.MESSAGE_DELIVERED,
                    {
                        "message_id": received.message_id,
                        "copy_id": received.copy_id,
                        "node_id": receiver.node_id,
                        "delay_seconds": at_time - received.creation_time,
                        "hop_count": received.hop_count,
                        "size_bytes": received.size_bytes,
                    },
                )
        else:
            self._schedule_buffered_event(received, receiver, engine)

    def _retry_or_fail(
        self,
        message: Message,
        from_node: str,
        to_node: str,
        mode: str,
        retry_count: int,
        transfer_budget: int,
        engine: SimulationEngine,
        reason: str,
    ) -> None:
        next_attempt_time = engine.current_time + self._scenario.ack_timeout_seconds
        deadline = min(message.expires_at, self._scenario.duration_seconds)
        if retry_count < self._scenario.max_link_retries and next_attempt_time < deadline:
            engine.schedule(
                EventType.RETRANSMISSION,
                {
                    "message_id": message.message_id,
                    "copy_id": message.copy_id,
                    "from_node": from_node,
                    "to_node": to_node,
                    "retry_count": retry_count + 1,
                    "reason": reason,
                },
            )
            engine.schedule_after(
                self._scenario.ack_timeout_seconds,
                EventType.TRANSFER_ATTEMPT,
                {
                    "message_id": message.message_id,
                    "copy_id": message.copy_id,
                    "from_node": from_node,
                    "to_node": to_node,
                    "mode": mode,
                    "retry_count": retry_count + 1,
                    "transfer_budget": transfer_budget,
                },
            )
            return

        self._pending_transfers.discard((*message.identity, to_node))
        self._schedule_transfer_outcome(
            EventType.TRANSFER_FAILED,
            message.identity,
            from_node,
            to_node,
            engine,
            reason=f"{reason}; retry limit or deadline reached",
        )

    def _schedule_transfer(
        self,
        message: Message,
        from_node: str,
        to_node: str,
        mode: str,
        engine: SimulationEngine,
        *,
        transfer_budget: int = 0,
    ) -> None:
        completion_time = engine.current_time + self._scenario.transfer_delay_seconds
        deadline = min(message.expires_at, self._scenario.duration_seconds)
        if completion_time >= deadline:
            self._schedule_transfer_outcome(
                EventType.TRANSFER_FAILED,
                message.identity,
                from_node,
                to_node,
                engine,
                reason="insufficient time before message or simulation deadline",
            )
            return
        pending_key = (*message.identity, to_node)
        self._pending_transfers.add(pending_key)
        engine.schedule_after(
            self._scenario.transfer_delay_seconds,
            EventType.TRANSFER_ATTEMPT,
            {
                "message_id": message.message_id,
                "copy_id": message.copy_id,
                "from_node": from_node,
                "to_node": to_node,
                "mode": mode,
                "retry_count": 0,
                "transfer_budget": transfer_budget,
            },
        )

    def _has_pending(self, identity: tuple[str, str]) -> bool:
        return any(pending[:2] == identity for pending in self._pending_transfers)

    def _skip_message(self, message: Message) -> bool:
        return message.is_terminal or message.message_id in self._delivered_message_ids

    def _next_copy_id(self, message_id: str) -> str:
        self._copy_sequence += 1
        return f"{message_id}-copy-{self._copy_sequence:04d}"

    def _channel_draw(
        self,
        outcome: str,
        message_id: str,
        from_node: str,
        to_node: str,
        retry_count: int,
        at_time: float,
    ) -> float:
        """Return a policy-independent deterministic channel outcome."""

        channel_seed = (
            f"{self._scenario.seed}:{outcome}:{message_id}:{from_node}:"
            f"{to_node}:{retry_count}:{at_time:.9f}"
        )
        return random.Random(channel_seed).random()

    def _schedule_baseline_decision(
        self,
        message: Message,
        from_node: str,
        to_node: str,
        reason: str,
        engine: SimulationEngine,
    ) -> None:
        self._schedule_decision(
            ForwardDecision(
                action=ForwardAction.FORWARD,
                from_node=from_node,
                to_node=to_node,
                message_id=message.message_id,
                copy_id=message.copy_id,
                reason=reason,
            ),
            engine,
        )

    def _schedule_baseline_hold(
        self, message: Message, holder_id: str, reason: str, engine: SimulationEngine
    ) -> None:
        self._schedule_decision(
            ForwardDecision(
                action=ForwardAction.HOLD,
                from_node=holder_id,
                to_node=None,
                message_id=message.message_id,
                copy_id=message.copy_id,
                reason=reason,
            ),
            engine,
        )

    @staticmethod
    def _schedule_link_event(
        event_type: EventType, payload: Mapping[str, object], engine: SimulationEngine
    ) -> None:
        engine.schedule(event_type, dict(payload))

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
    def _schedule_buffer_update(node: Node, engine: SimulationEngine) -> None:
        engine.schedule(
            EventType.BUFFER_UPDATED,
            {
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

    def _build_router(self) -> AdaptiveRouter:
        return AdaptiveRouter(
            self._scenario.adaptive_weights,
            area_width=self._scenario.area.width,
            area_height=self._scenario.area.height,
            contact_window_seconds=self._scenario.adaptive_contact_window_seconds,
            contact_saturation=self._scenario.adaptive_contact_saturation,
            edge_cooldown_seconds=self._scenario.adaptive_edge_cooldown_seconds,
        )


def build_simulation(scenario: ScenarioConfig) -> ScenarioSimulation:
    """Build a ready-to-step simulation from a validated scenario."""

    return ScenarioSimulation(scenario)
