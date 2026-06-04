"""
tests/test_ui_formatter.py
Unit tests for the presentation-layer label formatter functions in app.py.

Tests:
1. _program_short_label  — acronym/short-name generation for program IDs
2. format_fulfillment_label — quantity stripping, typo fixing, full label format
3. Deduplication          — same sanitized desc within one track appears once
"""

import sys
import os
import unittest
from unittest.mock import MagicMock

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


def _make_st_mock() -> MagicMock:
    """Return a Streamlit mock that lets app.py be imported without a running server."""
    st = MagicMock()
    st.cache_resource = lambda f: f   # passthrough — no caching in test env
    st.cache_data     = lambda f: f
    st.selectbox      = MagicMock(return_value=None)
    st.multiselect    = MagicMock(return_value=[])
    st.toggle         = MagicMock(return_value=False)
    st.file_uploader  = MagicMock(return_value=None)
    st.checkbox       = MagicMock(return_value=False)
    st.stop           = MagicMock()   # no-op so module-level execution completes
    # session_state must support `in` and attribute assignment
    class _SS(dict):
        def __getattr__(self, k):
            try:
                return self[k]
            except KeyError:
                return None
        def __setattr__(self, k, v):
            self[k] = v
        def get(self, k, d=None):  # type: ignore[override]
            return super().get(k, d)
        def pop(self, k, *args):
            return super().pop(k, *args) if args else super().pop(k)
    st.session_state = _SS()
    return st


# ── Install mocks before any app-level import ─────────────────────────────────
if "streamlit" not in sys.modules:
    sys.modules["streamlit"] = _make_st_mock()

if "gspread" not in sys.modules:
    sys.modules["gspread"] = MagicMock()

# Now it is safe to import the formatter helpers from app
import app  # noqa: E402  (import after sys.modules patching is intentional)
from app import _program_short_label, _sanitize_desc, format_fulfillment_label


# ══════════════════════════════════════════════════════════════════════════════
# 1 — Program short-label (acronym generation)
# ══════════════════════════════════════════════════════════════════════════════

class TestProgramShortLabel(unittest.TestCase):
    """_program_short_label converts track IDs to concise display labels."""

    def test_computer_science_bs(self):
        self.assertEqual(_program_short_label("Computer_Science_BS"), "CS BS")

    def test_data_science_minor(self):
        self.assertEqual(_program_short_label("Data_Science_Minor"), "DS Minor")

    def test_unc_gen_ed(self):
        self.assertEqual(_program_short_label("UNC_General_Education"), "Gen Ed")

    def test_data_science_bs(self):
        self.assertEqual(_program_short_label("Data_Science_BS"), "DS BS")

    def test_mathematics_bs(self):
        self.assertEqual(_program_short_label("Mathematics_BS"), "Math BS")

    def test_economics_ba(self):
        self.assertEqual(_program_short_label("Economics_BA"), "Econ BA")

    def test_biology_bs(self):
        self.assertEqual(_program_short_label("Biology_BS"), "Bio BS")

    def test_fallback_returns_something_sensible(self):
        result = _program_short_label("Underwater_Basket_Weaving_BS")
        self.assertTrue(result, "Fallback must return a non-empty string")
        self.assertIn("BS", result)


# ══════════════════════════════════════════════════════════════════════════════
# 2 — Quantity stripping and typo correction
# ══════════════════════════════════════════════════════════════════════════════

