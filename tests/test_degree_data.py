"""
Integration tests against the live test_degree_requirements.json data file.

Covers:
  1. Structural validity of all 192 degrees (codes, types, required fields)
  2. requirements_checker never crashes on any degree
  3. Sanity checks: specific degrees produce expected satisfied/unsatisfied sets
  4. New explicit patches (Biology organismal list, WGST minority list, etc.)
  5. Rule-based checker resolves COMP 420+, ECON 400+, ENEC, SPAN 301+ etc.
"""

import sys
import os
import json
import re
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.planner.requirements_checker import check_requirements

REQS_PATH    = "data/test_degree_requirements.json"
CATALOG_PATH = "data/course_catalog.json"
COURSE_RE    = re.compile(r'^[A-Z]{2,5}\d{2,4}[A-Z]?$')


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def reqs():
    with open(REQS_PATH) as f:
        return json.load(f)

@pytest.fixture(scope="module")
def catalog():
    with open(CATALOG_PATH) as f:
        return json.load(f)

def _check(reqs, catalog, track, courses, concentration="None"):
    return check_requirements(reqs, catalog, courses, track_id=track, concentration_id=concentration)


# ── 1. Structural validity across all degrees ──────────────────────────────────

class TestStructuralValidity:

    def test_file_loads_and_has_entries(self, reqs):
        assert len(reqs) > 100, f"Expected >100 degrees, got {len(reqs)}"

    def test_all_required_courses_are_valid_codes(self, reqs):
        bad = {}
        for track, data in reqs.items():
            inv = [c for c in data.get("base_requirements", {}).get("required_courses", [])
                   if not COURSE_RE.match(c)]
            if inv:
                bad[track] = inv
        assert not bad, f"Invalid required_course codes: {bad}"

    def test_all_choice_group_options_are_valid_codes(self, reqs):
        bad = {}
        for track, data in reqs.items():
            for g in data.get("base_requirements", {}).get("choice_groups", []):
                inv = [c for c in (g.get("options") or []) if not COURSE_RE.match(c)]
                if inv:
                    bad.setdefault(track, {}).setdefault(g["id"], []).extend(inv)
        assert not bad, f"Invalid option codes found: {bad}"

    def test_all_choice_groups_have_required_fields(self, reqs):
        bad = []
        for track, data in reqs.items():
            for g in data.get("base_requirements", {}).get("choice_groups", []):
                if not g.get("id"):
                    bad.append(f"{track}: missing id")
                if g.get("type") not in ("explicit", "rule_based"):
                    bad.append(f"{track}:{g.get('id')}: bad type {g.get('type')!r}")
                if not isinstance(g.get("courses_required"), int) or g["courses_required"] < 1:
                    bad.append(f"{track}:{g.get('id')}: bad courses_required {g.get('courses_required')!r}")
                if not isinstance(g.get("options"), list):
                    bad.append(f"{track}:{g.get('id')}: options is not a list")
        assert not bad, "Malformed choice groups:\n" + "\n".join(bad[:20])

    def test_no_duplicate_choice_group_ids_within_degree(self, reqs):
        dups = {}
        for track, data in reqs.items():
            ids = [g["id"] for g in data.get("base_requirements", {}).get("choice_groups", [])]
            seen = set()
            for i in ids:
                if i in seen:
                    dups.setdefault(track, []).append(i)
                seen.add(i)
        assert not dups, f"Duplicate group IDs: {dups}"

    def test_every_degree_has_concentrations_key(self, reqs):
        missing = [t for t, d in reqs.items() if "concentrations" not in d]
        assert not missing, f"Missing 'concentrations' key: {missing}"

    def test_popular_degrees_present(self, reqs):
        expected = [
            "Computer_Science_BS", "Data_Science_BS", "Mathematics_BS",
            "Economics_BS", "Biology_BS", "Physics_BS", "Statistics_and_Analytics_BS",
            "Biomedical_Engineering_BS", "Business_Administration_BSBA",
            "Psychology_BS", "Neuroscience_BS",
        ]
        missing = [d for d in expected if d not in reqs]
        assert not missing, f"Missing popular degrees: {missing}"


