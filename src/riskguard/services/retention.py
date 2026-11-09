"""Periodic in-memory retention cleanup."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from typing import Protocol


class ExpiringStore(Protocol):
    def purge_expired(self) -> int:
        ...


class RetentionSweeper:
    """Purge expired in-memory records even when their IDs are not accessed."""

    def __init__(self, stores: Iterable[ExpiringStore], *, interval_seconds: int = 60) -> None:
        if not 1 <= interval_seconds <= 3600:
            raise ValueError("interval_seconds must be between 1 and 3600")
        self._stores = tuple(stores)
        self.interval_seconds = interval_seconds

    def purge_once(self) -> dict[str, int]:
        return {
            type(store).__name__: store.purge_expired()
            for store in self._stores
        }

    async def run_forever(self, stop_event: asyncio.Event) -> None:
        while not stop_event.is_set():
            self.purge_once()
            try:
                await asyncio.wait_for(
                    stop_event.wait(),
                    timeout=self.interval_seconds,
                )
            except TimeoutError:
                continue
