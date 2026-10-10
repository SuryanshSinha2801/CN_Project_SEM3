"""Event definitions shared by the BLACKOUT simulation components."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Mapping


class EventType(StrEnum):
    """Events that can occur on the simulator's deterministic timeline."""

    SIMULATION_STARTED = "simulation_started"
    MESSAGE_CREATED = "message_created"
    NODE_MOVED = "node_moved"
    CONTACT_STARTED = "contact_started"
    CONTACT_ENDED = "contact_ended"
    LINK_FAILED = "link_failed"
    LINK_RESTORED = "link_restored"
    MESSAGE_BUFFERED = "message_buffered"
    FORWARD_DECISION = "forward_decision"
    TRANSFER_COMPLETED = "transfer_completed"
    MESSAGE_DELIVERED = "message_delivered"
    SIMULATION_ENDED = "simulation_ended"


@dataclass(order=True, frozen=True, slots=True)
class SimulationEvent:
    """One immutable item on the event queue.

    Events are ordered by simulated time and then by their monotonically increasing
    sequence number. The latter guarantees FIFO behaviour for equal timestamps.
    """

    event_time: float
    sequence_number: int
    event_type: EventType = field(compare=False)
    payload: Mapping[str, Any] = field(default_factory=dict, compare=False)

