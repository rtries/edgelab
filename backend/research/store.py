"""Experiment registry: filesystem-backed, searchable, loses nothing.

Layout:
  root/
    index.json                 summary rows for fast search/list
    experiments/{id}.json      full experiment payloads
    notes/{id}.json            research notes
    registry.json              optimization-count registry (pipeline)

Search supports the terminal's registry view: free text over id /
strategy / tags / symbols, exact filters (strategy, symbol, tag,
engine_version, dataset fingerprint prefix), and metric expressions like
"sharpe>1.5" or "max_drawdown>=-0.2" evaluated against indexed metrics.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_EXPR = re.compile(r"^\s*([a-z_]+)\s*(>=|<=|>|<|=)\s*(-?\d+(?:\.\d+)?)\s*$")

INDEXED_METRICS = [
    "sharpe", "sortino", "max_drawdown", "profit_factor", "expectancy",
    "win_rate", "n_trades", "exposure",
]


@dataclass(slots=True)
class ExperimentStore:
    root: Path

    def __post_init__(self) -> None:
        self.root = Path(self.root)
        (self.root / "experiments").mkdir(parents=True, exist_ok=True)
        (self.root / "notes").mkdir(parents=True, exist_ok=True)

    # ── internals ─────────────────────────────────────────────────────
    def _index_path(self) -> Path:
        return self.root / "index.json"

    def _load_index(self) -> list[dict]:
        path = self._index_path()
        return json.loads(path.read_text()) if path.exists() else []

    def _save_index(self, rows: list[dict]) -> None:
        self._index_path().write_text(json.dumps(rows, indent=1))

    @staticmethod
    def _summary(exp: dict) -> dict:
        dev = exp.get("development", {}).get("metrics", {})
        wf = exp.get("walkforward", {}).get("aggregate", {})
        mc = exp.get("montecarlo", {}).get("cis", {})
        mc_lower = None
        for method in mc.values():
            lower = method.get("sharpe", {}).get("q0.025")
            if lower is not None:
                mc_lower = lower if mc_lower is None else min(mc_lower, lower)
        return {
            "id": exp["id"],
            "created_at": exp["created_at"],
            "strategy": exp["strategy"],
            "symbols": exp["symbols"],
            "timeframe": exp["timeframe"],
            "engine_version": exp["engine_version"],
            "dataset_fingerprint": exp["dataset"]["fingerprint"],
            "tags": exp.get("tags", []),
            "selected_params": exp.get("selected_params", {}),
            "confidence": exp.get("confidence", {}).get("level"),
            "n_warnings": len(exp.get("warnings", [])),
            "metrics": {k: dev.get(k) for k in INDEXED_METRICS},
            "val_sharpe_mean": wf.get("sharpe_mean"),
            "mc_sharpe_lower": mc_lower,
            "final_sharpe": exp.get("final_test", {}).get("sharpe"),
        }

    # ── writes ────────────────────────────────────────────────────────
    def save(self, exp: dict) -> str:
        exp_id = exp["id"]
        (self.root / "experiments" / f"{exp_id}.json").write_text(
            json.dumps(exp, indent=1)
        )
        rows = [r for r in self._load_index() if r["id"] != exp_id]
        rows.append(self._summary(exp))
        rows.sort(key=lambda r: r["created_at"], reverse=True)
        self._save_index(rows)
        return exp_id

    # ── reads ─────────────────────────────────────────────────────────
    def get(self, exp_id: str) -> dict:
        path = self.root / "experiments" / f"{exp_id}.json"
        if not path.exists():
            raise KeyError(f"no experiment {exp_id}")
        return json.loads(path.read_text())

    def list(self) -> list[dict]:
        return self._load_index()

    def search(
        self,
        text: str | None = None,
        strategy: str | None = None,
        symbol: str | None = None,
        tag: str | None = None,
        engine_version: str | None = None,
        fingerprint: str | None = None,
        confidence: str | None = None,
        filters: list[str] | None = None,
    ) -> list[dict]:
        rows = self._load_index()

        def matches(row: dict) -> bool:
            if text:
                haystack = " ".join(
                    [row["id"], row["strategy"], *row.get("tags", []),
                     *row.get("symbols", [])]
                ).lower()
                if text.lower() not in haystack:
                    return False
            if strategy and row["strategy"].lower() != strategy.lower():
                return False
            if symbol and symbol.upper() not in [s.upper() for s in row["symbols"]]:
                return False
            if tag and tag.lower() not in [t.lower() for t in row.get("tags", [])]:
                return False
            if engine_version and row["engine_version"] != engine_version:
                return False
            if fingerprint and not row["dataset_fingerprint"].startswith(fingerprint):
                return False
            if confidence and row.get("confidence") != confidence:
                return False
            for expr in filters or []:
                m = _EXPR.match(expr)
                if not m:
                    raise ValueError(
                        f"bad filter '{expr}': expected e.g. sharpe>1.5"
                    )
                name, op, raw = m.groups()
                target = float(raw)
                sources = {**(row.get("metrics") or {}),
                           "val_sharpe_mean": row.get("val_sharpe_mean"),
                           "mc_sharpe_lower": row.get("mc_sharpe_lower"),
                           "final_sharpe": row.get("final_sharpe"),
                           "n_warnings": row.get("n_warnings")}
                value = sources.get(name)
                if value is None:
                    return False
                ok = {
                    ">": value > target, ">=": value >= target,
                    "<": value < target, "<=": value <= target,
                    "=": value == target,
                }[op]
                if not ok:
                    return False
            return True

        return [r for r in rows if matches(r)]

    # ── notes ─────────────────────────────────────────────────────────
    def add_note(self, title: str, body: str, tags: list[str] | None = None) -> dict:
        note_id = datetime.now(UTC).strftime("%Y%m%d%H%M%S%f")
        note = {
            "id": note_id,
            "created_at": datetime.now(UTC).isoformat(),
            "title": title,
            "body": body,
            "tags": sorted(tags or []),
        }
        (self.root / "notes" / f"{note_id}.json").write_text(json.dumps(note, indent=1))
        return note

    def notes(self) -> list[dict]:
        out = [
            json.loads(p.read_text())
            for p in sorted((self.root / "notes").glob("*.json"), reverse=True)
        ]
        return out

    def delete_note(self, note_id: str) -> bool:
        path = self.root / "notes" / f"{note_id}.json"
        if path.exists():
            path.unlink()
            return True
        return False
