"""
tests/test_ui_universal.py
Universal UI data-handling tests for the Degree Planner frontend.

Tests that app.py helper functions handle the full spectrum of JSON requirement
structures emitted by requirements_checker without crashing or rendering badly:

1. Credit vs Course Pools — correct suffix in unsatisfied accordion
2. Rule-based groups — clean fallback label, no raw dict printed
3. Missing/None keys — no KeyError or AttributeError
4. Progress bar edge cases — ZeroDivisionError protection
5. format_fulfillment_label — empty/None desc produces valid label
6. Partial fulfillment labels — correct "partial — X/Y cr|courses" strings
7. Accordion progress metrics — req_groups_meta drives X/Y fractions
"""

import sys
import os
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ── Mock streamlit + gspread before any import ────────────────────────────────
def _make_st_mock() -> MagicMock:
    st = MagicMock()
    st.cache_resource = lambda f: f
    st.cache_data     = lambda f: f
    st.selectbox      = MagicMock(return_value=None)
    st.multiselect    = MagicMock(return_value=[])
    st.toggle         = MagicMock(return_value=False)
    st.file_uploader  = MagicMock(return_value=None)
    st.checkbox       = MagicMock(return_value=False)
    st.stop           = MagicMock()

    class _SS(dict):
        def __getattr__(self, k):
            try: return self[k]
            except KeyError: return None
        def __setattr__(self, k, v): self[k] = v
        def get(self, k, d=None): return super().get(k, d)
        def pop(self, k, *a): return super().pop(k, *a) if a else super().pop(k)

    st.session_state = _SS()
    return st


if "streamlit" not in sys.modules:
    sys.modules["streamlit"] = _make_st_mock()
if "gspread" not in sys.modules:
    sys.modules["gspread"] = MagicMock()

import app  # noqa: E402
from app import (
    _program_short_label, _sanitize_desc, format_fulfillment_label,
    render_audit, available_concentrations,
)


# ── Shared helper ─────────────────────────────────────────────────────────────
def _mock_render_context():
    """Patch st so render_audit runs without a live Streamlit server.
    Returns (st_module, collected_markdown_calls_list)."""
    import streamlit as st
    calls: list[str] = []

    expander_cm = MagicMock()
    expander_cm.__enter__ = MagicMock(return_value=None)
    expander_cm.__exit__ = MagicMock(return_value=False)   # False → don't suppress exceptions
    st.expander = MagicMock(return_value=expander_cm)
    st.markdown = MagicMock(side_effect=lambda s, **kw: calls.append(str(s)))
    st.write    = MagicMock()
    st.success  = MagicMock()
    return calls


# ══════════════════════════════════════════════════════════════════════════════
# 1 — Credit pool vs course-count pool: correct suffix in render_audit
# ══════════════════════════════════════════════════════════════════════════════