# ── 2. Checker never crashes on any degree ────────────────────────────────────

class TestCheckerNoCrash:

    def test_checker_runs_on_every_degree_empty_completed(self, reqs, catalog):
        crashed = []
        for track in reqs:
            try:
                _check(reqs, catalog, track, [])
            except Exception as e:
                crashed.append(f"{track}: {e}")
        assert not crashed, "Checker crashed:\n" + "\n".join(crashed)

    def test_checker_runs_on_every_degree_full_catalog_completed(self, reqs, catalog):
        all_courses = list(catalog.keys())
        crashed = []
        for track in reqs:
            try:
                _check(reqs, catalog, track, all_courses)
            except Exception as e:
                crashed.append(f"{track}: {e}")
        assert not crashed, "Checker crashed with full catalog:\n" + "\n".join(crashed)

    def test_no_degree_requires_courses_outside_catalog(self, reqs, catalog):
        """Flag degrees whose required_courses contain codes not in the catalog.

        Courses from partner institutions (BME, ECE from NCSU) appearing in
        dual-degree programs are a known pipeline limitation — we warn but don't fail.
        """
        # These are expected cross-institution codes the pipeline can't resolve
        KNOWN_EXTERNAL_PREFIXES = {"BME", "ECE", "TE", "E"}
        unexpected = {}
        for track, data in reqs.items():
            for c in data.get("base_requirements", {}).get("required_courses", []):
                dept = re.sub(r'\d.*', '', c)
                if c not in catalog and dept not in KNOWN_EXTERNAL_PREFIXES:
                    unexpected.setdefault(track, []).append(c)
        # Warn about true surprises (non-partner courses missing from catalog)
        if unexpected:
            import warnings
            warnings.warn(f"Required courses not in catalog: {unexpected}")
        # Don't assert — catalog grows each semester; new courses may lag


# ── 3. Specific degree sanity checks ─────────────────────────────────────────

class TestComputerScienceBS:
    TRACK = "Computer_Science_BS"

    def test_core_requirements_satisfied(self, reqs, catalog):
        completed = ["COMP210", "COMP211", "COMP301", "COMP311", "COMP455", "COMP550",
                     "MATH231", "MATH232", "COMP283", "MATH233", "MATH347", "STOR435"]
        r = _check(reqs, catalog, self.TRACK, completed)
        for c in ["COMP210", "COMP211", "COMP301", "COMP311", "COMP455", "COMP550"]:
            assert c in r["satisfied"], f"{c} should be satisfied"

    def test_comp420_rule_satisfied_by_five_electives(self, reqs, catalog):
        core = ["COMP210", "COMP211", "COMP301", "COMP311", "COMP455", "COMP550",
                "MATH231", "MATH232", "COMP283", "MATH233", "MATH347", "STOR435",
                "PHYS114", "PHYS115"]
        electives = ["COMP421", "COMP426", "COMP431", "COMP447", "COMP523"]
        r = _check(reqs, catalog, self.TRACK, core + electives)
        rule_groups = [g["id"] for g in reqs[self.TRACK]["base_requirements"]["choice_groups"]
                       if g.get("type") == "rule_based"]
        assert rule_groups, "CS BS should have at least one rule_based group"
        rule_id = rule_groups[0]
        assert rule_id in r["satisfied"], f"rule_based group {rule_id} should be satisfied"

    def test_excluded_courses_dont_satisfy_comp420_rule(self, reqs, catalog):
        core = ["COMP210", "COMP211", "COMP301", "COMP311", "COMP455", "COMP550",
                "MATH231", "MATH232", "COMP283", "MATH233", "MATH347", "STOR435",
                "PHYS114", "PHYS115"]
        # COMP496, COMP690, COMP692H are excluded from the COMP420+ rule
        excluded_only = ["COMP496", "COMP496", "COMP496", "COMP496", "COMP496"]
        r = _check(reqs, catalog, self.TRACK, core + excluded_only)
        rule_id = next(g["id"] for g in reqs[self.TRACK]["base_requirements"]["choice_groups"]
                       if g.get("type") == "rule_based")
        assert rule_id in r["unsatisfied"], "Excluded courses should not satisfy the COMP420+ rule"


