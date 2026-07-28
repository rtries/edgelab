"""Typed strategy parameters."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Param:
    name: str
    type: str                       # "int" | "float" | "bool" | "str"
    default: object
    min: float | None = None
    max: float | None = None
    step: float | None = None
    description: str = ""

    def coerce(self, value: object) -> object:
        caster = {"int": int, "float": float, "bool": bool, "str": str}[self.type]
        try:
            v = caster(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"param '{self.name}': cannot cast {value!r} to {self.type}") from exc
        if self.min is not None and v < self.min:
            raise ValueError(f"param '{self.name}': {v} < min {self.min}")
        if self.max is not None and v > self.max:
            raise ValueError(f"param '{self.name}': {v} > max {self.max}")
        return v


def resolve_params(spec: list[Param], overrides: dict | None = None) -> dict:
    """Defaults + validated overrides. Unknown override names are errors —
    a typo'd parameter silently using its default is how research lies."""
    overrides = overrides or {}
    names = {p.name for p in spec}
    unknown = set(overrides) - names
    if unknown:
        raise ValueError(f"unknown parameters: {sorted(unknown)}")
    out = {}
    for p in spec:
        out[p.name] = p.coerce(overrides[p.name]) if p.name in overrides else p.coerce(p.default)
    return out
