"""
tests/test_exhaustive_backend.py
V1 Launch — Exhaustive Backend Gauntlet

Covers four attack vectors:
  1. All-Majors Matrix  — every track key, no crash
  2. All-Combos Matrix  — Double Major / Major+Minor / Major+2 Minors, ≤30 s
  3. Persona Matrix     — Freshman / Transfer / Senior / Chaos Student
  4. Exception Hunter   — malformed inputs, graceful failure

Loads real JSON data. The locked algorithm is NEVER mutated.
"""

import copy
import json
import os
import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.planner.requirements_checker import (
    check_requirements,
    generate_slots_and_candidates,
)
from src.planner.path_generator import solve_optimal_path

# ── Load real data once ────────────────────────────────────────────────────────
_DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

with open(os.path.join(_DATA_DIR, "course_catalog.json")) as _f:
    CATALOG = json.load(_f)

with open(os.path.join(_DATA_DIR, "degree_requirements.json")) as _f:
    REQUIREMENTS = json.load(_f)

_REAL_TIME = time.time


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _make_fast_time():
    """Patch time.time so the ILS exits after one check (greedy-only, fast)."""
    calls = [0]

    def _fast():
        calls[0] += 1
        t = _REAL_TIME()
        return t if calls[0] == 1 else t + 10.0

    return _fast


def _run_solver(majors, catalog=None, requirements=None,
                completed=None, avoid=None,
                remaining_semesters=8, fast_ils=False):
    cat = catalog if catalog is not None else CATALOG
    req = requirements if requirements is not None else REQUIREMENTS

    slots, cc, cl, mb, bl = generate_slots_and_candidates(
        requirements=req,
        catalog=cat,
        majors_to_check=majors,
        completed_courses=list(completed) if completed is not None else [],
        avoid_courses=list(avoid) if avoid is not None else [],
    )

    if fast_ils:
        fast_fn = _make_fast_time()
        with patch("time.time", side_effect=fast_fn):
            path, slot_map = solve_optimal_path(
                slots=slots, canon_catalog=cc, credit_ledger=cl,
                macro_bindings=mb, blacklist=bl,
                remaining_semesters=remaining_semesters,
            )
    else:
        path, slot_map = solve_optimal_path(
            slots=slots, canon_catalog=cc, credit_ledger=cl,
            macro_bindings=mb, blacklist=bl,
            remaining_semesters=remaining_semesters,
        )

    return path, slot_map, slots


def _first_concentration(track_id: str) -> str:
    concs = list(REQUIREMENTS.get(track_id, {}).get("concentrations", {}).keys())
    return concs[0] if concs else "None"


# ── Persona course sets ────────────────────────────────────────────────────────

# Verified to exist in catalog; sum ≈ 59 credit hours
_TRANSFER_COURSES = [
    "COMP110", "COMP210", "MATH231", "MATH232",
    "ENGL105", "ECON101", "BIOL101", "PSYC101",
    "HIST126", "POLI130", "CHEM101", "PHYS114",
    "AAAD231", "ENEC202", "ASTR101", "PHIL101",
    "SOCI101", "DRAM115",
]

# Transfer + upper-division CS/Math courses; total ≈ 105 credit hours
_SENIOR_COURSES = _TRANSFER_COURSES + [
    "COMP301", "COMP311", "COMP401", "COMP410",
    "COMP421", "COMP455", "COMP475", "COMP496",
    "MATH233", "MATH381", "MATH383", "DATA110",
    "ECON410", "BIOL252", "CHEM261",
]

# Completely unrelated humanities/language courses — satisfy almost no CS reqs
_CHAOS_COURSES = [c for c in [
    "HIST126", "DRAM115", "COMM140", "PHIL101",
    "SOCI101", "ARAB101", "JAPN101", "PORT101",
    "MUSC91", "RELI95",
] if c in CATALOG][:8]

_CS_MAJOR   = {"track": "Computer_Science_BS",  "concentration": "None"}
_DS_BS      = {"track": "Data_Science_BS",       "concentration": "None"}
_DS_MINOR   = {"track": "Data_Science_Minor",    "concentration": "None"}
_STATS_MIN  = {"track": "Statistics_and_Analytics_Minor", "concentration": "None"}
_ECON_MINOR = {"track": "Economics_Minor",       "concentration": "None"}


# ══════════════════════════════════════════════════════════════════════════════
# Vector 1 — All-Majors Matrix
# ══════════════════════════════════════════════════════════════════════════════

