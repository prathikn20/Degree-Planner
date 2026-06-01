import time
import random
from collections import defaultdict

def solve_optimal_path(slots, canon_catalog, credit_ledger, macro_bindings, blacklist, remaining_semesters=8):
    """Phase 1 Greedy + Phase 2 Short ILS Optimization Engine."""
    if not slots:
        return [], {}

    def calculate_objective(assignment):
        penalties = 0
        unique_courses: set = set()
        fc_course_slots: dict = {}       # canon_id  -> [slot_ids that are FC/FY slots]
        prog_course_slots: dict = {}     # (prog_id, canon_id) -> count within that program
        global_usage: dict = {}          # canon_id -> total slot assignments across all programs

        # ── Pass 1: traverse every slot assignment ────────────────────────────
        for s in slots:
            sid  = s["slot_id"]
            pid  = s["program_id"]
            assigned = assignment.get(sid, [])

            # C6 – Slot sufficiency: every slot must be fully satisfied
            if s["type"] == "single" and not assigned:
                penalties += 10000
            elif s["type"] == "pool":
                pool_credits = sum(canon_catalog.get(c, {}).get("credits", 3) for c in assigned)
                if pool_credits < s.get("credits_needed", 3):
                    penalties += 10000

            for c in assigned:
                unique_courses.add(c)
                global_usage[c] = global_usage.get(c, 0) + 1

                # Track for C3 – FC Singularity (FC-* and FY-SEMINAR slots)
                if "__FC-" in sid or "__FY-SEMINAR" in sid or "__FAD" in sid or "__INTERDISCIPLINARY" in sid:
                    fc_course_slots.setdefault(c, []).append(sid)

                # Track for C1 – Intra-program exclusivity
                key = (pid, c)
                prog_course_slots[key] = prog_course_slots.get(key, 0) + 1

                # C7 – Longest-path temporal ceiling
                if canon_catalog.get(c, {}).get("depth", 1) > remaining_semesters:
                    penalties += 1000

                # C4 – Anti-requisite penalty
                for anti in blacklist.get(c, []):
                    if anti in unique_courses:
                        penalties += 1000

            # Low-credit penalty: strongly discourage <3-credit courses when
            # 3+-credit alternatives exist in the same slot's candidate pool
            for c in assigned:
                cr = canon_catalog.get(c, {}).get("credits", 3)
                if cr < 3:
                    if any(canon_catalog.get(alt, {}).get("credits", 0) >= 3
                           for alt in s.get("candidates", []) if alt != c):
                        penalties += 2000

        # ── Pass 2: structural constraint penalties ───────────────────────────

        # C3 – FC Singularity: a course may satisfy AT MOST one FC/FY/FAD/IDST slot
        for c, fc_slots_list in fc_course_slots.items():
            if len(fc_slots_list) > 1:
                penalties += 5000 * (len(fc_slots_list) - 1)

        # C1 – Intra-program exclusivity: non-repeatable courses may fill only
        # ONE slot per program (cross-program double-counting is encouraged)
        for (pid, c), count in prog_course_slots.items():
            if count > 1 and not canon_catalog.get(c, {}).get("is_repeatable", False):
                penalties += 3000 * (count - 1)

        # C5 – FY Foundation XOR: plan may not contain both an FY-SEMINAR and
        # an FY-LAUNCH assignment simultaneously
        fy_types_assigned: set = set()
        for c, fc_slots_list in fc_course_slots.items():
            for fsl in fc_slots_list:
                if "__FY-SEMINAR" in fsl:
                    fy_types_assigned.add("FY-SEMINAR")
                elif "__FY-LAUNCH" in fsl:
                    fy_types_assigned.add("FY-LAUNCH")
        if len(fy_types_assigned) > 1:
            penalties += 10000

        # C4 – 50% Program Exclusivity Rule
        prog_exclusivity: dict = {}
        for s in slots:
            pid = s["program_id"]
            if pid not in prog_exclusivity:
                prog_exclusivity[pid] = {"core_total": 0, "exclusive": 0}
            if s.get("is_core") and len(s.get("candidates", [])) > 1:
                prog_exclusivity[pid]["core_total"] += 1
                assigned = assignment.get(s["slot_id"], [])
                if assigned and all(global_usage.get(c, 0) == 1 for c in assigned):
                    prog_exclusivity[pid]["exclusive"] += 1

        for pid, stats in prog_exclusivity.items():
            if stats["core_total"] > 0 and (stats["exclusive"] * 2) <= stats["core_total"]:
                penalties += 500

        # ── Objective: total UNIQUE credits ───────────────────────────────────
        # Courses that cross-count across programs are counted ONCE, so the
        # solver is naturally rewarded for aggressive double-counting.
        total_unique_credits = sum(
            canon_catalog.get(c, {}).get("credits", 3)
            for c in unique_courses
        )

        return total_unique_credits + penalties

    # ─── Phase 1: Coverage-Ranked Greedy Assignment ───────────────────────────

    def _is_fc_slot(sid):
        return ("__FC-" in sid or "__FY-SEMINAR" in sid or
                "__FAD" in sid or "__INTERDISCIPLINARY" in sid)

    # Map each candidate to the list of slots it appears in
    candidate_to_slots = defaultdict(list)
    for s in slots:
        for c in s.get("candidates", []):
            candidate_to_slots[c].append(s)

    greedy_assignment = {s["slot_id"]: [] for s in slots}
    filled_slots = set()

    # Constraint state for the greedy
    prog_course_assigned = defaultdict(int)   # (prog_id, canon_id) -> number of slots in that prog
    fc_course_assigned = set()                # canon_ids already placed in an FC/FY/FAD/IDST slot
    fy_types_seen = set()                     # "FY-SEMINAR" and/or "FY-LAUNCH"

    def _pool_credits(sid):
        return sum(canon_catalog.get(c, {}).get("credits", 3) for c in greedy_assignment[sid])

    def _is_filled(s):
        sid = s["slot_id"]
        if sid in filled_slots:
            return True
        if s["type"] == "single":
            return bool(greedy_assignment[sid])
        return _pool_credits(sid) >= s.get("credits_needed", 3)

    def _mark_filled_if_done(s):
        if _is_filled(s):
            filled_slots.add(s["slot_id"])

    # Sort candidates: highest coverage first, then highest credits as tiebreaker
    sorted_candidates = sorted(
        candidate_to_slots.keys(),
        key=lambda c: (-len(candidate_to_slots[c]), -canon_catalog.get(c, {}).get("credits", 3))
    )

    # Phase 1a: assign each high-coverage candidate to every slot it qualifies for
    for c in sorted_candidates:
        is_repeatable = canon_catalog.get(c, {}).get("is_repeatable", False)
        depth = canon_catalog.get(c, {}).get("depth", 1)

        # C7: skip courses too deep to complete in time
        if depth > remaining_semesters:
            continue

        prog_assigned_this_c = set()   # programs where c has been assigned in this pass
        fc_assigned_this_c = False

        # Process required/single slots first (most critical), then pools
        slots_for_c = sorted(
            candidate_to_slots[c],
            key=lambda s: (
                0 if "__req__" in s["slot_id"] else 1,   # required slots first
                0 if s["type"] == "single" else 1,        # single before pool
                len(s.get("candidates", []))              # fewer alternatives = more critical
            )
        )

        for s in slots_for_c:
            sid = s["slot_id"]
            pid = s["program_id"]

            # C6: skip already-filled slots
            if _is_filled(s):
                continue

            # C1: one slot per program per non-repeatable course
            if not is_repeatable:
                if pid in prog_assigned_this_c:
                    continue
                if prog_course_assigned[(pid, c)] > 0:
                    continue

            # C3: FC singularity + C5: FY XOR
            if _is_fc_slot(sid):
                if fc_assigned_this_c or c in fc_course_assigned:
                    continue
                if "__FY-SEMINAR" in sid and "FY-LAUNCH" in fy_types_seen:
                    continue
                if "__FY-LAUNCH" in sid and "FY-SEMINAR" in fy_types_seen:
                    continue

            # Assign
            greedy_assignment[sid].append(c)

            if not is_repeatable:
                prog_assigned_this_c.add(pid)
                prog_course_assigned[(pid, c)] += 1

            if _is_fc_slot(sid):
                fc_assigned_this_c = True
                fc_course_assigned.add(c)
                if "__FY-SEMINAR" in sid:
                    fy_types_seen.add("FY-SEMINAR")
                elif "__FY-LAUNCH" in sid:
                    fy_types_seen.add("FY-LAUNCH")

            _mark_filled_if_done(s)

    # Phase 1b: fill any remaining empty slots with the best available candidate
    for s in slots:
        if _is_filled(s):
            continue
        sid = s["slot_id"]
        pid = s["program_id"]

        while not _is_filled(s):
            best_c = None
            best_score_t = (-1, -1)   # (prefer_3cr_flag, credits)

            for c in s.get("candidates", []):
                if c in greedy_assignment[sid]:
                    continue  # already assigned to this slot

                is_repeatable = canon_catalog.get(c, {}).get("is_repeatable", False)
                if canon_catalog.get(c, {}).get("depth", 1) > remaining_semesters:
                    continue
                if not is_repeatable and prog_course_assigned[(pid, c)] > 0:
                    continue
                if _is_fc_slot(sid):
                    if c in fc_course_assigned:
                        continue
                    if "__FY-SEMINAR" in sid and "FY-LAUNCH" in fy_types_seen:
                        continue
                    if "__FY-LAUNCH" in sid and "FY-SEMINAR" in fy_types_seen:
                        continue

                cr = canon_catalog.get(c, {}).get("credits", 3)
                has_3cr_alt = (cr < 3) and any(
                    canon_catalog.get(alt, {}).get("credits", 0) >= 3
                    for alt in s.get("candidates", []) if alt != c
                )
                score_t = (0 if has_3cr_alt else 1, cr)
                if score_t > best_score_t:
                    best_score_t = score_t
                    best_c = c

            if best_c is None:
                break  # no valid candidate; ILS will repair

            greedy_assignment[sid].append(best_c)
            is_rep = canon_catalog.get(best_c, {}).get("is_repeatable", False)
            if not is_rep:
                prog_course_assigned[(pid, best_c)] += 1
            if _is_fc_slot(sid):
                fc_course_assigned.add(best_c)
                if "__FY-SEMINAR" in sid:
                    fy_types_seen.add("FY-SEMINAR")
                elif "__FY-LAUNCH" in sid:
                    fy_types_seen.add("FY-LAUNCH")

            if s["type"] == "single":
                filled_slots.add(sid)
                break  # single slot: one assignment is sufficient
            elif _pool_credits(sid) >= s.get("credits_needed", 3):
                filled_slots.add(sid)
                # while condition exits naturally

    # ─── Phase 2: Short ILS Refinement (5 seconds) ────────────────────────────
    # Start from the greedy solution; the ILS fixes C4 edge cases and makes
    # marginal improvements without the 28-second cold-start cost.

    current_assignment = {k: list(v) for k, v in greedy_assignment.items()}
    best_score = calculate_objective(current_assignment)
    best_schedule = {k: list(v) for k, v in current_assignment.items()}

    ils_start = time.time()
    ILS_TIMEOUT = 5.0
    iterations = 0
    rng = random.Random(42)   # local seed so we don't disturb global random state

    while time.time() - ils_start < ILS_TIMEOUT:
        iterations += 1
        local_min_reached = False

        while not local_min_reached and time.time() - ils_start < ILS_TIMEOUT:
            local_min_reached = True

            for s in slots:
                sid = s["slot_id"]
                current_cands = current_assignment[sid]
                best_local_cands = current_cands
                best_local_score = calculate_objective(current_assignment)

                for cand in s.get("candidates", []):
                    test_assignment = {k: list(v) for k, v in current_assignment.items()}

                    if s["type"] == "single":
                        test_assignment[sid] = [cand]
                    elif s["type"] == "pool":
                        # C8: Erase-and-Refill Macro Move
                        pool_credits = s.get("credits_needed", 3)
                        new_pool = [cand]
                        acc_credits = canon_catalog.get(cand, {}).get("credits", 3)

                        rem_cands = [x for x in s.get("candidates", []) if x != cand]
                        for rc in rem_cands:
                            if acc_credits >= pool_credits: break
                            new_pool.append(rc)
                            acc_credits += canon_catalog.get(rc, {}).get("credits", 3)
                        test_assignment[sid] = new_pool

                    test_score = calculate_objective(test_assignment)
                    if test_score < best_local_score:
                        best_local_score = test_score
                        best_local_cands = test_assignment[sid]
                        local_min_reached = False

                current_assignment[sid] = best_local_cands

        current_score = calculate_objective(current_assignment)
        if current_score < best_score:
            best_score = current_score
            best_schedule = {k: list(v) for k, v in current_assignment.items()}

        # Perturbation
        if time.time() - ils_start < ILS_TIMEOUT:
            for sid in current_assignment.keys():
                if rng.random() < 0.10:
                    current_assignment[sid] = []

    # ─── Phase 3: Post-Processing (unchanged) ─────────────────────────────────
    final_path_set = set()
    course_to_slots_map = {}

    if best_schedule:
        for sid, assigned_canons in best_schedule.items():
            for canon in assigned_canons:
                actual_courses = macro_bindings.get(canon, [canon])
                for actual_c in actual_courses:
                    # Prefer the primary course_id (last in original_courses, always in
                    # the real catalog) over alphabetically-first cross-listed variants
                    orig = canon_catalog.get(actual_c, {}).get("original_courses", [])
                    clean_c = orig[-1] if orig else actual_c.replace("CANON_", "").split("_")[0]
                    final_path_set.add(clean_c)
                    course_to_slots_map.setdefault(clean_c, []).append(sid)

    print(f"[Engine] Greedy+ILS finished. ILS Iterations: {iterations}. Final Score: {best_score}")
    return list(final_path_set), course_to_slots_map
