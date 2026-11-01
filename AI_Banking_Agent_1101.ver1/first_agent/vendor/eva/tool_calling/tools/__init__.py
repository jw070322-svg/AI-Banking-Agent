"""Built-in Module 6 tools.

The requested 13-tool list is registered without additions or removals. Each
tool is defined once in a domain module and is discoverable through the single
ToolRegistry.
"""

from __future__ import annotations

from typing import Any

from ..services import ToolServices
from . import accounts, analysis, planning, policies, products, transactions


def register_core_tools(registry: Any, services: ToolServices) -> None:
    accounts.register(registry, services)
    analysis.register(registry, services)
    products.register(registry, services)
    policies.register(registry, services)
    planning.register(registry, services)
    transactions.register(registry, services)


__all__ = ["register_core_tools"]
