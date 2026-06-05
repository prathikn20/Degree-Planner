import copy


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


def check_requirements(requirements, catalog, completed, other_majors_courses=None,
                        other_required_courses=None, avoid_courses=None,
                        track_id="COMP_BS", concentration_id="None"):
    avoid_set = set(avoid_courses) if avoid_courses else set()
    available_completed = set(completed)
    original_completed  = set(completed)

    virtual_to_real: dict[str, str] = {}
    for c in original_completed:
        for equiv in (catalog.get(c, {}).get('cross_listed') or []):
            if equiv not in original_completed:
                virtual_to_real[equiv] = c
        # Honors variant: MATH232H satisfies anything requiring MATH232
        if c.endswith('H') and len(c) > 1 and c[-2].isdigit():
            base = c[:-1]
            if base not in original_completed and base not in virtual_to_real:
                virtual_to_real[base] = c

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

    fys_consumed:  set[str] = set()
    fad_consumed:  set[str] = set()
    idst_consumed: set[str] = set()
    fc_consumed:   set[str] = set()

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
            if not sat and is_fc:
                sat = _get_satisfying_course(option, catalog, fys_consumed, virtual_to_real)
            if not sat and is_fc:
                sat = _get_satisfying_course(option, catalog, fad_consumed, virtual_to_real)
            if not sat and is_fc:
                sat = _get_satisfying_course(option, catalog, idst_consumed, virtual_to_real)
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

        # Report companion labs for science courses that have been taken but whose
        # lab hasn't been completed yet (applies whether the group is satisfied or not).
        companion_labs = group.get("companion_labs")
        if companion_labs and used:
            missing_labs: list[str] = []
            seen_labs: set[str] = set()
            for option, _sat in used:
                lab = companion_labs.get(option)
                if lab and lab not in seen_labs:
                    seen_labs.add(lab)
                    if not _get_satisfying_course(lab, catalog, original_completed, virtual_to_real):
                        missing_labs.append(lab)
            if missing_labs:
                results.setdefault("companion_labs_needed", {})[group["id"]] = missing_labs

    total_items = len(program["required_courses"]) + len(program["choice_groups"])
    results["completion_pct"]     = len(results["satisfied"]) / total_items if total_items else 1.0
    results["total_requirements"] = total_items
    results["total_satisfied"]    = len(results["satisfied"])

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

def generate_slots_and_candidates(requirements, catalog, majors_to_check, completed_courses, avoid_courses=None):
    """Phase 2: Resilient Slot Materialization and Credit Ledger."""
    canon_catalog, course_to_canon, macro_bindings, blacklist = build_canonical_catalog(catalog)

    # Build the avoid set (canonicalized)
    avoid_canon_set = set()
    for c in (avoid_courses or []):
        avoid_canon_set.add(course_to_canon.get(c, c))

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

        # Explode Fixed Requirements into Single Slots
        # Required courses are never filtered by avoid_courses — they are mandatory.
        for course in req_courses:
            canon_id = course_to_canon.get(course, course)
            if canon_id in global_satisfied_set:
                continue
            slots.append({
                "program_id":   program_id,
                "slot_id":      f"{program_id}__req__{canon_id}",
                "is_core":      True,
                "type":         "single",
                "candidates":   [canon_id],
                "credits_needed": canon_catalog.get(canon_id, {}).get("credits", 3),
            })

        # Choice Groups (Pools vs Explicit Slots)
        for i, group in enumerate(choice_groups):
            group_id = group.get("id", f"group_{i}")
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

            credits_req = group.get("credits_required")
            courses_req = group.get("courses_required", 1)

            if credits_req:
                if not valid_candidates:
                    continue  # pool fully satisfied by completed courses
                slots.append({
                    "program_id":   program_id,
                    "slot_id":      f"{program_id}__{group_id}__POOL",
                    "is_core":      group.get("is_core", False),
                    "type":         "pool",
                    "candidates":   valid_candidates,
                    "credits_needed": credits_req,
                })
            else:
                # Subtract courses already completed from this group before creating splits
                already_done = sum(1 for o in options if o in global_satisfied_set)

                # For rule-based attribute groups, also count completed courses directly
                # by catalog attribute. This handles cases where a completed course code
                # doesn't match any catalog key exactly (section variants, leading zeros, etc.)
                if group.get("type") == "rule_based" and group.get("rule", {}).get("attribute"):
                    attr = group["rule"]["attribute"].lower()
                    direct_done = sum(
                        1 for c in (completed_courses or [])
                        if any(attr in a.lower() for a in catalog.get(c, {}).get("attributes", []))
                    )
                    already_done = max(already_done, direct_done)

                remaining_needed = max(0, courses_req - already_done)
                if remaining_needed == 0 or not valid_candidates:
                    continue  # group fully satisfied
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
    seen_companion_lab_slots: set[str] = set()
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