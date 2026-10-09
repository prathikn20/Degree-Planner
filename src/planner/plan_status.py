"""Report unresolved requirement obligations without silently dropping them.

This is a post-selection status report, not an independent graduation audit.
Prerequisite closure and load feasibility are added in the later approved waves.
"""


def build_plan_report(slots, canon_catalog, path, course_to_slots, requirements, programs):
    issues = []
    for p in programs:
        pid = p['track']
        program = requirements.get(pid, {})
        sections = [program.get('base_requirements', {}),
                    program.get('concentrations', {}).get(p.get('concentration', 'None'), {})]
        if not any(s.get('required_courses') or s.get('choice_groups') for s in sections):
            issues.append({'type': 'EMPTY_PROGRAM_REQUIREMENTS', 'program': pid,
                           'group': None, 'message': 'No requirement data for this program.'})
    for s in slots:
        if s.get('is_optional'):
            continue
        sid = s['slot_id']
        represented = {c for c in path if sid in course_to_slots.get(c, [])}
        # Count canonical credits once even if output exposes more than one alias.
        assigned = {c for c in s['candidates']
                    if represented.intersection(canon_catalog.get(c, {}).get('original_courses', []))}
        credits = sum(canon_catalog.get(c, {}).get('credits', 0) for c in assigned)
        if not assigned or (s['type'] == 'pool' and credits < s['credits_needed']):
            issues.append({'type': 'UNFILLED_REQUIREMENT', 'program': s['program_id'],
                           'slot_id': sid, 'group': sid.split('__')[1],
                           'eligible_candidates': len(s['candidates']),
                           'credits_needed': s.get('credits_needed'), 'assigned_credits': credits,
                           'reason': 'No eligible candidates' if not s['candidates'] else 'Selection does not fill this requirement'})
    return {'requirements_complete': not issues, 'issues': issues,
            'scope': 'Requirement assignments only; not a graduation or scheduling feasibility certificate.'}
