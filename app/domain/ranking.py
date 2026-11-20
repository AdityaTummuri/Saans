"""Impact Ladder: rank actions by vulnerability-weighted dose avoided per unit of effort."""

from __future__ import annotations

from app.domain import constants as c
from app.domain.models import ActionKind, BudgetTier, LedgerEntry, MemberDelta


def build_entry(
    *,
    entry_id: str,
    kind: ActionKind,
    subject: str,
    effort_tier: int,
    deltas: list[MemberDelta],
    weights: dict[str, float],
    co2_avoided_kg: float = 0.0,
    pm25_avoided_g: float = 0.0,
    tradeoff: bool = False,
    details: dict[str, str | float] | None = None,
) -> LedgerEntry:
    """Assemble a ledger entry and its aggregates from per-member dose changes."""
    before = sum(d.dose_before_ug for d in deltas)
    avoided = sum(d.avoided_ug for d in deltas)
    weighted = sum(weights[d.member_id] * d.avoided_ug for d in deltas)
    return LedgerEntry(
        id=entry_id,
        kind=kind,
        subject=subject,
        effort_tier=effort_tier,
        members=deltas,
        avoided_ug=avoided,
        weighted_avoided_ug=weighted,
        pct_change=100 * avoided / before if before > 0 else 0.0,
        cigarettes_avoided=sum(d.cigarettes_avoided for d in deltas),
        co2_avoided_kg=co2_avoided_kg,
        pm25_avoided_g=pm25_avoided_g,
        score=impact_score(weighted, effort_tier),
        tradeoff=tradeoff,
        details=details or {},
    )


def impact_score(weighted_avoided_ug: float, effort_tier: int) -> float:
    """score = sum_m(w_m * avoided_m) / effort_tier."""
    return weighted_avoided_ug / effort_tier


def affordable(entry: LedgerEntry, budget: BudgetTier) -> bool:
    """Purchases are filtered out for the low-budget tier."""
    return budget != BudgetTier.LOW or entry.effort_tier <= c.LOW_BUDGET_MAX_TIER


def rank_actions(entries: list[LedgerEntry], budget: BudgetTier) -> list[LedgerEntry]:
    """Filter by budget and sort by score, then CO2 avoided, then id for stable output."""
    kept = [e for e in entries if affordable(e, budget)]
    return sorted(kept, key=lambda e: (-e.score, -e.co2_avoided_kg, e.id))
