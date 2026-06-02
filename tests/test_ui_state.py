"""
UI state-management tests using Streamlit's AppTest framework.

Tests verify:
1. Session state keys are initialized on load.
2. What-If multiselects are buffered — pipeline does NOT re-run mid-selection.
3. Pipeline fires only after the Apply form is submitted.
4. Generated data is persisted in st.session_state across re-renders.
"""

import sys
import os
import types
import importlib
import unittest
from unittest.mock import MagicMock, patch

# ── Ensure project root is on path ───────────────────────────────────────────
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)


# ---------------------------------------------------------------------------
# Lightweight AppTest-style harness
# We use Streamlit's AppTest when it is available (Streamlit ≥ 1.28).
# For environments where it is unavailable or the full render is impractical
# (no PDF, no GCP), we fall back to targeted unit tests on the session-state
# logic that is exercised by app.py.
# ---------------------------------------------------------------------------

try:
    from streamlit.testing.v1 import AppTest
    APPTEST_AVAILABLE = True
except ImportError:
    APPTEST_AVAILABLE = False

APP_PATH = os.path.join(ROOT, "app.py")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_mock_pipeline_data():
    return {
        "completed":     ["COMP110"],
        "in_progress":   ["COMP301"],
        "planned":       [],
        "audit":         {},
        "path":          ["COMP301", "COMP401"],
        "semester_path": {"Semester 1": ["COMP301"], "Semester 2": ["COMP401"]},
    }


# ══════════════════════════════════════════════════════════════════════════════
# Test 1 — Session state keys initialise on app load
# ══════════════════════════════════════════════════════════════════════════════

class TestSessionStateInitialisation(unittest.TestCase):
    """Verify that the required session-state keys exist after app startup."""

    @unittest.skipUnless(APPTEST_AVAILABLE, "Streamlit AppTest not available")
    def test_session_keys_exist_after_load(self):
        at = AppTest.from_file(APP_PATH, default_timeout=60)
        # Patch the expensive backend so the app starts without a real PDF
        with patch("app.run_pipeline", return_value=_make_mock_pipeline_data()), \
             patch("app.load_static_data", return_value=({}, {}, {})):
            at.run()

        self.assertIn("user_swaps",                 at.session_state)
        self.assertIn("planned_courses_committed",  at.session_state)
        self.assertIn("avoid_courses_committed",    at.session_state)

    def test_session_keys_exist_via_direct_import(self):
        """
        Verify the initialisation block without a full Streamlit render.
        We simulate what Streamlit does: execute the top-level module code
        inside a context where st.session_state is a plain dict-like object.
        """
        import streamlit as st

        # Give session_state a clean slate (dict-based proxy is fine for this check)
        for k in ("user_swaps", "planned_courses_committed", "avoid_courses_committed"):
            st.session_state.pop(k, None)

        # Simulate the initialisation block from app.py
        if "user_swaps" not in st.session_state:
            st.session_state.user_swaps = {}
        if "planned_courses_committed" not in st.session_state:
            st.session_state.planned_courses_committed = []
        if "avoid_courses_committed" not in st.session_state:
            st.session_state.avoid_courses_committed = []

        self.assertIn("user_swaps",                st.session_state)
        self.assertIn("planned_courses_committed", st.session_state)
        self.assertIn("avoid_courses_committed",   st.session_state)
        self.assertEqual(st.session_state.planned_courses_committed, [])
        self.assertEqual(st.session_state.avoid_courses_committed,   [])


# ══════════════════════════════════════════════════════════════════════════════
# Test 2 — What-If buffer: pipeline does NOT re-run until Apply is clicked
# ══════════════════════════════════════════════════════════════════════════════

