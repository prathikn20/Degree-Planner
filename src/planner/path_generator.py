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

                # Track for C3 – FC Singularity (FC-*, FY-SEMINAR, FY-LAUNCH, FAD, IDST slots)
                if ("__FC-" in sid or "__FY-SEMINAR" in sid or "__FY-LAUNCH" in sid
                        or "__FAD" in sid or "__INTERDISCIPLINARY" in sid):
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

            # Non-standard relative preference: penalize internships (93) and
            # honors (H) courses only when a standard alternative exists in the
            # same slot's original candidate pool.
            for c in assigned:
                if _is_non_standard(c):
                    if any(not _is_non_standard(alt)
                           for alt in s.get("candidates", []) if alt != c):
                        penalties += 5000

        # ── Pass 2: structural constraint penalties ───────────────────────────

        # C3 – FC Singularity: a course may satisfy AT MOST one FC/FY/FAD/IDST slot
        for c, fc_slots_list in fc_course_slots.items():
            if len(fc_slots_list) > 1:
                penalties += 5000 * (len(fc_slots_list) - 1)

        # C1 – Intra-program exclusivity: any course may fill only ONE slot per
        # program (cross-program double-counting is still encouraged).
        # Penalty exceeds C6 (10000) so the ILS never fills an empty slot with a
        # duplicate course just to avoid the C6 unfilled-slot penalty.
        for (pid, c), count in prog_course_slots.items():
            if count > 1:
                penalties += 11000 * (count - 1)

        # C5 – FY Foundation XOR + Singularity:
        # (a) plan may not contain both an FY-SEMINAR and an FY-LAUNCH simultaneously
        # (b) plan may not contain more than 1 FY-SEMINAR course or more than 1 FY-LAUNCH course
        fy_types_assigned: set = set()
        fy_seminar_count = 0
        fy_launch_count = 0
        for c, fc_slots_list in fc_course_slots.items():
            for fsl in fc_slots_list:
                if "__FY-SEMINAR" in fsl:
                    fy_seminar_count += 1
                    fy_types_assigned.add("FY-SEMINAR")
                elif "__FY-LAUNCH" in fsl:
                    fy_launch_count += 1
                    fy_types_assigned.add("FY-LAUNCH")
        if len(fy_types_assigned) > 1:
            penalties += 10000                                      # C5a: XOR
        if fy_seminar_count > 1:
            penalties += 10000 * (fy_seminar_count - 1)            # C5b: singularity
        if fy_launch_count > 1:
            penalties += 10000 * (fy_launch_count - 1)             # C5b: singularity

        # C4 – 50% Program Exclusivity Rule
        # A core slot is exclusive to P when every assigned course is absent
        # from every OTHER program's slots (program-aware, not global-count-aware).
        _all_pids_in_use = {k[0] for k in prog_course_slots}
        prog_exclusivity: dict = {}
        for s in slots:
            pid = s["program_id"]
            if pid not in prog_exclusivity:
                prog_exclusivity[pid] = {"core_total": 0, "exclusive": 0}
            if s.get("is_core") and len(s.get("candidates", [])) > 1:
                prog_exclusivity[pid]["core_total"] += 1
                assigned = assignment.get(s["slot_id"], [])
                if assigned and all(
                    all(prog_course_slots.get((other_pid, c), 0) == 0
                        for other_pid in _all_pids_in_use if other_pid != pid)
                    for c in assigned
                ):
                    prog_exclusivity[pid]["exclusive"] += 1

        for pid, stats in prog_exclusivity.items():
            if stats["core_total"] > 0 and (stats["exclusive"] * 2) <= stats["core_total"]:
                penalties += 3500

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
        return ("__FC-" in sid or "__FY-SEMINAR" in sid or "__FY-LAUNCH" in sid or
                "__FAD" in sid or "__INTERDISCIPLINARY" in sid)

    def _is_non_standard(c):
        """True for internship courses (numeric suffix ends in 93) or honors courses (end in H)."""
        cu = c.upper().replace(' ', '')
        if cu.endswith('H'):
            return True
        # Strip alphabetic prefix to get numeric suffix
        i = len(cu)
        while i > 0 and cu[i - 1].isdigit():
            i -= 1
        return cu[i:].endswith('93')

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

            # C1: one slot per program per course
            if pid in prog_assigned_this_c:
                continue
            if prog_course_assigned[(pid, c)] > 0:
                continue

            # C3: FC singularity + C5: FY XOR + C5: FY singularity
            if _is_fc_slot(sid):
                if fc_assigned_this_c or c in fc_course_assigned:
                    continue
                if "__FY-SEMINAR" in sid and "FY-LAUNCH" in fy_types_seen:
                    continue
                if "__FY-LAUNCH" in sid and "FY-SEMINAR" in fy_types_seen:
                    continue
                if "__FY-SEMINAR" in sid and "FY-SEMINAR" in fy_types_seen:
                    continue  # C5b: only 1 FY-SEMINAR allowed across entire plan
                if "__FY-LAUNCH" in sid and "FY-LAUNCH" in fy_types_seen:
                    continue  # C5b: only 1 FY-LAUNCH allowed across entire plan

            # Assign
            greedy_assignment[sid].append(c)

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

                if canon_catalog.get(c, {}).get("depth", 1) > remaining_semesters:
                    continue
                if prog_course_assigned[(pid, c)] > 0:
                    continue
                if _is_fc_slot(sid):
                    if c in fc_course_assigned:
                        continue
                    if "__FY-SEMINAR" in sid and "FY-LAUNCH" in fy_types_seen:
                        continue
                    if "__FY-LAUNCH" in sid and "FY-SEMINAR" in fy_types_seen:
                        continue
                    if "__FY-SEMINAR" in sid and "FY-SEMINAR" in fy_types_seen:
                        continue  # C5b singularity
                    if "__FY-LAUNCH" in sid and "FY-LAUNCH" in fy_types_seen:
                        continue  # C5b singularity

                # Non-standard relative preference: skip internships/honors
                # in Phase 1b when a standard candidate exists in the pool
                if _is_non_standard(c):
                    if any(not _is_non_standard(alt)
                           for alt in s.get("candidates", []) if alt != c):
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

    # ─── Phase 1c: C4 Greedy Repair ──────────────────────────────────────────────
    # Audit C4 violations after the greedy passes; repair them so ILS starts
    # from a feasible point rather than spending its budget climbing out of a
    # heavily cross-counted state.
    #
    # Uses canon_to_progs (which programs each canon appears in) rather than a
    # raw usage count, so repeatable courses filling multiple same-program slots
    # are correctly treated as exclusive (not cross-counted).

    canon_to_progs: dict = defaultdict(set)  # canon_id -> set of program_ids
    for s in slots:
        for c in greedy_assignment[s['slot_id']]:
            canon_to_progs[c].add(s['program_id'])

    for prog_id in list(dict.fromkeys(s['program_id'] for s in slots)):
        core_slots_P = [s for s in slots
                        if s['program_id'] == prog_id
                        and s.get('is_core')
                        and len(s.get('candidates', [])) > 1]
        core_total = len(core_slots_P)
        if core_total == 0:
            continue

        while True:
            # Slot is exclusive to P iff every assigned canon appears ONLY in P's slots.
            exclusive_count = sum(
                1 for s in core_slots_P
                if greedy_assignment[s['slot_id']]
                and all(canon_to_progs[c] == {prog_id}
                        for c in greedy_assignment[s['slot_id']])
            )
            if exclusive_count * 2 > core_total:
                break  # C4 satisfied for this program

            target_canon = None
            best_max_alts = -1
            for s in core_slots_P:
                for c in greedy_assignment[s['slot_id']]:
                    if len(canon_to_progs[c]) <= 1:
                        continue  # already exclusive to P (or unset)
                    # Only target canons removable from foreign slots that have
                    # genuine alternatives (skip single-candidate required slots).
                    foreign_with_c = [
                        fs for fs in slots
                        if fs['program_id'] != prog_id
                        and c in greedy_assignment[fs['slot_id']]
                        and len(fs.get('candidates', [])) > 1
                    ]
                    if not foreign_with_c:
                        continue
                    max_alts = max(len(fs.get('candidates', [])) for fs in foreign_with_c)
                    if max_alts > best_max_alts:
                        best_max_alts = max_alts
                        target_canon = c

            if target_canon is None:
                break  # can't fix further; ILS will handle

            newly_unfilled = []
            for s in slots:
                if s['program_id'] == prog_id:
                    continue
                if len(s.get('candidates', [])) <= 1:
                    continue  # never touch single-candidate (required) slots
                sid = s['slot_id']
                if target_canon not in greedy_assignment[sid]:
                    continue
                greedy_assignment[sid].remove(target_canon)
                canon_to_progs[target_canon].discard(s['program_id'])
                filled_slots.discard(sid)
                if _is_filled(s):
                    filled_slots.add(sid)
                else:
                    newly_unfilled.append(s)

            for s in newly_unfilled:
                sid = s['slot_id']
                pid_s = s['program_id']
                while not _is_filled(s):
                    best_c = None
                    best_score_t = (-1, -1)
                    for c in s.get('candidates', []):
                        if c in greedy_assignment[sid]:
                            continue
                        if canon_catalog.get(c, {}).get('depth', 1) > remaining_semesters:
                            continue
                        if prog_course_assigned[(pid_s, c)] > 0:
                            continue
                        if _is_fc_slot(sid):
                            if c in fc_course_assigned:
                                continue
                            if '__FY-SEMINAR' in sid and 'FY-LAUNCH' in fy_types_seen:
                                continue
                            if '__FY-LAUNCH' in sid and 'FY-SEMINAR' in fy_types_seen:
                                continue
                            if '__FY-SEMINAR' in sid and 'FY-SEMINAR' in fy_types_seen:
                                continue  # C5b singularity
                            if '__FY-LAUNCH' in sid and 'FY-LAUNCH' in fy_types_seen:
                                continue  # C5b singularity
                        # Non-standard relative preference: skip internships/honors
                        # in Phase 1c repair when a standard candidate exists in pool
                        if _is_non_standard(c):
                            if any(not _is_non_standard(alt)
                                   for alt in s.get('candidates', []) if alt != c):
                                continue

                        cr = canon_catalog.get(c, {}).get('credits', 3)
                        has_3cr_alt = (cr < 3) and any(
                            canon_catalog.get(alt, {}).get('credits', 0) >= 3
                            for alt in s.get('candidates', []) if alt != c
                        )
                        score_t = (0 if has_3cr_alt else 1, cr)
                        if score_t > best_score_t:
                            best_score_t = score_t
                            best_c = c
                    if best_c is None:
                        break
                    greedy_assignment[sid].append(best_c)
                    prog_course_assigned[(pid_s, best_c)] += 1
                    if _is_fc_slot(sid):
                        fc_course_assigned.add(best_c)
                        if '__FY-SEMINAR' in sid:
                            fy_types_seen.add('FY-SEMINAR')
                        elif '__FY-LAUNCH' in sid:
                            fy_types_seen.add('FY-LAUNCH')
                    canon_to_progs[best_c].add(pid_s)
                    if s['type'] == 'single':
                        filled_slots.add(sid)
                        break
                    elif _pool_credits(sid) >= s.get('credits_needed', 3):
                        filled_slots.add(sid)

    # ─── Phase 2: Short ILS Refinement (15 seconds) ───────────────────────────
    # Start from the greedy solution; the ILS fixes C4 edge cases and makes
    # marginal improvements without the 28-second cold-start cost.

    current_assignment = {k: list(v) for k, v in greedy_assignment.items()}
    best_score = calculate_objective(current_assignment)
    best_schedule = {k: list(v) for k, v in current_assignment.items()}

    ils_start = time.time()
    ILS_TIMEOUT = 15.0
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

    # Guard: remove courses absent from the canon catalog (happens when
    # requirements.json references a course not yet in course_catalog.json).
    valid_codes = {
        orig
        for data in canon_catalog.values()
        for orig in data.get("original_courses", [])
    }
    final_path_set = {c for c in final_path_set if c in valid_codes}
    course_to_slots_map = {c: v for c, v in course_to_slots_map.items() if c in valid_codes}

    print(f"[Engine] Greedy+ILS finished. ILS Iterations: {iterations}. Final Score: {best_score}")
    return list(final_path_set), course_to_slots_map