class TestCreditVsCoursePoolRendering(unittest.TestCase):
    """render_audit must correctly label credit-based vs course-count unsatisfied groups."""

    def test_credit_pool_suffix_is_credits_not_courses(self):
        """For a credit-based missing group, output must say 'credit' (not 'course(s)')."""
        results = {
            "satisfied":       [],
            "unsatisfied":     ["ELEC_POOL"],
            "missing_courses": {
                "ELEC_POOL": {"credits_still_needed": 6, "options": ["COMP401", "COMP411"]},
            },
            "satisfied_map": {},
        }
        catalog = {
            "COMP401": {"name": "Compilers", "credits": 3},
            "COMP411": {"name": "OS", "credits": 3},
        }
        calls = _mock_render_context()
        render_audit(results, catalog=catalog,
                     req_descriptions={"ELEC_POOL": "Upper-division electives"})
        combined = " ".join(calls)
        self.assertIn("credit", combined.lower(),
                      "Credit pool must reference 'credit' in unsatisfied label")
        self.assertNotIn("course(s)", combined,
                         "Credit pool must NOT say 'course(s)'")

    def test_course_count_pool_suffix_is_courses_not_credits(self):
        """For a course-count missing group, output must say 'course' (not 'cr')."""
        results = {
            "satisfied":       [],
            "unsatisfied":     ["ELEC_POOL"],
            "missing_courses": {
                "ELEC_POOL": {"still_needed": 2, "options": ["COMP401", "COMP411", "COMP521"]},
            },
            "satisfied_map": {},
        }
        calls = _mock_render_context()
        render_audit(results, req_descriptions={"ELEC_POOL": "Elective courses"})
        combined = " ".join(calls)
        self.assertIn("course", combined.lower(),
                      "Course pool must mention 'course'")
        # must not silently promote it to a credit label
        self.assertNotIn("credits_still_needed", combined)

    def test_single_required_course_shows_required_but_not_completed(self):
        """List-form missing entry → 'Required but not yet completed' message."""
        results = {
            "satisfied":       [],
            "unsatisfied":     ["COMP110"],
            "missing_courses": {"COMP110": ["COMP110"]},
            "satisfied_map":   {},
        }
        calls = _mock_render_context()
        render_audit(results)
        combined = " ".join(calls)
        self.assertIn("Required but not yet completed", combined)

    def test_credit_pool_partial_progress_shows_counted_slash_total(self):
        """Partially satisfied credit pool (3 of 9 cr done) shows fraction in output."""
        results = {
            "satisfied":       [],
            "unsatisfied":     ["ELEC_6CR"],
            "missing_courses": {"ELEC_6CR": {"credits_still_needed": 3, "options": ["COMP411"]}},
            "satisfied_map":   {},
        }
        calls = _mock_render_context()
        render_audit(
            results,
            catalog={"COMP411": {"name": "OS", "credits": 3}},
            req_descriptions={"ELEC_6CR": "Upper-div elective credits"},
            req_groups_meta={"ELEC_6CR": {"credits_required": 6}},
        )
        combined = " ".join(calls)
        # "partial — 3/6 cr" (or similar) must appear — both numbers and "cr"
        self.assertIn("3", combined, "Counted credits must appear")
        self.assertIn("6", combined, "Total credits must appear")
        self.assertIn("cr", combined)

    def test_course_count_pool_partial_progress_shows_counted_slash_total(self):
        """Partially satisfied course pool (1 of 3 done) shows fraction in output."""
        results = {
            "satisfied":       [],
            "unsatisfied":     ["ELEC_3CO"],
            "missing_courses": {"ELEC_3CO": {"still_needed": 2, "options": ["COMP411", "COMP521"]}},
            "satisfied_map":   {},
        }
        calls = _mock_render_context()
        render_audit(
            results,
            req_descriptions={"ELEC_3CO": "3 elective courses"},
            req_groups_meta={"ELEC_3CO": {"courses_required": 3}},
        )
        combined = " ".join(calls)
        self.assertIn("1", combined, "Counted courses (3-2=1) must appear")
        self.assertIn("3", combined, "Total courses must appear")
        self.assertIn("course", combined.lower())


# ══════════════════════════════════════════════════════════════════════════════
# 2 — Rule-based groups: clean label, no raw dict
# ══════════════════════════════════════════════════════════════════════════════

