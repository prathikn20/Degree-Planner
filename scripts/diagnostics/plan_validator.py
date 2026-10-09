"""Independent catalog/requirement checks. No imports of planner or app logic; only shared policy constants.

Reuse is informational, per Prathik: coverage checks each requirement separately.
Solver debug evidence is explicitly not an independent requirement oracle.
"""
from collections import Counter, defaultdict
import re

from src.planner.policy import MIN_NONFINAL_CREDITS, MAX_SEMESTER_CREDITS
NEAR_EMPTY_COURSES = 2
COURSE_CODE = re.compile(r"^([A-Z]{2,5})(\d{2,4})([A-Z0-9]*)$")


class CatalogView:
    """Undirected transitive equivalence of cross-lists and honors/base codes."""
    def __init__(self, catalog):
        self.catalog = catalog
        self.parent = {}
        for code, data in catalog.items():
            self.root(code)
            for alias in data.get('cross_listed') or []:
                self.union(code, alias)
            if code.endswith('H') and code[-2:-1].isdigit():
                self.union(code, code[:-1])
        self.members = defaultdict(set)
        for code in list(self.parent):
            self.members[self.root(code)].add(code)

    def root(self, code):
        self.parent.setdefault(code, code)
        if self.parent[code] != code:
            self.parent[code] = self.root(self.parent[code])
        return self.parent[code]

    def union(self, a, b):
        ra, rb = self.root(a), self.root(b)
        self.parent[max(ra, rb)] = min(ra, rb)

    def equivalent(self, a, b):
        return self.root(a) == self.root(b)

    def distinct(self, courses):
        result = {}
        for code in sorted(set(courses)):
            if code in self.catalog:
                result.setdefault(self.root(code), code)
        return list(result.values())

    def matches_rule(self, code, rule):
        """Conjoin declared JSON predicates; no planner rule helper is used."""
        data = self.catalog[code]
        match = COURSE_CODE.fullmatch(code)
        if code in (rule.get('exclude') or []):
            return False
        if rule.get('attribute'):
            if rule['attribute'].casefold() not in {a.casefold() for a in data.get('attributes') or []}:
                return False
        if rule.get('department') and (not match or match[1] != rule['department']):
            return False
        if rule.get('exclude_department') and match and match[1] == rule['exclude_department']:
            return False
        if rule.get('min_number') is not None and (not match or int(match[2]) < rule['min_number']):
            return False
        if rule.get('max_number') is not None and (not match or int(match[2]) > rule['max_number']):
            return False
        return data.get('credits', 0) >= (rule.get('min_credits') or 0)

    def group_courses(self, group):
        options = group.get('options') or []
        if options:
            roots = {self.root(c) for c in options}
            return {c for c in self.catalog if self.root(c) in roots}
        if group.get('type') == 'rule_based':
            rule = group.get('rule') or {}
            return {c for c in self.catalog if rule and self.matches_rule(c, rule)}
        return set()


def requirements_for(requirements, programs):
    """Stable identifiers include section and position, avoiding duplicate-ID loss."""
    for p in programs:
        track = requirements[p['track']]
        sections = [('base', track.get('base_requirements', {})),
                    ('concentration', track.get('concentrations', {}).get(p['concentration'], {}))]
        for section, data in sections:
            for i, code in enumerate(data.get('required_courses', [])):
                yield p['track'], f"{p['track']}:{p['concentration']}:{section}:required:{i}:{code}", {'options': [code], 'courses_required': 1}
            for i, group in enumerate(data.get('choice_groups', [])):
                yield p['track'], f"{p['track']}:{p['concentration']}:{section}:group:{i}:{group.get('id')}", group


