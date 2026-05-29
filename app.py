import io
import os
import tempfile

import pandas as pd
import streamlit as st

from planner.graph import build_graph, load_catalog, load_requirements
from planner.path_generator import get_remaining_courses, kahns_algorithm
from planner.requirements_checker import check_requirements
from planner.tracker_parser import parse_tarheel_tracker

CATALOG_PATH      = "data/course_catalog.json"
REQUIREMENTS_PATH = "data/degree_requirements.json"
UNC_MIN_CREDITS   = 120


# ── Cached data loading ────────────────────────────────────────────────────────

@st.cache_resource
def load_static_data():
    catalog      = load_catalog(CATALOG_PATH)
    requirements = load_requirements(REQUIREMENTS_PATH)
    graph        = build_graph(catalog)
    return catalog, requirements, graph


# ── Helpers ────────────────────────────────────────────────────────────────────

def fmt(key: str) -> str:
    """'Computer_Science_BS' → 'Computer Science BS'."""
    return key.replace("_", " ")


def is_minor(track_id: str) -> bool:
    """Classify a requirements key as a minor by convention: 'minor' anywhere in the name."""
    return "minor" in track_id.lower()


def available_concentrations(requirements: dict, track: str) -> list[str]:
    concs = list(requirements.get(track, {}).get("concentrations", {}).keys())
    return concs if concs else ["None"]


def has_real_concentrations(concs: list[str]) -> bool:
    return any(c != "None" for c in concs)


def _concentration_widget(requirements: dict, track: str, key: str) -> str:
    """Render a concentration selectbox only when real options exist; otherwise return 'None'."""
    concs = available_concentrations(requirements, track)
    if has_real_concentrations(concs):
        return st.selectbox("Concentration", options=concs, format_func=fmt, key=key)
    return "None"


# ── Pipeline ───────────────────────────────────────────────────────────────────

def run_pipeline(
    pdf_path: str,
    majors_to_check: list[dict],
    catalog: dict,
    requirements: dict,
    graph: dict,
    planned_courses: list[str] | None = None,
    avoid_courses:   list[str] | None = None,
) -> dict:
    parsed      = parse_tarheel_tracker(pdf_path)
    completed   = parsed["completed"]
    in_progress = parsed["in_progress"]

    planned  = list(planned_courses or [])
    avoid    = list(avoid_courses   or [])
    # Deduplicate while preserving order; planned courses sit at the end so they
    # are clearly distinguishable from the transcript in the returned data.
    assumed  = list(dict.fromkeys(completed + in_progress + planned))

    # Pass 1 — each program in isolation to establish its course footprint
    baseline: dict[str, set] = {}
    for m in majors_to_check:
        res = check_requirements(
            requirements, catalog, assumed,
            other_majors_courses=set(),
            avoid_courses=avoid,
            track_id=m["track"], concentration_id=m["concentration"],
        )
        baseline[m["track"]] = res.get("courses_used", set())

    # Pass 2 — full cross-dip / pre-flight / deficit-routing audit
    audit: dict[str, dict] = {}
    all_remaining: set[str] = set()

    for m in majors_to_check:
        track, conc = m["track"], m["concentration"]

        other_pool:     set[str] = set()
        other_required: set[str] = set()
        for other_track, courses in baseline.items():
            if other_track != track:
                other_pool.update(courses)
                other_base = requirements.get(other_track, {}).get("base_requirements", {})
                other_required.update(other_base.get("required_courses", []))

        results = check_requirements(
            requirements, catalog, assumed,
            other_majors_courses=other_pool,
            other_required_courses=other_required,
            avoid_courses=avoid,
            track_id=track, concentration_id=conc,
        )
        remaining = get_remaining_courses(
            results, requirements, catalog, assumed,
            avoid_courses=avoid,
            track_id=track, concentration_id=conc,
        )

        audit[track] = {"results": results, "remaining": remaining}
        all_remaining.update(remaining)

    path = kahns_algorithm(graph, catalog, assumed, list(all_remaining))

    return {
        "completed":   completed,
        "in_progress": in_progress,
        "planned":     planned,
        "audit":       audit,
        "path":        path,
    }


