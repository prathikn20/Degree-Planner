from scripts.diagnostics.plan_validator import validate_plan


def test_declared_lab_pair_can_share_term_but_other_prerequisite_cannot():
    cat = {'TEST100': {'credits': 3}, 'TEST200': {'credits': 3},
           'TEST100L': {'credits': 1, 'prerequisites': [['TEST100', 'TEST200']]}}
    req = {'P': {'base_requirements': {'choice_groups': [
        {'id': 'lab', 'options': ['TEST100'], 'companion_labs': {'TEST100': 'TEST100L'}}]}}}
    case = {'programs': [{'track':'P','concentration':'None'}], 'completed':['TEST200'], 'in_progress':[], 'failed':[]}
    out = {'path':['TEST100','TEST100L'], 'semester_path':{'Semester 1':['TEST100','TEST100L']},
           'completed':['TEST200'], 'in_progress':[], 'audit':{}}
    assert not [e for e in validate_plan(case, out, cat, req, {})['events'] if e['severity']=='HARD']
    case['completed'] = []; out['completed'] = []
    out['path'].append('TEST200'); out['semester_path']['Semester 1'].append('TEST200')
    errors = [e for e in validate_plan(case, out, cat, req, {})['events'] if e['type']=='PREREQUISITE_NOT_EARLIER']
    assert len(errors) == 1
    assert errors[0]['pathways'] == [{'hard':['TEST200'], 'soft':[]}]


def test_self_prerequisite_is_not_a_mutual_corequisite_pair():
    cat = {'TEST100': {'credits': 3, 'prerequisites': [['TEST100']]}}
    case = {'programs': [], 'completed': [], 'in_progress': [], 'failed': []}
    out = {'path': ['TEST100'], 'semester_path': {'Semester 1': ['TEST100']},
           'completed': [], 'in_progress': [], 'audit': {}}
    events = validate_plan(case, out, cat, {}, {})['events']
    assert any(e['type'] == 'PREREQUISITE_NOT_EARLIER' for e in events)
