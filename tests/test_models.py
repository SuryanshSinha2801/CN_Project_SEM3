from dataclasses import FrozenInstanceError

import pytest

from blackout.models import (
    DuplicateMessageError,
    ExpiredMessageError,
    InsufficientBufferCapacityError,
    Message,
    MessageBuffer,
    MessageState,
    Node,
    NodeState,
    Position,
    Velocity,
)


def make_message(
    message_id: str = "m1",
    *,
    copy_id: str = "original",
    size_bytes: int = 100,
    creation_time: float = 0,
    ttl_seconds: float = 10,
) -> Message:
    return Message(
        message_id=message_id,
        copy_id=copy_id,
        source="A",
        destination="D",
        creation_time=creation_time,
        size_bytes=size_bytes,
        ttl_seconds=ttl_seconds,
    )


def test_message_identity_is_immutable_and_ttl_is_deterministic() -> None:
    message = make_message()

    assert message.identity == ("m1", "original")
    assert message.expires_at == 10
    assert message.remaining_ttl(4) == 6
    assert not message.is_expired(9.999)
    assert message.is_expired(10)
    with pytest.raises(FrozenInstanceError):
        message.message_id = "changed"  # type: ignore[misc]


def test_message_tracks_hops_delivery_and_visited_nodes() -> None:
    message = make_message()
    original_hash = hash(message)
    message.mark_buffered("A", 0)
    message.record_hop("A", "B", 2)
    message.record_hop("B", "D", 5)
    message.mark_delivered(5, "D")

    assert message.state is MessageState.DELIVERED
    assert message.delivery_time == 5
    assert message.hop_count == 2
    assert message.visited_nodes == frozenset({"A", "B", "D"})
    assert message.last_custody_holder == "D"
    assert hash(message) == original_hash


def test_message_rejects_invalid_lifecycle_changes() -> None:
    message = make_message()

    with pytest.raises(ValueError, match="destination"):
        message.mark_delivered(2, "B")
    with pytest.raises(ValueError, match="current custody holder"):
        message.record_hop("B", "C", 2)
    with pytest.raises(ValueError, match="TTL has expired"):
        message.mark_buffered("A", 10)


def test_message_rejects_fractional_byte_size() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        make_message(size_bytes=1.5)  # type: ignore[arg-type]


def test_buffer_accounts_for_bytes_and_preserves_order() -> None:
    buffer = MessageBuffer(capacity_bytes=250, owner_node_id="A")
    first = make_message("m1", size_bytes=100)
    second = make_message("m2", size_bytes=150)

    buffer.put(first, 0)
    buffer.put(second, 0)

    assert len(buffer) == 2
    assert buffer.items() == (first, second)
    assert buffer.used_bytes == 250
    assert buffer.free_bytes == 0
    assert buffer.utilization == 1
    assert first.state is MessageState.BUFFERED

    assert buffer.remove("m1") is first
    assert buffer.used_bytes == 150


def test_buffer_rejects_duplicate_copy_and_overflow() -> None:
    buffer = MessageBuffer(capacity_bytes=150)
    buffer.put(make_message("m1", size_bytes=100), 0)

    with pytest.raises(DuplicateMessageError):
        buffer.put(make_message("m1", size_bytes=100), 0)
    with pytest.raises(InsufficientBufferCapacityError):
        buffer.put(make_message("m2", size_bytes=100), 0)


def test_buffer_allows_distinct_routing_copies() -> None:
    buffer = MessageBuffer(capacity_bytes=200)

    buffer.put(make_message(copy_id="copy-1"), 0)
    buffer.put(make_message(copy_id="copy-2"), 0)

    assert buffer.contains("m1", "copy-1")
    assert buffer.contains("m1", "copy-2")
    assert buffer.contains("m1")


def test_buffer_expires_items_and_reclaims_capacity() -> None:
    buffer = MessageBuffer(capacity_bytes=100)
    expired = make_message("old", size_bytes=100, ttl_seconds=5)
    replacement = make_message("new", size_bytes=100, creation_time=5)
    buffer.put(expired, 0)

    buffer.put(replacement, 5)

    assert expired.state is MessageState.EXPIRED
    assert buffer.items() == (replacement,)
    assert buffer.used_bytes == 100


def test_buffer_rejects_an_expired_incoming_message() -> None:
    buffer = MessageBuffer(capacity_bytes=100)

    with pytest.raises(ExpiredMessageError):
        buffer.put(make_message(ttl_seconds=5), 5)


def test_buffer_capacity_must_be_an_integer() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        MessageBuffer(capacity_bytes=1.5)  # type: ignore[arg-type]


def test_node_owns_buffer_and_exposes_routing_state() -> None:
    node = Node(
        "A",
        Position(10, 20),
        communication_range=50,
        buffer_capacity_bytes=100,
        state=NodeState.DEGRADED,
    )
    message = make_message(size_bytes=100)

    node.store_message(message, 0)

    assert node.buffer.contains("m1")
    assert node.buffer.free_bytes == 0
    assert node.counters.messages_received == 1
    assert node.is_available
    assert node.state_score == 0.5


def test_node_movement_range_and_contacts() -> None:
    first = Node(
        "A",
        Position(0, 0),
        communication_range=10,
        buffer_capacity_bytes=100,
        velocity=Velocity(3, 4),
    )
    second = Node("B", Position(10, 0), communication_range=10, buffer_capacity_bytes=100)

    assert first.in_range_of(second)
    assert first.move_for(1) == Position(3, 4)
    first.start_contact("B", 1)
    assert first.current_neighbors == frozenset({"B"})

    contact = first.end_contact("B", 3)

    assert contact.started_at == 1
    assert contact.ended_at == 3
    assert first.current_neighbors == frozenset()
    assert first.contact_history == (contact,)
