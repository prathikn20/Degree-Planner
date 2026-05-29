from collections import deque
import heapq
import re
from src.planner.graph import is_available

def get_prereq_depth(course, catalog, completed_set):
    if course not in catalog:
        return float('inf')

    if is_available(course, catalog, completed_set):
        return 0

    visited = set()
    queue = deque([(course, 0)])
    max_depth = 0

    while queue:
        current, depth = queue.popleft()
        if current in visited:
            continue
        visited.add(current)
        max_depth = max(max_depth, depth)

        if current not in catalog:
            continue

        pathways = catalog[current].get('prerequisites', [])
        if not pathways:
            continue

        for path in pathways:
            for prereq in path:
                if prereq not in completed_set and prereq not in visited:
                    queue.append((prereq, depth + 1))

    return max_depth

def expand_prerequisites(courses, catalog, completed_set):
    all_needed = set()
    queue = deque(courses)

    while queue:
        course = queue.popleft()

        if course in completed_set or course in all_needed:
            continue

        all_needed.add(course)

        if course not in catalog:
            continue

        pathways = catalog[course].get('prerequisites', [])
        if not pathways:
            continue

        path_satisfied = False
        for path in pathways:
            components_satisfied = True
            for p in path:
                if p in completed_set or p in all_needed:
                    continue
                cross_listed = catalog.get(p, {}).get('cross_listed', [])
                if any(eq in completed_set or eq in all_needed for eq in cross_listed):
                    continue
                components_satisfied = False
                break
            
            if components_satisfied:
                path_satisfied = True
                break

        if path_satisfied:
            continue

        best_path = min(
            pathways,
            key=lambda path: sum(get_prereq_depth(c, catalog, completed_set) for c in path)
        )
        
        for prereq in best_path:
            queue.append(prereq)

    return all_needed

def get_remaining_courses(results, requirements, catalog, completed, avoid_courses=None, track_id="COMP_BS", concentration_id="None"):
    completed_set = set(completed)
    avoid_set     = set(avoid_courses) if avoid_courses else set()
    remaining = []

    track_data = requirements.get(track_id, {})
    if not track_data:
        return remaining

    base = track_data.get("base_requirements", {})
    conc = track_data.get("concentrations", {}).get(concentration_id, {})

    program = {
        "required_courses": base.get("required_courses", []) + conc.get("required_courses", []),
        "choice_groups": base.get("choice_groups", []) + conc.get("choice_groups", [])
    }

    for course in program.get("required_courses", []):
        if course in results["unsatisfied"]:
            remaining.append(course)

    for group in program.get("choice_groups", []):
        if group["id"] not in results["unsatisfied"]:
            continue

        group_info = results["missing_courses"][group["id"]]
        options = group_info["options"]

        sorted_options = sorted(
            [c for c in options if c not in avoid_set],
            key=lambda c: get_prereq_depth(c, catalog, completed_set)
        )

        if "credits_required" in group and group["credits_required"]:
            credits_needed = group_info.get("credits_still_needed", group["credits_required"])
            current_credits = 0
            for opt in sorted_options:
                if current_credits >= credits_needed:
                    break
                remaining.append(opt)
                current_credits += catalog.get(opt, {}).get("credits", 3)
                
        else:
            courses_needed = group_info.get("still_needed", group.get("courses_required", 1))
            chosen = sorted_options[:courses_needed]
            remaining.extend(chosen)

    return remaining
def compute_in_degrees(graph):
    in_degree = {course: 0 for course in graph}
    for course in graph:
        for neighbor in graph[course]:
            in_degree[neighbor] += 1
    return in_degree

def kahns_algorithm(graph, catalog, completed, required_courses):
    completed_set = set(completed)

    all_needed = expand_prerequisites(required_courses, catalog, completed_set)

    filtered_graph = {
        course: [n for n in neighbors if n in all_needed]
        for course, neighbors in graph.items()
        if course in all_needed
    }

    topo_queue = []
    enqueued = set()
    
    for course in all_needed:
        if is_available(course, catalog, completed_set):
            match = re.search(r'\d+', course)
            priority = int(match.group()) if match else 999
            heapq.heappush(topo_queue, (priority, course))
            enqueued.add(course)

    result = []

    while topo_queue:
        priority, course = heapq.heappop(topo_queue)
        result.append(course)
        completed_set.add(course)

        for neighbor in filtered_graph.get(course, []):
            if neighbor not in result and neighbor not in enqueued and is_available(neighbor, catalog, completed_set):
                match = re.search(r'\d+', neighbor)
                n_priority = int(match.group()) if match else 999
                heapq.heappush(topo_queue, (n_priority, neighbor))
                enqueued.add(neighbor)

    if len(result) < len(all_needed):
        unresolved = all_needed - set(result)
        print(f"Warning: unresolvable prerequisites: {unresolved}")

    return result