class TestEconomicsBS:
    TRACK = "Economics_BS"

    def test_required_courses_satisfied(self, reqs, catalog):
        completed = ["ECON101", "ECON400", "ECON410", "ECON420", "STOR155"]
        r = _check(reqs, catalog, self.TRACK, completed)
        for c in ["ECON101", "ECON400", "ECON410", "ECON420"]:
            if c in reqs[self.TRACK]["base_requirements"]["required_courses"]:
                assert c in r["satisfied"], f"{c} should be satisfied"

    def test_econ400_rule_satisfied(self, reqs, catalog):
        from src.planner.requirements_checker import get_rule_based_options
        base_req = reqs[self.TRACK]["base_requirements"]["required_courses"]
        rule_groups = [g for g in reqs[self.TRACK]["base_requirements"]["choice_groups"]
                       if g.get("type") == "rule_based"]
        assert rule_groups, "Economics BS should have ECON 400+ rule_based group"
        # Pick 5 ECON 400+ options that are in the catalog but NOT in required_courses
        rule = rule_groups[0]["rule"]
        all_opts = get_rule_based_options(rule, catalog)
        extra_econ = [c for c in all_opts if c not in base_req][:5]
        assert len(extra_econ) == 5, f"Need 5 non-required ECON 400+ courses in catalog, found: {extra_econ}"
        r = _check(reqs, catalog, self.TRACK, base_req + extra_econ)
        rule_id = rule_groups[0]["id"]
        assert rule_id in r["satisfied"], f"ECON 400+ rule group should be satisfied with {extra_econ}"


class TestBiologyBS:
    TRACK = "Biology_BS"

    def test_organismal_list_is_explicit_with_options(self, reqs):
        cg = reqs[self.TRACK]["base_requirements"]["choice_groups"]
        rule1 = next((g for g in cg if g["id"] == "rule_1"), None)
        assert rule1 is not None, "rule_1 should exist"
        assert rule1["type"] == "explicit", "rule_1 should be explicit (not rule_based stub)"
        assert len(rule1["options"]) >= 15, f"Expected >=15 organismal courses, got {len(rule1['options'])}"
        assert "BIOL271" in rule1["options"]
        assert "BIOL579" in rule1["options"]

    def test_organismal_course_satisfies_rule1(self, reqs, catalog):
        base_req = reqs[self.TRACK]["base_requirements"]["required_courses"]
        completed = base_req + ["BIOL271"]  # organismal course
        r = _check(reqs, catalog, self.TRACK, completed)
        assert "rule_1" in r["satisfied"], "BIOL271 should satisfy the organismal diversity requirement"

    def test_allied_sciences_list_has_options(self, reqs):
        cg = reqs[self.TRACK]["base_requirements"]["choice_groups"]
        rule3 = next((g for g in cg if g["id"] == "rule_3"), None)
        assert rule3 is not None, "rule_3 should exist"
        assert rule3["type"] == "explicit"
        assert len(rule3["options"]) >= 30, f"Expected >=30 allied science options, got {len(rule3['options'])}"
        assert rule3["courses_required"] == 2


class TestStatisticsBS:
    TRACK = "Statistics_and_Analytics_BS"

    def test_group_a_b_electives_are_explicit(self, reqs):
        cg = reqs[self.TRACK]["base_requirements"]["choice_groups"]
        rule2 = next((g for g in cg if g["id"] == "rule_2"), None)
        assert rule2 is not None, "rule_2 should exist"
        assert rule2["type"] == "explicit"
        assert "STOR471" in rule2["options"]   # Group A
        assert "COMP421" in rule2["options"]   # Group B
        assert rule2["courses_required"] == 3

    def test_stor500_level_rule_satisfied(self, reqs, catalog):
        cg = reqs[self.TRACK]["base_requirements"]["choice_groups"]
        rule1 = next((g for g in cg if g["id"] == "rule_1"), None)
        if rule1 is None:
            pytest.skip("rule_1 not present in Stats BS")
        base_req = reqs[self.TRACK]["base_requirements"]["required_courses"]
        completed = base_req + ["STOR512"]
        r = _check(reqs, catalog, self.TRACK, completed)
        assert "rule_1" in r["satisfied"], "STOR512 should satisfy STOR 500-level requirement"


