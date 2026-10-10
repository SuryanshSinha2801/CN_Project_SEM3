"""Message identity and lifecycle for delay-tolerant routing."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Mapping


class MessageState(StrEnum):
    """Lifecycle states for one routing copy of a message."""

    CREATED = "created"
    BUFFERED = "buffered"
    DELIVERED = "delivered"
    EXPIRED = "expired"
    DROPPED = "dropped"


@dataclass(frozen=True, slots=True)
class MessageHop:
    """One completed custody or copy transfer."""

    from_node: str
    to_node: str
    completed_at: float

    def __post_init__(self) -> None:
        if not self.from_node or not self.to_node:
            raise ValueError("hop endpoints must not be empty")
        if self.from_node == self.to_node:
            raise ValueError("hop endpoints must differ")
        if not math.isfinite(self.completed_at) or self.completed_at < 0:
            raise ValueError("hop completion time must be finite and non-negative")


@dataclass(frozen=True, slots=True)
class Message:
    """A routing-level message with immutable identity and controlled state.

    ``copy_id`` distinguishes replicas made by routing policies. The logical identity of
    a buffered item is therefore ``(message_id, copy_id)``.
    """

    message_id: str
    source: str
    destination: str
    creation_time: float
    size_bytes: int
    ttl_seconds: float
    copy_id: str = "original"
    routing_metadata: Mapping[str, Any] = field(default_factory=dict, compare=False)
    _state: MessageState = field(
        default=MessageState.CREATED, init=False, repr=False, compare=False
    )
    _delivery_time: float | None = field(default=None, init=False, repr=False, compare=False)
    _last_custody_holder: str = field(default="", init=False, repr=False, compare=False)
    _hop_history: tuple[MessageHop, ...] = field(default=(), init=False, repr=False, compare=False)
    _visited_nodes: frozenset[str] = field(
        default_factory=frozenset, init=False, repr=False, compare=False
    )

    def __post_init__(self) -> None:
        for field_name, value in (
            ("message_id", self.message_id),
            ("copy_id", self.copy_id),
            ("source", self.source),
            ("destination", self.destination),
        ):
            if not value:
                raise ValueError(f"{field_name} must not be empty")
        if self.source == self.destination:
            raise ValueError("message source and destination must differ")
        if not math.isfinite(self.creation_time) or self.creation_time < 0:
            raise ValueError("creation_time must be finite and non-negative")
        if (
            not isinstance(self.size_bytes, int)
            or isinstance(self.size_bytes, bool)
            or self.size_bytes <= 0
        ):
            raise ValueError("size_bytes must be a positive integer")
        if not math.isfinite(self.ttl_seconds) or self.ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be finite and positive")

        object.__setattr__(self, "routing_metadata", MappingProxyType(dict(self.routing_metadata)))
        object.__setattr__(self, "_last_custody_holder", self.source)
        object.__setattr__(self, "_visited_nodes", frozenset({self.source}))

    @property
    def identity(self) -> tuple[str, str]:
        return (self.message_id, self.copy_id)

    @property
    def expires_at(self) -> float:
        return self.creation_time + self.ttl_seconds

    @property
    def state(self) -> MessageState:
        return self._state

    @property
    def delivery_time(self) -> float | None:
        return self._delivery_time

    @property
    def last_custody_holder(self) -> str:
        return self._last_custody_holder

    @property
    def hop_history(self) -> tuple[MessageHop, ...]:
        return self._hop_history

    @property
    def hop_count(self) -> int:
        return len(self._hop_history)

    @property
    def visited_nodes(self) -> frozenset[str]:
        return self._visited_nodes

    @property
    def is_terminal(self) -> bool:
        return self._state in {
            MessageState.DELIVERED,
            MessageState.EXPIRED,
            MessageState.DROPPED,
        }

    def is_expired(self, at_time: float) -> bool:
        self._validate_observation_time(at_time)
        return at_time >= self.expires_at

    def remaining_ttl(self, at_time: float) -> float:
        self._validate_observation_time(at_time)
        return max(0.0, self.expires_at - at_time)

    def mark_buffered(self, node_id: str, at_time: float) -> None:
        """Record that this copy is safely stored at ``node_id``."""

        self._require_active(at_time)
        if not node_id:
            raise ValueError("buffer node ID must not be empty")
        object.__setattr__(self, "_state", MessageState.BUFFERED)
        object.__setattr__(self, "_last_custody_holder", node_id)
        object.__setattr__(self, "_visited_nodes", self._visited_nodes | {node_id})

    def record_hop(self, from_node: str, to_node: str, completed_at: float) -> None:
        """Append one successful transfer and move custody to its receiver."""

        self._require_active(completed_at)
        if from_node != self._last_custody_holder:
            raise ValueError("hop sender must be the current custody holder")
        hop = MessageHop(from_node=from_node, to_node=to_node, completed_at=completed_at)
        object.__setattr__(self, "_hop_history", (*self._hop_history, hop))
        object.__setattr__(self, "_last_custody_holder", to_node)
        object.__setattr__(self, "_visited_nodes", self._visited_nodes | {to_node})
        object.__setattr__(self, "_state", MessageState.BUFFERED)

    def mark_delivered(self, at_time: float, node_id: str) -> None:
        """Finish the message lifecycle at its configured destination."""

        self._require_active(at_time)
        if node_id != self.destination:
            raise ValueError("a message can only be delivered at its destination")
        object.__setattr__(self, "_state", MessageState.DELIVERED)
        object.__setattr__(self, "_delivery_time", float(at_time))
        object.__setattr__(self, "_last_custody_holder", node_id)
        object.__setattr__(self, "_visited_nodes", self._visited_nodes | {node_id})

    def mark_expired(self, at_time: float) -> None:
        if not self.is_expired(at_time):
            raise ValueError("message TTL has not expired")
        if self.is_terminal:
            raise ValueError("cannot expire a terminal message")
        object.__setattr__(self, "_state", MessageState.EXPIRED)

    def mark_dropped(self, at_time: float) -> None:
        self._require_active(at_time)
        object.__setattr__(self, "_state", MessageState.DROPPED)

    def _require_active(self, at_time: float) -> None:
        self._validate_observation_time(at_time)
        if self.is_terminal:
            raise ValueError(f"message is already {self._state.value}")
        if self.is_expired(at_time):
            raise ValueError("message TTL has expired")

    def _validate_observation_time(self, at_time: float) -> None:
        if not math.isfinite(at_time) or at_time < self.creation_time:
            raise ValueError("observation time must be finite and not precede message creation")
