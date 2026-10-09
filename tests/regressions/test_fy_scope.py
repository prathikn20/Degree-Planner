from src.planner.requirements_checker import generate_slots_and_candidates


def test_completed_seminar_does_not_remove_calculus_from_major():
    cat = {'AAAD50': {'credits': 3, 'attributes': ['FY-SEMINAR']},
           'MATH231': {'credits': 3, 'attributes': ['FY-LAUNCH']}}
    req = {'P': {'base_requirements': {'choice_groups': [
        {'id': 'calculus', 'options': ['MATH231'], 'courses_required': 1}]}}}
    slots, *_ = generate_slots_and_candidates(req, cat, ['P'], ['AAAD50'])
    assert len(slots) == 1
    assert slots[0]['candidates'] == ['CANON_MATH231']


def test_completed_launch_satisfies_foundation_without_seminar():
    cat = {'AAAD50': {'credits': 3, 'attributes': ['FY-SEMINAR']},
           'MATH231': {'credits': 3, 'attributes': ['FY-LAUNCH']}}
    req = {'UNC_General_Education': {'base_requirements': {'choice_groups': [
        {'id': 'FY-SEMINAR', 'type': 'rule_based', 'rule': {'attribute': 'FY-SEMINAR'}, 'courses_required': 1}]}}}
    slots, *_ = generate_slots_and_candidates(req, cat, ['UNC_General_Education'], ['MATH231'])
    assert slots == []
