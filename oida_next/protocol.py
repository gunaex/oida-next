"""Version 1 wire contracts and immutable action plans."""

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Recipe = Literal["system_info", "workspace_demo", "package_check"]
TERMINAL = {"SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"}


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Goal(StrictModel):
    goal: str = Field(min_length=1, max_length=2000)
    target: str = Field(min_length=1, max_length=100)
    recipe: Recipe | None = None
    timeout: int = Field(default=30, ge=1, le=120)
    idempotency_key: str = Field(min_length=8, max_length=100)


class Registration(StrictModel):
    name: str = Field(min_length=1, max_length=80, pattern=r"^[\w .-]+$")
    public_key: str = Field(min_length=40, max_length=100)
    capabilities: dict[str, str | int | float | bool] = Field(default_factory=dict, max_length=40)


class Heartbeat(StrictModel):
    capabilities: dict[str, str | int | float | bool] = Field(default_factory=dict, max_length=40)


class Approval(StrictModel):
    action_hash: str
    approve: bool


class Progress(StrictModel):
    lease: str
    sequence: int = Field(ge=0)
    output: str = Field(max_length=8000)


class Result(StrictModel):
    lease: str
    state: Literal["SUCCEEDED", "FAILED", "CANCELLED", "TIMED_OUT"]
    output: str = Field(max_length=16000)
    evidence: str = Field(max_length=64000)
    checksum: str = Field(pattern=r"^[a-f0-9]{64}$")
    exit_code: int


def canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def digest(value: object) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def action_plan(recipe: Recipe, target: str, timeout: int) -> dict:
    return {
        "protocol": "oida.v1",
        "recipe": recipe,
        "target": target,
        "timeout": timeout,
        "risk": "MEDIUM" if recipe == "package_check" else "LOW",
        "permissions": ["isolated_workspace", "fixed_recipe_only"],
        "required_capabilities": ["python", "linux"],
        "executor": "python-isolated",
        "arguments": [],
        "environment_references": [],
        "retry_policy": "never automatically repeat started execution",
        "success_criteria": "zero exit code and verified evidence checksum",
        "rollback": "Only disposable workspace is changed; preserve evidence for review.",
    }
