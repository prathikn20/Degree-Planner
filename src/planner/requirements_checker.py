def _split_course_id(course_id: str) -> tuple[str, str]:
    """Return (dept_prefix, digit_string) by collecting leading alpha chars only.

    'BUSI691H'  → ('BUSI', '691')  — trailing suffix letter ignored
    'COMP110'   → ('COMP', '110')
    'FY-SEMINAR'→ ('FY',   '')     — hyphenated ids handled gracefully
    'APPL760L'  → ('APPL', '760')
    """
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
    cross_listed = catalog.get(course, {}).get('cross_listed', [])
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
    rule_attribute   = rule.get("attribute")
    rule_dept        = rule.get("department")
    rule_exclude_dept = rule.get("exclude_department")
    rule_min_num     = rule.get("min_number") or 0
    rule_max_num     = rule.get("max_number") or float("inf")
    rule_exclude     = set(rule.get("exclude") or [])
    rule_min_cred    = rule.get("min_credits") or 0

    for course_id, data in catalog.items():
        if course_id in rule_exclude:
            continue

        if rule_attribute:
            rule_attr_lower = rule_attribute.lower()
            if any(rule_attr_lower in attr.lower() for attr in data.get("attributes", [])):
                valid.append(course_id)
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
        print(
            f"Warning: attribute rule '{rule_attribute}' matched 0 courses in the catalog. "
            "Check that the scraper is writing the correct attribute string."
        )

    return valid