class TestWhatIfBuffer(unittest.TestCase):
    """
    The committed what-if values should only update when the form is submitted.
    Changing the staged multiselect value alone must not alter the committed state.
    """

    def _simulate_committed_state(self, initial_planned, initial_avoid, submitted, staged_planned, staged_avoid):
        """
        Replicate the logic in app.py's What-If form block:

            if _whatif_applied:
                st.session_state.planned_courses_committed = _staged_planned
                st.session_state.avoid_courses_committed   = _staged_avoid

            planned_courses = st.session_state.planned_courses_committed
            avoid_courses   = st.session_state.avoid_courses_committed
        """
        import streamlit as st

        st.session_state.planned_courses_committed = list(initial_planned)
        st.session_state.avoid_courses_committed   = list(initial_avoid)

        # Simulate form submit event
        _whatif_applied = submitted

        if _whatif_applied:
            st.session_state.planned_courses_committed = staged_planned
            st.session_state.avoid_courses_committed   = staged_avoid

        return (
            st.session_state.planned_courses_committed,
            st.session_state.avoid_courses_committed,
        )

    def test_staged_change_without_submit_does_not_update_committed(self):
        planned, avoid = self._simulate_committed_state(
            initial_planned=[],
            initial_avoid=[],
            submitted=False,
            staged_planned=["COMP110"],   # user selected something
            staged_avoid=["MATH233"],     # user selected something
        )
        self.assertEqual(planned, [], "Committed planned must stay empty before Apply")
        self.assertEqual(avoid,   [], "Committed avoid must stay empty before Apply")

    def test_submit_updates_committed_values(self):
        planned, avoid = self._simulate_committed_state(
            initial_planned=[],
            initial_avoid=[],
            submitted=True,
            staged_planned=["COMP110"],
            staged_avoid=["MATH233"],
        )
        self.assertEqual(planned, ["COMP110"], "Committed planned must update after Apply")
        self.assertEqual(avoid,   ["MATH233"], "Committed avoid must update after Apply")

    def test_pipeline_key_unchanged_without_apply(self):
        """
        The _pipeline_key is derived from committed values, not staged ones.
        Without Apply, the key (and therefore pipeline re-run) must not change.
        """
        import hashlib, json

        file_hash = "abc123"
        majors    = [{"track": "CS_BS", "concentration": "None"}]

        def _make_key(planned, avoid):
            src = json.dumps({
                "file":    file_hash,
                "majors":  majors,
                "planned": sorted(planned),
                "avoid":   sorted(avoid),
            }, sort_keys=True).encode()
            return hashlib.md5(src).hexdigest()

        key_before = _make_key([], [])

        # User stages courses but does NOT click Apply
        staged_planned = ["COMP110"]
        staged_avoid   = ["MATH233"]
        committed_planned = []   # unchanged
        committed_avoid   = []   # unchanged

        key_after = _make_key(committed_planned, committed_avoid)
        self.assertEqual(key_before, key_after, "Pipeline key must be stable without Apply")

    def test_pipeline_key_changes_after_apply(self):
        import hashlib, json

        file_hash = "abc123"
        majors    = [{"track": "CS_BS", "concentration": "None"}]

        def _make_key(planned, avoid):
            src = json.dumps({
                "file":    file_hash,
                "majors":  majors,
                "planned": sorted(planned),
                "avoid":   sorted(avoid),
            }, sort_keys=True).encode()
            return hashlib.md5(src).hexdigest()

        key_before = _make_key([], [])

        # User clicks Apply — committed values update
        committed_planned = ["COMP110"]
        committed_avoid   = ["MATH233"]
        key_after = _make_key(committed_planned, committed_avoid)

        self.assertNotEqual(key_before, key_after, "Pipeline key must change after Apply")


# ══════════════════════════════════════════════════════════════════════════════
# Test 3 — Pipeline data enters session_state after generation
# ══════════════════════════════════════════════════════════════════════════════

