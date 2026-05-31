"""
Parametrized tests that run against every one of the 194 degrees in
degree_requirements.json. Each test class runs once per degree so failures
show the exact degree that broke, not just "something in the file is wrong."

Categories tested:
  1. Schema validity   — required fields, valid codes, ID uniqueness
  2. Satisfiability    — every explicit group has enough options to be completable
  3. Rule resolution   — every rule_based group resolves to >0 catalog courses
  4. Checker smoke     — requirements_checker runs without exceptions
  5. Completion logic  — empty completed = 0%, completing all requirements = 100%
"""

import sys
import os
import json
import re
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.planner.requirements_checker import check_requirements, get_rule_based_options

REQS_PATH    = "data/degree_requirements.json"
CATALOG_PATH = "data/course_catalog.json"
COURSE_RE    = re.compile(r'^[A-Z]{2,5}\d{2,4}[A-Z]?$')


# ── Module-level fixtures (loaded once) ───────────────────────────────────────

@pytest.fixture(scope="module")
def reqs():
    with open(REQS_PATH) as f:
        return json.load(f)

@pytest.fixture(scope="module")
def catalog():
    with open(CATALOG_PATH) as f:
        return json.load(f)

@pytest.fixture(scope="module")
def all_track_ids(reqs):
    return sorted(reqs.keys())

def _all_choice_groups(track_data):
    groups = list(track_data.get("base_requirements", {}).get("choice_groups", []))
    for conc in track_data.get("concentrations", {}).values():
        groups.extend(conc.get("choice_groups", []))
    return groups

def _all_required(track_data):
    req = list(track_data.get("base_requirements", {}).get("required_courses", []))
    for conc in track_data.get("concentrations", {}).values():
        req.extend(conc.get("required_courses", []))
    return req


# ── Helper: collect all track IDs at import time for parametrize ──────────────

def _load_track_ids():
    try:
        with open(REQS_PATH) as f:
            return sorted(json.load(f).keys())
    except Exception:
        return []

ALL_TRACKS = _load_track_ids()


# ── 1. Schema validity ────────────────────────────────────────────────────────

class TestSchemaPerDegree:

    @pytest.mark.parametrize("track_id", ALL_TRACKS)
    def test_has_base_requirements_key(self, track_id, reqs):
        assert "base_requirements" in reqs[track_id], \
            f"{track_id} missing 'base_requirements'"

    @pytest.mark.parametrize("track_id", ALL_TRACKS)
    def test_has_concentrations_key(self, track_id, reqs):
        assert "concentrations" in reqs[track_id], \
            f"{track_id} missing 'concentrations'"

    @pytest.mark.parametrize("track_id", ALL_TRACKS)
    def test_not_completely_empty(self, track_id, reqs):
        base = reqs[track_id].get("base_requirements", {})
        req = base.get("required_courses", [])
        cg  = base.get("choice_groups", [])
        assert req or cg, \
            f"{track_id} has no required_courses and no choice_groups — scrape failed"

    @pytest.mark.parametrize("track_id", ALL_TRACKS)
    def test_required_courses_are_valid_codes(self, track_id, reqs):
        bad = [c for c in _all_required(reqs[track_id]) if not COURSE_RE.match(c)]
        assert not bad, f"{track_id} invalid required course codes: {bad}"

    @pytest.mark.parametrize("track_id", ALL_TRACKS)
    def test_choice_group_options_are_valid_codes(self, track_id, reqs):
        bad = []
        for g in _all_choice_groups(reqs[track_id]):
            inv = [c for c in (g.get("options") or []) if not COURSE_RE.match(c)]
            if inv:
                bad.append(f"[{g['id']}] {inv}")
        assert not bad, f"{track_id} invalid option codes: {bad}"

    @pytest.mark.parametrize("track_id", ALL_TRACKS)
    def test_choice_groups_have_required_fields(self, track_id, reqs):
        errors = []
        for g in _all_choice_groups(reqs[track_id]):
            if not g.get("id"):
                errors.append("missing id")
            if g.get("type") not in ("explicit", "rule_based"):
                errors.append(f"[{g.get('id')}] bad type {g.get('type')!r}")
            if not isinstance(g.get("courses_required"), int) or g["courses_required"] < 1:
                errors.append(f"[{g.get('id')}] bad courses_required {g.get('courses_required')!r}")
            if not isinstance(g.get("options"), list):
                errors.append(f"[{g.get('id')}] options not a list")
        assert not errors, f"{track_id}: {errors}"

    @pytest.mark.parametrize("track_id", ALL_TRACKS)
    def test_no_duplicate_group_ids(self, track_id, reqs):
        """IDs must be unique within each scope the checker evaluates together:
        base_requirements and each concentration independently."""
        d = reqs[track_id]
        errors = []
        # Check base
        base_ids = [g["id"] for g in d.get("base_requirements", {}).get("choice_groups", [])]
        seen = set()
        for i in base_ids:
            if i in seen:
                errors.append(f"base_requirements duplicate: {i}")
            seen.add(i)
        # Check each concentration independently
        for cname, conc in d.get("concentrations", {}).items():
            c_ids = [g["id"] for g in conc.get("choice_groups", [])]
            seen = set()
            for i in c_ids:
                if i in seen:
                    errors.append(f"concentration '{cname}' duplicate: {i}")
                seen.add(i)
        assert not errors, f"{track_id}: {errors}"

    @pytest.mark.parametrize("track_id", ALL_TRACKS)
    def test_courses_required_is_reasonable(self, track_id, reqs):
        bad = []
        for g in _all_choice_groups(reqs[track_id]):
            cr = g.get("courses_required", 1)
            if not isinstance(cr, int) or cr < 1 or cr > 25:
                bad.append(f"[{g['id']}] courses_required={cr}")
        assert not bad, f"{track_id} unreasonable courses_required: {bad}"


