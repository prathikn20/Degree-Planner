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
    # Pre-seed with all initially requested courses so that when course A checks
    # whether sibling course B satisfies one of A's prerequisite paths, B is already
    # recognised as "planned" even if the BFS hasn't reached it yet.
    # (Without this, e.g. ECON411 sees ECON410 not yet in all_needed and falls back
    # to an alternative path like COMP550, pulling in a spurious dependency.)
    initial_set = set(courses) - completed_set
    all_needed.update(initial_set)

    queue = deque(courses)

    while queue:
        course = queue.popleft()

        if course in completed_set or (course in all_needed and course not in initial_set):
            continue

        initial_set.discard(course)   # allow re-processing to expand its own prereqs
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

def _course_num(course: str) -> int:
    """Return the numeric portion of a course ID for sort-order preference.
    Lower numbers are preferred so elective slots fill from accessible courses up."""
    m = re.search(r'\d+', course)
    return int(m.group()) if m else 9999


def _is_restricted_pseudo_leaf(course: str, catalog: dict) -> bool:
    """True when a course is >= 400-level with no prerequisites defined.
    The engine must never spontaneously recommend these for open elective slots;
    they behave like sinks that absorb a slot without requiring any prior work."""
    match = re.search(r'\d+', course)
    if not match or int(match.group()) < 400:
        return False
    prereqs = catalog.get(course, {}).get('prerequisites', [])
    return not prereqs


def get_remaining_courses(results, requirements, catalog, completed, avoid_courses=None, track_id="COMP_BS", concentration_id="None", explicitly_requested=None):
    completed_set          = set(completed)
    avoid_set              = set(avoid_courses) if avoid_courses else set()
    explicitly_requested_set = set(explicitly_requested) if explicitly_requested else set()
    remaining        = []
    fulfillment_map: dict[str, str] = {}
    # Tracks courses already assigned to a group within this program so the
    # same course cannot fill two choice-group slots in the same major.
    # Scoped per call, so inter-major double-dipping (e.g. STOR415 counting
    # for both Data Science BS and Gen Ed) is intentionally unaffected.
    consumed_by_path = set()

    track_data = requirements.get(track_id, {})
    if not track_data:
        return remaining, fulfillment_map

    base = track_data.get("base_requirements", {})
    conc = track_data.get("concentrations", {}).get(concentration_id, {})

    program = {
        "required_courses": base.get("required_courses", []) + conc.get("required_courses", []),
        "choice_groups": base.get("choice_groups", []) + conc.get("choice_groups", [])
    }

    for course in program.get("required_courses", []):
        if course in results["unsatisfied"]:
            remaining.append(course)
            consumed_by_path.add(course)
            fulfillment_map[course] = "Required Course"

    for group in program.get("choice_groups", []):
        if group["id"] not in results["unsatisfied"]:
            continue

        group_info = results["missing_courses"][group["id"]]
        options = group_info["options"]
        group_desc = group.get("description") or group["id"]

        sorted_options = sorted(
            [c for c in options if c not in avoid_set and c not in consumed_by_path
             and (c in explicitly_requested_set or not _is_restricted_pseudo_leaf(c, catalog))],
            key=lambda c: (0 if c in explicitly_requested_set else 1,
                           get_prereq_depth(c, catalog, completed_set),
                           _course_num(c))
        )

        if "credits_required" in group and group["credits_required"]:
            credits_needed = group_info.get("credits_still_needed", group["credits_required"])
            current_credits = 0
            for opt in sorted_options:
                if current_credits >= credits_needed:
                    break
                remaining.append(opt)
                consumed_by_path.add(opt)
                fulfillment_map[opt] = group_desc
                current_credits += catalog.get(opt, {}).get("credits", 3)

        else:
            courses_needed = group_info.get("still_needed", group.get("courses_required", 1))
            chosen = sorted_options[:courses_needed]
            remaining.extend(chosen)
            consumed_by_path.update(chosen)
            for c in chosen:
                fulfillment_map[c] = group_desc

    return remaining, fulfillment_map