# ── Prerequisite graph builder ────────────────────────────────────────────────

def build_prereq_dot(
    path: list[str],
    catalog: dict,
    assumed_completed: list[str],
    in_progress: list[str],
) -> str:
    import re as _re

    completed_set = set(assumed_completed)
    in_prog_set   = set(in_progress)
    remaining_set = set(path)

    visible: set[str] = set(path)
    edges: list[tuple[str, str]] = []

    for course in path:
        pathways = catalog.get(course, {}).get("prerequisites", [])
        if not pathways:
            continue
        # Prefer the prereq pathway that overlaps most with what the student already has
        completed_paths = [p for p in pathways if any(c in completed_set for c in p)]
        best = min(completed_paths or pathways, key=len)
        for prereq in best:
            if prereq in completed_set or prereq in remaining_set:
                visible.add(prereq)
                edges.append((prereq, course))

    def _node(c: str) -> str:
        name = catalog.get(c, {}).get("name", "")
        short = (name[:20] + "…") if len(name) > 20 else name
        label = f"{c}\\n{short}" if short else c
        # Escape any double-quotes inside the label
        label = label.replace('"', '\\"')
        if c in in_prog_set:
            fill, border = "#FFD966", "#7d6608"   # amber  – in progress
        elif c in completed_set:
            fill, border = "#93C47D", "#2d5f2d"   # green  – completed
        else:
            fill, border = "#6FA8DC", "#1a4a6b"   # blue   – still needed
        return (
            f'    "{c}" [label="{label}", fillcolor="{fill}", '
            f'color="{border}", penwidth=1.5];'
        )

    lines = [
        "digraph {",
        '    rankdir=LR;',
        '    graph [bgcolor="transparent", pad="0.3", nodesep="0.4", ranksep="0.7"];',
        '    node [shape=box, style="filled,rounded", fontname="Helvetica", fontsize=9];',
        '    edge [color="#666666", arrowsize=0.7];',
    ]
    for node in sorted(visible):
        lines.append(_node(node))
    for src, dst in edges:
        lines.append(f'    "{src}" -> "{dst}";')
    lines.append("}")
    return "\n".join(lines)


# ── Per-program audit renderer ─────────────────────────────────────────────────

def render_audit(
    results: dict,
    double_dipped: set | None = None,
    path: list | None = None,
    catalog: dict | None = None,
    planned: list | None = None,
) -> None:
    satisfied     = results.get("satisfied", [])
    missing       = results.get("missing_courses", {})
    unsatisfied   = results.get("unsatisfied", [])
    satisfied_map = results.get("satisfied_map", {})
    double_dipped = double_dipped or set()
    path_set      = set(path or [])
    planned_set   = set(planned or [])
    catalog       = catalog or {}

    def _course_chip(code: str) -> str:
        name = catalog.get(code, {}).get("name", "")
        suffix = " _(planned)_" if code in planned_set else ""
        return f"**{code}**" + (f" — {name}" if name else "") + suffix

    with st.expander(f"✅ Satisfied Requirements ({len(satisfied)})", expanded=False):
        if satisfied:
            for req in satisfied:
                courses_used = satisfied_map.get(req, [])
                is_dipped    = any(c in double_dipped for c in courses_used)
                badge        = " `[Double-Dipped]`" if is_dipped else ""
                if courses_used:
                    fulfilled = ", ".join(_course_chip(c) for c in courses_used)
                    st.markdown(f"- ✅ **{req}** — Fulfilled by: {fulfilled}{badge}")
                else:
                    st.markdown(f"- ✅ **{req}**{badge}")
        else:
            st.write("No requirements satisfied yet.")

    with st.expander(f"❌ Unsatisfied Requirements ({len(unsatisfied)})", expanded=True):
        if missing:
            for req_id, details in missing.items():
                if isinstance(details, list):
                    # Required course — no alternatives, must take this specific one
                    st.markdown(f"- ❌ **{req_id}** — Required but not yet completed")
                else:
                    needed  = details.get("still_needed") or details.get("credits_still_needed", 0)
                    suffix  = "credits" if "credits_still_needed" in details else "course(s)"
                    options = details.get("options", [])

                    # Recommended = first option already in Kahn's path
                    recommended  = next((o for o in options if o in path_set), None)
                    alternatives = [o for o in options if o != recommended][:3]

                    rec_part = f" — Recommended: **{recommended}**" if recommended else f" — Need **{needed}** more {suffix}"
                    alt_part = (
                        f" *(Alternatives: {', '.join(alternatives)})*"
                        if alternatives and recommended else ""
                    )
                    st.markdown(f"- ❌ **{req_id}**{rec_part}{alt_part}")
        else:
            st.success("All requirements are satisfied!")