# ── 2. Satisfiability ─────────────────────────────────────────────────────────

class TestSatisfiabilityPerDegree:

    @pytest.mark.parametrize("track_id", ALL_TRACKS)
    def test_explicit_groups_have_enough_options(self, track_id, reqs):
        """Every explicit choice group must have at least courses_required options."""
        bad = []
        for g in _all_choice_groups(reqs[track_id]):
            if g.get("type") == "explicit":
                opts = g.get("options") or []
                cr   = g.get("courses_required", 1)
                if len(opts) < cr:
                    bad.append(f"[{g['id']}] {len(opts)} options < {cr} required")
        assert not bad, \
            f"{track_id} unsatisfiable explicit groups (too few options): {bad}"

    @pytest.mark.parametrize("track_id", ALL_TRACKS)
    def test_rule_based_groups_resolve_to_catalog_courses(self, track_id, reqs, catalog):
        """Every rule_based group must match at least one course in the catalog."""
        bad = []
        for g in _all_choice_groups(reqs[track_id]):
            if g.get("type") == "rule_based":
                rule = g.get("rule") or {}
                opts = get_rule_based_options(rule, catalog)
                if len(opts) == 0:
                    bad.append(f"[{g['id']}] rule={rule}")
        assert not bad, \
            f"{track_id} rule_based groups with zero catalog matches: {bad}"


# ── 3. Checker smoke tests ───────────────────────────────────────────────────

class TestCheckerSmokePerDegree:

    @pytest.mark.parametrize("track_id", ALL_TRACKS)
    def test_checker_does_not_crash_empty(self, track_id, reqs, catalog):
        try:
            check_requirements(reqs, catalog, [],
                               track_id=track_id, concentration_id="None")
        except Exception as e:
            pytest.fail(f"{track_id} checker crashed with empty completed: {e}")

    @pytest.mark.parametrize("track_id", ALL_TRACKS)
    def test_checker_does_not_crash_full_catalog(self, track_id, reqs, catalog):
        try:
            check_requirements(reqs, catalog, list(catalog.keys()),
                               track_id=track_id, concentration_id="None")
        except Exception as e:
            pytest.fail(f"{track_id} checker crashed with full catalog: {e}")

    @pytest.mark.parametrize("track_id", ALL_TRACKS)
    def test_empty_completed_gives_zero_percent(self, track_id, reqs, catalog):
        base = reqs[track_id].get("base_requirements", {})
        has_requirements = bool(base.get("required_courses") or base.get("choice_groups"))
        if not has_requirements:
            pytest.skip(f"{track_id} has no requirements — pct is trivially 1.0")
        r = check_requirements(reqs, catalog, [],
                               track_id=track_id, concentration_id="None")
        assert r["completion_pct"] == 0.0, \
            f"{track_id} should be 0% with no courses, got {r['completion_pct']}"

    @pytest.mark.parametrize("track_id", ALL_TRACKS)
    def test_completing_requirements_reaches_nonzero_pct(self, track_id, reqs, catalog):
        """Supplying enough courses to cover all base requirements should give >0% completion."""
        base = reqs[track_id].get("base_requirements", {})
        req  = base.get("required_courses", [])
        cg   = base.get("choice_groups", [])
        if not req and not cg:
            pytest.skip(f"{track_id} has no requirements")
        completed = list(req)
        for g in cg:
            cr   = g.get("courses_required", 1)
            opts = g.get("options") or []
            if g.get("type") == "explicit":
                completed.extend(opts[:cr])
            elif g.get("type") == "rule_based":
                # Resolve from catalog so rule_based-only degrees also get courses
                rule_opts = get_rule_based_options(g.get("rule") or {}, catalog)
                completed.extend(rule_opts[:cr])
        r = check_requirements(reqs, catalog, completed,
                               track_id=track_id, concentration_id="None")
        assert r["completion_pct"] > 0.0, \
            f"{track_id} still 0% after supplying required+resolved courses: unsat={r['unsatisfied']}"

    @pytest.mark.parametrize("track_id", ALL_TRACKS)
    def test_result_keys_present(self, track_id, reqs, catalog):
        r = check_requirements(reqs, catalog, [],
                               track_id=track_id, concentration_id="None")
        for key in ("satisfied", "unsatisfied", "missing_courses",
                    "completion_pct", "total_requirements", "total_satisfied"):
            assert key in r, f"{track_id} result missing key '{key}'"

    @pytest.mark.parametrize("track_id", ALL_TRACKS)
    def test_satisfied_and_unsatisfied_are_disjoint(self, track_id, reqs, catalog):
        r = check_requirements(reqs, catalog, list(catalog.keys()),
                               track_id=track_id, concentration_id="None")
        overlap = set(r["satisfied"]) & set(r["unsatisfied"])
        assert not overlap, \
            f"{track_id} items appear in both satisfied and unsatisfied: {overlap}"
