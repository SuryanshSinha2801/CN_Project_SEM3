"""Network node model and its local mutable state."""

from __future__ import annotations

import math
from dataclasses import dataclass
from enum import StrEnum

from blackout.models.buffer import MessageBuffer
from blackout.models.message import Message


class NodeState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class Position:
    x: float
    y: float

    def __post_init__(self) -> None:
        if not math.isfinite(self.x) or not math.isfinite(self.y):
            raise ValueError("position coordinates must be finite")
        if self.x < 0 or self.y < 0:
            raise ValueError("position coordinates must be non-negative")

    def distance_to(self, other: Position) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


@dataclass(frozen=True, slots=True)
class Velocity:
    x_per_second: float = 0.0
    y_per_second: float = 0.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.x_per_second) or not math.isfinite(self.y_per_second):
            raise ValueError("velocity components must be finite")


@dataclass(frozen=True, slots=True)
class ContactRecord:
    peer_node_id: str
    started_at: float
    ended_at: float

    def __post_init__(self) -> None:
        if not self.peer_node_id:
            raise ValueError("contact peer must not be empty")
        if not math.isfinite(self.started_at) or not math.isfinite(self.ended_at):
            raise ValueError("contact times must be finite")
        if self.started_at < 0 or self.ended_at < self.started_at:
            raise ValueError("contact interval is invalid")


@dataclass(slots=True)
class NodeCounters:
    messages_generated: int = 0
    messages_forwarded: int = 0
    messages_received: int = 0
    messages_delivered: int = 0
    messages_dropped: int = 0


class Node:
    """A simulated endpoint or relay with finite local storage."""

    def __init__(
        self,
        node_id: str,
        position: Position,
        communication_range: float,
        buffer_capacity_bytes: int,
        *,
        state: NodeState = NodeState.HEALTHY,
        simulated_ip: str | None = None,
        velocity: Velocity | None = None,
    ) -> None:
        if not node_id:
            raise ValueError("node ID must not be empty")
        if not math.isfinite(communication_range) or communication_range <= 0:
            raise ValueError("communication range must be finite and positive")
        if simulated_ip == "":
            raise ValueError("simulated IP address must not be empty")

        self._node_id = node_id
        self._simulated_ip = simulated_ip
        self._position = position
        self._velocity = velocity or Velocity()
        self._communication_range = float(communication_range)
        self._state = NodeState(state)
        self._buffer = MessageBuffer(buffer_capacity_bytes, owner_node_id=node_id)
        self._current_neighbors: set[str] = set()
        self._contact_history: list[ContactRecord] = []
        self._active_contact_starts: dict[str, float] = {}
        self._counters = NodeCounters()

    @property
    def node_id(self) -> str:
        return self._node_id

    @property
    def simulated_ip(self) -> str | None:
        return self._simulated_ip

    @property
    def position(self) -> Position:
        return self._position

    @property
    def velocity(self) -> Velocity:
        return self._velocity

    @property
    def communication_range(self) -> float:
        return self._communication_range

    @property
    def state(self) -> NodeState:
        return self._state

    @property
    def buffer(self) -> MessageBuffer:
        return self._buffer

    @property
    def current_neighbors(self) -> frozenset[str]:
        return frozenset(self._current_neighbors)

    @property
    def contact_history(self) -> tuple[ContactRecord, ...]:
        return tuple(self._contact_history)

    @property
    def counters(self) -> NodeCounters:
        return self._counters

    @property
    def is_available(self) -> bool:
        return self._state is not NodeState.UNAVAILABLE

    @property
    def state_score(self) -> float:
        return {
            NodeState.HEALTHY: 1.0,
            NodeState.DEGRADED: 0.5,
            NodeState.UNAVAILABLE: 0.0,
        }[self._state]

    def set_position(self, position: Position) -> None:
        self._position = position

    def set_velocity(self, velocity: Velocity) -> None:
        self._velocity = velocity

    def move_for(self, duration_seconds: float) -> Position:
        if not math.isfinite(duration_seconds) or duration_seconds < 0:
            raise ValueError("movement duration must be finite and non-negative")
        next_position = Position(
            x=self._position.x + self._velocity.x_per_second * duration_seconds,
            y=self._position.y + self._velocity.y_per_second * duration_seconds,
        )
        self._position = next_position
        return next_position

    def set_state(self, state: NodeState) -> None:
        self._state = NodeState(state)

    def distance_to(self, other: Node) -> float:
        return self._position.distance_to(other.position)

    def in_range_of(self, other: Node) -> bool:
        distance = self.distance_to(other)
        return distance <= min(self._communication_range, other.communication_range)

    def start_contact(self, peer_node_id: str, at_time: float) -> None:
        self._validate_peer(peer_node_id)
        if peer_node_id in self._current_neighbors:
            raise ValueError(f"contact with {peer_node_id!r} is already active")
        if not math.isfinite(at_time) or at_time < 0:
            raise ValueError("contact start time must be finite and non-negative")
        self._current_neighbors.add(peer_node_id)
        self._active_contact_starts[peer_node_id] = float(at_time)

    def end_contact(self, peer_node_id: str, at_time: float) -> ContactRecord:
        if peer_node_id not in self._current_neighbors:
            raise ValueError(f"contact with {peer_node_id!r} is not active")
        started_at = self._active_contact_starts[peer_node_id]
        record = ContactRecord(peer_node_id, started_at, float(at_time))
        self._current_neighbors.remove(peer_node_id)
        self._active_contact_starts.pop(peer_node_id)
        self._contact_history.append(record)
        return record

    def store_message(self, message: Message, at_time: float) -> None:
        self._buffer.put(message, at_time)
        self._counters.messages_received += 1

    def _validate_peer(self, peer_node_id: str) -> None:
        if not peer_node_id:
            raise ValueError("peer node ID must not be empty")
        if peer_node_id == self._node_id:
            raise ValueError("a node cannot contact itself")