# ══════════════════════════════════════════════════════════════════════════════
# App layout
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="UNC Tar Heel Tracker Degree Planner",
    page_icon="🐏",
    layout="wide",
)

catalog, requirements, graph = load_static_data()
all_tracks    = list(requirements.keys())
# Gen ed is always checked automatically — exclude from selectable program dropdowns
GEN_ED_TRACK  = "UNC_General_Education"
major_tracks  = [t for t in all_tracks if not is_minor(t) and t != GEN_ED_TRACK]
minor_tracks  = [t for t in all_tracks if is_minor(t) and t != GEN_ED_TRACK]


# ── Sidebar — degree configuration ────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Degree Configuration")
    st.caption("Select programs, then upload your transcript.")

    # ─── Majors ───────────────────────────────────────────────────────────────
    st.subheader("🎓 Majors")

    major1 = st.selectbox(
        "Primary Major",
        options=major_tracks,
        format_func=fmt,
        key="major1",
        label_visibility="collapsed",
    )
    conc1 = _concentration_widget(requirements, major1, key="conc1")

    dual = st.toggle("Add Second Major", key="dual")
    major2, conc2 = None, None
    if dual:
        default_idx = 1 if len(major_tracks) > 1 else 0
        major2 = st.selectbox(
            "Second Major",
            options=major_tracks,
            format_func=fmt,
            index=default_idx,
            key="major2",
            label_visibility="collapsed",
        )
        conc2 = _concentration_widget(requirements, major2, key="conc2")
        if major2 == major1 and conc2 == conc1:
            st.warning("Primary and second major are identical — select different programs.")
            dual, major2, conc2 = False, None, None

    st.divider()

    # ─── Minors ───────────────────────────────────────────────────────────────
    st.subheader("📖 Minors")

    minor1, minor2 = None, None
    add_minor1 = add_minor2 = False

    if not minor_tracks:
        st.caption("No minors available in requirements data yet.")
    else:
        add_minor1 = st.toggle("Add a Minor", key="add_minor1")

        if add_minor1:
            minor1 = st.selectbox(
                "First Minor",
                options=minor_tracks,
                format_func=fmt,
                key="minor1",
                label_visibility="collapsed",
            )

            # Constraint: 2 majors + 2 minors is not allowed.
            # Disable "Add Second Minor" when a second major is active.
            second_minor_blocked = dual  # bool
            add_minor2_raw = st.toggle(
                "Add Second Minor",
                key="add_minor2",
                disabled=second_minor_blocked,
                help="Requires only 1 major (rule: max 2 majors + 1 minor, or 1 major + 2 minors).",
            )
            # Guard: if dual was enabled AFTER add_minor2 was set True, the widget is
            # disabled but session state still holds True — override here.
            add_minor2 = add_minor2_raw and not second_minor_blocked

            if add_minor2:
                default_m2 = 1 if len(minor_tracks) > 1 else 0
                minor2 = st.selectbox(
                    "Second Minor",
                    options=minor_tracks,
                    format_func=fmt,
                    index=default_m2,
                    key="minor2",
                    label_visibility="collapsed",
                )
                if minor2 == minor1:
                    st.warning("Both minors are identical — select different programs.")
                    add_minor2, minor2 = False, None

    st.divider()

    # ─── What-If Scenarios ────────────────────────────────────────────────────
    with st.expander("🔮 What-If Scenarios", expanded=False):
        st.caption("Simulate future courses or block specific recommendations.")

        import re as _re
        def _course_label(c: str) -> str:
            name = catalog.get(c, {}).get("name", "")
            # Include both "STOR435" and "STOR 435" forms so either search works
            spaced = _re.sub(r'([A-Z]{2,4})(\d{3,4}[A-Z]?)', r'\1 \2', c)
            display = spaced if spaced != c else c
            return f"{display} — {name[:42]}" if name else display

        planned_courses: list[str] = st.multiselect(
            "Planned Courses (simulate taking these)",
            options=sorted(catalog.keys()),
            format_func=_course_label,
            key="planned_courses",
            placeholder="Type a course ID or name…",
        )

        avoid_courses: list[str] = st.multiselect(
            "Courses to Avoid (do not recommend these)",
            options=sorted(catalog.keys()),
            format_func=_course_label,
            key="avoid_courses",
            placeholder="Type a course ID or name…",
        )

    st.divider()

    # ─── Configuration summary ────────────────────────────────────────────────
    n_majors = 1 + (1 if dual and major2 else 0)
    n_minors = (1 if add_minor1 and minor1 else 0) + (1 if add_minor2 and minor2 else 0)
    st.caption(f"📋 **{n_majors}** major(s) + **{n_minors}** minor(s) + General Education (always)")


