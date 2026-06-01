def kahns_algorithm(course_list, catalog):
    """
    Takes a flat list of courses and organizes them into sequential semesters 
    using Kahn's Algorithm for Topological Sorting, respecting prerequisite chains.
    """
    if not course_list:
        return {}

    # 1. Initialize Graph Data Structures
    in_degree = {c: 0 for c in course_list}
    adj_list = {c: [] for c in course_list}

    # 2. Build the Adjacency Graph strictly from the chosen courses
    for course in course_list:
        # UNC prerequisites are often nested lists (e.g., [[Path A], [Path B]])
        prereqs = catalog.get(course, {}).get("prerequisites", [])
        
        # Flatten all possible prerequisites into a single set for sequencing
        flat_prereqs = set()
        for pathway in prereqs:
            for p in pathway:
                flat_prereqs.add(p)

        # If a prerequisite is also in our planned course list, draw a dependency edge
        for prereq in flat_prereqs:
            if prereq in course_list:
                adj_list[prereq].append(course)
                in_degree[course] += 1

    # 3. Find Initial Courses (0 incoming dependencies)
    queue = [c for c in course_list if in_degree[c] == 0]
    
    semesters = {}
    semester_num = 1

    # 4. Process the Graph Level-by-Level (Simulating Semesters)
    while queue:
        next_queue = []
        
        # Sort for clean alphabetical display in the UI
        semesters[f"Semester {semester_num}"] = sorted(queue)

        for node in queue:
            for neighbor in adj_list[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    next_queue.append(neighbor)

        queue = next_queue
        semester_num += 1

    # 5. Safety Net for Broken Prerequisite Cycles
    leftovers = [c for c, deg in in_degree.items() if deg > 0]
    if leftovers:
        semesters["Unsequenced (Data Error / Cycle)"] = sorted(leftovers)

    return semesters