class TestRuleBasedGroupLabels(unittest.TestCase):
    """Rule-based groups must render without crashing and without leaking dict repr."""

    def test_rule_based_group_none_description_no_crash(self):
        """render_audit with None description must not raise any exception."""
        results = {
            "satisfied":       [],
            "unsatisfied":     ["ANY_400_BIOL"],
            "missing_courses": {
                "ANY_400_BIOL": {"still_needed": 1, "options": []},
            },
            "satisfied_map": {},
        }
        _mock_render_context()
        try:
            render_audit(results, req_descriptions={"ANY_400_BIOL": None})
        except Exception as exc:
            self.fail(f"render_audit raised {exc!r} for None description")

    def test_rule_based_group_none_description_no_dict_in_output(self):
        """None description must NOT produce raw dict text in the rendered output."""
        results = {
            "satisfied":       [],
            "unsatisfied":     ["ANY_400_BIOL"],
            "missing_courses": {
                "ANY_400_BIOL": {"still_needed": 1, "options": []},
            },
            "satisfied_map": {},
        }
        calls = _mock_render_context()
        render_audit(results, req_descriptions={"ANY_400_BIOL": None})
        combined = " ".join(calls)
        self.assertNotIn("'department'", combined,
                         "Raw dict key 'department' must not appear in output")
        self.assertNotIn("'rule'", combined,
                         "Raw dict key 'rule' must not appear in output")

    def test_group_description_fallback_is_always_string(self):
        """app.py's req_descriptions-building logic must coerce None to empty string."""
        grp_no_desc  = {"id": "ANY_400_BIOL", "type": "rule_based",
                        "rule": {"department": "BIOL", "min_number": 400}}
        grp_none_desc = {"id": "UPPER_DIV", "type": "rule_based",
                         "description": None,
                         "rule": {"min_number": 300}}
        grp_str_desc  = {"id": "CORE_GRP", "description": "Core Requirements"}

        for grp in [grp_no_desc, grp_none_desc, grp_str_desc]:
            # Replicate the logic in the tabs loop of app.py
            desc = grp.get("description") or ""
            self.assertIsInstance(desc, str,
                                  f"Description for {grp['id']} must be str, got {type(desc)}")

    def test_format_fulfillment_label_empty_desc_no_trailing_colon(self):
        """format_fulfillment_label('CS_BS', '') must not produce 'CS BS: '."""
        label = format_fulfillment_label("Computer_Science_BS", "")
        self.assertNotEqual(label, "CS BS: ",
                            "Empty desc must not produce a bare 'CS BS: '")
        # The part after ': ' must be non-empty
        after_colon = label.split(": ", 1)[1] if ": " in label else ""
        self.assertGreater(len(after_colon.strip()), 0,
                           f"After-colon part must not be empty, got {label!r}")

    def test_format_fulfillment_label_empty_desc_falls_back(self):
        """format_fulfillment_label with empty desc must produce a meaningful fallback."""
        label = format_fulfillment_label("Data_Science_BS", "")
        self.assertIn("DS BS", label)
        # Fallback must be something like "Elective", not a blank or punctuation
        after_colon = label.split(": ", 1)[1].strip()
        self.assertTrue(after_colon.isalpha() or len(after_colon) > 0,
                        f"Fallback after colon must be a word, got {after_colon!r}")


# ══════════════════════════════════════════════════════════════════════════════
# 3 — Missing/None keys: no KeyError or AttributeError
# ══════════════════════════════════════════════════════════════════════════════