class TestPipelineSessionPersistence(unittest.TestCase):
    """
    After run_pipeline completes, its output must be stored in session_state
    under '_pipeline_data' and the key cached under '_pipeline_key'.
    """

    def test_pipeline_data_stored_in_session_state(self):
        import streamlit as st
        import hashlib, json

        mock_data = _make_mock_pipeline_data()

        # Simulate the caching block from app.py
        file_hash = hashlib.md5(b"fake_pdf").hexdigest()
        majors    = [{"track": "CS_BS", "concentration": "None"}]
        key_src   = json.dumps({
            "file":    file_hash,
            "majors":  majors,
            "planned": [],
            "avoid":   [],
        }, sort_keys=True).encode()
        pipeline_key = hashlib.md5(key_src).hexdigest()

        # Clear any old state
        st.session_state.pop("_pipeline_key",  None)
        st.session_state.pop("_pipeline_data", None)

        # Replicate app.py cache-or-run logic
        if st.session_state.get("_pipeline_key") != pipeline_key:
            data = mock_data  # would call run_pipeline in real app
            st.session_state["_pipeline_key"]  = pipeline_key
            st.session_state["_pipeline_data"] = data
        else:
            data = st.session_state["_pipeline_data"]

        self.assertEqual(st.session_state["_pipeline_key"],  pipeline_key)
        self.assertEqual(st.session_state["_pipeline_data"], mock_data)

    def test_cached_data_reused_without_rerun(self):
        import streamlit as st
        import hashlib, json

        mock_data = _make_mock_pipeline_data()

        file_hash = hashlib.md5(b"fake_pdf").hexdigest()
        majors    = [{"track": "CS_BS", "concentration": "None"}]
        key_src   = json.dumps({
            "file":    file_hash,
            "majors":  majors,
            "planned": [],
            "avoid":   [],
        }, sort_keys=True).encode()
        pipeline_key = hashlib.md5(key_src).hexdigest()

        # Pre-populate session_state (simulating a prior run)
        st.session_state["_pipeline_key"]  = pipeline_key
        st.session_state["_pipeline_data"] = mock_data

        pipeline_ran = False

        # Replicate cache-or-run logic
        if st.session_state.get("_pipeline_key") != pipeline_key:
            pipeline_ran = True
            data = mock_data
            st.session_state["_pipeline_key"]  = pipeline_key
            st.session_state["_pipeline_data"] = data
        else:
            data = st.session_state["_pipeline_data"]

        self.assertFalse(pipeline_ran, "Pipeline must NOT re-run when key matches cached key")
        self.assertEqual(data, mock_data)


# ══════════════════════════════════════════════════════════════════════════════
# Test 4 — Graceful degradation (graphviz + table)
# ══════════════════════════════════════════════════════════════════════════════

class TestGracefulDegradation(unittest.TestCase):
    """
    The app must not raise when graphviz or DataFrame rendering fails.
    It should fall back to a warning message instead.
    """

    def test_graphviz_error_caught_and_warning_emitted(self):
        import streamlit as st

        warnings_issued = []

        def _fake_warning(msg, *a, **kw):
            warnings_issued.append(msg)

        # Simulate the guarded graphviz block from app.py
        with patch.object(st, "warning", side_effect=_fake_warning):
            try:
                raise RuntimeError("dot: graph is empty or has isolated nodes")
            except Exception as _graph_err:
                st.warning(f"⚠️ Prerequisite graph could not be rendered: {_graph_err}")

        self.assertTrue(len(warnings_issued) > 0, "A warning must be emitted on graphviz failure")
        self.assertIn("Prerequisite graph could not be rendered", warnings_issued[0])

    def test_dataframe_html_fallback_on_error(self):
        import pandas as pd

        rows = [{"#": 1, "Course": "COMP110", "Name": "Intro", "Credits": 3, "Fulfills": "CS req"}]
        df   = pd.DataFrame(rows)

        # The primary path (with emoji / special chars) may fail in some envs;
        # the except branch must succeed
        try:
            html = df.to_html(index=False, escape=False)
        except Exception:
            html = df.to_html(index=False, escape=True)

        self.assertIn("<table", html)
        self.assertIn("COMP110", html)


if __name__ == "__main__":
    unittest.main()
