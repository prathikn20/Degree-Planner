import copy
from src.planner import policy
from src.planner.completed_allocator import allocate_completed
from src.planner.equivalence import CourseEquivalence


def _split_course_id(course_id: str) -> tuple[str, str]:
    dept = ""
    for ch in course_id:
        if ch.isalpha():
            dept += ch
        else:
            break
    digits = "".join(filter(str.isdigit, course_id))
    return dept, digits


def _get_satisfying_course(course, catalog, completed_set, virtual_to_real=None):
    if course in completed_set:
        return course
    cross_listed = catalog.get(course, {}).get('cross_listed') or []
    for equiv in cross_listed:
        if equiv in completed_set:
            return equiv
    if virtual_to_real and course in virtual_to_real:
        real = virtual_to_real[course]
        if real in completed_set:
            return real
    return None


def get_rule_based_options(rule, catalog, virtual_courses=None):
    if not rule:
        return []

    valid = []
    rule_attribute    = rule.get("attribute")
    rule_dept         = rule.get("department")
    rule_exclude_dept = rule.get("exclude_department")
    rule_min_num      = rule.get("min_number") or 0
    rule_max_num      = rule.get("max_number") or float("inf")
    rule_exclude      = set(rule.get("exclude") or [])
    rule_min_cred     = rule.get("min_credits") or 0

    for course_id, data in catalog.items():
        if course_id in rule_exclude:
            continue
        if rule_attribute:
            rule_attr_lower = rule_attribute.lower()
            if any(rule_attr_lower in attr.lower() for attr in (data.get("attributes") or [])):
                valid.append(course_id)
            continue
        # FY-SEMINAR courses are first-year seminars; exclude them from
        # department/number-based elective pools so they cannot satisfy
        # requirements like busi_electives or comp_420_electives.
        if "FY-SEMINAR" in (data.get("attributes") or []):
            continue
        dept, number_str = _split_course_id(course_id)
        if not number_str:
            continue
        number = int(number_str)
        if rule_exclude_dept and dept == rule_exclude_dept:
            continue
        if ((not rule_dept or dept == rule_dept) and
                rule_min_num <= number <= rule_max_num and
                data.get("credits", 0) >= rule_min_cred):
            valid.append(course_id)

    if virtual_courses and not rule_attribute:
        valid_set = set(valid)
        for virtual_id in virtual_courses:
            if virtual_id in rule_exclude or virtual_id in valid_set:
                continue
            v_dept, v_num_str = _split_course_id(virtual_id)
            if not v_num_str:
                continue
            v_num = int(v_num_str)
            if rule_exclude_dept and v_dept == rule_exclude_dept:
                continue
            if (not rule_dept or v_dept == rule_dept) and rule_min_num <= v_num <= rule_max_num:
                valid.append(virtual_id)

    if rule_attribute and not valid:
        print(f"Warning: attribute rule '{rule_attribute}' matched 0 courses in the catalog.")

    return valid


def allocate_completed_work(requirements, catalog, majors_to_check, completed_courses, avoid_courses=None):
    """Normalize selected programs once and allocate completed work for both callers."""
    equivalence = CourseEquivalence(catalog)
    avoided = {equivalence.key(c) for c in avoid_courses or []}
    virtual = set(completed_courses)
    for c in completed_courses:
        virtual.update(catalog.get(c, {}).get('cross_listed') or [])
        if c.endswith('H') and c[-2:-1].isdigit():
            virtual.add(c[:-1])
    groups = []
    for entry in majors_to_check:
        pid = entry if isinstance(entry, str) else entry['track']
        conc = 'None' if isinstance(entry, str) else entry.get('concentration', 'None')
        track = requirements.get(pid, {})
        base = track.get('base_requirements', {})
        concentration = track.get('concentrations', {}).get(conc, {})
        required = base.get('required_courses', []) + concentration.get('required_courses', [])
        choices = base.get('choice_groups', []) + concentration.get('choice_groups', [])
        for i, course in enumerate(required):
            groups.append({'program': (pid, conc), 'section': 'required', 'index': i,
                           'id': course, 'kind': 'required', 'options': [course],
                           'unit': 'courses', 'target': 1})
        for i, group in enumerate(choices):
            gid = group.get('id', f'group_{i}')
            options = list(group.get('options') or [])
            if not options and group.get('type') == 'rule_based':
                options = get_rule_based_options(group.get('rule') or {}, catalog, sorted(virtual))
            # Preserve Wave 1's foundation completion interpretation in both consumers.
            if gid in {'FY-SEMINAR', 'FY-LAUNCH'}:
                options += [c for c in completed_courses
                            if {'FY-SEMINAR', 'FY-LAUNCH'}.intersection(catalog.get(c, {}).get('attributes') or [])]
            options = list(dict.fromkeys(c for c in options if equivalence.key(c) not in avoided))
            kind = 'FC' if gid.startswith('FC-') else gid
            groups.append({'program': (pid, conc), 'section': 'choice', 'index': i,
                           'id': gid, 'kind': kind, 'options': options,
                           'unit': 'credits' if group.get('credits_required') else 'courses',
                           'target': group.get('credits_required') or group.get('courses_required', 1)})
    return allocate_completed(groups, catalog, completed_courses)


