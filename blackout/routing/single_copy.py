"""Deterministic single-copy store-carry-forward decisions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping

from blackout.models import Message, Node


class ForwardAction(StrEnum):
    HOLD = "hold"
    FORWARD = "forward"


@dataclass(frozen=True, slots=True)
class ForwardDecision:
    """Explainable decision for one message at its current holder."""

    action: ForwardAction
    from_node: str
    to_node: str | None
    message_id: str
    copy_id: str
    reason: str
    score_components: Mapping[str, float] = field(default_factory=dict, compare=False)
    total_score: float = 0.0

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "score_components", MappingProxyType(dict(self.score_components))
        )


class GreedySingleCopyRouter:
    """Choose one in-contact relay that makes deterministic geometric progress.

    This is the first store-carry-forward policy foundation, not the final weighted
    BLACKOUT Adaptive algorithm. Direct delivery always wins. Otherwise, an unvisited
    peer must be closer to the destination and have enough buffer space.
    """

    def decide(
        self,
        holder: Node,
        message: Message,
        nodes: Mapping[str, Node],
        at_time: float,
    ) -> ForwardDecision:
        destination = nodes[message.destination]
        holder_distance = holder.distance_to(destination)
        candidates: list[tuple[int, float, str, Node]] = []

        for peer_id in sorted(holder.current_neighbors):
            peer = nodes[peer_id]
            if not peer.is_available or not peer.buffer.can_accept(message, at_time):
                continue
            if peer_id == message.destination:
                candidates.append((0, 0.0, peer_id, peer))
                continue
            if peer_id in message.visited_nodes:
                continue
            peer_distance = peer.distance_to(destination)
            if peer_distance < holder_distance:
                candidates.append((1, peer_distance, peer_id, peer))

        if not candidates:
            return ForwardDecision(
                action=ForwardAction.HOLD,
                from_node=holder.node_id,
                to_node=None,
                message_id=message.message_id,
                copy_id=message.copy_id,
                reason="no eligible neighbor makes progress toward the destination",
                score_components={"holder_distance": holder_distance},
            )

        _priority, peer_distance, _peer_id, selected = min(candidates)
        progress = holder_distance - peer_distance
        reason = (
            "destination is in direct contact"
            if selected.node_id == message.destination
            else "relay is closer to the destination"
        )
        return ForwardDecision(
            action=ForwardAction.FORWARD,
            from_node=holder.node_id,
            to_node=selected.node_id,
            message_id=message.message_id,
            copy_id=message.copy_id,
            reason=reason,
            score_components={
                "holder_distance": holder_distance,
                "peer_distance": peer_distance,
                "distance_progress": progress,
            },
            total_score=progress,
        )
