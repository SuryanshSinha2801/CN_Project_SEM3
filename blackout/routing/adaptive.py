"""Explainable weighted BLACKOUT Adaptive single-copy routing policy."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Mapping

from blackout.config import AdaptiveWeights
from blackout.models import Message, Node
from blackout.routing.single_copy import ForwardAction, ForwardDecision


@dataclass(frozen=True, slots=True)
class AdaptiveScore:
    """Normalized factors and their weighted total for one node."""

    connectivity: float
    proximity: float
    buffer_availability: float
    node_state: float
    total: float

    def as_components(self, prefix: str = "") -> dict[str, float]:
        return {
            f"{prefix}connectivity": self.connectivity,
            f"{prefix}proximity": self.proximity,
            f"{prefix}buffer_availability": self.buffer_availability,
            f"{prefix}node_state": self.node_state,
        }


class AdaptiveRouter:
    """Apply the documented four-factor score and hysteresis forwarding rule."""

    def __init__(
        self,
        weights: AdaptiveWeights,
        *,
        area_width: float,
        area_height: float,
        contact_window_seconds: float = 30,
        contact_saturation: int = 3,
        edge_cooldown_seconds: float = 2,
    ) -> None:
        if contact_window_seconds <= 0:
            raise ValueError("contact observation window must be positive")
        if contact_saturation <= 0:
            raise ValueError("contact saturation must be positive")
        if edge_cooldown_seconds < 0:
            raise ValueError("edge cooldown must be non-negative")
        self._weights = weights
        self._area_diagonal = math.hypot(area_width, area_height)
        self._contact_window_seconds = contact_window_seconds
        self._contact_saturation = contact_saturation
        self._edge_cooldown_seconds = edge_cooldown_seconds
        self._recent_edges: dict[tuple[str, str, str, str], float] = {}

    def score_node(
        self,
        node: Node,
        destination: Node,
        *,
        node_count: int,
        at_time: float,
    ) -> AdaptiveScore:
        """Calculate all normalized score factors for a node."""

        window_start = at_time - self._contact_window_seconds
        recent_destination_contacts = sum(
            1
            for contact in node.contact_history
            if contact.peer_node_id == destination.node_id
            and window_start <= contact.ended_at <= at_time
        )
        contact_term = min(1.0, recent_destination_contacts / self._contact_saturation)
        degree_term = len(node.current_neighbors) / max(1, node_count - 1)
        connectivity = 0.7 * contact_term + 0.3 * degree_term
        proximity = max(
            0.0,
            min(1.0, 1.0 - node.distance_to(destination) / self._area_diagonal),
        )
        buffer_availability = node.buffer.free_bytes / node.buffer.capacity_bytes
        node_state = node.state_score
        total = (
            self._weights.connectivity * connectivity
            + self._weights.proximity * proximity
            + self._weights.buffer_availability * buffer_availability
            + self._weights.node_state * node_state
        )
        return AdaptiveScore(
            connectivity=connectivity,
            proximity=proximity,
            buffer_availability=buffer_availability,
            node_state=node_state,
            total=total,
        )

    def decide(
        self,
        holder: Node,
        message: Message,
        nodes: Mapping[str, Node],
        at_time: float,
    ) -> ForwardDecision:
        destination = nodes[message.destination]
        holder_score = self.score_node(
            holder, destination, node_count=len(nodes), at_time=at_time
        )
        eligible: list[tuple[Node, AdaptiveScore]] = []

        for peer_id in sorted(holder.current_neighbors):
            peer = nodes[peer_id]
            if not peer.is_available or not peer.buffer.can_accept(message, at_time):
                continue
            if peer_id == message.destination:
                direct_score = self.score_node(
                    peer, destination, node_count=len(nodes), at_time=at_time
                )
                return self._forward_decision(
                    holder,
                    peer,
                    message,
                    holder_score,
                    direct_score,
                    "destination is in direct contact; scoring bypassed",
                )
            if peer_id in message.visited_nodes or self._is_on_cooldown(
                message, holder.node_id, peer_id, at_time
            ):
                continue
            eligible.append(
                (
                    peer,
                    self.score_node(
                        peer, destination, node_count=len(nodes), at_time=at_time
                    ),
                )
            )

        if not eligible:
            return self._hold_decision(
                holder, message, holder_score, "no eligible neighbor is available"
            )

        peer, peer_score = min(
            eligible,
            key=lambda item: (
                -item[1].total,
                -item[1].proximity,
                -item[1].buffer_availability,
                item[0].node_id,
            ),
        )
        required_score = holder_score.total + self._weights.minimum_improvement
        if peer_score.total + 1e-12 < required_score:
            return self._hold_decision(
                holder,
                message,
                holder_score,
                (
                    f"best candidate {peer.node_id} scored {peer_score.total:.3f}; "
                    f"requires at least {required_score:.3f}"
                ),
                candidate=peer,
                candidate_score=peer_score,
            )

        return self._forward_decision(
            holder,
            peer,
            message,
            holder_score,
            peer_score,
            (
                f"candidate improves score by "
                f"{peer_score.total - holder_score.total:.3f}, meeting hysteresis"
            ),
        )

    def record_transfer(
        self, message: Message, from_node: str, to_node: str, at_time: float
    ) -> None:
        node_a, node_b = self._edge(from_node, to_node)
        self._recent_edges[(message.message_id, message.copy_id, node_a, node_b)] = at_time

    def _is_on_cooldown(
        self, message: Message, node_a: str, node_b: str, at_time: float
    ) -> bool:
        edge_a, edge_b = self._edge(node_a, node_b)
        last_used = self._recent_edges.get(
            (message.message_id, message.copy_id, edge_a, edge_b)
        )
        return last_used is not None and at_time - last_used < self._edge_cooldown_seconds

    @staticmethod
    def _edge(node_a: str, node_b: str) -> tuple[str, str]:
        return (node_a, node_b) if node_a < node_b else (node_b, node_a)

    def _forward_decision(
        self,
        holder: Node,
        peer: Node,
        message: Message,
        holder_score: AdaptiveScore,
        peer_score: AdaptiveScore,
        reason: str,
    ) -> ForwardDecision:
        return ForwardDecision(
            action=ForwardAction.FORWARD,
            from_node=holder.node_id,
            to_node=peer.node_id,
            message_id=message.message_id,
            copy_id=message.copy_id,
            reason=reason,
            score_components=self._combined_components(holder_score, peer_score),
            total_score=peer_score.total,
        )

    def _hold_decision(
        self,
        holder: Node,
        message: Message,
        holder_score: AdaptiveScore,
        reason: str,
        *,
        candidate: Node | None = None,
        candidate_score: AdaptiveScore | None = None,
    ) -> ForwardDecision:
        components = holder_score.as_components("holder_")
        components["holder_total"] = holder_score.total
        components["minimum_improvement"] = self._weights.minimum_improvement
        if candidate_score is not None:
            components.update(candidate_score.as_components("candidate_"))
            components["candidate_total"] = candidate_score.total
        return ForwardDecision(
            action=ForwardAction.HOLD,
            from_node=holder.node_id,
            to_node=None if candidate is None else candidate.node_id,
            message_id=message.message_id,
            copy_id=message.copy_id,
            reason=reason,
            score_components=components,
            total_score=holder_score.total,
        )

    def _combined_components(
        self, holder_score: AdaptiveScore, candidate_score: AdaptiveScore
    ) -> dict[str, float]:
        components = holder_score.as_components("holder_")
        components.update(candidate_score.as_components("candidate_"))
        components.update(
            {
                "holder_total": holder_score.total,
                "candidate_total": candidate_score.total,
                "minimum_improvement": self._weights.minimum_improvement,
            }
        )
        return components