class TestAllMajorsMatrix(unittest.TestCase):
    """
    Every track in degree_requirements.json must run through the full
    check_requirements + solver pipeline without raising KeyError,
    IndexError, AttributeError, or any unhandled exception.
    """

    def _audit_one_track(self, track_id: str):
        conc = _first_concentration(track_id)
        majors = [{"track": track_id, "concentration": conc}]

        # --- check_requirements audit ---
        result = check_requirements(
            REQUIREMENTS, CATALOG,
            completed=[],
            track_id=track_id,
            concentration_id=conc,
        )
        self.assertIsInstance(result, dict,
            f"{track_id}: check_requirements returned non-dict")
        self.assertIn("satisfied", result,
            f"{track_id}: 'satisfied' key missing from audit result")

        # --- full solver pipeline ---
        t0 = _REAL_TIME()
        path, slot_map, _ = _run_solver(majors, fast_ils=True)
        elapsed = _REAL_TIME() - t0

        self.assertIsNotNone(path,     f"{track_id}: path is None")
        self.assertIsInstance(path, list, f"{track_id}: path not a list")
        self.assertIsInstance(slot_map, dict, f"{track_id}: slot_map not a dict")
        self.assertLess(elapsed, 6.0,
            f"{track_id}: greedy solve took {elapsed:.2f}s (>6 s limit)")

    def test_all_tracks_no_crash(self):
        """All tracks pass audit + solver without error."""
        all_tracks = sorted(REQUIREMENTS.keys())
        failures = []

        for track_id in all_tracks:
            try:
                self._audit_one_track(track_id)
            except (KeyError, IndexError, AttributeError, TypeError) as exc:
                failures.append(f"{track_id}: {type(exc).__name__}: {exc}")
            except AssertionError as exc:
                failures.append(str(exc))
            except Exception as exc:
                failures.append(f"{track_id}: UNHANDLED {type(exc).__name__}: {exc}")

        if failures:
            self.fail(
                f"{len(failures)}/{len(all_tracks)} tracks crashed:\n"
                + "\n".join(failures[:20])
            )

    def test_no_track_returns_none_path(self):
        """Solver path must never be None for any track."""
        nones = []
        for track_id in sorted(REQUIREMENTS.keys()):
            conc = _first_concentration(track_id)
            try:
                path, _, _ = _run_solver(
                    [{"track": track_id, "concentration": conc}], fast_ils=True
                )
                if path is None:
                    nones.append(track_id)
            except Exception:
                pass  # crash failures are caught by test_all_tracks_no_crash

        self.assertEqual(nones, [],
            f"Tracks returning None path: {nones}")

    def test_all_tracks_check_requirements_returns_dict(self):
        """check_requirements must return a dict with expected keys for every track."""
        EXPECTED_KEYS = {"satisfied", "unsatisfied", "missing_courses",
                         "courses_used", "completion_pct", "satisfied_map"}
        failures = []
        for track_id in sorted(REQUIREMENTS.keys()):
            conc = _first_concentration(track_id)
            try:
                result = check_requirements(
                    REQUIREMENTS, CATALOG, [],
                    track_id=track_id, concentration_id=conc,
                )
                missing_keys = EXPECTED_KEYS - set(result.keys())
                if missing_keys:
                    failures.append(f"{track_id}: missing keys {missing_keys}")
            except Exception as exc:
                failures.append(f"{track_id}: {type(exc).__name__}: {exc}")

        if failures:
            self.fail("check_requirements key failures:\n" + "\n".join(failures[:20]))


# ══════════════════════════════════════════════════════════════════════════════
# Vector 2 — All-Combos Matrix
# ══════════════════════════════════════════════════════════════════════════════

