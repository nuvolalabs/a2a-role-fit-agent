"""Unit tests for the deterministic role-fit scoring logic."""

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from rolefit.fit import (  # noqa: E402
    load_profile,
    portfolio_summary,
    render_fit_report,
    score_role_fit,
)

STRONG_JD = """Applied GenAI Engineer
Must have: Python, RAG, vector databases and agentic orchestration.
Nice to have: FastAPI, MCP, observability, guardrails.
"""

GAPPY_JD = """Staff LLM Engineer
Required: Python and RAG experience, plus LangChain and Kubernetes.
"""

UNRELATED = "We are hiring a forklift operator for a warehouse in Ohio."


class TestScoring(unittest.TestCase):
    def test_deterministic(self):
        a = score_role_fit(STRONG_JD)
        b = score_role_fit(STRONG_JD)
        self.assertEqual(a, b)

    def test_strong_match_scores_high(self):
        res = score_role_fit(STRONG_JD)
        self.assertEqual(res["verdict"], "strong")
        self.assertGreaterEqual(res["score"], 80)
        self.assertFalse(res["gaps"])

    def test_no_signal_on_unrelated_text(self):
        res = score_role_fit(UNRELATED)
        self.assertEqual(res["verdict"], "no_signal")
        self.assertEqual(res["score"], 0)
        self.assertEqual(res["matched"], [])

    def test_empty_input_scores_zero(self):
        self.assertEqual(score_role_fit("")["score"], 0)
        self.assertEqual(score_role_fit(None)["verdict"], "no_signal")

    def test_must_have_gaps_are_flagged(self):
        res = score_role_fit(GAPPY_JD)
        labels = [g["label"] for g in res["gaps"]]
        self.assertIn("LangChain / LangGraph", labels)
        self.assertIn("Kubernetes", labels)
        self.assertTrue(all(g["must_have"] for g in res["gaps"]))
        self.assertIn("LangChain / LangGraph", res["signal"]["must_have_gaps"])

    def test_lower_score_when_gaps_present(self):
        clean = score_role_fit("Must have Python, RAG and agentic orchestration.")
        gappy = score_role_fit("Must have Python, RAG, agentic orchestration "
                               "and LangChain and Kubernetes.")
        self.assertLess(gappy["score"], clean["score"])

    def test_matches_carry_evidence(self):
        for skill in score_role_fit(STRONG_JD)["matched"]:
            self.assertTrue(skill["evidence"], skill["id"])
            self.assertTrue(skill["matched_on"])

    def test_report_renders_score_and_verdict(self):
        res = score_role_fit(STRONG_JD)
        report = render_fit_report(res)
        self.assertIn(f"{res['score']}/100", report)
        self.assertIn(res["verdict"], report)

    def test_report_handles_no_signal(self):
        self.assertIn("no known capability", render_fit_report(score_role_fit(UNRELATED)))


class TestProfileIntegrity(unittest.TestCase):
    """Guards against the profile contradicting itself."""

    def test_gaps_are_not_also_strengths(self):
        profile = load_profile()
        skill_aliases = {a.lower() for s in profile["skills"] for a in s["aliases"]}
        overlap = sorted(
            a.lower() for g in profile["gaps"] for a in g["aliases"]
            if a.lower() in skill_aliases
        )
        self.assertEqual(overlap, [],
                         f"alias appears as both a strength and a gap: {overlap}")

    def test_required_fields_present(self):
        profile = load_profile()
        for s in profile["skills"]:
            for key in ("id", "label", "aliases", "weight", "evidence"):
                self.assertIn(key, s, s.get("id"))
            self.assertGreater(s["weight"], 0)
        for p in profile["projects"]:
            self.assertIn("proves", p)

    def test_portfolio_lists_every_project(self):
        profile = load_profile()
        report = portfolio_summary(profile)
        for p in profile["projects"]:
            self.assertIn(p["id"], report)

    def test_profile_file_is_valid_json_on_disk(self):
        raw = (ROOT / "src" / "rolefit" / "profile.json").read_text(encoding="utf-8")
        self.assertIn("skills", json.loads(raw))


if __name__ == "__main__":
    unittest.main(verbosity=2)