# ── Build generic majors_to_check list (drives all pipeline + UI) ─────────────
majors_to_check: list[dict] = [{"track": major1, "concentration": conc1}]
if dual and major2:
    majors_to_check.append({"track": major2, "concentration": conc2})
if add_minor1 and minor1:
    majors_to_check.append({"track": minor1, "concentration": "None"})
if add_minor2 and minor2:
    majors_to_check.append({"track": minor2, "concentration": "None"})
# Gen ed is always checked for every UNC student
majors_to_check.append({"track": GEN_ED_TRACK, "concentration": "None"})


# ── Main area ──────────────────────────────────────────────────────────────────
st.title("🐏 UNC Tar Heel Tracker Degree Planner")
degree_label = " + ".join(fmt(m["track"]) for m in majors_to_check if m["track"] != GEN_ED_TRACK)
st.caption(f"Auditing: **{degree_label}** + UNC General Education — upload your Tar Heel Tracker PDF below.")

uploaded = st.file_uploader(
    "Upload Tar Heel Tracker PDF",
    type=["pdf"],
    label_visibility="collapsed",
)

if uploaded is not None:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(uploaded.read())
        tmp_path = tmp.name

    try:
        with st.spinner("Parsing transcript and auditing requirements…"):
            data = run_pipeline(
                tmp_path, majors_to_check, catalog, requirements, graph,
                planned_courses=planned_courses,
                avoid_courses=avoid_courses,
            )
    except Exception as exc:
        st.error(f"Pipeline error: {exc}")
        st.stop()
    finally:
        os.unlink(tmp_path)

    completed   = data["completed"]
    in_progress = data["in_progress"]
    planned     = data["planned"]
    audit       = data["audit"]
    path        = data["path"]

    # ── Metrics ────────────────────────────────────────────────────────────────
    completed_credits    = sum(catalog.get(c, {}).get("credits", 0) for c in completed)
    in_progress_credits  = sum(catalog.get(c, {}).get("credits", 0) for c in in_progress)
    planned_credits      = sum(catalog.get(c, {}).get("credits", 0) for c in planned)
    total_parsed_credits = completed_credits + in_progress_credits

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Courses Completed",   len(completed))
    mc2.metric("Courses In-Progress", len(in_progress))
    mc3.metric(
        "Planned (What-If)",
        len(planned),
        delta=f"+{planned_credits} cr" if planned else None,
        delta_color="normal",
    )
    mc4.metric("Total Credits (Parsed)", total_parsed_credits)

    if in_progress:
        with st.expander(f"📘 In-Progress Courses ({len(in_progress)}) — counted as satisfied", expanded=True):
            st.caption(
                "These courses are currently being taken and are counted toward your requirements. "
                "They will not appear in the graduation path."
            )
            for c in in_progress:
                name = catalog.get(c, {}).get("name", "Unknown course")
                cr   = catalog.get(c, {}).get("credits", "?")
                st.markdown(f"- **{c}** — {name} ({cr} cr)")

    if planned:
        # Build impact map: which requirements does each planned course fulfill?
        planned_impact: dict[str, list[tuple[str, str]]] = {}
        for m in majors_to_check:
            if m["track"] not in audit:
                continue
            sat_map = audit[m["track"]]["results"].get("satisfied_map", {})
            for req_id, courses in sat_map.items():
                for c in courses:
                    if c in set(planned):
                        planned_impact.setdefault(c, []).append((fmt(m["track"]), req_id))

        with st.expander(f"🔮 Planned Courses Impact ({len(planned)})", expanded=True):
            st.caption("Simulated as completed. Shows which requirements each planned course fulfills.")
            for c in planned:
                name    = catalog.get(c, {}).get("name", "Unknown course")
                cr      = catalog.get(c, {}).get("credits", "?")
                impacts = planned_impact.get(c, [])
                if impacts:
                    impact_str = " &nbsp;·&nbsp; ".join(
                        f"**{track}** → `{req}`" for track, req in impacts
                    )
                    st.markdown(f"- **{c}** — {name} ({cr} cr) → {impact_str}")
                else:
                    st.markdown(
                        f"- **{c}** — {name} ({cr} cr) "
                        f"_(satisfies no currently-tracked requirement)_"
                    )

    st.divider()

    # ── Global progress bar (all programs combined) ────────────────────────────
    total_req_all = sum(
        audit[m["track"]]["results"].get("total_requirements", 0)
        for m in majors_to_check if m["track"] in audit
    )
    total_sat_all = sum(
        audit[m["track"]]["results"].get("total_satisfied", 0)
        for m in majors_to_check if m["track"] in audit
    )
    global_pct = total_sat_all / total_req_all if total_req_all else 0.0
    st.subheader("📊 Overall Degree Progress")
    gcol1, gcol2 = st.columns([5, 1])
    with gcol1:
        st.progress(min(global_pct, 1.0))
    with gcol2:
        st.metric("Overall", f"{global_pct:.0%}")
    st.caption(
        f"{total_sat_all} of {total_req_all} requirements satisfied across all programs"
    )

    st.divider()

    # ── Per-program audit tabs — loop-driven over majors_to_check ─────────────
    def _tab_label(m: dict) -> str:
        if m["track"] == GEN_ED_TRACK:
            return "🎓 General Education"
        label = fmt(m["track"])
        if m["concentration"] != "None":
            label += f" — {fmt(m['concentration'])}"
        return label

    tab_labels = [_tab_label(m) for m in majors_to_check]
    tabs = st.tabs(tab_labels)

    # Build cross-track double-dip map: for each track, which courses were also
    # used by at least one other track in this session?
    all_used: dict[str, set] = {
        m["track"]: audit[m["track"]]["results"].get("courses_used", set())
        for m in majors_to_check
        if m["track"] in audit
    }

    def _double_dipped_for(track: str) -> set:
        others = set().union(*(u for t, u in all_used.items() if t != track))
        return all_used.get(track, set()) & others

    for tab, program in zip(tabs, majors_to_check):
        with tab:
            track_data = audit.get(program["track"])
            if track_data:
                pct = track_data["results"].get("completion_pct", 0.0)
                satisfied_n = len(track_data["results"].get("satisfied", []))
                total_n     = satisfied_n + len(track_data["results"].get("unsatisfied", []))
                pcol1, pcol2 = st.columns([5, 1])
                with pcol1:
                    st.progress(min(pct, 1.0))
                with pcol2:
                    st.metric("Complete", f"{pct:.0%}")
                st.caption(f"{satisfied_n} of {total_n} requirements satisfied")
                render_audit(
                    track_data["results"],
                    double_dipped=_double_dipped_for(program["track"]),
                    path=path,
                    catalog=catalog,
                    planned=planned,
                )
            else:
                st.warning(f"No audit data found for {fmt(program['track'])}.")

    st.divider()

    # ── Graduation path ────────────────────────────────────────────────────────
    st.subheader("📅 Suggested Graduation Path")

    path_credits    = sum(catalog.get(c, {}).get("credits", 3) for c in path)
    total_projected = total_parsed_credits + planned_credits + path_credits

    if path:
        unknown_in_path = [c for c in path if c not in catalog]

        # ── Prerequisite graph ─────────────────────────────────────────────────
        assumed_for_graph = list(dict.fromkeys(completed + in_progress + planned))
        with st.expander("🕸️ Visualize Prerequisite Path", expanded=False):
            st.caption(
                "🟢 **Green** = already completed &nbsp;|&nbsp; "
                "🟡 **Amber** = in-progress this semester &nbsp;|&nbsp; "
                "🔵 **Blue** = still needed &nbsp;|&nbsp; "
                "Arrows show prerequisite dependencies."
            )
            dot_src = build_prereq_dot(path, catalog, assumed_for_graph, in_progress)
            st.graphviz_chart(dot_src, use_container_width=True)

        # ── Course table ───────────────────────────────────────────────────────
        rows = [
            {
                "#":       i,
                "Course":  course,
                "Name":    catalog.get(course, {}).get("name", "—"),
                "Credits": catalog.get(course, {}).get("credits", 3),
            }
            for i, course in enumerate(path, 1)
        ]
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        st.caption(f"Remaining path credits: **{path_credits}**")
        if unknown_in_path:
            st.warning(
                f"⚠️ {len(unknown_in_path)} course(s) in the path are not in the catalog "
                f"and assumed 3 credits: {', '.join(unknown_in_path)}"
            )

        # ── Export CSV ─────────────────────────────────────────────────────────
        csv_buf = io.StringIO()
        csv_buf.write("Course Code,Course Name,Credits\n")
        for row in rows:
            name_escaped = row["Name"].replace('"', '""')
            csv_buf.write(f'"{row["Course"]}","{name_escaped}",{row["Credits"]}\n')

        st.download_button(
            label="📥 Download Graduation Plan",
            data=csv_buf.getvalue().encode("utf-8"),
            file_name="graduation_plan.csv",
            mime="text/csv",
            use_container_width=True,
        )
    else:
        st.success("No remaining required courses — all requirements are covered by your transcript!")

    # ── 120-hour graduation check ──────────────────────────────────────────────
    st.divider()
    st.subheader("🎓 Credit Progress")
    credit_pct = min(total_projected / UNC_MIN_CREDITS, 1.0)
    ccol1, ccol2 = st.columns([5, 1])
    with ccol1:
        st.progress(credit_pct)
    with ccol2:
        st.metric("Credits", f"{total_projected} / {UNC_MIN_CREDITS}")
    st.caption(
        f"Parsed: **{total_parsed_credits}** cr &nbsp;·&nbsp; "
        f"Path: **{path_credits}** cr &nbsp;·&nbsp; "
        f"Planned (What-If): **{planned_credits}** cr &nbsp;·&nbsp; "
        f"Projected total: **{total_projected}** cr"
    )
    if total_projected < UNC_MIN_CREDITS:
        deficit = UNC_MIN_CREDITS - total_projected
        st.warning(
            f"**{deficit} credits short** of the UNC {UNC_MIN_CREDITS}-hour graduation minimum. "
            f"Complete additional general electives to close the gap."
        )
    else:
        st.success(f"✅ Projected total meets the UNC {UNC_MIN_CREDITS}-hour graduation minimum.")

    # ── Developer Audit Log ────────────────────────────────────────────────────
    import json as _json
    with st.expander("🛠 Developer Audit Log", expanded=False):
        st.caption("Raw output from `check_requirements()` for each program.")
        for m in majors_to_check:
            track = m["track"]
            if track in audit:
                raw = audit[track]["results"].copy()
                raw["courses_used"] = sorted(raw.get("courses_used", set()))
                st.markdown(f"**{fmt(track)}**")
                st.json(raw)

else:
    st.info("👆 Upload a Tar Heel Tracker PDF above to get started.")
