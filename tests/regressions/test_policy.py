def test_provisional_policy_has_one_editable_source():
    from src.planner import policy
    from scripts.diagnostics import plan_validator
    assert policy.MIN_NONFINAL_CREDITS == plan_validator.MIN_NONFINAL_CREDITS == 12
    assert policy.MAX_SEMESTER_CREDITS == plan_validator.MAX_SEMESTER_CREDITS == 18
    assert policy.FAILED_GRADES == frozenset({'F'})
    assert policy.PASSING_SUPERSEDES_FAILURE
    assert policy.PROHIBIT_SAME_PROGRAM_REUSE
    assert policy.COMPLETED_REUSE_POOLS['FY-SEMINAR'] == ('FC',)
    assert policy.COMPLETED_REUSE_POOLS['FC'] == ('FAD', 'INTERDISCIPLINARY')
    assert policy.REUSE_COMPLETED_ACROSS_PROGRAMS
