"""Allocate whole completed-course identities once, with policy-controlled reuse.

Count demands use augmenting-path maximum bipartite matching. Credit pools add
whole-course demand positions until their targets or available supply are
exhausted; no course is split into independently reusable credit fragments.
A second matching pass allocates the permitted reuse of primary assignments.
This is not a globally optimal weighted/credit packing solver.
"""
import math
from src.planner import policy
from src.planner.equivalence import CourseEquivalence


def maximum_matching(nodes, edges, owners=None):
    """Maximum cardinality matching, preserving earlier demands on equal ties."""
    owners = {} if owners is None else owners

    def augment(node, seen):
        for resource in edges(node):
            if resource in seen:
                continue
            seen.add(resource)
            prior = owners.get(resource)
            if prior is None or augment(prior, seen):
                owners[resource] = node
                return True
        return False

    for node in nodes:
        if node not in owners.values():
            augment(node, set())
    return owners


def allocate_completed(groups, catalog, completed):
    """Return allocations aligned with normalized required/choice group records.

    Each group has program, kind, options, target and unit. Program is the
    (track, concentration) identity. A course's aliases share a single resource.
    Reuse can join two compatible requirement classes, never three groups.
    """
    equivalence = CourseEquivalence(catalog)
    def course_credits(code):
        value = catalog.get(code, {}).get('credits', 3)
        # Malformed values cannot contribute earned credits; count requirements
        # can still recognize the completed course without arithmetic on text.
        return value if isinstance(value, (int, float)) and math.isfinite(value) and value >= 0 else 0

    actual = {}
    for c in sorted(set(completed)):
        root = equivalence.key(c)
        if root not in actual or course_credits(c) > course_credits(actual[root]):
            actual[root] = c
    credits = {r: course_credits(c) for r, c in actual.items()}
    eligible = []
    for g in groups:
        roots = list(dict.fromkeys(equivalence.key(c) for c in g['options']))
        roots = [r for r in roots if r in actual and (g['unit'] != 'credits' or credits[r] > 0)]
        if g['unit'] == 'credits':
            roots.sort(key=lambda r: -credits[r])
        eligible.append([(g['program'] if policy.REUSE_COMPLETED_ACROSS_PROGRAMS else None, r) for r in roots])

    nodes = []
    serial = [0] * len(groups)
    def add_node(i):
        node = (i, serial[i]); serial[i] += 1; nodes.append(node)
        return node
    for i, g in enumerate(groups):
        n = g['target']
        if g['unit'] == 'credits':
            largest = max((credits[r] for _, r in eligible[i]), default=1)
            n = min(len(eligible[i]), math.ceil(n / largest))
        for _ in range(int(n)):
            add_node(i)

    def amount(i, *matchings):
        resources = {resource for matching in matchings for resource, node in matching.items() if node[0] == i}
        return sum(credits[r] for _, r in resources) if groups[i]['unit'] == 'credits' else len(resources)

    primary = maximum_matching(nodes, lambda node: eligible[node[0]])
    # A lower-credit reassignment can make a pool need another whole course.
    # Each successful augmentation increases cardinality; supply bounds the loop.
    while True:
        changed = False
        for i, g in enumerate(groups):
            if g['unit'] != 'credits' or amount(i, primary) >= g['target']:
                continue
            if any(n[0] == i and n not in primary.values() for n in nodes):
                continue
            node = add_node(i)
            before = len(primary)
            maximum_matching([node], lambda n: eligible[n[0]], primary)
            changed |= len(primary) > before
        if not changed:
            break

    def trim(matching, other):
        for i, g in enumerate(groups):
            if g['unit'] != 'credits':
                continue
            for resource, node in list(matching.items()):
                if node[0] == i and amount(i, matching, other) - credits[resource[1]] >= g['target']:
                    del matching[resource]
    trim(primary, {})

    def can_reuse(a, b):
        if a['program'] != b['program'] or a is b:
            return False
        def permits(source, dest):
            allowed = policy.COMPLETED_REUSE_POOLS.get(source['kind'], ())
            return dest['kind'] in allowed or ('choice' in allowed and dest['kind'] != 'required')
        # The rule describes a legal pair, not a dependency on stored group order.
        return permits(a, b) or permits(b, a)

    def reuse_edges(node):
        i = node[0]
        return [r for r in eligible[i]
                if r not in primary or can_reuse(groups[primary[r][0]], groups[i])]

    remaining = [n for n in nodes if n not in primary.values()
                 and amount(n[0], primary) < groups[n[0]]['target']]
    reused = maximum_matching(remaining, reuse_edges)
    while True:
        changed = False
        for i, g in enumerate(groups):
            if g['unit'] != 'credits' or amount(i, primary, reused) >= g['target']:
                continue
            if any(n[0] == i and n not in primary.values() and n not in reused.values() for n in nodes):
                continue
            node = add_node(i)
            before = len(reused)
            maximum_matching([node], reuse_edges, reused)
            changed |= len(reused) > before
        if not changed:
            break
    trim(reused, primary)

    result = []
    for i, g in enumerate(groups):
        resources = {r for matching in [primary, reused] for r, n in matching.items() if n[0] == i}
        assigned = [actual[root] for resource_program, root in eligible[i]
                    if (resource_program, root) in resources]
        # Resource aliases are already unique; retain option order for stable UI maps.
        earned = sum(course_credits(c) for c in assigned)
        used = earned if g['unit'] == 'credits' else len(assigned)
        result.append({**g, 'assigned': assigned, 'earned_credits': earned,
                       'remaining': max(0, g['target'] - used)})
    return result