def _program_total_size(track: str, conc: str, requirements: dict, catalog: dict) -> tuple:
    """(total_slot_count, total_credit_hours) for a program's full degree requirements.
    Used to compute per-program 50% exclusivity thresholds."""
    track_req = requirements.get(track, {})
    base      = track_req.get("base_requirements", {})
    conc_data = track_req.get("concentrations", {}).get(conc, {})

    required = base.get("required_courses", []) + conc_data.get("required_courses", [])
    groups   = base.get("choice_groups",    []) + conc_data.get("choice_groups",    [])

    n_slots   = len(required)
    n_credits = sum(catalog.get(c, {}).get("credits", 3) for c in required)

    for g in groups:
        if g.get("credits_required"):
            cr = g["credits_required"]
            n_slots   += max(1, cr // 3)
            n_credits += cr
        else:
            n = g.get("courses_required", 1)
            n_slots   += n
            n_credits += n * 3      # approximation; actual credits refined at selection time

    return n_slots, n_credits


def select_courses_globally(
    audit_by_track:    dict,
    requirements:      dict,
    catalog:           dict,
    completed:         list,
    majors_to_check:   list,
    avoid_courses:     list | None = None,
    explicitly_requested: list | None = None,
) -> dict:
    """
    Cross-program greedy selector with Lazy Exclusivity enforcement.

    Optimisation goal: maximise the number of courses that satisfy requirement
    slots in MORE THAN ONE distinct program (inter-program double-dipping).

    Constraints:
      1. Intra-program exclusivity — a course fills at most ONE requirement group
         within a given program (base + concentration share one pool).
      2. Strict-majority exclusivity — for every program, MORE THAN 50% of its
         total required slots (by count and by credit hours) must be filled by
         courses exclusive to that program.  The algorithm assumes sharing is OK
         and lazily rejects only when this threshold would be exceeded.

    Returns: track_id → (remaining_courses: list[str], fulfillment_map: dict[str,str])
    """
    completed_set            = set(completed)
    avoid_set                = set(avoid_courses) if avoid_courses else set()
    explicitly_requested_set = set(explicitly_requested) if explicitly_requested else set()

    # ── Per-program mutable state ─────────────────────────────────────────────
    class _PS:
        __slots__ = ("max_shared_slots", "max_shared_credits",
                     "shared_slots", "shared_credits", "consumed")

        def __init__(self, track: str, conc: str):
            n_slots, n_credits = _program_total_size(track, conc, requirements, catalog)
            # strict majority → shared < total/2 → max_shared = (total-1)//2
            self.max_shared_slots   = (n_slots   - 1) // 2
            self.max_shared_credits = (n_credits - 1) // 2
            self.shared_slots   = 0
            self.shared_credits = 0
            self.consumed: set = set()      # intra-program dedup

    ps: dict = {m["track"]: _PS(m["track"], m["concentration"]) for m in majors_to_check}

    # ── Build pending slots from each program's audit results ─────────────────
    # Each slot is a mutable dict representing one still-unfilled requirement group.
    slots: list = []

    for m in majors_to_check:
        track, conc = m["track"], m["concentration"]
        results     = audit_by_track[track]
        track_req   = requirements.get(track, {})
        base        = track_req.get("base_requirements", {})
        conc_data   = track_req.get("concentrations", {}).get(conc, {})

        for course in base.get("required_courses", []) + conc_data.get("required_courses", []):
            if course in results["unsatisfied"]:
                slots.append({
                    "track": track, "gid": course, "desc": "Required Course",
                    "options": [course],
                    "needed": 1, "credits": None, "accrued": 0,
                })

        for group in base.get("choice_groups", []) + conc_data.get("choice_groups", []):
            gid = group["id"]
            if gid not in results["unsatisfied"]:
                continue
            info    = results["missing_courses"].get(gid, {})
            options = [o for o in info.get("options", [])
                       if o not in avoid_set
                       and (o in explicitly_requested_set or not _is_restricted_pseudo_leaf(o, catalog))]
            desc = group.get("description") or gid
            if not options:
                print(
                    f"Warning: requirement '{gid}' ({desc}) for track '{track}' has no valid "
                    "course options after filtering — it will remain Unsatisfied in the path."
                )
            if group.get("credits_required"):
                slots.append({
                    "track": track, "gid": gid, "desc": desc, "options": options,
                    "needed": None,
                    "credits": info.get("credits_still_needed", group["credits_required"]),
                    "accrued": 0,
                })
            else:
                slots.append({
                    "track": track, "gid": gid, "desc": desc, "options": options,
                    "needed": info.get("still_needed", group.get("courses_required", 1)),
                    "credits": None, "accrued": 0,
                })

    # ── Output containers ─────────────────────────────────────────────────────
    remaining_out:   dict = {m["track"]: [] for m in majors_to_check}
    fulfillment_out: dict = {m["track"]: {} for m in majors_to_check}

    # ── Helpers ───────────────────────────────────────────────────────────────
    def _filled(s: dict) -> bool:
        if s["credits"] is not None:
            return s["accrued"] >= s["credits"]
        return s["needed"] is not None and s["needed"] <= 0

    def _can_share(course: str, tracks: list) -> bool:
        """True iff adding this course as shared keeps every involved program
        within its strict-majority-exclusive budget (both slot count and credits)."""
        if len(tracks) <= 1:
            return True
        cr = catalog.get(course, {}).get("credits", 3)
        for t in tracks:
            p = ps[t]
            if p.shared_slots >= p.max_shared_slots:
                return False
            if p.shared_credits + cr > p.max_shared_credits:
                return False
        return True

    # ── Greedy selection loop ─────────────────────────────────────────────────
    for _ in range(len(slots) * 300):       # safety cap prevents infinite loops
        open_s = [s for s in slots if not _filled(s)]
        if not open_s:
            break

        # Build course → [open-slot indices] for every course still assignable
        c2si: dict = {}
        for i, s in enumerate(open_s):
            consumed = ps[s["track"]].consumed
            for c in s["options"]:
                if c not in consumed:
                    c2si.setdefault(c, []).append(i)

        if not c2si:
            break   # no remaining assignable courses (may leave slots unfilled)

        # Score: prioritise courses satisfying more distinct programs;
        # break ties by lower prerequisite depth then lexicographic code.
        def _score(c: str) -> tuple:
            n_tracks  = len({open_s[i]["track"] for i in c2si[c]})
            depth     = get_prereq_depth(c, catalog, completed_set)
            requested = 0 if c in explicitly_requested_set else 1
            return (-n_tracks, requested, depth, _course_num(c), c)

        best = min(c2si, key=_score)
        cr   = catalog.get(best, {}).get("credits", 3)

        # For each track, pick the most-constrained fillable slot (fewest remaining options).
        # Most-constrained-first reduces the chance of painting ourselves into a corner.
        t2si: dict = {}
        t2n:  dict = {}
        for idx in c2si[best]:
            t = open_s[idx]["track"]
            n_alts = sum(1 for c in open_s[idx]["options"]
                         if c not in ps[t].consumed and c != best)
            if t not in t2si or n_alts < t2n[t]:
                t2si[t] = idx
                t2n[t]  = n_alts

        tracks = list(t2si)

        # Lazy exclusivity: assume sharing OK, reject only if 50% rule violated
        if len(tracks) > 1 and not _can_share(best, tracks):
            # Fall back to exclusive for the most-constrained track
            sole = min(tracks, key=lambda t: t2n[t])
            t2si = {sole: t2si[sole]}
            tracks = [sole]

        is_shared = len(tracks) > 1

        # Commit the assignment
        for t, idx in t2si.items():
            s = open_s[idx]
            if s["credits"] is not None:
                s["accrued"] += cr
            else:
                s["needed"] -= 1

            ps[t].consumed.add(best)
            if is_shared:
                ps[t].shared_slots   += 1
                ps[t].shared_credits += cr

            if best not in remaining_out[t]:
                remaining_out[t].append(best)
            fulfillment_out[t][best] = s["desc"]

    return {t: (remaining_out[t], fulfillment_out[t]) for t in remaining_out}


def build_selection_avoid(catalog: dict, assumed: list, avoid: list) -> list:
    """Return an avoid list for select_courses_globally that blocks all courses of
    a first-year program type when the student has already completed one of that type.

    UNC allows each student exactly ONE FY-SEMINAR enrollment and ONE FY-LAUNCH
    enrollment.  If *assumed* (completed + in-progress) already contains a course
    with the relevant attribute, the selection pass must never recommend another —
    not even for an FC or INTERDISCIPLINARY slot — because the student literally
    cannot enroll in a second FY-SEMINAR or FY-LAUNCH course.
    """
    extended = list(avoid)
    for fy_attr in ("FY-SEMINAR", "FY-LAUNCH"):
        if any(fy_attr in catalog.get(c, {}).get("attributes", []) for c in assumed):
            blocked = {c for c in catalog if fy_attr in catalog[c].get("attributes", [])}
            extended = list(set(extended) | blocked)
    return extended


def dedup_fy_seminar(
    all_remaining: set,
    audit:         dict,
    majors_to_check: list,
    requirements:  dict,
    catalog:       dict,
    assumed:       list,
    gen_ed_track:  str = "UNC_General_Education",
) -> set:
    """Enforce the UNC 'one per career' rules for FY-SEMINAR and FY-LAUNCH programs.

    FY-SEMINAR (fulfillment-aware):
      Only courses whose fulfillment label matches the FY-SEMINAR slot are subject
      to dedup.  Courses assigned to other requirements (INTERDISCIPLINARY, FC-NATSCI,
      …) are left untouched — this fixed Bug 1 where IDST89 (FY-SEMINAR +
      INTERDISCIPLINARY) was removed because it had fewer attributes than a
      co-selected FY-SEMINAR course.

    FY-LAUNCH (attribute-count sort):
      FY-LAUNCH has no dedicated requirement slot; the greedy selector may assign
      multiple FY-LAUNCH courses to different FC slots.  Keep the most
      attribute-rich one (maximises gen-ed overlap from one enrollment) and discard
      the rest.  When the student has already completed a FY-LAUNCH course, every
      FY-LAUNCH course in remaining is discarded.
    """
    # ── FY-SEMINAR ────────────────────────────────────────────────────────────
    assumed_fy_taken = any(
        "FY-SEMINAR" in catalog.get(c, {}).get("attributes", [])
        for c in assumed
    )

    combined_fm: dict[str, str] = {}
    for m in majors_to_check:
        for c, d in audit[m["track"]].get("fulfillment_map", {}).items():
            if c not in combined_fm:
                combined_fm[c] = d

    fy_group_desc = next(
        (g.get("description") or g["id"]
         for g in requirements.get(gen_ed_track, {})
                              .get("base_requirements", {})
                              .get("choice_groups", [])
         if g["id"] == "FY-SEMINAR"),
        "FY-SEMINAR",
    )

    fy_for_slot = sorted(
        [c for c in all_remaining
         if "FY-SEMINAR" in catalog.get(c, {}).get("attributes", [])
         and combined_fm.get(c) == fy_group_desc],
        key=lambda c: -len(catalog.get(c, {}).get("attributes", [])),
    )

    if assumed_fy_taken:
        for c in fy_for_slot:
            all_remaining.discard(c)
    else:
        for c in fy_for_slot[1:]:
            all_remaining.discard(c)

    # ── FY-LAUNCH ─────────────────────────────────────────────────────────────
    assumed_fl_taken = any(
        "FY-LAUNCH" in catalog.get(c, {}).get("attributes", [])
        for c in assumed
    )

    fl_in_remaining = sorted(
        [c for c in all_remaining if "FY-LAUNCH" in catalog.get(c, {}).get("attributes", [])],
        key=lambda c: -len(catalog.get(c, {}).get("attributes", [])),
    )

    if assumed_fl_taken:
        for c in fl_in_remaining:
            all_remaining.discard(c)
    else:
        for c in fl_in_remaining[1:]:
            all_remaining.discard(c)

    return all_remaining


def compute_in_degrees(graph):
    in_degree = {course: 0 for course in graph}
    for course in graph:
        for neighbor in graph[course]:
            in_degree[neighbor] += 1
    return in_degree

def kahns_algorithm(graph, catalog, completed, required_courses, remaining_per_track=None):
    """
    Topological sort with two-level priority:
      1. Courses satisfying more distinct programs are processed first (inter-major
         overlaps get scheduled early, minimising total courses needed).
      2. Among equal program-count ties, lower course number wins (lower-level
         courses tend to be prerequisites and should come first).

    *remaining_per_track* maps track_id → set(course_ids) as returned by the
    path-generation loop in run_pipeline.  Pass None to fall back to number-only
    ordering (used by the CLI in main.py).
    """
    completed_set   = set(completed)
    _track_sets     = list((remaining_per_track or {}).values())

    all_needed = expand_prerequisites(required_courses, catalog, completed_set)

    filtered_graph = {
        course: [n for n in neighbors if n in all_needed]
        for course, neighbors in graph.items()
        if course in all_needed
    }

    def _key(course: str) -> tuple:
        match   = re.search(r'\d+', course)
        num     = int(match.group()) if match else 9999
        n_progs = sum(1 for s in _track_sets if course in s)
        # Negate so more programs → lower heap value → higher priority
        return (-n_progs, num, course)

    topo_queue: list = []
    enqueued:   set  = set()

    for course in all_needed:
        if is_available(course, catalog, completed_set):
            heapq.heappush(topo_queue, _key(course))
            enqueued.add(course)

    result: list[str] = []

    while topo_queue:
        _, _, course = heapq.heappop(topo_queue)
        result.append(course)
        completed_set.add(course)

        for neighbor in filtered_graph.get(course, []):
            if neighbor not in result and neighbor not in enqueued and is_available(neighbor, catalog, completed_set):
                heapq.heappush(topo_queue, _key(neighbor))
                enqueued.add(neighbor)

    if len(result) < len(all_needed):
        unresolved = all_needed - set(result)
        print(f"Warning: unresolvable prerequisites: {unresolved}")

    return result