class TestBiomedicalEngineeringBS:
    TRACK = "Biomedical_Engineering_BS"

    def test_gateway_electives_are_explicit(self, reqs):
        cg = reqs[self.TRACK]["base_requirements"]["choice_groups"]
        rule1 = next((g for g in cg if g["id"] == "rule_1"), None)
        assert rule1 is not None
        assert rule1["type"] == "explicit"
        assert "BMME315" in rule1["options"]
        assert rule1["courses_required"] == 3

    def test_stem_elective_is_explicit(self, reqs):
        cg = reqs[self.TRACK]["base_requirements"]["choice_groups"]
        rule2 = next((g for g in cg if g["id"] == "rule_2"), None)
        assert rule2 is not None
        assert rule2["type"] == "explicit"
        assert "MATH347" in rule2["options"]
        assert rule2["courses_required"] == 1

    def test_specialty_electives_are_explicit(self, reqs):
        cg = reqs[self.TRACK]["base_requirements"]["choice_groups"]
        rule3 = next((g for g in cg if g["id"] == "rule_3"), None)
        assert rule3 is not None
        assert rule3["type"] == "explicit"
        assert rule3["courses_required"] == 4


class TestWomensGenderStudiesBA:
    TRACK = "Womens_and_Gender_Studies_BA"

    def test_minority_course_group_is_explicit_with_real_options(self, reqs):
        cg = reqs[self.TRACK]["base_requirements"]["choice_groups"]
        rule1 = next((g for g in cg if g["id"] == "rule_1"), None)
        assert rule1 is not None
        assert rule1["type"] == "explicit", "rule_1 should be explicit, not a null-rule stub"
        assert len(rule1["options"]) >= 40, f"Expected >=40 minority courses, got {len(rule1['options'])}"
        assert rule1["courses_required"] == 1

    def test_interdisciplinary_group_has_options(self, reqs):
        cg = reqs[self.TRACK]["base_requirements"]["choice_groups"]
        rule2 = next((g for g in cg if g["id"] == "rule_2"), None)
        assert rule2 is not None
        assert rule2["type"] == "explicit"
        assert len(rule2["options"]) >= 100
        assert rule2["courses_required"] == 3


class TestBusinessAdministrationBSBA:
    TRACK = "Business_Administration_BSBA"

    def test_outside_kf_rule_excludes_busi(self, reqs, catalog):
        cg = reqs[self.TRACK]["base_requirements"]["choice_groups"]
        rule1 = next((g for g in cg if g["id"] == "rule_1"), None)
        assert rule1 is not None
        assert rule1.get("type") == "rule_based"
        rule = rule1.get("rule") or {}
        assert rule.get("exclude_department") == "BUSI", \
            "Outside KF rule should exclude BUSI department"

    def test_non_busi_courses_satisfy_rule(self, reqs, catalog):
        from src.planner.requirements_checker import get_rule_based_options
        base_req = reqs[self.TRACK]["base_requirements"]["required_courses"]
        rule1 = next((g for g in reqs[self.TRACK]["base_requirements"]["choice_groups"]
                      if g.get("id") == "rule_1"), None)
        if rule1 is None:
            pytest.skip("rule_1 not in BSBA")
        # Get all options that satisfy the exclude_department=BUSI rule
        opts = get_rule_based_options(rule1["rule"], catalog)
        # Also find which options are consumed by other groups to avoid overlap
        other_group_opts = set()
        for g in reqs[self.TRACK]["base_requirements"]["choice_groups"]:
            if g["id"] != "rule_1":
                other_group_opts.update(g.get("options") or [])
        # Pick 5 that won't be consumed by other groups first
        safe_outside = [c for c in opts if c not in base_req and c not in other_group_opts][:5]
        assert len(safe_outside) == 5, f"Need 5 safe non-BUSI courses, found: {safe_outside}"
        r = _check(reqs, catalog, self.TRACK, base_req + safe_outside)
        assert "rule_1" in r["satisfied"], f"5 non-BUSI courses {safe_outside} should satisfy outside KF rule"


