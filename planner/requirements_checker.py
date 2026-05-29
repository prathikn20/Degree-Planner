def _get_satisfying_course(course, catalog, completed_set, virtual_to_real=None):
    if course in completed_set:
        return course
    cross_listed = catalog.get(course, {}).get('cross_listed', [])
    for equiv in cross_listed:
        if equiv in completed_set:
            return equiv
    # Check reverse: a completed course lists this course as its cross-listed equivalent
    if virtual_to_real and course in virtual_to_real:
        real = virtual_to_real[course]
        if real in completed_set:
            return real
    return None


def get_rule_based_options(rule, catalog, virtual_courses=None):
    if not rule:
        return []

    valid = []
    rule_attribute = rule.get("attribute")
    rule_dept      = rule.get("department")
    rule_min_num   = rule.get("min_number", 0)
    rule_exclude   = set(rule.get("exclude", []))
    rule_min_cred  = rule.get("min_credits", 0)

    for course_id, data in catalog.items():
        if course_id in rule_exclude:
            continue

        # Attribute-based rule: match any course whose attributes list contains the tag.
        # Dept/number filters are ignored when an attribute key is present.
        if rule_attribute:
            if rule_attribute in data.get("attributes", []):
                valid.append(course_id)
            continue

        # Department / number-range rule (original behaviour)
        dept       = ''.join(filter(str.isalpha, course_id))
        number_str = ''.join(filter(str.isdigit, course_id))
        if not number_str:
            continue
        number = int(number_str)

        if ((not rule_dept or dept == rule_dept) and
                number >= rule_min_num and
                data.get("credits", 0) >= rule_min_cred):
            valid.append(course_id)

    # Virtual cross-listed IDs only apply to dept/number rules, not attribute rules.
    if virtual_courses and not rule_attribute:
        valid_set = set(valid)
        for virtual_id in virtual_courses:
            if virtual_id in rule_exclude or virtual_id in valid_set:
                continue
            v_dept     = ''.join(filter(str.isalpha, virtual_id))
            v_num_str  = ''.join(filter(str.isdigit, virtual_id))
            if not v_num_str:
                continue
            v_num = int(v_num_str)
            if (not rule_dept or v_dept == rule_dept) and v_num >= rule_min_num:
                valid.append(virtual_id)

    return valid


