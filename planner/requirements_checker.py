def check_requirements(requirements, catalog, completed):
    completed_set = set(completed)
    
    results = {
        "satisfied": [],
        "unsatisfied": [],
        "missing_courses": {}
    }
    
    program = requirements["CS_major"]
    
    # Check required courses
    for course in program["required_courses"]:
        if _is_satisfied(course, catalog, completed_set):
            results["satisfied"].append(course)
        else:
            results["unsatisfied"].append(course)
            results["missing_courses"][course] = [course]
    
    # Check choice groups
    for group in program["choice_groups"]:
        satisfied_options = []
        
        for option in group["options"]:
            if _is_satisfied(option, catalog, completed_set):
                satisfied_options.append(option)
        
        if len(satisfied_options) >= group["courses_required"]:
            results["satisfied"].append(group["id"])
        else:
            results["unsatisfied"].append(group["id"])
            still_needed = group["courses_required"] - len(satisfied_options)
            remaining_options = [
                o for o in group["options"] 
                if not _is_satisfied(o, catalog, completed_set)
            ]
            results["missing_courses"][group["id"]] = {
                "still_needed": still_needed,
                "options": remaining_options
            }
    
    return results


def _is_satisfied(course, catalog, completed_set):
    if course in completed_set:
        return True
    
    cross_listed = catalog.get(course, {}).get('cross_listed', [])
    return any(equiv in completed_set for equiv in cross_listed)