class TestSanitizeDesc(unittest.TestCase):
    """_sanitize_desc cleans raw group descriptions for display."""

    def test_digit_prefix_stripped(self):
        self.assertEqual(_sanitize_desc("6 upper div electives"), "Upper Div Elective")

    def test_digit_prefix_four(self):
        self.assertEqual(_sanitize_desc("4 upper div electives"), "Upper Div Elective")

    def test_typo_dive_corrected(self):
        self.assertEqual(_sanitize_desc("6 upper dive electives"), "Upper Div Elective")

    def test_word_number_stripped(self):
        self.assertEqual(_sanitize_desc("Six upper-division electives"), "Upper Div Elective")

    def test_word_number_with_additional(self):
        self.assertEqual(
            _sanitize_desc("Four additional upper-division electives"),
            "Upper Div Elective",
        )

    def test_required_course_unchanged(self):
        self.assertEqual(_sanitize_desc("Required Course"), "Required Course")

    def test_empty_string_unchanged(self):
        self.assertEqual(_sanitize_desc(""), "")

    def test_one_course_paren_stripped(self):
        result = _sanitize_desc("Data and Computational Thinking (one course)")
        self.assertNotIn("(one course)", result)
        self.assertIn("Data and Computational Thinking", result)

    def test_first_year_seminar_paren_stripped(self):
        result = _sanitize_desc("First-Year Seminar (one FY seminar course)")
        self.assertNotIn("(one", result)
        self.assertIn("First-Year Seminar", result)

    def test_quantitative_reasoning_unchanged(self):
        self.assertEqual(_sanitize_desc("Quantitative Reasoning"), "Quantitative Reasoning")

    def test_select_one_colon_stripped(self):
        result = _sanitize_desc("Machine Learning and AI (select one):")
        self.assertEqual(result, "Machine Learning and AI")

    def test_elective_courses_normalised(self):
        result = _sanitize_desc("Two additional elective courses from the list below")
        self.assertNotIn("courses", result.lower())
        self.assertIn("Elective", result)

    def test_capitalised(self):
        result = _sanitize_desc("upper div electives")
        self.assertTrue(result[0].isupper(), "First character must be capitalised")


# ══════════════════════════════════════════════════════════════════════════════
# 3 — Full label format
# ══════════════════════════════════════════════════════════════════════════════

class TestFormatFulfillmentLabel(unittest.TestCase):
    """format_fulfillment_label returns 'Short Program: Clean Desc'."""

    def test_cs_bs_required_course(self):
        self.assertEqual(
            format_fulfillment_label("Computer_Science_BS", "Required Course"),
            "CS BS: Required Course",
        )

    def test_ds_minor_upper_div_elective(self):
        result = format_fulfillment_label("Data_Science_Minor", "6 upper div electives")
        self.assertEqual(result, "DS Minor: Upper Div Elective")

    def test_ds_minor_typo_dive(self):
        result = format_fulfillment_label("Data_Science_Minor", "6 upper dive electives")
        self.assertEqual(result, "DS Minor: Upper Div Elective")

    def test_gen_ed_quant(self):
        result = format_fulfillment_label("UNC_General_Education", "Quantitative Reasoning")
        self.assertEqual(result, "Gen Ed: Quantitative Reasoning")

    def test_label_format_is_prog_colon_desc(self):
        result = format_fulfillment_label("Computer_Science_BS", "Some requirement")
        self.assertIn(": ", result)
        prog, desc = result.split(": ", 1)
        self.assertEqual(prog, "CS BS")
        self.assertEqual(desc, "Some requirement")


# ══════════════════════════════════════════════════════════════════════════════
# 4 — Deduplication
# ══════════════════════════════════════════════════════════════════════════════

class TestDeduplication(unittest.TestCase):
    """
    When a fulfillment_map entry has duplicate sanitized descriptions (same
    track), the building logic should produce each unique label only once.
    """

    @staticmethod
    def _build_labels(program_id: str, combined_desc: str) -> list[str]:
        """Simulate the _course_fulfillment / _path_dc_raw injection in app.py."""
        seen: set[str] = set()
        result: list[str] = []
        for raw_part in combined_desc.split(" · "):
            label = format_fulfillment_label(program_id, raw_part.strip())
            if label not in seen:
                seen.add(label)
                result.append(label)
        return result

    def test_identical_descs_deduplicated(self):
        labels = self._build_labels(
            "Data_Science_Minor",
            "6 upper div electives · 4 upper div electives",
        )
        self.assertEqual(labels, ["DS Minor: Upper Div Elective"])

    def test_typo_variant_deduplicated(self):
        labels = self._build_labels(
            "Data_Science_Minor",
            "6 upper dive electives · 6 upper div electives",
        )
        self.assertEqual(labels, ["DS Minor: Upper Div Elective"])

    def test_different_descs_preserved(self):
        labels = self._build_labels(
            "Computer_Science_BS",
            "Required Course · Machine Learning and AI",
        )
        self.assertEqual(len(labels), 2)
        self.assertIn("CS BS: Required Course", labels)
        self.assertIn("CS BS: Machine Learning and AI", labels)

    def test_single_desc_no_change(self):
        labels = self._build_labels("UNC_General_Education", "Quantitative Reasoning")
        self.assertEqual(labels, ["Gen Ed: Quantitative Reasoning"])


if __name__ == "__main__":
    unittest.main()