def check_requirements(requirements, catalog, completed, other_majors_courses=None,
                        other_required_courses=None, avoid_courses=None,
                        track_id="COMP_BS", concentration_id="None"):
    if other_majors_courses is None:
        other_majors_courses = set()
    if other_required_courses is None:
        other_required_courses = set()
    avoid_set = set(avoid_courses) if avoid_courses else set()

    available_completed = set(completed)
    original_completed = set(completed)

    # --- Task 1.1: Cross-listed normalization ---
    # Build virtual_to_real: for each completed course, map its cross_listed equivalents
    # back to the real completed course so rule-based lookups can find cross-dept completions.
    virtual_to_real = {}
    for c in original_completed:
        for equiv in catalog.get(c, {}).get('cross_listed', []):
            if equiv not in original_completed:
                virtual_to_real[equiv] = c

    results = {
        "satisfied": [],
        "unsatisfied": [],
        "missing_courses": {},
        "courses_used": set(),
        "completion_pct": 0.0,
        "satisfied_map": {},       # req_id → [course_code, ...]
        "total_requirements": 0,
        "total_satisfied": 0,
    }

    track_data = requirements.get(track_id, {})
    if not track_data:
        return results

    base = track_data.get("base_requirements", {})
    conc = track_data.get("concentrations", {}).get(concentration_id, {})

    program = {
        "required_courses": base.get("required_courses", []) + conc.get("required_courses", []),
        "choice_groups": base.get("choice_groups", []) + conc.get("choice_groups", [])
    }

    total_core = len(program.get("required_courses", []))
    for group in program.get("choice_groups", []):
        if group.get("is_core", True):
            total_core += group.get("courses_required", 1)

    max_double_dips = (total_core - 1) // 2
    current_dips = 0
    core_deficit_count = 0  # Task 1.3: tracks required courses routed to elective deficit

    # --- Task 1.2: Pre-flight overlap detection ---
    # Identify required courses shared with the other major's required list.
    # These forced overlaps bypass the double-dip ceiling (student has no choice),
    # but still consume toward the dip budget before elective groups are evaluated.
    pre_flight_shared = set()
    if other_required_courses:
        other_req_set = set(other_required_courses)
        for course in program.get("required_courses", []):
            if course in other_req_set:
                sat = _get_satisfying_course(course, catalog, available_completed, virtual_to_real)
                if sat and sat in other_majors_courses:
                    pre_flight_shared.add(course)

    # --- Required courses loop ---
    for course in program.get("required_courses", []):
        sat_course = _get_satisfying_course(course, catalog, available_completed, virtual_to_real)
        if sat_course:
            if sat_course in other_majors_courses:
                if course in pre_flight_shared:
                    # Unavoidable overlap — always allowed, counts toward budget
                    current_dips += 1
                else:
                    if current_dips >= max_double_dips:
                        # Task 1.3: deficit routing — mark satisfied, defer to elective pool
                        core_deficit_count += 1
                        results["satisfied"].append(course)
                        results["satisfied_map"][course] = [sat_course]
                        results["courses_used"].add(sat_course)
                        available_completed.discard(sat_course)
                        continue
                    current_dips += 1

            available_completed.discard(sat_course)
            results["courses_used"].add(sat_course)
            results["satisfied"].append(course)
            results["satisfied_map"][course] = [sat_course]
        else:
            results["unsatisfied"].append(course)
            results["missing_courses"][course] = [course]

    required_set = set(program.get("required_courses", []))

    # --- Choice groups loop ---
    for group in program.get("choice_groups", []):
        is_core_req = group.get("is_core", True)
        group_type = group.get("type")

        if group.get("options"):
            options = list(group.get("options"))
        elif group_type == "rule_based":
            rule = group.get("rule") or {}
            options = get_rule_based_options(
                rule, catalog, virtual_courses=list(virtual_to_real.keys())
            )
        else:
            options = []

        options = [o for o in options if o not in required_set and o not in avoid_set]

        courses_needed = group.get("courses_required", 1)
        credits_needed = group.get("credits_required")

        # Task 1.3: if this is the elective group, absorb the core deficit
        if "elective" in group.get("id", "").lower() and core_deficit_count > 0:
            if credits_needed is not None:
                credits_needed += core_deficit_count * 3
            else:
                courses_needed += core_deficit_count
            core_deficit_count = 0

        used_course_mappings = []
        current_credits = 0

        for option in options:
            sat_course = _get_satisfying_course(option, catalog, available_completed, virtual_to_real)
            if sat_course:
                if is_core_req and sat_course in other_majors_courses:
                    if current_dips >= max_double_dips:
                        continue

                used_course_mappings.append((option, sat_course))
                if credits_needed:
                    current_credits += catalog.get(sat_course, {}).get("credits", 3)
                    if current_credits >= credits_needed:
                        break
                else:
                    if len(used_course_mappings) >= courses_needed:
                        break

        if credits_needed:
            is_group_satisfied = current_credits >= credits_needed
            still_needed_val = max(0, credits_needed - current_credits)
        else:
            is_group_satisfied = len(used_course_mappings) >= courses_needed
            still_needed_val = max(0, courses_needed - len(used_course_mappings))

        for opt, sat_course in used_course_mappings:
            available_completed.discard(sat_course)
            if is_core_req and sat_course in other_majors_courses:
                current_dips += 1
            results["courses_used"].add(sat_course)

        if is_group_satisfied:
            results["satisfied"].append(group["id"])
            results["satisfied_map"][group["id"]] = [opt for opt, _ in used_course_mappings]
        else:
            results["unsatisfied"].append(group["id"])

            remaining_options = [
                o for o in options
                if not _get_satisfying_course(o, catalog, original_completed, virtual_to_real)
            ]

            results["missing_courses"][group["id"]] = {
                "options": remaining_options
            }
            if credits_needed:
                results["missing_courses"][group["id"]]["credits_still_needed"] = still_needed_val
            else:
                results["missing_courses"][group["id"]]["still_needed"] = still_needed_val

    total_items = len(program["required_courses"]) + len(program["choice_groups"])
    results["completion_pct"]      = len(results["satisfied"]) / total_items if total_items else 1.0
    results["total_requirements"]  = total_items
    results["total_satisfied"]     = len(results["satisfied"])

    return results
