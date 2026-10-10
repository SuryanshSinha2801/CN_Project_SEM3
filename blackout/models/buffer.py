"""Finite byte-capacity storage for delay-tolerant messages."""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Iterator

from blackout.models.message import Message


class MessageBufferError(Exception):
    """Base class for expected buffer admission failures."""


class DuplicateMessageError(MessageBufferError):
    """Raised when the same message copy is already buffered."""


class InsufficientBufferCapacityError(MessageBufferError):
    """Raised when an incoming message cannot fit without eviction."""


class ExpiredMessageError(MessageBufferError):
    """Raised when an incoming message has reached its TTL."""


class MessageBuffer:
    """Insertion-ordered message storage with capacity measured in bytes.

    Version one rejects overflow instead of evicting an existing message. Expired items
    are removed before each insertion so they never consume usable capacity indefinitely.
    """

    def __init__(self, capacity_bytes: int, owner_node_id: str | None = None) -> None:
        if (
            not isinstance(capacity_bytes, int)
            or isinstance(capacity_bytes, bool)
            or capacity_bytes <= 0
        ):
            raise ValueError("buffer capacity must be a positive integer")
        if owner_node_id == "":
            raise ValueError("owner node ID must not be empty")
        self._capacity_bytes = capacity_bytes
        self._owner_node_id = owner_node_id
        self._messages: OrderedDict[tuple[str, str], Message] = OrderedDict()
        self._used_bytes = 0

    @property
    def capacity_bytes(self) -> int:
        return self._capacity_bytes

    @property
    def used_bytes(self) -> int:
        return self._used_bytes

    @property
    def free_bytes(self) -> int:
        return self._capacity_bytes - self._used_bytes

    @property
    def utilization(self) -> float:
        return self._used_bytes / self._capacity_bytes

    def __len__(self) -> int:
        return len(self._messages)

    def __iter__(self) -> Iterator[Message]:
        return iter(self._messages.values())

    def contains(self, message_id: str, copy_id: str | None = None) -> bool:
        if copy_id is not None:
            return (message_id, copy_id) in self._messages
        return any(key_message_id == message_id for key_message_id, _ in self._messages)

    def get(self, message_id: str, copy_id: str = "original") -> Message:
        return self._messages[(message_id, copy_id)]

    def can_accept(self, message: Message, at_time: float) -> bool:
        """Check admission after logically reclaiming expired stored items."""

        if message.is_terminal or message.is_expired(at_time):
            return False
        active_items = {
            identity: item
            for identity, item in self._messages.items()
            if not item.is_expired(at_time)
        }
        if message.identity in active_items:
            return False
        active_bytes = sum(item.size_bytes for item in active_items.values())
        return active_bytes + message.size_bytes <= self._capacity_bytes

    def put(self, message: Message, at_time: float) -> None:
        """Store a message copy or raise a specific admission error."""

        self.expire(at_time)
        if message.is_terminal or message.is_expired(at_time):
            raise ExpiredMessageError(f"message copy {message.identity!r} is not active")
        if message.identity in self._messages:
            raise DuplicateMessageError(f"message copy {message.identity!r} is already buffered")
        if message.size_bytes > self.free_bytes:
            raise InsufficientBufferCapacityError(
                f"message needs {message.size_bytes} bytes but only {self.free_bytes} are free"
            )

        self._messages[message.identity] = message
        self._used_bytes += message.size_bytes
        if self._owner_node_id is not None:
            message.mark_buffered(self._owner_node_id, at_time)

    def remove(self, message_id: str, copy_id: str = "original") -> Message:
        message = self._messages.pop((message_id, copy_id))
        self._used_bytes -= message.size_bytes
        return message

    def expire(self, at_time: float) -> tuple[Message, ...]:
        """Remove and mark every item whose TTL is reached, preserving buffer order."""

        expired: list[Message] = []
        for identity, message in tuple(self._messages.items()):
            if not message.is_terminal and message.is_expired(at_time):
                self._messages.pop(identity)
                self._used_bytes -= message.size_bytes
                message.mark_expired(at_time)
                expired.append(message)
        return tuple(expired)

    def items(self) -> tuple[Message, ...]:
        return tuple(self._messages.values())