def check_requirements(requirements, catalog, completed, other_majors_courses=None,
                        other_required_courses=None, avoid_courses=None,
                        track_id="COMP_BS", concentration_id="None", completed_allocation=None):
    results = {'satisfied': [], 'unsatisfied': [], 'missing_courses': {},
               'courses_used': set(), 'completion_pct': 0.0, 'satisfied_map': {},
               'total_requirements': 0, 'total_satisfied': 0,
               'completed_allocation': []}
    if track_id not in requirements:
        return results
    if completed_allocation is None:
        completed_allocation = allocate_completed_work(
            requirements, catalog, [{'track': track_id, 'concentration': concentration_id}], completed, avoid_courses)
    rows = [r for r in completed_allocation if r['program'] == (track_id, concentration_id)]
    equivalence = CourseEquivalence(catalog)
    completed_roots = {equivalence.key(c) for c in completed}
    track = requirements[track_id]
    base = track.get('base_requirements', {})
    conc = track.get('concentrations', {}).get(concentration_id, {})
    choices = base.get('choice_groups', []) + conc.get('choice_groups', [])
    for row in rows:
        rid, assigned = row['id'], row['assigned']
        results['completed_allocation'].append(row)
        results['courses_used'].update(assigned)
        if row['remaining'] == 0:
            results['satisfied'].append(rid)
            if row['section'] == 'required':
                results['satisfied_map'][rid] = assigned
            else:
                results['satisfied_map'][rid] = [next((o for o in row['options'] if equivalence.equivalent(o,c)), c) for c in assigned]
        else:
            results['unsatisfied'].append(rid)
            if row['section'] == 'required':
                results['missing_courses'][rid] = [rid]
            else:
                results['missing_courses'][rid] = {
                    'options': [o for o in row['options'] if equivalence.key(o) not in completed_roots],
                    'credits_still_needed' if row['unit'] == 'credits' else 'still_needed': row['remaining']}
        if row['section'] == 'choice':
            labs = choices[row['index']].get('companion_labs') or {}
            missing = list(dict.fromkeys(lab for lecture, lab in labs.items()
                           if any(equivalence.equivalent(lecture, c) for c in assigned)
                           and equivalence.key(lab) not in completed_roots))
            if missing:
                results.setdefault('companion_labs_needed', {})[rid] = missing
    results['total_requirements'] = len(rows)
    results['total_satisfied'] = len(results['satisfied'])
    results['completion_pct'] = len(results['satisfied']) / len(rows) if rows else 1.0
    return results


def calculate_static_depths(catalog):
    """Phase 1: Tarjan's/DFS Cycle Severing and Static Depth Calculation."""
    depths = {}
    visited = set()
    path = set()

    def dfs(course_id):
        if course_id in path:
            return 0  # Cycle detected, sever the back-edge safely
        if course_id in visited:
            return depths.get(course_id, 1)

        path.add(course_id)
        max_prereq_depth = 0
        
        prereqs = catalog.get(course_id, {}).get("prerequisites", [])
        for pathway in prereqs:
            pathway_depth = 0
            for prereq in pathway:
                pathway_depth = max(pathway_depth, dfs(prereq))
            max_prereq_depth = max(max_prereq_depth, pathway_depth)

        path.remove(course_id)
        visited.add(course_id)
        
        depth = max_prereq_depth + 1
        depths[course_id] = depth
        return depth

    for c in catalog:
        if c not in visited:
            dfs(c)
    return depths

