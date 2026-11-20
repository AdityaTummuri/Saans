"""A tiny in-memory TTL cache (no extra dependency)."""

from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Awaitable, Callable, Hashable


class TTLCache[V]:
    """Bounded TTL cache. Entries expire `ttl_s` seconds after being stored."""

    def __init__(
        self,
        ttl_s: float,
        max_entries: int = 512,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._ttl = ttl_s
        self._max = max_entries
        self._clock = clock
        self._data: OrderedDict[Hashable, tuple[float, V]] = OrderedDict()

    def get(self, key: Hashable) -> V | None:
        item = self._data.get(key)
        if item is None:
            return None
        stored_at, value = item
        if self._clock() - stored_at >= self._ttl:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    def set(self, key: Hashable, value: V) -> None:
        self._data[key] = (self._clock(), value)
        self._data.move_to_end(key)
        while len(self._data) > self._max:
            self._data.popitem(last=False)

    async def get_or_set(self, key: Hashable, factory: Callable[[], Awaitable[V]]) -> V:
        cached = self.get(key)
        if cached is not None:
            return cached
        value = await factory()
        self.set(key, value)
        return value

    def __len__(self) -> int:
        return len(self._data)
