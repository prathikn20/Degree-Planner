def get_rule_based_options(rule, catalog):
    if not rule:
        return []
        
    valid = []
    rule_dept = rule.get("department")
    rule_min_num = rule.get("min_number", 0)
    rule_exclude = rule.get("exclude", [])
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

def check_requirements(requirements, catalog, completed, track_id="COMP_BS"):
    completed_set = set(completed)
    results = {"satisfied": [], "unsatisfied": [], "missing_courses": {}}
    
    program = requirements.get(track_id, {})
    if not program:
        return results

    for course in program.get("required_courses", []):
        if _is_satisfied(course, catalog, completed_set):
            results["satisfied"].append(course)
        else:
            results["unsatisfied"].append(course)
            results["missing_courses"][course] = [course]

    required_set = set(program.get("required_courses", []))

    for group in program.get("choice_groups", []):
        group_type = group.get("type")
        
        if group.get("options"):
            options = group.get("options")
        elif group_type == "rule_based":
            rule = group.get("rule") or {}
            options = get_rule_based_options(rule, catalog)
        else:
            options = []
    
        options = [o for o in options if o not in required_set]
        satisfied_options = []
        for option in options:
            if _is_satisfied(option, catalog, completed_set):
                satisfied_options.append(option)

        is_group_satisfied = False
        credits_needed = group.get("credits_required")
        
        courses_needed = group.get("courses_required")
        if not courses_needed and group.get("rule"):
            courses_needed = group.get("rule", {}).get("min_number")
        
        if credits_needed:
            total_credits = sum(catalog.get(course, {}).get("credits", 3) for course in satisfied_options)
            if total_credits >= credits_needed:
                is_group_satisfied = True
            still_needed_val = credits_needed - total_credits
        else:
            if courses_needed and len(satisfied_options) >= courses_needed:
                is_group_satisfied = True
            still_needed_val = (courses_needed or 1) - len(satisfied_options)

        if is_group_satisfied:
            results["satisfied"].append(group["id"])
        else:
            results["unsatisfied"].append(group["id"])
            remaining_options = [
                o for o in options
                if not _is_satisfied(o, catalog, completed_set)
            ]
            
            results["missing_courses"][group["id"]] = {
                "options": remaining_options
            }
            if credits_needed:
                results["missing_courses"][group["id"]]["credits_still_needed"] = still_needed_val
            else:
                results["missing_courses"][group["id"]]["still_needed"] = still_needed_val
                
    return results

def _is_satisfied(course, catalog, completed_set):
    if course in completed_set:
        return True
    cross_listed = catalog.get(course, {}).get('cross_listed', [])
    return any(equiv in completed_set for equiv in cross_listed)