def build_canonical_catalog(catalog):
    """Phase 1: Ingestion, Canonical Masking, and Macro-Nodes."""
    canon_catalog = {}
    course_to_canon = {}
    macro_bindings = {}
    blacklist = {}

    depths = calculate_static_depths(catalog)

    def _honors_equiv(course_id):
        """Return the H-variant if base, or the base if H-variant, when both exist."""
        if course_id.endswith('H') and len(course_id) > 1 and course_id[-2].isdigit():
            base = course_id[:-1]
            return [base] if base in catalog else []
        else:
            h = course_id + 'H'
            return [h] if h in catalog else []

    visited = set()
    for course_id, data in catalog.items():
        if course_id in visited:
            continue

        # Handle Co-requisite Macro Binding (Atomic Nodes)
        coreqs = data.get("corequisites", [])
        if coreqs:
            macro_id = f"MACRO_{course_id}_AND_{coreqs[0]}"
            macro_bindings[macro_id] = [course_id, coreqs[0]]
            base_canon = macro_id
            visited.add(coreqs[0])
            members = [course_id]
        else:
            cross_listed = data.get("cross_listed", []) + _honors_equiv(course_id)
            cross_listed = list(dict.fromkeys(cross_listed))  # dedup, preserve order
            group = sorted(set([course_id] + cross_listed))
            base_canon = f"CANON_{'_'.join(group)}"
            for c in group:
                visited.add(c)
            members = group

        # Register anti-requisites
        anti_reqs = data.get("mutually_exclusive", [])
        if anti_reqs:
            blacklist[base_canon] = anti_reqs

        for c in members:
            course_to_canon[c] = base_canon

        canon_catalog[base_canon] = {
            "original_courses": members,
            "credits": data.get("credits", 3),
            "is_repeatable": data.get("is_repeatable", False) or any(course_id.endswith(str(x)) for x in [93, 95, 99]),
            "prerequisites": data.get("prerequisites", []),
            "depth": depths.get(course_id, 1)
        }

    return canon_catalog, course_to_canon, macro_bindings, blacklist

