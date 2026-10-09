from src.planner.requirements_checker import generate_slots_and_candidates


def test_pool_subtracts_earned_credits_once_per_equivalence():
    cat = {c: {'credits': 3} for c in ['COMP110', 'COMP110H', 'COMP210']}
    req = {'P': {'base_requirements': {'choice_groups': [
        {'id': 'electives', 'options': ['COMP110', 'COMP110H', 'COMP210'], 'credits_required': 6}]}}}
    slots, *_ = generate_slots_and_candidates(req, cat, ['P'], ['COMP110', 'COMP110H'])
    assert len(slots) == 1
    assert slots[0]['credits_needed'] == 3
    assert slots[0]['candidates'] == ['CANON_COMP210']
    assert generate_slots_and_candidates(req, cat, ['P'], ['COMP110', 'COMP210'])[0] == []


def test_pool_uses_actual_completed_credits():
    cat = {'TEST100': {'credits': 3}, 'TEST100H': {'credits': 4}, 'TEST200': {'credits': 3}}
    req = {'P': {'base_requirements': {'choice_groups': [
        {'id': 'electives', 'options': ['TEST100', 'TEST200'], 'credits_required': 6}]}}}
    slots, *_ = generate_slots_and_candidates(req, cat, ['P'], ['TEST100H'])
    assert slots[0]['credits_needed'] == 2