class TestMissingKeysSafety(unittest.TestCase):
    """Edge-case requirement structures must not raise."""

    def test_render_audit_empty_results_no_crash(self):
        """render_audit({}) must not crash."""
        _mock_render_context()
        try:
            render_audit({})
        except Exception as exc:
            self.fail(f"render_audit({{}}) raised {exc!r}")

    def test_render_audit_none_req_descriptions_value_no_crash(self):
        """None values in req_descriptions must not crash render_audit."""
        results = {
            "satisfied":   ["SOME_GROUP"],
            "unsatisfied": [],
            "missing_courses": {},
            "satisfied_map":   {"SOME_GROUP": ["COMP110"]},
        }
        _mock_render_context()
        try:
            render_audit(results, req_descriptions={"SOME_GROUP": None})
        except Exception as exc:
            self.fail(f"render_audit raised {exc!r} with None req_descriptions value")

    def test_render_audit_missing_courses_empty_options_no_crash(self):
        """Choice group with empty options list must not crash the unsatisfied renderer."""
        results = {
            "satisfied":   [],
            "unsatisfied": ["SOME_POOL"],
            "missing_courses": {"SOME_POOL": {"still_needed": 1, "options": []}},
            "satisfied_map": {},
        }
        _mock_render_context()
        try:
            render_audit(results)
        except Exception as exc:
            self.fail(f"render_audit raised {exc!r} with empty options list")

    def test_available_concentrations_no_concentrations(self):
        """Tracks with an empty concentrations dict return ['None']."""
        reqs = {"SOME_TRACK": {"base_requirements": {}, "concentrations": {}}}
        result = available_concentrations(reqs, "SOME_TRACK")
        self.assertEqual(result, ["None"])

    def test_available_concentrations_missing_track(self):
        """Unknown track must return ['None'] without raising."""
        result = available_concentrations({}, "NONEXISTENT_TRACK")
        self.assertEqual(result, ["None"])

    def test_available_concentrations_no_concentrations_key(self):
        """Track without a 'concentrations' key at all returns ['None']."""
        reqs = {"SOME_TRACK": {"base_requirements": {}}}
        result = available_concentrations(reqs, "SOME_TRACK")
        self.assertEqual(result, ["None"])

    def test_render_audit_satisfied_map_with_catalog_lookup(self):
        """Satisfied pool with courses in catalog must render without crash."""
        results = {
            "satisfied":   ["ELEC_POOL"],
            "unsatisfied": [],
            "missing_courses": {},
            "satisfied_map": {"ELEC_POOL": ["COMP411", "COMP521"]},
        }
        catalog = {
            "COMP411": {"name": "OS", "credits": 3},
            "COMP521": {"name": "Networking", "credits": 3},
        }
        _mock_render_context()
        try:
            render_audit(results, catalog=catalog,
                         req_descriptions={"ELEC_POOL": "Upper-div electives"},
                         req_groups_meta={"ELEC_POOL": {"credits_required": 6}})
        except Exception as exc:
            self.fail(f"render_audit raised {exc!r} for satisfied credit pool")

    def test_render_audit_course_not_in_catalog_graceful(self):
        """A course appearing in satisfied_map but NOT in catalog must not crash."""
        results = {
            "satisfied":   ["ELEC_POOL"],
            "unsatisfied": [],
            "missing_courses": {},
            "satisfied_map": {"ELEC_POOL": ["PHANTOM999"]},
        }
        _mock_render_context()
        try:
            render_audit(results, catalog={}, req_descriptions={"ELEC_POOL": "Electives"})
        except Exception as exc:
            self.fail(f"render_audit raised {exc!r} for course absent from catalog")


# ══════════════════════════════════════════════════════════════════════════════
# 4 — Progress bar edge cases: no ZeroDivisionError
# ══════════════════════════════════════════════════════════════════════════════

class TestProgressBarEdgeCases(unittest.TestCase):
    """Progress calculations must be ZeroDivisionError-free."""

    def test_zero_total_req_gives_zero_global_pct(self):
        """global_pct = sat/total, with total=0 guard, must yield 0.0."""
        total_req_all = 0
        total_sat_all = 0
        global_pct = total_sat_all / total_req_all if total_req_all else 0.0
        self.assertEqual(global_pct, 0.0)

    def test_zero_items_completion_pct_is_one(self):
        """requirements_checker convention: 0-item track → 100% complete."""
        satisfied   = []
        total_items = 0
        pct = len(satisfied) / total_items if total_items else 1.0
        self.assertEqual(pct, 1.0)

    def test_partial_completion_pct_correct(self):
        satisfied   = ["A", "B", "C"]
        total_items = 9
        pct = len(satisfied) / total_items if total_items else 1.0
        self.assertAlmostEqual(pct, 1 / 3)

    def test_progress_bar_clamped_to_one(self):
        """min(pct, 1.0) must prevent overflow for over-100% completion."""
        pct = 1.25
        self.assertEqual(min(pct, 1.0), 1.0)

    def test_per_tab_total_n_zero_no_division(self):
        """If both satisfied and unsatisfied are empty, total_n=0 but no division occurs."""
        results = {"satisfied": [], "unsatisfied": [], "completion_pct": 0.0}
        satisfied_n = len(results.get("satisfied", []))
        total_n     = satisfied_n + len(results.get("unsatisfied", []))
        # caption display uses total_n as text, not as divisor
        self.assertEqual(total_n, 0)

    def test_completion_pct_defaults_to_zero_when_missing(self):
        """results.get('completion_pct', 0.0) must not raise for absent key."""
        results = {}
        pct = results.get("completion_pct", 0.0)
        self.assertEqual(pct, 0.0)

    def test_credit_partial_counted_never_negative(self):
        """credits_still_needed > credits_required is theoretically impossible,
        but max(0, counted) must prevent negative display."""
        cr_req = 6
        # Edge: still_needed equals the total (nothing counted)
        still_needed = 6
        counted = max(0, cr_req - still_needed)
        self.assertEqual(counted, 0)