class TestAllCombosMatrix(unittest.TestCase):
    """
    Extreme-valid multi-program combinations resolve without crash
    and within the 30-second UX timeout.
    """

    _TIMEOUT = 30.0

    def _run_timed(self, majors, label, completed=None):
        t0 = _REAL_TIME()
        path, slot_map, slots = _run_solver(majors, completed=completed or [])
        elapsed = _REAL_TIME() - t0
        self.assertIsInstance(path, list,
            f"{label}: path is not a list")
        self.assertIsInstance(slot_map, dict,
            f"{label}: slot_map is not a dict")
        self.assertLess(elapsed, self._TIMEOUT,
            f"{label}: solver took {elapsed:.1f}s (>{self._TIMEOUT}s UX limit)")
        return path, elapsed

    def test_double_major_cs_ds(self):
        """Double major: CS_BS + DS_BS resolves within 30 s."""
        path, elapsed = self._run_timed(
            [_CS_MAJOR, _DS_BS],
            label="CS_BS + DS_BS",
        )
        self.assertGreater(len(path), 0, "Double major path must not be empty")

    def test_double_major_cs_math(self):
        """Double major: CS_BS + Mathematics_BS resolves within 30 s."""
        path, elapsed = self._run_timed(
            [_CS_MAJOR, {"track": "Mathematics_BS", "concentration": "None"}],
            label="CS_BS + Mathematics_BS",
        )
        self.assertGreater(len(path), 0)

    def test_major_plus_minor(self):
        """Major + Minor: CS_BS + DS_Minor resolves within 30 s."""
        path, elapsed = self._run_timed(
            [_CS_MAJOR, _DS_MINOR],
            label="CS_BS + DS_Minor",
        )
        self.assertGreater(len(path), 0)

    def test_major_plus_two_minors(self):
        """Major + 2 Minors: CS_BS + DS_Minor + Stats_Minor resolves within 30 s."""
        path, elapsed = self._run_timed(
            [_CS_MAJOR, _DS_MINOR, _STATS_MIN],
            label="CS_BS + DS_Minor + Stats_Minor",
        )
        self.assertGreater(len(path), 0)

    def test_triple_program_cs_ds_econ(self):
        """Triple: CS_BS + DS_BS + Econ_Minor resolves within 30 s."""
        path, elapsed = self._run_timed(
            [_CS_MAJOR, _DS_BS, _ECON_MINOR],
            label="CS_BS + DS_BS + Econ_Minor",
        )
        self.assertGreater(len(path), 0)

    def test_double_major_path_shorter_than_sum(self):
        """Combined double major path is shorter than the sum of individual paths."""
        p_cs,  _, _ = _run_solver([_CS_MAJOR], fast_ils=True)
        p_ds,  _, _ = _run_solver([_DS_BS],    fast_ils=True)
        p_both, _, _ = _run_solver([_CS_MAJOR, _DS_BS], fast_ils=True)

        self.assertLess(
            len(p_both), len(p_cs) + len(p_ds),
            f"Combined ({len(p_both)}) should be < sum ({len(p_cs)} + {len(p_ds)})"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Vector 3 — Persona Matrix
# ══════════════════════════════════════════════════════════════════════════════

class TestPersonaMatrix(unittest.TestCase):
    """
    Four real student archetypes for CS_BS + DS_Minor + UNC_General_Education.
    Asserts: solver completes, path is a list, remaining courses are non-negative,
    and the system never hallucinates requirements it already satisfied.
    """

    _PROGRAMS = [
        {"track": "Computer_Science_BS",  "concentration": "None"},
        {"track": "Data_Science_Minor",   "concentration": "None"},
        {"track": "UNC_General_Education","concentration": "None"},
    ]

    def _completed_credits(self, courses):
        return sum(CATALOG.get(c, {}).get("credits", 3) for c in courses)

    def _run_persona(self, completed, label):
        result = {}
        for m in self._PROGRAMS:
            result[m["track"]] = check_requirements(
                REQUIREMENTS, CATALOG, completed,
                track_id=m["track"], concentration_id=m["concentration"],
            )

        path, slot_map, _ = _run_solver(self._PROGRAMS, completed=completed)

        self.assertIsInstance(path, list,         f"{label}: path not a list")
        self.assertIsNotNone(path,                f"{label}: path is None")
        self.assertIsInstance(slot_map, dict,     f"{label}: slot_map not a dict")

        for track_id, audit_result in result.items():
            self.assertIsInstance(audit_result, dict,
                f"{label} / {track_id}: check_requirements returned non-dict")
            pct = audit_result.get("completion_pct", 0.0)
            self.assertGreaterEqual(pct, 0.0,
                f"{label} / {track_id}: completion_pct < 0")
            self.assertLessEqual(pct, 1.0,
                f"{label} / {track_id}: completion_pct > 1.0 (hallucination?)")

        return path, result

    # ── Freshman ────────────────────────────────────────────────────────────

    def test_freshman_zero_credits(self):
        """Freshman: 0 credits assumed — full path, completion_pct near 0."""
        path, results = self._run_persona([], label="Freshman")
        # CS path must have content (there are many requirements to satisfy)
        cs_pct = results["Computer_Science_BS"].get("completion_pct", 0.0)
        self.assertLess(cs_pct, 0.1,
            f"Freshman CS completion_pct {cs_pct:.1%} suspiciously high (>10%)")
        self.assertGreater(len(path), 5,
            "Freshman must have significant remaining courses")

    def test_freshman_path_courses_exist_in_catalog(self):
        """All courses recommended for a Freshman exist in the catalog."""
        path, _ = self._run_persona([], label="Freshman-catalog-check")
        missing = [c for c in path if c not in CATALOG]
        self.assertEqual(missing, [],
            f"Freshman path contains courses not in catalog: {missing}")

    # ── Transfer Student ────────────────────────────────────────────────────

    def test_transfer_student_60_credits(self):
        """Transfer Student (~59 cr): shorter path than Freshman, pct > 0."""
        transfer_valid = [c for c in _TRANSFER_COURSES if c in CATALOG]
        transfer_cr    = self._completed_credits(transfer_valid)

        path_fresh,    _ = self._run_persona([],            label="Transfer-fresh-baseline")
        path_transfer, r = self._run_persona(transfer_valid, label="Transfer")

        cs_pct = r["Computer_Science_BS"].get("completion_pct", 0.0)
        self.assertGreater(cs_pct, 0.0,
            f"Transfer pct is 0 despite {transfer_cr:.0f} credits completed")
        self.assertLessEqual(len(path_transfer), len(path_fresh),
            f"Transfer path ({len(path_transfer)}) longer than Freshman path ({len(path_fresh)})")

    def test_transfer_no_phantom_requirements(self):
        """Transfer: no completed course appears in the recommended path (would be a dup)."""
        transfer_valid = [c for c in _TRANSFER_COURSES if c in CATALOG]
        path, _ = self._run_persona(transfer_valid, label="Transfer-no-phantom")
        completed_set = set(transfer_valid)
        phantoms = [c for c in path if c in completed_set]
        self.assertEqual(phantoms, [],
            f"Solver recommended already-completed courses: {phantoms}")

    # ── Senior ──────────────────────────────────────────────────────────────

    def test_senior_105_credits(self):
        """Senior (~105 cr): very few remaining courses, high CS completion pct."""
        senior_valid = [c for c in _SENIOR_COURSES if c in CATALOG]
        senior_cr    = self._completed_credits(senior_valid)

        path, r = self._run_persona(senior_valid, label="Senior")

        cs_pct = r["Computer_Science_BS"].get("completion_pct", 0.0)
        self.assertGreater(cs_pct, 0.3,
            f"Senior ({senior_cr:.0f} cr) CS pct {cs_pct:.1%} too low (expected >30%)")
        # Senior should have a shorter remaining path than Transfer
        transfer_valid = [c for c in _TRANSFER_COURSES if c in CATALOG]
        path_transfer, _ = self._run_persona(transfer_valid, label="Senior-transfer-baseline")
        self.assertLessEqual(len(path), len(path_transfer),
            f"Senior path ({len(path)}) longer than Transfer path ({len(path_transfer)})")

    def test_senior_no_phantom_courses(self):
        """Senior: no already-completed course appears in recommended path."""
        senior_valid = [c for c in _SENIOR_COURSES if c in CATALOG]
        path, _ = self._run_persona(senior_valid, label="Senior-no-phantom")
        completed_set = set(senior_valid)
        phantoms = [c for c in path if c in completed_set]
        self.assertEqual(phantoms, [],
            f"Senior path contains already-completed courses: {phantoms}")

    # ── Chaos Student ────────────────────────────────────────────────────────

    def test_chaos_student_unrelated_courses(self):
        """Chaos Student (15 random humanities courses): CS pct ≈ 0, solver still runs."""
        chaos_valid = [c for c in _CHAOS_COURSES if c in CATALOG]
        path, r = self._run_persona(chaos_valid, label="Chaos")

        cs_pct = r["Computer_Science_BS"].get("completion_pct", 0.0)
        self.assertLess(cs_pct, 0.1,
            f"Chaos student CS pct {cs_pct:.1%} suspiciously high (humanities don't count)")
        self.assertIsInstance(path, list, "Chaos path must be a list")

    def test_chaos_student_path_is_non_empty(self):
        """Chaos Student with no relevant credits still gets a full recommended path."""
        chaos_valid = [c for c in _CHAOS_COURSES if c in CATALOG]
        path, _ = self._run_persona(chaos_valid, label="Chaos-non-empty")
        self.assertGreater(len(path), 5,
            "Chaos student must still have many remaining requirements to satisfy")


# ══════════════════════════════════════════════════════════════════════════════
# Vector 4 — Exception Hunter
# ══════════════════════════════════════════════════════════════════════════════

class TestExceptionHunter(unittest.TestCase):
    """
    Inject malformed data. Assert the system fails gracefully:
    - No raw IndexError / KeyError / AttributeError from deep within the engine
    - Non-existent track IDs return empty/safe results (never crash)
    - Wrong types raise known exceptions, not silent corruption
    """

    # ── Non-existent major IDs ───────────────────────────────────────────────

    def test_nonexistent_track_check_requirements_returns_empty(self):
        """Non-existent track_id returns a safe empty result dict."""
        result = check_requirements(
            REQUIREMENTS, CATALOG, [],
            track_id="FAKE_MAJOR_THAT_DOES_NOT_EXIST",
            concentration_id="None",
        )
        self.assertIsInstance(result, dict)
        self.assertEqual(result.get("satisfied", []), [],
            "Non-existent track should have empty satisfied list")

    def test_nonexistent_track_solver_returns_empty_path(self):
        """Non-existent track_id in majors_to_check produces an empty-or-list path."""
        majors = [{"track": "BOGUS_TRACK_XYZ", "concentration": "None"}]
        try:
            slots, cc, cl, mb, bl = generate_slots_and_candidates(
                requirements=REQUIREMENTS,
                catalog=CATALOG,
                majors_to_check=majors,
                completed_courses=[],
                avoid_courses=[],
            )
            path, slot_map = solve_optimal_path(
                slots=slots, canon_catalog=cc, credit_ledger=cl,
                macro_bindings=mb, blacklist=bl, remaining_semesters=8,
            )
            self.assertIsInstance(path, list)
        except (KeyError, IndexError, AttributeError) as exc:
            self.fail(f"Non-existent track caused raw engine crash: {type(exc).__name__}: {exc}")

    # ── String instead of list for completed_courses ─────────────────────────

    def test_string_completed_courses_no_raw_crash(self):
        """
        Passing a string (e.g. 'COMP110') instead of a list must not cause
        IndexError, KeyError, or AttributeError. A TypeError or ValueError is
        acceptable (known bad-input boundary); a deep engine crash is not.
        """
        raised_type = None
        try:
            result = check_requirements(
                REQUIREMENTS, CATALOG,
                "COMP110",   # string — should be a list
                track_id="Computer_Science_BS",
                concentration_id="None",
            )
            # If no exception: it iterated chars, returned some dict — that's OK
            self.assertIsInstance(result, dict)
        except (TypeError, ValueError):
            pass  # expected boundary failures
        except (KeyError, IndexError, AttributeError) as exc:
            self.fail(
                f"String completed_courses caused a raw engine crash "
                f"({type(exc).__name__}: {exc})"
            )

    def test_none_completed_courses_no_raw_crash(self):
        """
        Passing None for completed_courses must not bubble up an unexpected
        exception type. TypeError from set(None) is acceptable; IndexError is not.
        """
        try:
            # Wrap in list() as the app does (via `list(completed or [])`)
            result = check_requirements(
                REQUIREMENTS, CATALOG,
                None,   # None — should be a list
                track_id="Computer_Science_BS",
                concentration_id="None",
            )
            self.assertIsInstance(result, dict)
        except TypeError:
            pass  # set(None) → TypeError is the expected boundary signal
        except (KeyError, IndexError, AttributeError) as exc:
            self.fail(
                f"None completed_courses caused a raw engine crash "
                f"({type(exc).__name__}: {exc})"
            )

    # ── Corrupt / zero-length slot list ─────────────────────────────────────

    def test_empty_slots_returns_empty_path(self):
        """solve_optimal_path with empty slots must return ([], {}) without crashing."""
        path, slot_map = solve_optimal_path(
            slots=[], canon_catalog={}, credit_ledger={},
            macro_bindings={}, blacklist={}, remaining_semesters=8,
        )
        self.assertEqual(path, [])
        self.assertEqual(slot_map, {})

    def test_slot_with_empty_candidates_no_crash(self):
        """A slot whose candidate list is [] must not cause an IndexError."""
        slots = [{
            "slot_id": "TEST__req__course__1",
            "program_id": "TEST",
            "type": "single",
            "is_core": True,
            "candidates": [],   # empty — nothing to assign
        }]
        try:
            path, slot_map = solve_optimal_path(
                slots=slots,
                canon_catalog={"DUMMY": {"credits": 3, "depth": 1, "original_courses": ["DUMMY"]}},
                credit_ledger={},
                macro_bindings={},
                blacklist={},
                remaining_semesters=8,
            )
            self.assertIsInstance(path, list)
        except (KeyError, IndexError, AttributeError) as exc:
            self.fail(f"Empty candidates caused raw crash: {type(exc).__name__}: {exc}")

    # ── Avoid list contains everything in catalog ────────────────────────────

    def test_avoid_all_courses_produces_empty_or_list_path(self):
        """Avoiding every course in the catalog: path is either empty or a list."""
        majors = [{"track": "Computer_Science_BS", "concentration": "None"}]
        all_courses = list(CATALOG.keys())
        try:
            path, slot_map, _ = _run_solver(
                majors, avoid=all_courses, fast_ils=True
            )
            self.assertIsInstance(path, list)
        except (KeyError, IndexError, AttributeError) as exc:
            self.fail(f"Avoid-all caused raw crash: {type(exc).__name__}: {exc}")

    # ── Nonexistent courses in completed list ────────────────────────────────

    def test_fake_completed_courses_silently_ignored(self):
        """Completed courses not in the catalog must be silently ignored, not crash."""
        fake_completed = ["XXXX999", "ZZZZ000", "FAKE101", "BOGUS202"]
        try:
            result = check_requirements(
                REQUIREMENTS, CATALOG,
                fake_completed,
                track_id="Computer_Science_BS",
                concentration_id="None",
            )
            self.assertIsInstance(result, dict)
        except (KeyError, IndexError, AttributeError) as exc:
            self.fail(
                f"Fake completed courses caused raw crash: {type(exc).__name__}: {exc}"
            )

    def test_mixed_real_and_fake_completed_no_crash(self):
        """Mix of real + fake completed courses: engine completes without crash."""
        mixed = ["COMP110", "XXXX999", "COMP210", "BOGUS202", "MATH231"]
        try:
            path, slot_map, _ = _run_solver(
                [_CS_MAJOR], completed=mixed, fast_ils=True
            )
            self.assertIsInstance(path, list)
        except (KeyError, IndexError, AttributeError) as exc:
            self.fail(
                f"Mixed real/fake completed caused raw crash: {type(exc).__name__}: {exc}"
            )

    # ── Corrupted PDF → parse_tarheel_tracker ────────────────────────────────

    def test_corrupted_pdf_raises_known_exception(self):
        """
        A file containing random bytes (not a valid PDF) passed to
        parse_tarheel_tracker must not produce an unexpected Python crash.
        It may raise pdfplumber/pdfminer exceptions or return empty lists —
        both are acceptable; an unhandled IndexError/KeyError is not.
        """
        import tempfile
        from src.planner.tracker_parser import parse_tarheel_tracker

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(b"NOTAPDF" + b"\x00\xff" * 512)
            tmp_path = tmp.name

        try:
            result = parse_tarheel_tracker(tmp_path)
            # If it returns, it must be the expected shape
            self.assertIsInstance(result, dict)
            self.assertIn("completed",   result)
            self.assertIn("in_progress", result)
        except (KeyError, IndexError) as exc:
            self.fail(
                f"Corrupted PDF raised raw engine crash: {type(exc).__name__}: {exc}"
            )
        except Exception:
            pass  # pdfplumber/pdfminer PDF-format errors are expected and fine
        finally:
            import os as _os
            _os.unlink(tmp_path)

    def test_empty_file_raises_known_exception(self):
        """A zero-byte file must not produce a raw stack trace."""
        import tempfile
        from src.planner.tracker_parser import parse_tarheel_tracker

        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(b"")
            tmp_path = tmp.name

        try:
            result = parse_tarheel_tracker(tmp_path)
            self.assertIsInstance(result, dict)
        except (KeyError, IndexError) as exc:
            self.fail(
                f"Empty file raised raw engine crash: {type(exc).__name__}: {exc}"
            )
        except Exception:
            pass  # any PDF-format error is acceptable
        finally:
            import os as _os
            _os.unlink(tmp_path)


if __name__ == "__main__":
    unittest.main(verbosity=2)