def generate_slots_and_candidates(requirements, catalog, majors_to_check, completed_courses, avoid_courses=None, completed_allocation=None):
    """Phase 2: Resilient Slot Materialization and Credit Ledger."""
    canon_catalog, course_to_canon, macro_bindings, blacklist = build_canonical_catalog(catalog)
    if completed_allocation is None:
        completed_allocation = allocate_completed_work(requirements, catalog, majors_to_check,
                                                       completed_courses or [], avoid_courses)
    allocation = {(r['program'], r['section'], r['index']): r for r in completed_allocation}

    # Build the avoid set (canonicalized)
    avoid_canon_set = set()
    for c in (avoid_courses or []):
        avoid_canon_set.add(course_to_canon.get(c, c))

    equivalence = CourseEquivalence(catalog)
    completed_roots = {equivalence.key(c) for c in completed_courses or []}

    # Deduplication set for companion lab slots (shared across both loops below)
    seen_companion_lab_slots: set[str] = set()

    # The Credit Ledger (Prevents Transcript Inflation)
    credit_ledger = {}
    global_satisfied_set = set()

    for c in (completed_courses or []):
        canon_id = course_to_canon.get(c, c)
        global_satisfied_set.add(canon_id)
        if canon_id not in credit_ledger:
            credit_ledger[canon_id] = {"earned_credits": 0, "original_codes": []}
        credit_ledger[canon_id]["earned_credits"] += catalog.get(c, {}).get("credits", 3)
        credit_ledger[canon_id]["original_codes"].append(c)

    # Keep already-earned equivalents out of search even when legacy canonical
    # groups do not include a transitive alias recognized by the shared allocator.
    global_satisfied_set.update(canon for canon, data in canon_catalog.items()
                                if any(equivalence.key(c) in completed_roots
                                       for c in data.get('original_courses', [])))

    slots = []

    for entry in majors_to_check:
        program_id = entry if isinstance(entry, str) else entry.get("track", "")
        concentration_id = entry.get("concentration", "None") if isinstance(entry, dict) else "None"
        track_data = requirements.get(program_id, {})
        if not track_data:
            continue

        base = track_data.get("base_requirements", {})
        conc = track_data.get("concentrations", {}).get(concentration_id, {})

        # Merge base + concentration requirements
        req_courses   = base.get("required_courses", []) + conc.get("required_courses", [])
        choice_groups = base.get("choice_groups",    []) + conc.get("choice_groups",    [])

        # Canonicalised set of all required courses for this program+concentration.
        # Used below to avoid creating duplicate choice-group slots for courses that
        # are already planned as required-course slots (prevents double-counting that
        # inflates credit totals, e.g. BME concentration courses satisfying the base
        # specialty-electives group).
        req_courses_canon_set = set(course_to_canon.get(r, r) for r in req_courses)

        # Explode Fixed Requirements into Single Slots
        # Required courses are never filtered by avoid_courses — they are mandatory.
        for required_index, course in enumerate(req_courses):
            canon_id = course_to_canon.get(course, course)
            completed_row = allocation[((program_id, concentration_id), 'required', required_index)]
            if completed_row['remaining'] == 0:
                continue
            slots.append({
                "program_id":   program_id,
                "slot_id":      f"{program_id}__req__{canon_id}",
                "is_core":      True,
                "type":         "single",
                "candidates":   [] if canon_id in global_satisfied_set else [canon_id],
                "credits_needed": canon_catalog.get(canon_id, {}).get("credits", 3),
            })

        # Choice Groups (Pools vs Explicit Slots)
        for i, group in enumerate(choice_groups):
            group_id = group.get("id", f"group_{i}")
            completed_row = allocation[((program_id, concentration_id), 'choice', i)]
            if group.get("options"):
                raw_options = group["options"]
            elif group.get("type") == "rule_based":
                raw_options = get_rule_based_options(group.get("rule") or {}, catalog)
            else:
                raw_options = []

            # Deduplicate after canonicalization (cross-listed pairs map to the same canon)
            options = list(dict.fromkeys(course_to_canon.get(o, o) for o in raw_options))
            valid_candidates = [
                o for o in options
                if o not in global_satisfied_set
                and o not in avoid_canon_set
                and canon_catalog.get(o, {}).get("credits", 0) > 0  # exclude 0-credit courses
            ]

            # If this group has companion_labs, exclude candidates that share a companion
            # lab already claimed by a completed course whose lab is still missing.
            # This prevents suggesting e.g. ASTR100 as the 2nd science when ASTR103 is
            # done (both need ASTR100L, so taking ASTR100 wouldn't bring a second lab).
            companion_labs = group.get("companion_labs")
            if companion_labs:
                claimed_labs: set[str] = set()
                for completed_c in (completed_courses or []):
                    lab = companion_labs.get(completed_c)
                    if lab:
                        lab_canon = course_to_canon.get(lab, lab)
                        if lab_canon not in global_satisfied_set:
                            claimed_labs.add(lab)
                if claimed_labs:
                    filtered: list[str] = []
                    for cand_canon in valid_candidates:
                        raw_names = canon_catalog.get(cand_canon, {}).get("original_courses", [])
                        raw_name  = raw_names[0] if raw_names else cand_canon
                        cand_lab  = companion_labs.get(raw_name)
                        if cand_lab and cand_lab in claimed_labs:
                            continue  # shares a lab with a completed course — skip
                        filtered.append(cand_canon)
                    valid_candidates = filtered

            credits_req = group.get("credits_required")
            courses_req = group.get("courses_required", 1)

            if credits_req:
                credits_req = completed_row['remaining']
                if credits_req == 0:
                    continue
                slots.append({
                    "program_id":   program_id,
                    "slot_id":      f"{program_id}__{group_id}__POOL",
                    "is_core":      group.get("is_core", False),
                    "type":         "pool",
                    "candidates":   valid_candidates,
                    "credits_needed": credits_req,
                })
            else:
                already_done = courses_req - completed_row['remaining']

                # Subtract options already covered by required-course slots so the
                # solver doesn't create duplicate slots (e.g. BME concentration courses
                # that also appear in the base bme_specialty_electives choice group).
                already_req = sum(
                    1 for o in options
                    if o in req_courses_canon_set and o not in global_satisfied_set
                ) if 'choice' in policy.COMPLETED_REUSE_POOLS.get('required', ()) else 0

                remaining_needed = max(0, courses_req - already_done - already_req)
                if remaining_needed == 0:
                    continue  # group fully satisfied

                # For groups with companion_labs, also add an optional future-lab slot for
                # each remaining split so the path generator schedules the companion lab
                # alongside whichever lecture course gets chosen.  The slot is marked
                # is_optional so that self-contained FC-LAB courses (e.g. PHYS114) don't
                # incur a large penalty when no separate lab exists.
                if companion_labs and remaining_needed > 0:
                    already_claimed = {companion_labs.get(c) for c in (completed_courses or []) if companion_labs.get(c)}
                    future_lab_candidates: list[str] = []
                    seen_future_labs: set[str] = set()
                    for cand_canon in valid_candidates:
                        raw_names = canon_catalog.get(cand_canon, {}).get("original_courses", [])
                        raw_name  = raw_names[0] if raw_names else cand_canon
                        lab       = companion_labs.get(raw_name)
                        if lab and lab not in already_claimed and lab not in seen_future_labs:
                            lab_canon = course_to_canon.get(lab, lab)
                            if lab_canon not in global_satisfied_set and lab_canon not in avoid_canon_set:
                                seen_future_labs.add(lab)
                                future_lab_candidates.append(lab_canon)
                    if future_lab_candidates:
                        for j in range(remaining_needed):
                            fl_key = f"{program_id}__future_science_lab__{group_id}_{j}"
                            if fl_key not in seen_companion_lab_slots:
                                seen_companion_lab_slots.add(fl_key)
                                slots.append({
                                    "program_id":     program_id,
                                    "slot_id":        fl_key,
                                    "is_core":        False,
                                    "is_optional":    True,
                                    "type":           "single",
                                    "candidates":     future_lab_candidates,
                                    "credits_needed": 1,
                                })

                for j in range(remaining_needed):
                    slots.append({
                        "program_id":   program_id,
                        "slot_id":      f"{program_id}__{group_id}__split_{j}",
                        "is_core":      group.get("is_core", False),
                        "type":         "single",
                        "candidates":   valid_candidates,
                        "credits_needed": 3,
                    })

    # Add companion lab slots for completed science courses whose labs are still missing.
    # This ensures the path generator schedules labs for already-taken science lectures.
    for entry in majors_to_check:
        program_id = entry if isinstance(entry, str) else entry.get("track", "")
        concentration_id = entry.get("concentration", "None") if isinstance(entry, dict) else "None"
        track_data = requirements.get(program_id, {})
        if not track_data:
            continue

        base = track_data.get("base_requirements", {})
        conc = track_data.get("concentrations", {}).get(concentration_id, {})
        all_groups = base.get("choice_groups", []) + conc.get("choice_groups", [])

        for group in all_groups:
            companion_labs = group.get("companion_labs")
            if not companion_labs:
                continue
            for completed_course in (completed_courses or []):
                lab = companion_labs.get(completed_course)
                if lab is None:
                    continue
                lab_canon = course_to_canon.get(lab, lab)
                if lab_canon in global_satisfied_set:
                    continue
                if lab_canon in avoid_canon_set:
                    continue
                slot_key = f"{program_id}__{lab_canon}"
                if slot_key in seen_companion_lab_slots:
                    continue
                seen_companion_lab_slots.add(slot_key)
                slots.append({
                    "program_id":     program_id,
                    "slot_id":        f"{program_id}__companion_lab__{lab_canon}",
                    "is_core":        False,
                    "type":           "single",
                    "candidates":     [lab_canon],
                    "credits_needed": canon_catalog.get(lab_canon, {}).get("credits", 1),
                })

    return slots, canon_catalog, credit_ledger, macro_bindings, blacklist