def check_requirements(requirements, catalog, completed, other_majors_courses=None,
                        other_required_courses=None, avoid_courses=None,
                        track_id="COMP_BS", concentration_id="None"):
    """
    Evaluate how well *completed* satisfies the requirements for *track_id*.

    Cross-program double-dipping is fully allowed: the same course may satisfy
    requirements in multiple distinct programs.  Intra-program deduplication is
    enforced by discarding each consumed course from *available_completed* so it
    cannot fill a second slot within the same degree.

    *other_majors_courses* and *other_required_courses* are accepted for API
    compatibility with call sites that pre-date this design, but are not used.
    """
    avoid_set = set(avoid_courses) if avoid_courses else set()

    # Each program evaluation gets its own consumption pool — courses discarded
    # here do not affect evaluations of other programs.
    available_completed = set(completed)
    original_completed  = set(completed)

    # Cross-listed normalization: map virtual IDs back to the real completed course.
    virtual_to_real: dict[str, str] = {}
    for c in original_completed:
        for equiv in catalog.get(c, {}).get('cross_listed', []):
            if equiv not in original_completed:
                virtual_to_real[equiv] = c

    results = {
        "satisfied":          [],
        "unsatisfied":        [],
        "missing_courses":    {},
        "courses_used":       set(),
        "completion_pct":     0.0,
        "satisfied_map":      {},
        "total_requirements": 0,
        "total_satisfied":    0,
    }

    track_data = requirements.get(track_id, {})
    if not track_data:
        return results

    base = track_data.get("base_requirements", {})
    conc = track_data.get("concentrations", {}).get(concentration_id, {})

    program = {
        "required_courses": base.get("required_courses", []) + conc.get("required_courses", []),
        "choice_groups":    base.get("choice_groups",    []) + conc.get("choice_groups",    []),
    }

    # ── Required courses ──────────────────────────────────────────────────────
    for course in program["required_courses"]:
        sat = _get_satisfying_course(course, catalog, available_completed, virtual_to_real)
        if sat:
            available_completed.discard(sat)
            results["courses_used"].add(sat)
            results["satisfied"].append(course)
            results["satisfied_map"][course] = [sat]
        else:
            results["unsatisfied"].append(course)
            results["missing_courses"][course] = [course]

    required_set = set(program["required_courses"])

    # UNC double-counting pools (all symmetric with one another):
    #   fys_consumed   — courses that satisfied FY-SEMINAR; each may still
    #                    count for exactly ONE FC group.
    #   fad_consumed   — courses that satisfied FAD; each may still count for
    #                    exactly ONE FC group (NC System policy).
    #   idst_consumed  — courses that satisfied INTERDISCIPLINARY; each may
    #                    still count for exactly ONE FC group (and vice versa).
    #   fc_consumed    — courses that satisfied an FC group; each may still
    #                    count for FAD or INTERDISCIPLINARY (the reverse direction).
    # Once a course is pulled from any of these pools it is fully consumed.
    fys_consumed:  set[str] = set()
    fad_consumed:  set[str] = set()
    idst_consumed: set[str] = set()
    fc_consumed:   set[str] = set()

    # ── Choice groups ─────────────────────────────────────────────────────────
    for group in program["choice_groups"]:
        if group.get("options"):
            options = list(group["options"])
        elif group.get("type") == "rule_based":
            options = get_rule_based_options(
                group.get("rule") or {}, catalog,
                virtual_courses=list(virtual_to_real.keys()),
            )
        else:
            options = []

        options = [o for o in options if o not in required_set and o not in avoid_set]

        is_fys  = group["id"] == "FY-SEMINAR"
        is_fc   = group["id"].startswith("FC-")
        is_fad  = group["id"] == "FAD"
        is_idst = group["id"] == "INTERDISCIPLINARY"

        courses_needed = group.get("courses_required", 1)
        credits_needed = group.get("credits_required")

        used: list[tuple[str, str]] = []
        current_credits = 0

        for option in options:
            sat = _get_satisfying_course(option, catalog, available_completed, virtual_to_real)
            # FYS-consumed courses may still satisfy exactly one FC group
            if not sat and is_fc:
                sat = _get_satisfying_course(option, catalog, fys_consumed, virtual_to_real)
            # FAD-consumed courses may also satisfy exactly one FC group
            if not sat and is_fc:
                sat = _get_satisfying_course(option, catalog, fad_consumed, virtual_to_real)
            # IDST-consumed courses may also satisfy exactly one FC group
            if not sat and is_fc:
                sat = _get_satisfying_course(option, catalog, idst_consumed, virtual_to_real)
            # FC-consumed courses may also satisfy FAD or INTERDISCIPLINARY (symmetric)
            if not sat and (is_fad or is_idst):
                sat = _get_satisfying_course(option, catalog, fc_consumed, virtual_to_real)
            if not sat:
                continue
            used.append((option, sat))
            if credits_needed:
                current_credits += catalog.get(sat, {}).get("credits", 3)
                if current_credits >= credits_needed:
                    break
            else:
                if len(used) >= courses_needed:
                    break

        if credits_needed:
            satisfied    = current_credits >= credits_needed
            still_needed = max(0, credits_needed - current_credits)
        else:
            satisfied    = len(used) >= courses_needed
            still_needed = max(0, courses_needed - len(used))

        for _, sat in used:
            if sat in fys_consumed:
                fys_consumed.discard(sat)
            elif sat in fad_consumed:
                fad_consumed.discard(sat)
            elif sat in idst_consumed:
                idst_consumed.discard(sat)
            elif sat in fc_consumed:
                fc_consumed.discard(sat)
            else:
                available_completed.discard(sat)
                if is_fys:
                    fys_consumed.add(sat)
                elif is_fad:
                    fad_consumed.add(sat)
                elif is_idst:
                    idst_consumed.add(sat)
                elif is_fc:
                    # Reserve: can still count for FAD or INTERDISCIPLINARY
                    fc_consumed.add(sat)
            results["courses_used"].add(sat)

        if satisfied:
            results["satisfied"].append(group["id"])
            results["satisfied_map"][group["id"]] = [opt for opt, _ in used]
        else:
            results["unsatisfied"].append(group["id"])
            remaining_options = [
                o for o in options
                if not _get_satisfying_course(o, catalog, original_completed, virtual_to_real)
            ]
            entry: dict = {"options": remaining_options}
            if credits_needed:
                entry["credits_still_needed"] = still_needed
            else:
                entry["still_needed"] = still_needed
            results["missing_courses"][group["id"]] = entry

    total_items = len(program["required_courses"]) + len(program["choice_groups"])
    results["completion_pct"]     = len(results["satisfied"]) / total_items if total_items else 1.0
    results["total_requirements"] = total_items
    results["total_satisfied"]    = len(results["satisfied"])

    return results
