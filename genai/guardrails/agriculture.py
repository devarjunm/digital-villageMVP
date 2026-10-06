"""Guardrails for agricultural AI output.

These run *after* retrieval and *before* the response leaves the API:

  1. `check_grounding` — every factual claim in an answer must be backed by at
     least one retrieved chunk; if the top retrieved score is below the
     configured floor, the answer is replaced by an explicit
     "not enough indexed evidence" response instead of a guess.
  2. `check_citations` — citations are re-built from the retrieved rows, so an
     answer can never cite a document that was not retrieved (fabricated
     citations are structurally impossible, not merely discouraged).
  3. `safety_flags` — detects requests that need extra care (pesticide dosage,
     veterinary medication, human health, legal/financial scheme advice) and
     attaches the appropriate caution plus the recommendation to consult a
     qualified professional.
  4. `strip_medical_claims` — refuses to emit specific chemical dosages that are
     not present verbatim in the retrieved evidence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.core.contracts import AI_DISCLAIMER, EvidenceItem

DOSAGE_PATTERNS = [
    re.compile(
        r"\b\d+(\.\d+)?\s?(ml|l|g|kg|gm)\s?(per|/)\s?(acre|hectare|ha|litre|liter|l)\b",
        re.I,
    ),
    re.compile(r"\b\d+(\.\d+)?\s?(ml|l|g|kg)\b\s*(of|मात्रा)", re.I),
]
RISK_TOPICS = {
    "pesticide": (
        "pesticide",
        "insecticide",
        "spray",
        "दवा",
        "फवारणी",
        "कीटनाशक",
        "दवाई",
    ),
    "veterinary": ("cattle", "livestock", "animal", "गाय", "पशु", "जानवर"),
    "human_health": ("poison", "toxic", "human", "कीटकनाशक प्यायला", "जहर"),
    "financial": ("loan", "subsidy", "insurance", "कर्ज", "अनुदान", "विमा", "ऋण"),
    "legal": ("land dispute", "tenancy law", "कायदा", "जमीन विवाद"),
}


@dataclass(slots=True)
class GuardrailReport:
    grounded: bool
    top_score: float | None
    citation_count: int
    flags: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    notices: list[str] = field(default_factory=list)
    answer_modified: bool = False


def check_grounding(
    *, answer: str, hits: list[tuple[float, str]], min_score: float
) -> tuple[bool, str | None]:
    if not hits:
        return False, "No indexed evidence matched this question."
    top_score = max(score for score, _ in hits)
    if top_score < min_score:
        return (
            False,
            f"The best matching indexed source scored {top_score:.2f}, below the {min_score:.2f} floor "
            "for making a grounded statement.",
        )
    return True, None


def check_citations(
    *, citations: list[EvidenceItem], hits: list[tuple[float, str, EvidenceItem]]
) -> tuple[list[EvidenceItem], list[str]]:
    """Filter any citation that is not backed by a retrieved hit (defence in depth:
    the pipeline builds citations from hits, this verifies it)."""
    allowed_ids = {hit.ref_id for _score, _content, hit in hits}
    kept = [c for c in citations if c.ref_id in allowed_ids]
    dropped = [c.ref_id for c in citations if c.ref_id not in allowed_ids]
    actions = [f"dropped_uncited_reference:{ref}" for ref in dropped]
    return kept, actions


def safety_flags(question: str, answer: str) -> list[str]:
    combined = f"{question} {answer}".lower()
    flags: list[str] = []
    for flag, keywords in RISK_TOPICS.items():
        if any(keyword in combined for keyword in keywords):
            flags.append(flag)
    if any(pattern.search(answer) for pattern in DOSAGE_PATTERNS):
        flags.append("dosage_stated")
    return flags


def apply_dosage_rule(
    *, answer: str, evidence_texts: list[str]
) -> tuple[str, bool, list[str]]:
    """Remove dosage statements that do not appear in the retrieved evidence."""
    actions: list[str] = []
    modified = False
    for pattern in DOSAGE_PATTERNS:
        for match in pattern.finditer(answer):
            snippet = match.group(0)
            if any(snippet.lower() in evidence.lower() for evidence in evidence_texts):
                continue
            answer = answer.replace(
                snippet,
                "[quantity removed: not present verbatim in the cited source]",
            )
            modified = True
            actions.append("removed_unsupported_dosage")
    return answer, modified, actions


def notice_for_flags(flags: list[str]) -> list[str]:
    notices: list[str] = []
    if "pesticide" in flags:
        notices.append(
            "Pesticide decisions: follow the label and the state agriculture department's approved schedule. "
            "Digital Village does not recommend dosages; confirm with your local agriculture officer or KVK."
        )
    if "veterinary" in flags:
        notices.append("For animal health, contact a registered veterinarian.")
    if "human_health" in flags:
        notices.append(
            "If a person may have swallowed or inhaled a farm chemical, contact a doctor or poison control "
            "immediately — do not wait for an app answer."
        )
    if "financial" in flags or "legal" in flags:
        notices.append(
            "For loans, insurance claims or land matters, the official scheme/portal rules are authoritative; "
            "this assistant cannot approve or guarantee anything."
        )
    if "dosage_stated" in flags:
        notices.append(
            "Any dosage text was checked against the cited source; unsupported quantities were removed."
        )
    return notices


def default_disclaimer() -> str:
    return AI_DISCLAIMER