def coverage(view, requirements, programs, courses):
    real = view.distinct(courses)
    rows, reuse = [], defaultdict(list)
    for track, rid, group in requirements_for(requirements, programs):
        eligible = view.group_courses(group)
        roots = {view.root(c) for c in eligible}
        matched = [c for c in real if view.root(c) in roots]
        credits = group.get('credits_required')
        target = credits if credits else group.get('courses_required', 1)
        amount = sum(view.catalog[c].get('credits', 0) for c in matched) if credits else len(matched)
        # Companion labs are conditional on which lecture supplies this requirement.
        # Only lab-complete lectures can serve as witnesses for a group declaring labs.
        labs = group.get('companion_labs') or {}
        available_roots = {view.root(c) for c in real}
        missing_labs = []
        usable = []
        for code in matched:
            relevant = [lab for lecture, lab in labs.items() if view.equivalent(code, lecture)]
            if relevant and not any(view.root(lab) in available_roots for lab in relevant):
                missing_labs.append({'lecture': code, 'lab_options': relevant})
            else:
                usable.append(code)
        if labs:
            amount = sum(view.catalog[c].get('credits', 0) for c in usable) if credits else len(usable)
        for code in matched:
            reuse[view.root(code)].append(rid)
        rows.append({'requirement': rid, 'program': track, 'target': target,
                     'unit': 'credits' if credits else 'courses', 'available': amount,
                     'matched_real_courses': matched, 'missing_companion_labs': missing_labs,
                     'satisfied': amount >= target})
    reuse_rows = [{'equivalent_codes': sorted(view.members.get(root, {root})),
                   'requirements': sorted(set(ids)), 'kind': 'eligible_reuse_not_exclusive_allocation'}
                  for root, ids in sorted(reuse.items()) if len(set(ids)) > 1]
    return rows, reuse_rows


