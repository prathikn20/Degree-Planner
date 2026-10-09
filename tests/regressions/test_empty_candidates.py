from unittest.mock import patch
from scripts.diagnostics.sweep_plans import load_pipeline
from src.planner.requirements_checker import generate_slots_and_candidates

CAT = {'COMP110': {'credits': 3}}
REQ = {'P': {'base_requirements': {'choice_groups': [
    {'id': 'intro', 'options': ['COMP110'], 'courses_required': 1}]}}}


def test_unmet_excluded_candidates_remain_explicit():
    slots, *_ = generate_slots_and_candidates(REQ, CAT, ['P'], [], ['COMP110'])
    assert len(slots) == 1
    assert slots[0]['candidates'] == []


def test_pipeline_reports_empty_plan_as_infeasible():
    pipeline = load_pipeline(lambda **kwargs: ([], {}))
    pipeline.__globals__['parse_tarheel_tracker'] = lambda _: {'completed': [], 'in_progress': []}
    out = pipeline('synthetic', [{'track': 'P', 'concentration': 'None'}], CAT, REQ, {}, avoid_courses=['COMP110'])
    assert out['plan_report']['requirements_complete'] is False
    assert any(i.get('slot_id', '').startswith('P__intro__') for i in out['plan_report']['issues'])


def test_empty_program_cannot_claim_complete():
    pipeline = load_pipeline(lambda **kwargs: ([], {}))
    pipeline.__globals__['parse_tarheel_tracker'] = lambda _: {'completed': [], 'in_progress': []}
    out = pipeline('synthetic', [{'track':'P','concentration':'None'}], CAT, {'P': {'base_requirements': {}}}, {})
    assert out['plan_report']['issues'][0]['type'] == 'EMPTY_PROGRAM_REQUIREMENTS'
    assert not out['plan_report']['requirements_complete']
