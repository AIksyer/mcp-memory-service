"""Plugin context — what a plugin receives at registration."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

HookName = Literal[
    "on_store", "on_delete", "on_retrieve", "on_consolidate", "before_store"
]

# Hook signatures
# on_store(memory_dict: dict) -> None
# on_delete(content_hash: str) -> None
# on_retrieve(query: str, results: list[dict]) -> list[dict]  (can rerank)
# on_consolidate(report: dict) -> None
# before_store(memory_dict: dict) -> dict | None  (can modify tags/metadata before storage)
HookFn = Callable[..., Awaitable[Any]]


@dataclass
class PluginContext:
    """Context passed to plugin register() functions.

    Provides access to storage and service, plus a method to subscribe to hooks.
    """

    storage: Any  # SqliteVecMemoryStorage (avoid import cycle)
    service: Any  # MemoryService (avoid import cycle)
    _hooks: dict[HookName, list[HookFn]] = field(default_factory=dict)

    def on(self, hook: HookName, fn: HookFn) -> None:
        """Subscribe to a lifecycle hook.

        Args:
            hook: One of on_store, on_delete, on_retrieve, on_consolidate, before_store
            fn: Async callable to invoke when the hook fires
        """
        self._hooks.setdefault(hook, []).append(fn)
