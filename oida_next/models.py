"""Provider-neutral planning, with a deterministic no-key implementation."""

from typing import Protocol

from .protocol import Recipe


class Planner(Protocol):
    def plan(self, goal: str) -> Recipe: ...


class DeterministicPlanner:
    def plan(self, goal: str) -> Recipe:
        lowered = goal.lower()
        if any(word in lowered for word in ("package", "pip", "แพ็กเกจ")):
            return "package_check"
        if any(word in lowered for word in ("artifact", "demo", "workspace", "ทดสอบ")):
            return "workspace_demo"
        if any(word in lowered for word in ("system", "machine", "info", "ระบบ")):
            return "system_info"
        raise ValueError("No safe recipe matches this goal. Select one of the supported workflows.")


MODEL_REGISTRY = [
    {
        "id": "deterministic",
        "provider": "builtin",
        "capabilities": ["recipe-routing"],
        "cost": 0,
        "privacy": "local",
        "available": True,
        "limitations": "No arbitrary natural-language administration or autonomous coding.",
    }
]
