import time
from collections import OrderedDict
from typing import Any


class TTLCache:
    """A tiny bounded TTL cache so hot lookups can skip the API."""

    def __init__(self, *, ttl: float, max_size: int = 1024) -> None:
        self.ttl = ttl
        self.max_size = max_size
        self._entries: OrderedDict[int, tuple[float, Any]] = OrderedDict()

    def get(self, key: int) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        set_at, value = entry
        if time.monotonic() - set_at > self.ttl:
            del self._entries[key]
            return None
        return value

    def set(self, key: int, value: Any) -> None:
        self._entries[key] = (time.monotonic(), value)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_size:
            self._entries.popitem(last=False)
