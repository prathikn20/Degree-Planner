def get_rule_based_options(rule, catalog):
    valid = []
    for course_id, data in catalog.items():
        dept = ''.join(filter(str.isalpha, course_id))
        number_str = ''.join(filter(str.isdigit, course_id))

        if not number_str:
            continue

        number = int(number_str)

        if (dept == rule["department"] and
            number >= rule["min_number"] and
            course_id not in rule["exclude"] and
            data["credits"] >= rule["min_credits"]):
            valid.append(course_id)

    return valid


def check_requirements(requirements, catalog, completed):
    completed_set = set(completed)

    results = {
        "satisfied": [],
        "unsatisfied": [],
        "missing_courses": {}
    }

    program = requirements["CS_major"]

    for course in program["required_courses"]:
        if _is_satisfied(course, catalog, completed_set):
            results["satisfied"].append(course)
        else:
            results["unsatisfied"].append(course)
            results["missing_courses"][course] = [course]

    for group in program["choice_groups"]:
        if group.get("type") == "rule_based":
            options = get_rule_based_options(group["rule"], catalog)
        else:
            options = group["options"]

        satisfied_options = []
        for option in options:
            if _is_satisfied(option, catalog, completed_set):
                satisfied_options.append(option)

        if len(satisfied_options) >= group["courses_required"]:
            results["satisfied"].append(group["id"])
        else:
            results["unsatisfied"].append(group["id"])
            still_needed = group["courses_required"] - len(satisfied_options)
            remaining_options = [
                o for o in options
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