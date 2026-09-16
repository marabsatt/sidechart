from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import pandas as pd


@dataclass
class RebalanceProposal:
    """
    Draft allocation produced by the supervisor agent before execution.

    The proposal is intentionally advisory: execution still flows through
    risk validation and the paper-trading path.
    """
    target_weights: pd.DataFrame
    rationale: str
    status: str = 'draft'
    generated_at: datetime = field(default_factory=datetime.now)
    source_signals: dict[str, Any] = field(default_factory=dict)
    source_research: str = ''
    actions: list[dict[str, Any]] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation of the proposal."""
        return {
            'status': self.status,
            'generated_at': self.generated_at.isoformat(),
            'target_weights': self.target_weights.to_dict(orient='records'),
            'rationale': self.rationale,
            'source_signals': self.source_signals,
            'source_research': self.source_research,
            'actions': self.actions,
            'assumptions': self.assumptions,
            'risks': self.risks,
        }
