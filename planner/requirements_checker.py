def _get_satisfying_course(course, catalog, completed_set):
    if course in completed_set:
        return course
    cross_listed = catalog.get(course, {}).get('cross_listed', [])
    for equiv in cross_listed:
        if equiv in completed_set:
            return equiv
    return None

def get_rule_based_options(rule, catalog):
    if not rule:
        return []
        
    valid = []
    rule_dept = rule.get("department")
    rule_min_num = rule.get("min_number", 0)
    rule_exclude = set(rule.get("exclude", []))
    rule_min_cred = rule.get("min_credits", 0)

    for course_id, data in catalog.items():
        dept = ''.join(filter(str.isalpha, course_id))
        number_str = ''.join(filter(str.isdigit, course_id))
        if not number_str:
            continue
        number = int(number_str)

        if ((not rule_dept or dept == rule_dept) and
            number >= rule_min_num and
            course_id not in rule_exclude and
            data.get("credits", 0) >= rule_min_cred):
            valid.append(course_id)
    return valid

def check_requirements(requirements, catalog, completed, other_majors_courses=None, track_id="COMP_BS", concentration_id="None"):
    if other_majors_courses is None:
        other_majors_courses = set()
        
    available_completed = set(completed)
    original_completed = set(completed) 
    
    results = {"satisfied": [], "unsatisfied": [], "missing_courses": {}, "courses_used": set()}
    
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

    for course in program.get("required_courses", []):
        sat_course = _get_satisfying_course(course, catalog, available_completed)
        if sat_course:
            # Required courses are inherently core
            if sat_course in other_majors_courses:
                if current_dips >= max_double_dips:
                    results["unsatisfied"].append(course)
                    results["missing_courses"][course] = [course]
                    continue
                current_dips += 1
            
            available_completed.remove(sat_course)
            results["courses_used"].add(sat_course)
            results["satisfied"].append(course)
        else:
            results["unsatisfied"].append(course)
            results["missing_courses"][course] = [course]

    required_set = set(program.get("required_courses", []))

    for group in program.get("choice_groups", []):
        is_core_req = group.get("is_core", True)
        group_type = group.get("type")
        
        if group.get("options"):
            options = group.get("options")
        elif group_type == "rule_based":
            rule = group.get("rule") or {}
            options = get_rule_based_options(rule, catalog)
        else:
            options = []
    
        options = [o for o in options if o not in required_set]
        
        used_course_mappings = []
        courses_needed = group.get("courses_required", 1)
        credits_needed = group.get("credits_required")
        current_credits = 0
        
        for option in options:
            sat_course = _get_satisfying_course(option, catalog, available_completed)
            if sat_course:
                # The Magic Logic: Only penalize if it is a Core Requirement for THIS major
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
            available_completed.remove(sat_course)
            if is_core_req and sat_course in other_majors_courses:
                current_dips += 1
            results["courses_used"].add(sat_course)

        if is_group_satisfied:
            results["satisfied"].append(group["id"])
        else:
            results["unsatisfied"].append(group["id"])
            
            remaining_options = [
                o for o in options
                if not _get_satisfying_course(o, catalog, original_completed)
            ]
            
            results["missing_courses"][group["id"]] = {
                "options": remaining_options
            }
            if credits_needed:
                results["missing_courses"][group["id"]]["credits_still_needed"] = still_needed_val
            else:
                results["missing_courses"][group["id"]]["still_needed"] = still_needed_val
                
    return results