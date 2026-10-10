"""Validated scenario configuration for deterministic BLACKOUT experiments."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

PositiveFloat = Annotated[float, Field(gt=0)]
NonNegativeFloat = Annotated[float, Field(ge=0)]
Probability = Annotated[float, Field(ge=0, le=1)]
PositiveInt = Annotated[int, Field(gt=0)]


class StrictModel(BaseModel):
    """Base model that catches misspelled fields instead of ignoring them."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class RoutingPolicy(StrEnum):
    EPIDEMIC = "epidemic"
    SPRAY_AND_WAIT = "spray_and_wait"
    ADAPTIVE = "adaptive"


class PositionConfig(StrictModel):
    x: NonNegativeFloat
    y: NonNegativeFloat


class AreaConfig(StrictModel):
    width: PositiveFloat = 1200
    height: PositiveFloat = 700


class NodeConfig(StrictModel):
    node_id: str = Field(min_length=1, pattern=r"^[A-Za-z][A-Za-z0-9_-]*$")
    position: PositionConfig
    communication_range: PositiveFloat = 180
    buffer_capacity_bytes: PositiveInt = 65_536
    state: Literal["healthy", "degraded", "unavailable"] = "healthy"


class MessageConfig(StrictModel):
    message_id: str = Field(min_length=1, pattern=r"^[A-Za-z0-9_-]+$")
    source: str
    destination: str
    size_bytes: PositiveInt
    creation_time: NonNegativeFloat = 0
    ttl_seconds: PositiveFloat = 120

    @model_validator(mode="after")
    def source_and_destination_differ(self) -> MessageConfig:
        if self.source == self.destination:
            raise ValueError("message source and destination must differ")
        return self


class LinkFailureConfig(StrictModel):
    node_a: str
    node_b: str
    start_time: NonNegativeFloat
    end_time: PositiveFloat

    @model_validator(mode="after")
    def valid_interval_and_endpoints(self) -> LinkFailureConfig:
        if self.node_a == self.node_b:
            raise ValueError("a link failure must reference two different nodes")
        if self.end_time <= self.start_time:
            raise ValueError("link-failure end_time must be greater than start_time")
        return self


class AdaptiveWeights(StrictModel):
    connectivity: Probability = 0.35
    proximity: Probability = 0.35
    buffer_availability: Probability = 0.20
    node_state: Probability = 0.10
    minimum_improvement: Probability = 0.05

    @model_validator(mode="after")
    def routing_weights_sum_to_one(self) -> AdaptiveWeights:
        total = self.connectivity + self.proximity + self.buffer_availability + self.node_state
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"adaptive factor weights must sum to 1.0, got {total:g}")
        return self


class ScenarioConfig(StrictModel):
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1)
    seed: int = Field(ge=0)
    duration_seconds: PositiveFloat
    area: AreaConfig = AreaConfig()
    routing_policy: RoutingPolicy = RoutingPolicy.ADAPTIVE
    packet_loss_probability: Probability = 0
    spray_copy_budget: PositiveInt = 4
    adaptive_weights: AdaptiveWeights = AdaptiveWeights()
    nodes: tuple[NodeConfig, ...] = Field(min_length=2)
    messages: tuple[MessageConfig, ...] = Field(min_length=1)
    forced_link_failures: tuple[LinkFailureConfig, ...] = ()

    @model_validator(mode="after")
    def validate_references_and_geometry(self) -> ScenarioConfig:
        node_ids = [node.node_id for node in self.nodes]
        if len(node_ids) != len(set(node_ids)):
            raise ValueError("node IDs must be unique")

        known_nodes = set(node_ids)
        nodes_by_id = {node.node_id: node for node in self.nodes}
        for node in self.nodes:
            if node.position.x > self.area.width or node.position.y > self.area.height:
                raise ValueError(f"node {node.node_id!r} is outside the simulation area")

        message_ids = [message.message_id for message in self.messages]
        if len(message_ids) != len(set(message_ids)):
            raise ValueError("message IDs must be unique")

        for message in self.messages:
            if message.source not in known_nodes or message.destination not in known_nodes:
                raise ValueError(
                    f"message {message.message_id!r} references an unknown source or destination"
                )
            if message.creation_time >= self.duration_seconds:
                raise ValueError(
                    f"message {message.message_id!r} is created after the simulation ends"
                )
            source = nodes_by_id[message.source]
            if message.size_bytes > source.buffer_capacity_bytes:
                raise ValueError(
                    f"message {message.message_id!r} exceeds source buffer capacity"
                )

        for failure in self.forced_link_failures:
            if failure.node_a not in known_nodes or failure.node_b not in known_nodes:
                raise ValueError("link failure references an unknown node")
            if failure.start_time >= self.duration_seconds:
                raise ValueError("link failure starts after the simulation ends")
            if failure.end_time > self.duration_seconds:
                raise ValueError("link failure ends after the simulation ends")

        return self


def load_scenario(path: str | Path) -> ScenarioConfig:
    """Load a trusted project YAML file and validate the complete scenario."""

    scenario_path = Path(path)
    with scenario_path.open("r", encoding="utf-8") as stream:
        raw: Any = yaml.safe_load(stream)
    if not isinstance(raw, dict):
        raise ValueError("scenario YAML must contain a mapping at its root")
    return ScenarioConfig.model_validate(raw)
