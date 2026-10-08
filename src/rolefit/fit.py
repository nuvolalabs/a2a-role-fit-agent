"""Pure, deterministic role-fit scoring.

No network calls, no LLM: every number below is reproducible from the job
description text plus the profile in profile.json, which is what makes the
skill testable and honest.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

PROFILE_PATH = Path(__file__).with_name("profile.json")

MUST_HAVE = re.compile(
    r"\b(must|required|requirement|mandatory|essential|minimum)\b", re.I)
NICE_TO_HAVE = re.compile(
    r"\b(nice to have|preferred|plus|bonus|desirable|a plus)\b", re.I)

# Weight of one unclaimed (gap) capability relative to one matched capability.
GAP_WEIGHT = 4
MUST_HAVE_GAP_WEIGHT = 8


def load_profile(path: str | Path | None = None) -> dict:
    """Load the candidate profile (defaults to the packaged profile.json)."""
    p = Path(path) if path else PROFILE_PATH
    return json.loads(p.read_text(encoding="utf-8"))


def _mentions(text: str, aliases: list[str]) -> list[str]:
    """Aliases present in `text`, matched on word boundaries and case-insensitively."""
    hits = []
    for alias in aliases:
        pattern = r"(?<![A-Za-z0-9+#.])" + re.escape(alias) + r"(?![A-Za-z0-9+#])"
        if re.search(pattern, text, re.I):
            hits.append(alias)
    return hits


def _is_must_have(text: str, alias: str, window: int = 160) -> bool:
    """True when an alias sits in the same sentence-ish window as a must-have word."""
    pattern = r"(?<![A-Za-z0-9+#.])" + re.escape(alias) + r"(?![A-Za-z0-9+#])"
    for m in re.finditer(pattern, text, re.I):
        lo, hi = max(0, m.start() - window), min(len(text), m.end() + window)
        if MUST_HAVE.search(text[lo:hi]):
            return True
    return False


def score_role_fit(jd_text: str, profile: dict | None = None) -> dict:
    """Score a job description against the profile.

    Returns a result dict with the matched capabilities, the unclaimed gaps,
    a 0-100 score and a verdict. Deterministic: same input, same output.
    """
    if profile is None:
        profile = load_profile()
    text = jd_text or ""

    matched, matched_weight = [], 0
    for skill in profile["skills"]:
        hits = _mentions(text, skill["aliases"])
        if not hits:
            continue
        matched_weight += skill["weight"]
        matched.append({
            "id": skill["id"],
            "label": skill["label"],
            "matched_on": hits,
            "weight": skill["weight"],
            "evidence": skill["evidence"],
        })
    matched.sort(key=lambda s: (-s["weight"], s["label"]))

    gaps, gap_penalty = [], 0
    for gap in profile.get("gaps", []):
        hits = _mentions(text, gap["aliases"])
        if not hits:
            continue
        must = _is_must_have(text, hits[0])
        gaps.append({"id": gap["id"], "label": gap["label"],
                     "matched_on": hits, "must_have": must})
        gap_penalty += MUST_HAVE_GAP_WEIGHT if must else GAP_WEIGHT

    denominator = matched_weight + gap_penalty
    score = 0 if denominator == 0 else round(100 * matched_weight / denominator)

    if matched_weight == 0:
        verdict = "no_signal"
    elif score >= 80:
        verdict = "strong"
    elif score >= 60:
        verdict = "promising"
    elif score >= 40:
        verdict = "partial"
    else:
        verdict = "weak"

    proven = {s["id"] for s in matched}
    projects = [p for p in profile.get("projects", []) if p["proves"] in proven]

    return {
        "candidate": profile["name"],
        "target_role": profile["target_role"],
        "score": score,
        "verdict": verdict,
        "matched": matched,
        "gaps": gaps,
        "relevant_projects": projects,
        "signal": {
            "matched_capabilities": len(matched),
            "unclaimed_capabilities": len(gaps),
            "must_have_gaps": [g["label"] for g in gaps if g["must_have"]],
        },
    }


def _bar(score: int, width: int = 20) -> str:
    filled = round(width * score / 100)
    return "#" * filled + "." * (width - filled)


def render_fit_report(result: dict) -> str:
    """Render a score_role_fit result as a compact plain-text report."""
    lines = [
        f"ROLE FIT: {result['candidate']} -> {result['target_role']}",
        f"score {result['score']}/100 [{_bar(result['score'])}] verdict={result['verdict']}",
        "",
        f"Matched capabilities ({result['signal']['matched_capabilities']}):",
    ]
    if result["matched"]:
        for s in result["matched"]:
            lines.append(f"  - {s['label']} (matched: {', '.join(s['matched_on'])})")
            lines.append(f"      evidence: {s['evidence']}")
    else:
        lines.append("  (none - the posting uses vocabulary outside this profile)")

    lines += ["", f"Unclaimed requirements ({result['signal']['unclaimed_capabilities']}):"]
    if result["gaps"]:
        for g in result["gaps"]:
            flag = " [MUST-HAVE]" if g["must_have"] else ""
            lines.append(f"  - {g['label']}{flag}")
    else:
        lines.append("  (none detected)")

    if result["relevant_projects"]:
        lines += ["", "Portfolio proof points:"]
        for p in result["relevant_projects"]:
            lines.append(f"  - {p['id']}: {p['summary']}")

    if result["verdict"] == "no_signal":
        lines += ["", "Note: no known capability appeared in this text. Either the "
                      "posting is outside scope, or it needs manual review."]
    return "\n".join(lines)


def portfolio_summary(profile: dict | None = None) -> str:
    """Human-readable inventory of the shipped portfolio."""
    if profile is None:
        profile = load_profile()
    lines = [f"{profile['name']} - portfolio ({profile['target_role']})", ""]
    for p in profile.get("projects", []):
        tests = f" ({p['tests']} tests)" if p.get("tests") else ""
        lines.append(f"- {p['id']}{tests}: {p['summary']}")
    lines += ["", f"GitHub: https://github.com/nuvolalabs"]
    return "\n".join(lines)
