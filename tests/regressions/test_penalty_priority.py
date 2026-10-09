from src.planner.path_generator import _debug_penalties, solve_optimal_path
from src.planner.plan_status import build_plan_report


def fixture():
    slots = [{'slot_id': 'P__'+g, 'program_id':'P', 'type':'single', 'candidates':['CANON_TEST100']}
             for g in ['first', 'second']]
    cat = {'CANON_TEST100': {'credits':3, 'depth':1, 'original_courses':['TEST100']}}
    return slots, cat


def test_mandatory_gap_dominates_combined_soft_costs():
    slots, cat = fixture()
    one = {'P__first':['CANON_TEST100'], 'P__second':[]}
    both = {'P__first':['CANON_TEST100'], 'P__second':['CANON_TEST100']}
    assert _debug_penalties(one, slots, cat, {}, 8)['objective'] > _debug_penalties(both, slots, cat, {}, 8)['objective']


def test_single_option_collision_is_filled_and_explicitly_reported():
    slots, cat = fixture()
    path, mapping, debug = solve_optimal_path(slots, cat, {}, {}, {}, debug=True)
    assert not debug['unfilled_slots']
    req = {'P':{'base_requirements':{'choice_groups':[{'id':'first'}, {'id':'second'}]}}}
    report = build_plan_report(slots, cat, path, mapping, req, [{'track':'P'}])
    assert not report['requirements_complete']
    assert any(i['type']=='SINGLE_OPTION_DATA_CONFLICT' for i in report['issues'])


def test_ordinary_reuse_remains_prohibited():
    slots, cat = fixture()
    slots[1]['candidates'] = ['CANON_TEST100', 'CANON_TEST200']
    cat['CANON_TEST200'] = {'credits':3, 'depth':1, 'original_courses':['TEST200']}
    path, mapping, debug = solve_optimal_path(slots, cat, {}, {}, {}, debug=True)
    assert set(path) == {'TEST100', 'TEST200'}
    assert not debug['unfilled_slots']