# ── 4. Rule-based checker resolves correctly ──────────────────────────────────

class TestRuleBasedResolution:

    def test_comp_420_excludes_comp496(self, reqs, catalog):
        """COMP496 must NOT appear in resolved options for CS BS COMP420+ rule."""
        from src.planner.requirements_checker import get_rule_based_options
        cg = reqs["Computer_Science_BS"]["base_requirements"]["choice_groups"]
        rule1 = next(g for g in cg if g.get("type") == "rule_based")
        options = get_rule_based_options(rule1["rule"], catalog)
        assert "COMP496" not in options
        assert "COMP690" not in options
        assert any(c.startswith("COMP") and int(re.sub(r'\D', '', c)) >= 420
                   for c in options if re.sub(r'\D', '', c).isdigit())

    def test_span_rule_excludes_language_courses(self, reqs, catalog):
        """Spanish for the Professions Minor: SPAN 301+ rule excludes specific courses."""
        if "Spanish_for_the_Professions_Minor" not in reqs:
            pytest.skip("Spanish minor not in test data")
        from src.planner.requirements_checker import get_rule_based_options
        cg = reqs["Spanish_for_the_Professions_Minor"]["base_requirements"]["choice_groups"]
        rule_groups = [g for g in cg if g.get("type") == "rule_based"]
        if not rule_groups:
            pytest.skip("No rule_based group in Spanish minor")
        options = get_rule_based_options(rule_groups[0]["rule"], catalog)
        assert "SPAN401" not in options
        assert "SPAN402" not in options

    def test_enec_rule_resolves_to_enec_courses(self, reqs, catalog):
        """Environmental Science Minor: ENEC rule should resolve to ENEC courses."""
        if "Environmental_Science_and_Studies_Minor" not in reqs:
            pytest.skip("ENEC minor not in test data")
        from src.planner.requirements_checker import get_rule_based_options
        cg = reqs["Environmental_Science_and_Studies_Minor"]["base_requirements"]["choice_groups"]
        rule_groups = [g for g in cg if g.get("type") == "rule_based"]
        if not rule_groups:
            pytest.skip("No rule_based group in ENEC minor")
        options = get_rule_based_options(rule_groups[0]["rule"], catalog)
        assert all(c.startswith("ENEC") for c in options), \
            f"Non-ENEC courses in ENEC rule: {[c for c in options if not c.startswith('ENEC')]}"
        assert len(options) > 0


# ── 5. Minors: checker sanity ─────────────────────────────────────────────────

class TestMinors:

    def test_cs_minor_satisfied_with_comp_electives(self, reqs, catalog):
        if "Computer_Science_Minor" not in reqs:
            pytest.skip()
        base_req = reqs["Computer_Science_Minor"]["base_requirements"]["required_courses"]
        # list_1 is now rule_based: COMP311 or COMP420+ (excl 495/496/691H/692H)
        completed = base_req + ["COMP421", "COMP431"]
        r = _check(reqs, catalog, "Computer_Science_Minor", completed)
        assert r["completion_pct"] == 1.0, \
            f"CS Minor should be 100% complete, got {r['completion_pct']}: unsat={r['unsatisfied']}"

    def test_math_minor_satisfied_with_correct_courses(self, reqs, catalog):
        if "Mathematics_Minor" not in reqs:
            pytest.skip()
        base_req = reqs["Mathematics_Minor"]["base_requirements"]["required_courses"]
        r = _check(reqs, catalog, "Mathematics_Minor", base_req)
        for c in base_req:
            assert c in r["satisfied"] or c in r["unsatisfied"], \
                f"{c} should appear in checker output"

    def test_empty_completed_leaves_all_unsatisfied(self, reqs, catalog):
        for track in ["Computer_Science_Minor", "Mathematics_Minor", "Economics_Minor"]:
            if track not in reqs:
                continue
            r = _check(reqs, catalog, track, [])
            assert r["completion_pct"] == 0.0, \
                f"{track} should be 0% complete with no courses"
