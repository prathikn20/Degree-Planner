import os
import tempfile

import pandas as pd
import streamlit as st

from planner.graph import build_graph, load_catalog, load_requirements
from planner.path_generator import get_remaining_courses, kahns_algorithm
from planner.requirements_checker import check_requirements
from planner.tracker_parser import parse_tarheel_tracker

CATALOG_PATH = "data/course_catalog.json"
REQUIREMENTS_PATH = "data/degree_requirements.json"

MAJORS = [
    {"track": "Data_Science_BS",      "concentration": "None", "label": "Data Science BS"},
    {"track": "Computer_Science_BS",  "concentration": "None", "label": "Computer Science BS"},
]


def run_pipeline(pdf_path: str) -> dict:
    parsed = parse_tarheel_tracker(pdf_path)
    completed   = parsed["completed"]
    in_progress = parsed["in_progress"]

    catalog      = load_catalog(CATALOG_PATH)
    requirements = load_requirements(REQUIREMENTS_PATH)
    graph        = build_graph(catalog)

    assumed = list(dict.fromkeys(completed + in_progress))  # dedup, preserve order

    # First pass — establish each major's course footprint with no cross-dip awareness
    baseline = {}
    for m in MAJORS:
        res = check_requirements(
            requirements, catalog, assumed,
            other_majors_courses=set(),
            track_id=m["track"], concentration_id=m["concentration"]
        )
        baseline[m["track"]] = res.get("courses_used", set())

    # Second pass — full audit with double-dip + pre-flight + deficit routing
    audit = {}
    all_remaining: set[str] = set()

    for m in MAJORS:
        track = m["track"]
        conc  = m["concentration"]

        other_pool     = set()
        other_required = set()
        for other_track, courses in baseline.items():
            if other_track != track:
                other_pool.update(courses)
                other_base = requirements.get(other_track, {}).get("base_requirements", {})
                other_required.update(other_base.get("required_courses", []))

        results = check_requirements(
            requirements, catalog, assumed,
            other_majors_courses=other_pool,
            other_required_courses=other_required,
            track_id=track, concentration_id=conc
        )

        remaining = get_remaining_courses(
            results, requirements, catalog, assumed,
            track_id=track, concentration_id=conc
        )

        audit[track] = {"results": results, "remaining": remaining, "label": m["label"]}
        all_remaining.update(remaining)

    path = kahns_algorithm(graph, catalog, assumed, list(all_remaining))

    return {
        "completed":   completed,
        "in_progress": in_progress,
        "catalog":     catalog,
        "audit":       audit,
        "path":        path,
    }


def _render_audit_tab(track_label: str, results: dict) -> None:
    satisfied   = results.get("satisfied", [])
    missing     = results.get("missing_courses", {})
    unsatisfied = results.get("unsatisfied", [])

    with st.expander(f"✅ Satisfied Requirements ({len(satisfied)})", expanded=True):
        if satisfied:
            for req in satisfied:
                st.markdown(f"- ✅ **{req}**")
        else:
            st.write("No requirements satisfied yet.")

    with st.expander(f"⚠️ Unsatisfied Requirements ({len(unsatisfied)})", expanded=True):
        if missing:
            for req_id, details in missing.items():
                if isinstance(details, list):
                    st.markdown(f"- ⚠️ **{req_id}** – course not completed")
                else:
                    needed = details.get("still_needed") or details.get("credits_still_needed", 0)
                    suffix = "credits" if "credits_still_needed" in details else "courses"
                    st.markdown(f"- ⚠️ **{req_id}** – need **{needed}** more {suffix}")
        else:
            st.success("All requirements are satisfied!")


# ─── App layout ───────────────────────────────────────────────────────────────

st.set_page_config(
    page_title="UNC Tar Heel Tracker Degree Planner",
    page_icon="🐏",
    layout="wide",
)

st.title("🐏 UNC Tar Heel Tracker Degree Planner")
st.caption("Upload your Tar Heel Tracker PDF to audit your dual-major progress and generate a graduation path.")

uploaded = st.file_uploader("Upload Tar Heel Tracker PDF", type=["pdf"], label_visibility="collapsed")

if uploaded is not None:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        tmp.write(uploaded.read())
        tmp_path = tmp.name

    try:
        with st.spinner("Parsing transcript and auditing requirements…"):
            data = run_pipeline(tmp_path)
    except Exception as exc:
        st.error(f"Pipeline error: {exc}")
        st.stop()
    finally:
        os.unlink(tmp_path)

    completed   = data["completed"]
    in_progress = data["in_progress"]
    catalog     = data["catalog"]
    audit       = data["audit"]
    path        = data["path"]

    # ── Metrics ────────────────────────────────────────────────────────────────
    completed_credits   = sum(catalog.get(c, {}).get("credits", 0) for c in completed)
    in_progress_credits = sum(catalog.get(c, {}).get("credits", 0) for c in in_progress)
    total_parsed_credits = completed_credits + in_progress_credits

    c1, c2, c3 = st.columns(3)
    c1.metric("Courses Completed",   len(completed))
    c2.metric("Courses In-Progress", len(in_progress))
    c3.metric("Total Credits (Parsed)", total_parsed_credits)

    st.divider()

    # ── Per-major audit tabs ───────────────────────────────────────────────────
    tracks = [m["track"] for m in MAJORS]
    tab_labels = [audit[t]["label"] for t in tracks]
    tabs = st.tabs(tab_labels)

    for tab, track in zip(tabs, tracks):
        with tab:
            _render_audit_tab(audit[track]["label"], audit[track]["results"])

    st.divider()

    # ── Graduation path ────────────────────────────────────────────────────────
    st.subheader("📅 Suggested Graduation Path")

    path_credits = sum(catalog.get(c, {}).get("credits", 0) for c in path)
    total_projected = total_parsed_credits + path_credits

    if path:
        rows = [
            {
                "#":      i,
                "Course": course,
                "Name":   catalog.get(course, {}).get("name", "—"),
                "Credits": catalog.get(course, {}).get("credits", "?"),
            }
            for i, course in enumerate(path, 1)
        ]
        st.dataframe(
            pd.DataFrame(rows),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(f"Remaining path credits: **{path_credits}**")
    else:
        st.success("No remaining required courses — all major requirements are covered by your transcript!")

    # ── 120-hour graduation check ──────────────────────────────────────────────
    st.divider()
    UNC_MIN_CREDITS = 120
    if total_projected < UNC_MIN_CREDITS:
        deficit = UNC_MIN_CREDITS - total_projected
        st.warning(
            f"**Graduation Credit Check ⚠️** — All major requirements checked, but total credit "
            f"volume falls short of graduation minimums. Student must complete **{deficit}** "
            f"additional general elective credits to hit the UNC {UNC_MIN_CREDITS}-hour degree minimum.\n\n"
            f"*(Parsed: {total_parsed_credits} cr · Path: {path_credits} cr · "
            f"Projected total: {total_projected} cr)*"
        )
    else:
        st.success(
            f"✅ Projected total credits: **{total_projected}** — meets the UNC "
            f"{UNC_MIN_CREDITS}-hour graduation minimum."
        )
else:
    st.info("👆 Upload a Tar Heel Tracker PDF above to get started.")