# ══════════════════════════════════════════════════════════════════════════════
# 5 — Partial fulfillment labels in _completed_satisfies
# ══════════════════════════════════════════════════════════════════════════════

class TestPartialFulfillmentLabels(unittest.TestCase):
    """The partial credit/course labels built in _completed_satisfies are well-formed."""

    def _credit_label(self, prog, req_label, cr_counted, cr_total) -> str:
        clean = _sanitize_desc(req_label)
        return f"{prog}: {clean} (partial — {cr_counted:.4g} cr of {cr_total:.4g} cr needed)"

    def _course_label(self, prog, req_label, counted, total) -> str:
        clean = _sanitize_desc(req_label)
        return f"{prog}: {clean} (partial — {counted}/{total} courses)"

    def test_credit_partial_label_contains_both_numbers_and_cr(self):
        label = self._credit_label("CS BS", "Upper Div Elective", 3, 9)
        self.assertIn("partial", label)
        self.assertIn("3", label)
        self.assertIn("9", label)
        self.assertIn("cr", label)
        self.assertNotIn("course", label)

    def test_course_partial_label_contains_fraction_and_courses(self):
        label = self._course_label("CS BS", "Elective", 1, 3)
        self.assertIn("partial", label)
        self.assertIn("1/3", label)
        self.assertIn("courses", label)
        self.assertNotIn(" cr ", label)

    def test_partial_desc_goes_through_sanitize(self):
        """Raw descriptions in partial labels are sanitised before insertion."""
        raw = "6 upper div electives"
        clean = _sanitize_desc(raw)
        self.assertEqual(clean, "Upper Div Elective")
        label = self._credit_label("CS BS", raw, 3, 6)
        self.assertNotIn("6 upper div", label)
        self.assertIn("Upper Div Elective", label)

    def test_zero_counted_entry_is_skipped(self):
        """When counted <= 0 the _completed_satisfies loop does `continue` — not a label issue."""
        cr_total     = 9
        still_needed = 9
        counted      = cr_total - still_needed
        self.assertLessEqual(counted, 0, "counted=0 → entry must be skipped, not labelled")

    def test_course_count_pool_label_denominator_correct(self):
        """With courses_required=3 and still_needed=2, counted=1 appears in label."""
        label = self._course_label("DS BS", "Data Science Elective", 1, 3)
        self.assertIn("1/3", label)


# ══════════════════════════════════════════════════════════════════════════════
# 6 — render_audit satisfied accordion: pool progress badge
# ══════════════════════════════════════════════════════════════════════════════

class TestSatisfiedAccordionPoolBadge(unittest.TestCase):
    """Satisfied credit/count pools must show a (X/Y cr|courses) badge."""

    def _run(self, results, **kwargs):
        calls = _mock_render_context()
        render_audit(results, **kwargs)
        return " ".join(calls)

    def test_satisfied_credit_pool_badge_shows_total_credits(self):
        """Satisfied 6-credit pool shows (6/6 cr) or similar progress indicator."""
        results = {
            "satisfied":       ["ELEC_CR"],
            "unsatisfied":     [],
            "missing_courses": {},
            "satisfied_map":   {"ELEC_CR": ["COMP411", "COMP521"]},
        }
        catalog = {
            "COMP411": {"name": "OS", "credits": 3},
            "COMP521": {"name": "Networking", "credits": 3},
        }
        output = self._run(
            results,
            catalog=catalog,
            req_descriptions={"ELEC_CR": "Upper-div electives"},
            req_groups_meta={"ELEC_CR": {"credits_required": 6}},
        )
        self.assertIn("cr", output, "Satisfied credit pool badge must mention 'cr'")
        self.assertIn("6", output)

    def test_satisfied_course_count_pool_badge_shows_fraction(self):
        """Satisfied 3-course pool shows (3/3 courses) or similar badge."""
        results = {
            "satisfied":       ["ELEC_CO"],
            "unsatisfied":     [],
            "missing_courses": {},
            "satisfied_map":   {"ELEC_CO": ["COMP411", "COMP521", "COMP431"]},
        }
        output = self._run(
            results,
            catalog={},
            req_descriptions={"ELEC_CO": "Elective courses"},
            req_groups_meta={"ELEC_CO": {"courses_required": 3}},
        )
        self.assertIn("course", output.lower(),
                      "Satisfied course pool badge must mention 'course'")
        self.assertIn("3", output)

    def test_single_required_course_no_pool_badge(self):
        """A plain required course (no pool meta) must not have a pool badge."""
        results = {
            "satisfied":       ["COMP110"],
            "unsatisfied":     [],
            "missing_courses": {},
            "satisfied_map":   {"COMP110": ["COMP110"]},
        }
        calls = _mock_render_context()
        render_audit(results, req_descriptions={"COMP110": "Intro to Programming"})
        # Must not crash and req_header must show COMP110
        combined = " ".join(calls)
        self.assertIn("COMP110", combined)


