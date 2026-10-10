import json
from pathlib import Path
from src.planner.requirements_checker import check_requirements, generate_slots_and_candidates

ROOT = Path(__file__).resolve().parents[2]
def run_repro(name):
    # Exact count/attribute structures from the named Phase 3 reproductions.
    if name == 'audit_reuse':
        cat = json.loads((ROOT/'data/course_catalog.json').read_text())
        attrs, completed = ['FC-VALUES', 'RESEARCH'], ['AMST55']
    else:
        cat = {'TEST100': {'credits': 3, 'attributes': ['FC-X', 'FC-Y']},
               'TEST200': {'credits': 3, 'attributes': ['FC-X']}}
        if name == 'greedy_matching_extra_course':
            cat['TEST300'] = {'credits': 3, 'attributes': ['FC-Y']}
        attrs, completed = ['FC-X', 'FC-Y'], ['TEST100', 'TEST200']
    req = {'P': {'base_requirements': {'required_courses': [], 'choice_groups': [
        {'id': a, 'type': 'rule_based', 'rule': {'attribute': a}, 'courses_required': 1}
        for a in attrs]}, 'concentrations': {}}}
    audit = check_requirements(req, cat, completed, track_id='P')
    slots, *_ = generate_slots_and_candidates(req, cat, ['P'], completed)
    return audit, slots


def test_audit_reuse():
    audit, slots = run_repro('audit_reuse')
    assert audit['unsatisfied'] == ['RESEARCH']
    assert any(s['slot_id'].startswith('P__RESEARCH__') for s in slots)


def test_greedy_completed_matching():
    audit, slots = run_repro('greedy_completed_matching')
    assert audit['unsatisfied'] == []
    assert slots == []
    assert audit['satisfied_map']['FC-X'] == ['TEST200']
    assert audit['satisfied_map']['FC-Y'] == ['TEST100']


def test_greedy_matching_extra_course():
    audit, slots = run_repro('greedy_matching_extra_course')
    assert slots == []
    assert audit['unsatisfied'] == []


def test_matching_cardinality_against_exhaustive_oracle():
    from itertools import product
    from src.planner.completed_allocator import maximum_matching
    for mask in range(1 << 9):
        edges = {n: [r for r in range(3) if mask & (1 << (n * 3 + r))] for n in range(3)}
        expected = max(sum(r is not None for r in assignment)
                       for assignment in product(*[[None] + edges[n] for n in range(3)])
                       if len([r for r in assignment if r is not None]) == len({r for r in assignment if r is not None}))
        assert len(maximum_matching(range(3), lambda n: edges[n])) == expected


def test_policy_controls_reuse_and_caps_it_at_two_groups(monkeypatch):
    from src.planner import policy
    cat = {'TEST100': {'credits': 3}}
    req = {'P': {'base_requirements': {'choice_groups': [
        {'id': g, 'options': ['TEST100']} for g in ['FC-X', 'FAD', 'INTERDISCIPLINARY']]}}}
    audit = check_requirements(req, cat, ['TEST100'], track_id='P')
    assert len(audit['satisfied']) == 2
    monkeypatch.setattr(policy, 'COMPLETED_REUSE_POOLS', {})
    audit = check_requirements(req, cat, ['TEST100'], track_id='P')
    slots, *_ = generate_slots_and_candidates(req, cat, ['P'], ['TEST100'])
    assert len(audit['satisfied']) == 1
    assert len(slots) == 2
    assert all(not s['candidates'] for s in slots)


def test_completed_aliases_cannot_supply_two_exclusive_groups():
    cat = {'TEST100': {'credits': 3, 'cross_listed': ['ALIS100']}, 'ALIS100': {'credits': 3}}
    req = {'P': {'base_requirements': {'choice_groups': [
        {'id': g, 'options': ['TEST100', 'ALIS100']} for g in ['one', 'two']]}}}
    audit = check_requirements(req, cat, list(cat), track_id='P')
    slots, *_ = generate_slots_and_candidates(req, cat, ['P'], list(cat))
    assert len(audit['satisfied']) == 1
    assert len(slots) == 1 and not slots[0]['candidates']


def test_credit_pool_is_shared_and_whole_courses_are_not_split():
    cat = {'TEST100': {'credits': 4}, 'TEST200': {'credits': 3}, 'TEST300': {'credits': 2}}
    req = {'P': {'base_requirements': {'choice_groups': [
        {'id': 'count', 'options': ['TEST100', 'TEST200']},
        {'id': 'pool', 'options': ['TEST100', 'TEST300'], 'credits_required': 6}]}}}
    audit = check_requirements(req, cat, list(cat), track_id='P')
    slots, *_ = generate_slots_and_candidates(req, cat, ['P'], list(cat))
    assert audit['unsatisfied'] == [] and slots == []
    used = [c for row in audit['completed_allocation'] for c in row['assigned']]
    assert len(used) == len(set(used)) == 3


def test_cross_program_policy_is_used_by_shared_pipeline_allocation(monkeypatch):
    from src.planner import policy
    from src.planner.requirements_checker import allocate_completed_work
    cat = {'TEST100': {'credits': 3}}
    req = {p: {'base_requirements': {'required_courses': ['TEST100']}} for p in ['P', 'Q']}
    programs = [{'track': p, 'concentration': 'None'} for p in req]
    assert all(r['remaining'] == 0 for r in allocate_completed_work(req, cat, programs, ['TEST100']))
    monkeypatch.setattr(policy, 'REUSE_COMPLETED_ACROSS_PROGRAMS', False)
    allocation = allocate_completed_work(req, cat, programs, ['TEST100'])
    assert [r['remaining'] for r in allocation] == [0, 1]
    audit = check_requirements(req, cat, ['TEST100'], track_id='Q', completed_allocation=allocation)
    slots, *_ = generate_slots_and_candidates(req, cat, programs, ['TEST100'], completed_allocation=allocation)
    assert audit['unsatisfied'] == ['TEST100']
    assert len(slots) == 1 and slots[0]['program_id'] == 'Q'


def test_crosslist_spellings_do_not_inflate_one_group_count():
    cat = {'TEST100': {'credits': 3, 'cross_listed': ['ALIS100']},
           'ALIS100': {'credits': 3}, 'TEST200': {'credits': 3},
           'TEST300': {'credits': 3}, 'TEST400': {'credits': 3}}
    req = {'P': {'base_requirements': {'choice_groups': [
        {'id': 'four', 'options': list(cat), 'courses_required': 4}]}}}
    three = ['TEST100', 'ALIS100', 'TEST200', 'TEST300']
    audit = check_requirements(req, cat, three, track_id='P')
    assert audit['missing_courses']['four']['still_needed'] == 1
    assert not check_requirements(req, cat, three + ['TEST400'], track_id='P')['unsatisfied']