def validate_plan(case, output, catalog, requirements, debug):
    view = CatalogView(catalog)
    events = []
    def emit(kind, severity='HARD', **details):
        events.append({'type': kind, 'severity': severity, **details})

    # Ground truth comes from synthetic transcript inputs, not parser output.
    passed = case['completed']
    in_progress = case.get('in_progress', [])
    failed = case.get('failed', [])
    path = output['path']
    for code in sorted(set(path)):
        if code not in catalog:
            emit('UNKNOWN_PLANNED_COURSE', course=code)
    for code, count in Counter(path).items():
        if count > 1:
            emit('DUPLICATE_PLANNED_COURSE', course=code, count=count)
    for code in failed:
        if code in output['completed'] and not any(view.equivalent(code, p) for p in passed):
            emit('FAILED_GRADE_TREATED_COMPLETED', course=code,
                 rescheduled=any(view.equivalent(code, p) for p in path))
    expected_completed = set(passed)  # Failed attempts do not confer completion credit.
    if set(output['completed']) != expected_completed or set(output['in_progress']) != set(in_progress):
        emit('TRANSCRIPT_PARSE_MISMATCH', expected_completed=sorted(expected_completed),
             parsed_completed=output['completed'], expected_in_progress=in_progress,
             parsed_in_progress=output['in_progress'])

    # Approved timing exceptions: declared companion pairs, catalog corequisites,
    # and mutual prerequisite pairs may share a term. Other prerequisites cannot.
    corequisite_pairs = set()
    for _, _, group in requirements_for(requirements, case['programs']):
        for lecture, lab in (group.get('companion_labs') or {}).items():
            corequisite_pairs.add(frozenset((view.root(lecture), view.root(lab))))
    prereq_edges = {(view.root(c), view.root(p)) for c, d in catalog.items()
                    for branch in d.get('prerequisites') or [] for p in branch}
    for a, b in prereq_edges:
        if a != b and (b, a) in prereq_edges:
            corequisite_pairs.add(frozenset((a, b)))
    for c, d in catalog.items():
        for coreq in d.get('corequisites') or []:
            corequisite_pairs.add(frozenset((view.root(c), view.root(coreq))))

    semesters = output['semester_path']
    regular = sorted((int(re.fullmatch(r'Semester (\d+)', k)[1]), k, cs)
                     for k, cs in semesters.items() if re.fullmatch(r'Semester (\d+)', k))
    last = max((n for n, _, _ in regular), default=0)
    earlier = {view.root(c) for c in passed + in_progress}
    for name, cs in semesters.items():
        if not re.fullmatch(r'Semester (\d+)', name) and cs:
            emit('UNSEQUENCED_COURSES', bucket=name, courses=cs)
    for number, name, courses in regular:
        credits = sum(catalog.get(c, {}).get('credits', 0) for c in courses)
        if credits > MAX_SEMESTER_CREDITS:
            emit('SEMESTER_OVERLOAD', semester=name, credits=credits, limit=MAX_SEMESTER_CREDITS)
        if number != last and credits < MIN_NONFINAL_CREDITS:
            emit('SEMESTER_UNDER_FULL_TIME', semester=name, credits=credits, limit=MIN_NONFINAL_CREDITS)
        for code in courses:
            branches = catalog.get(code, {}).get('prerequisites') or []
            if not branches:
                continue
            missing = []
            for branch in branches:
                hard, soft = [], []
                for pre in branch:
                    if view.root(pre) in earlier:
                        continue
                    if (frozenset((view.root(code), view.root(pre))) in corequisite_pairs
                            and any(view.equivalent(pre, c) for c in courses)):
                        continue
                    if COURSE_CODE.fullmatch(pre):
                        hard.append(pre)
                    else:
                        soft.append(pre)
                missing.append({'hard': hard, 'soft': soft})
            if any(not m['hard'] and not m['soft'] for m in missing):
                continue
            if any(not m['hard'] for m in missing):
                emit('PREREQUISITE_NONCOURSE', 'SOFT', course=code, semester=name, pathways=missing)
            else:
                emit('PREREQUISITE_NOT_EARLIER', course=code, semester=name, pathways=missing)
                if any(m['soft'] for m in missing):
                    emit('PREREQUISITE_NONCOURSE', 'SOFT', course=code, semester=name, pathways=missing)
        # Same-semester courses never become prerequisites until the whole bucket is checked.
        earlier.update(view.root(c) for c in courses if c in catalog)

    rows, reuse = coverage(view, requirements, case['programs'], passed + in_progress + path)
    for row in rows:
        if not row['satisfied']:
            emit('REQUIREMENT_UNCOVERED', **row)
    for item in debug.get('unfilled_slots', []):
        emit('UNFILLED_OPTIONAL_SLOT' if item['optional'] else 'UNFILLED_MANDATORY_SLOT',
             'INFO' if item['optional'] else 'HARD', evidence='SOLVER DEBUG / NOT INDEPENDENT', **item)
    for issue in output.get('plan_report', {}).get('issues', []):
        if issue['type'] in {'SINGLE_OPTION_DATA_CONFLICT', 'EMPTY_PROGRAM_REQUIREMENTS'}:
            emit('REQUIREMENT_DATA_CONFLICT', evidence='PLAN REPORT / NOT INDEPENDENT', issue=issue)
    for code in debug.get('dropped_courses', []):
        emit('COURSE_DROPPED_AFTER_ASSIGNMENT', course=code)
    before = {track: data['results']['unsatisfied'] for track, data in output['audit'].items()
              if data['results']['unsatisfied']}
    if len(path) <= NEAR_EMPTY_COURSES and before:
        emit('EMPTY_OR_NEAR_EMPTY_WITH_UNMET_AUDIT', 'REVIEW', path_length=len(path),
             threshold=NEAR_EMPTY_COURSES, evidence='PRE-PLAN AUDIT / NOT INDEPENDENT', unmet=before)
    slot_usage = defaultdict(list)
    for sid, canons in debug.get('assignment', {}).items():
        for canon in canons:
            slot_usage[canon].append(sid)
    assigned_reuse = [{'canonical_course': c, 'slots': sorted(set(ids))}
                      for c, ids in sorted(slot_usage.items()) if len(set(ids)) > 1]
    return {'events': events, 'coverage': rows, 'reuse_eligible': reuse,
            'reuse_assigned_NOT_INDEPENDENT': assigned_reuse,
            'semester_path_hidden_in_UI': True,
            'coverage_policy': 'Each JSON requirement independently; reuse informational, no exclusivity policy imposed.'}