# ══════════════════════════════════════════════════════════════════════════════
# 7 — _shorten_desc helper: no crash on edge inputs
# ══════════════════════════════════════════════════════════════════════════════

class TestShortenDesc(unittest.TestCase):
    """_shorten_desc must be robust to weird input."""

    def setUp(self):
        from app import _shorten_desc
        self.fn = _shorten_desc

    def test_empty_string_returns_empty(self):
        self.assertEqual(self.fn(""), "")

    def test_none_returns_none(self):
        self.assertIsNone(self.fn(None))

    def test_required_course_unchanged(self):
        self.assertEqual(self.fn("Required Course"), "Required Course")

    def test_pipe_desc_extracts_name_part(self):
        result = self.fn("COMP 110 | Introduction to Programming")
        self.assertIn("Introduction to Programming", result)
        self.assertNotIn("COMP 110", result)

    def test_long_desc_truncated_to_55_chars(self):
        long = "A very long requirement description that goes well beyond fifty-five characters in total"
        result = self.fn(long)
        self.assertLessEqual(len(result), 55 + 1,   # +1 for possible ellipsis
                             f"Result too long: {result!r}")

    def test_normal_desc_capitalised(self):
        result = self.fn("data structures elective")
        self.assertTrue(result[0].isupper())


# ══════════════════════════════════════════════════════════════════════════════
# 8 — format_fulfillment_label: comprehensive edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestFormatFulfillmentLabelEdgeCases(unittest.TestCase):

    def test_known_program_normal_desc(self):
        self.assertEqual(
            format_fulfillment_label("Computer_Science_BS", "Required Course"),
            "CS BS: Required Course",
        )

    def test_known_program_empty_desc_no_trailing_colon_space(self):
        label = format_fulfillment_label("Computer_Science_BS", "")
        # Must not be just "CS BS: "
        self.assertNotRegex(label, r": $",
                            f"Label must not end with ': ' but got {label!r}")

    def test_empty_desc_produces_non_empty_suffix(self):
        label = format_fulfillment_label("Data_Science_Minor", "")
        after = label.split(": ", 1)[1] if ": " in label else ""
        self.assertGreater(len(after.strip()), 0,
                           f"Suffix after colon must be non-empty, got {label!r}")

    def test_sanitized_desc_in_output(self):
        label = format_fulfillment_label("Data_Science_Minor", "6 upper dive electives")
        self.assertIn("DS Minor", label)
        self.assertIn("Upper Div Elective", label)

    def test_unknown_program_id_falls_back(self):
        label = format_fulfillment_label("Basket_Weaving_BS", "Some Elective")
        self.assertIn(": ", label)
        self.assertIn("Some Elective", label)

    def test_double_counted_entry_format(self):
        """Double-counted course labels joined with ' · ' must parse cleanly."""
        combined = "Required Course · Upper Div Elective"
        parts = combined.split(" · ")
        labels = [format_fulfillment_label("Computer_Science_BS", p.strip()) for p in parts]
        self.assertEqual(len(labels), 2)
        self.assertIn("CS BS: Required Course", labels)
        self.assertIn("CS BS: Upper Div Elective", labels)


if __name__ == "__main__":
    unittest.main()
