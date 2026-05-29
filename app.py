import datetime
import io
import json
import os
import re as _re
import tempfile
from collections import Counter

import pandas as pd
import streamlit as st

from src.planner.graph import build_graph, load_catalog, load_requirements
from src.planner.path_generator import kahns_algorithm, select_courses_globally
from src.planner.requirements_checker import check_requirements, get_rule_based_options
from src.planner.tracker_parser import parse_tarheel_tracker

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


# ── Feedback persistence ───────────────────────────────────────────────────────

@st.cache_resource
def _get_feedback_sheet():
    """Return the first worksheet of the feedback Google Sheet.
    Cached for the lifetime of the server process so we only authenticate once.
    Raises if gcp_service_account secrets are not configured."""
    import gspread
    gc = gspread.service_account_from_dict(dict(st.secrets["gcp_service_account"]))
    ws = gc.open_by_key(st.secrets["FEEDBACK_SHEET_ID"]).sheet1
    if not ws.get_all_values():
        ws.append_row(["Timestamp", "Type", "Title", "Description", "Email"])
    return ws


def _write_feedback(entry: dict) -> None:
    """Write one feedback entry to Google Sheets when secrets are present,
    otherwise fall back to logs/feedback.json for local development."""
    if "gcp_service_account" in st.secrets:
        ws = _get_feedback_sheet()
        ws.append_row([
            entry["timestamp"],
            entry["type"],
            entry["title"],
            entry["description"],
            entry.get("email") or "",
        ])
    else:
        _fb_path = "logs/feedback.json"
        _existing: list = []
        if os.path.exists(_fb_path):
            try:
                with open(_fb_path) as _f:
                    _existing = json.load(_f)
            except Exception:
                _existing = []
        _existing.append(entry)
        _tmp = _fb_path + ".tmp"
        with open(_tmp, "w") as _f:
            json.dump(_existing, _f, indent=2)
        os.replace(_tmp, _fb_path)


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
    planned_courses:      list[str] | None = None,
    avoid_courses:        list[str] | None = None,
    explicitly_requested: list[str] | None = None,
) -> dict:
    parsed      = parse_tarheel_tracker(pdf_path)
    completed   = parsed["completed"]
    in_progress = parsed["in_progress"]

    planned  = list(planned_courses or [])
    avoid    = list(avoid_courses   or [])
    assumed  = list(dict.fromkeys(completed + in_progress))

    # Planned courses are treated like explicit swap requests: they are
    # prioritised by the greedy selector and appear in the graduation path
    # rather than being counted as already completed.
    _all_requested = list(dict.fromkeys(list(explicitly_requested or []) + planned))

    # Pass 1 — requirements audit (each program uses its own consumption pool so
    # cross-program double-dipping is structurally allowed at the checker level).
    results_by_track: dict[str, dict] = {}
    for m in majors_to_check:
        track, conc = m["track"], m["concentration"]
        results_by_track[track] = check_requirements(
            requirements, catalog, assumed,
            avoid_courses=avoid,
            track_id=track, concentration_id=conc,
        )

    # Pass 2 — global cross-program course selection with Lazy Exclusivity.
    # Greedily maximises inter-program double-dipping while ensuring each
    # program retains a strict majority (>50%) of exclusive slots/credits.
    selections = select_courses_globally(
        results_by_track, requirements, catalog, assumed,
        majors_to_check, avoid_courses=avoid,
        explicitly_requested=_all_requested,
    )

    audit: dict[str, dict] = {}
    all_remaining: set[str] = set()
    for m in majors_to_check:
        track = m["track"]
        remaining, fulfillment_map = selections[track]
        audit[track] = {
            "results":         results_by_track[track],
            "remaining":       remaining,
            "fulfillment_map": fulfillment_map,
        }
        all_remaining.update(remaining)

    # UNC rule: a student may only enroll in 1 FY-SEMINAR course ever.
    # Because many FY-SEMINAR courses carry additional gen-ed attributes
    # (e.g. FC-NATSCI), the sequential requirements checker can consume one
    # for FC-NATSCI and then demand a second for the FY-SEMINAR group.
    # Keep only the most attribute-rich FY-SEMINAR (maximises gen-ed overlap),
    # drop the rest before handing off to the path generator.
    _fy_in_remaining = sorted(
        [c for c in all_remaining if "FY-SEMINAR" in catalog.get(c, {}).get("attributes", [])],
        key=lambda c: -len(catalog.get(c, {}).get("attributes", [])),
    )
    for _extra_fy in _fy_in_remaining[1:]:
        all_remaining.discard(_extra_fy)

    # Build per-track sets so Kahn's can prioritise courses that satisfy the
    # most distinct programs (inter-major overlaps get scheduled first).
    remaining_per_track = {track: set(data["remaining"]) for track, data in audit.items()}
    path = kahns_algorithm(graph, catalog, assumed, list(all_remaining), remaining_per_track=remaining_per_track)

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
    completed_set = set(assumed_completed)
    in_prog_set   = set(in_progress)

    edges: list[tuple[str, str]] = []

    for course in path:
        pathways = catalog.get(course, {}).get("prerequisites", [])
        if not pathways:
            continue
        completed_paths = [p for p in pathways if any(c in completed_set for c in p)]
        best = min(completed_paths or pathways, key=len)
        for prereq in best:
            edges.append((prereq, course))

    # Only show nodes that participate in at least one edge — this prevents
    # isolated no-prereq courses from stretching the top rank.
    nodes_with_edges: set[str] = set()
    for src, dst in edges:
        nodes_with_edges.add(src)
        nodes_with_edges.add(dst)

    def _node(c: str) -> str:
        name  = catalog.get(c, {}).get("name", "")
        short = (name[:26] + "…") if len(name) > 26 else name
        # Use \n between code and name so boxes grow tall, not wide
        label = f"{c}\\n{short}" if short else c
        label = label.replace('"', '\\"')
        if c in in_prog_set:
            fill, border = "#FFD966", "#7d6608"
        elif c in completed_set:
            fill, border = "#93C47D", "#2d5f2d"
        else:
            fill, border = "#6FA8DC", "#1a4a6b"
        return (
            f'    "{c}" [label="{label}", fillcolor="{fill}", '
            f'color="{border}", penwidth=1.6];'
        )

    lines = [
        "digraph {",
        '    rankdir=TB;',
        '    graph [bgcolor="transparent", pad="0.4", nodesep="0.5", ranksep="1.0", splines="ortho"];',
        '    node [shape=box, style="filled,rounded", fontname="Helvetica", fontsize=11];',
        '    edge [color="#555555", arrowsize=0.8, penwidth=1.2];',
    ]
    for node in sorted(nodes_with_edges):
        lines.append(_node(node))
    for src, dst in edges:
        lines.append(f'    "{src}" -> "{dst}";')
    lines.append("}")
    return "\n".join(lines)


# ── Per-program audit renderer ─────────────────────────────────────────────────

def render_audit(
    results: dict,
    path: list | None = None,
    catalog: dict | None = None,
    planned: list | None = None,
    global_course_usage: dict | None = None,
    req_descriptions: dict | None = None,
) -> None:
    satisfied     = results.get("satisfied", [])
    missing       = results.get("missing_courses", {})
    unsatisfied   = results.get("unsatisfied", [])
    satisfied_map = results.get("satisfied_map", {})
    path_set      = set(path or [])
    planned_set   = set(planned or [])
    catalog       = catalog or {}
    usage         = global_course_usage or {}
    descriptions  = req_descriptions or {}

    def _spaced(code: str) -> str:
        return _re.sub(r'([A-Z]{2,4})(\d{3,4}[A-Z]?)', r'\1 \2', code)

    def _req_header(req_id: str) -> str:
        name = descriptions.get(req_id, "")
        return f"**{req_id}** — {name}" if name and name != req_id else f"**{req_id}**"

    with st.expander(f"✅ Satisfied Requirements ({len(satisfied)})", expanded=False):
        if satisfied:
            for req in satisfied:
                courses_used = satisfied_map.get(req, [])
                if courses_used:
                    chips      = []
                    is_double  = False
                    for c in courses_used:
                        suffix = " _(planned)_" if c in planned_set else ""
                        chips.append(f"**{_spaced(c)}**{suffix}")
                        if usage.get(c, 0) > 1:
                            is_double = True
                    fulfilled = ", ".join(chips)
                    badge     = " &nbsp;🔄 **[Double-Counted]**" if is_double else ""
                    st.markdown(f"- ✅ {_req_header(req)} — Fulfilled by: {fulfilled}{badge}")
                else:
                    st.markdown(f"- ✅ {_req_header(req)}")
        else:
            st.write("No requirements satisfied yet.")

    with st.expander(f"❌ Unsatisfied Requirements ({len(unsatisfied)})", expanded=True):
        if missing:
            for req_id, details in missing.items():
                if isinstance(details, list):
                    st.markdown(f"- ❌ {_req_header(req_id)} — Required but not yet completed")
                else:
                    needed  = details.get("still_needed") or details.get("credits_still_needed", 0)
                    suffix  = "credits" if "credits_still_needed" in details else "course(s)"
                    options = details.get("options", [])

                    recommended  = next((o for o in options if o in path_set), None)
                    alternatives = [o for o in options if o != recommended][:3]

                    rec_part = (
                        f" — Recommended: **{_spaced(recommended)}**"
                        if recommended else
                        f" — Need **{needed}** more {suffix}"
                    )
                    alt_part = (
                        f" *(Alternatives: {', '.join(_spaced(o) for o in alternatives)})*"
                        if alternatives and recommended else ""
                    )
                    st.markdown(f"- ❌ {_req_header(req_id)}{rec_part}{alt_part}")
        else:
            st.success("All requirements are satisfied!")


# ── Swap-course alternatives builder ──────────────────────────────────────────

def build_alternatives_map(
    path: list[str],
    audit: dict,
    requirements: dict,
    majors_to_check: list[dict],
    catalog: dict,
    assumed_set: set[str],
    avoid_set: set[str],
) -> dict[str, dict]:
    """
    For every course in *path*, return a dict:
      course → {
          "desc":         human requirement label (or "Required Course" / "Prerequisite"),
          "track":        track_id that owns this slot (str | None),
          "alternatives": [course_id, ...] — valid swaps (empty if non-swappable),
      }

    A course is swappable iff it fills a *choice group* slot and at least one
    other option in that group is not already assumed, avoided, or in the path.
    """
    path_set = set(path)
    result: dict[str, dict] = {}

    for course in path:
        if course in result:
            continue

        found = False
        for m in majors_to_check:
            track = m["track"]
            conc  = m["concentration"]
            fm    = audit.get(track, {}).get("fulfillment_map", {})
            if course not in fm:
                continue

            desc = fm[course]
            found = True

            if desc == "Required Course":
                result[course] = {"desc": desc, "track": track, "alternatives": []}
                break

            # Locate the choice group by matching its description/id label
            track_req  = requirements.get(track, {})
            base       = track_req.get("base_requirements", {})
            conc_data  = track_req.get("concentrations", {}).get(conc, {})
            all_groups = base.get("choice_groups", []) + conc_data.get("choice_groups", [])

            for group in all_groups:
                g_desc = group.get("description") or group["id"]
                if g_desc != desc:
                    continue

                if group.get("options"):
                    full_options = list(group["options"])
                elif group.get("type") == "rule_based":
                    full_options = get_rule_based_options(group.get("rule", {}), catalog)
                else:
                    full_options = []

                alternatives = [
                    o for o in full_options
                    if o not in assumed_set
                    and o not in avoid_set
                    and o not in path_set
                    and o != course
                    and o in catalog
                ]
                result[course] = {
                    "desc": desc, "track": track, "alternatives": alternatives,
                }
                break
            break

        if not found:
            # Pure prerequisite — mechanically required, no swap concept
            result[course] = {"desc": "Prerequisite", "track": None, "alternatives": []}

    return result


# ══════════════════════════════════════════════════════════════════════════════
# App layout
# ══════════════════════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="UNC Tar Heel Tracker Degree Planner",
    page_icon="🐏",
    layout="wide",
)

catalog, requirements, graph = load_static_data()

if "user_swaps" not in st.session_state:
    st.session_state.user_swaps = set()

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
        index=None,
        placeholder="Choose your major…",
        label_visibility="collapsed",
    )
    conc1 = _concentration_widget(requirements, major1, key="conc1") if major1 else "None"

    dual = st.toggle("Add Second Major", key="dual")
    major2, conc2 = None, None
    if dual:
        major2 = st.selectbox(
            "Second Major",
            options=major_tracks,
            format_func=fmt,
            index=None,
            placeholder="Choose your second major…",
            key="major2",
            label_visibility="collapsed",
        )
        conc2 = _concentration_widget(requirements, major2, key="conc2") if major2 else "None"
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
                index=None,
                placeholder="Choose your minor…",
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
                minor2 = st.selectbox(
                    "Second Minor",
                    options=minor_tracks,
                    format_func=fmt,
                    index=None,
                    placeholder="Choose your minor…",
                    key="minor2",
                    label_visibility="collapsed",
                )
                if minor2 == minor1:
                    st.warning("Both minors are identical — select different programs.")
                    add_minor2, minor2 = False, None

    st.caption("Don't see your program? Request it in the feedback section below ↓")

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

    st.divider()

    # ─── Feedback ─────────────────────────────────────────────────────────────
    with st.expander("💬 Suggest a Feature / Report a Bug", expanded=False):
        st.caption("Don't see your major or minor? Use **Request a Major/Minor** below.")
        # st.form with clear_on_submit=True resets all inputs automatically on
        # submission, avoiding the StreamlitAPIException that occurs when you
        # write to a widget-bound session-state key after the widget renders.
        with st.form(key="feedback_form", clear_on_submit=True):
            fb_type = st.radio(
                "Type", ["Request a Major/Minor", "Feature Request", "Bug Report"],
                horizontal=True,
                label_visibility="collapsed",
            )
            fb_title = st.text_input(
                "Brief title", placeholder="One-line summary…"
            )
            fb_desc = st.text_area(
                "Details", placeholder="Describe the feature or bug…",
                height=110,
            )
            fb_email = st.text_input(
                "Email (optional)", placeholder="so I can follow up",
            )
            _fb_submitted = st.form_submit_button("Submit", use_container_width=True)

        if _fb_submitted:
            if fb_title.strip() and fb_desc.strip():
                entry = {
                    "type": fb_type,
                    "title": fb_title.strip(),
                    "description": fb_desc.strip(),
                    "email": fb_email.strip() or None,
                    "timestamp": datetime.datetime.now().isoformat(),
                }
                try:
                    _write_feedback(entry)
                    st.success("✅ Thanks! Your feedback has been submitted.")
                except Exception as _fb_err:
                    st.error(f"Submission failed: {_fb_err}")
            else:
                st.warning("Please fill in both the title and description.")


# ── Build generic majors_to_check list (drives all pipeline + UI) ─────────────
majors_to_check: list[dict] = []
if major1:
    majors_to_check.append({"track": major1, "concentration": conc1})
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
_real_majors = [m for m in majors_to_check if m["track"] != GEN_ED_TRACK]
degree_label = " + ".join(fmt(m["track"]) for m in _real_majors)
if degree_label:
    st.caption(f"Auditing: **{degree_label}** + UNC General Education — upload your Tar Heel Tracker PDF below.")
else:
    st.caption("Select a major in the sidebar to get started.")

if not _real_majors:
    st.info("👈 Choose at least one major in the sidebar, then upload your Tar Heel Tracker PDF.")
    st.stop()

uploaded = st.file_uploader(
    "Upload Tar Heel Tracker PDF",
    type=["pdf"],
    label_visibility="collapsed",
)

if uploaded is not None:
    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
        uploaded.seek(0)
        tmp.write(uploaded.read())
        tmp_path = tmp.name

    try:
        with st.spinner("Parsing transcript and auditing requirements…"):
            data = run_pipeline(
                tmp_path, majors_to_check, catalog, requirements, graph,
                planned_courses=planned_courses,
                avoid_courses=avoid_courses,
                explicitly_requested=list(st.session_state.get("user_swaps", set())),
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
        "Planned (Pinned to Path)",
        len(planned),
        delta=f"+{planned_credits} cr" if planned else None,
        delta_color="normal",
    )
    mc4.metric("Total Credits (Parsed)", total_parsed_credits)

    st.warning(
        "⚠️ **Always cross-check with your academic advisor and the official Tar Heel Tracker.** "
        "This planner is a planning aid — it may not reflect catalog-year exceptions, "
        "transfer credit evaluations, or policy changes. Do not rely on it as the sole "
        "source of truth for graduation clearance."
    )

    # ── Completed courses — build requirement satisfaction map ─────────────────
    # Covers both fully-satisfied requirements (via satisfied_map) and partial
    # credit contributions to unsatisfied credit-based choice groups.
    _completed_satisfies: dict[str, list[str]] = {}
    for _m in majors_to_check:
        _tr = _m["track"]
        if _tr not in audit:
            continue
        _plbl = "Gen Ed" if _tr == GEN_ED_TRACK else fmt(_tr)
        _prog_reqs = requirements.get(_tr, {})
        _base_reqs = _prog_reqs.get("base_requirements", {})
        _conc_reqs = _prog_reqs.get("concentrations", {}).get(_m["concentration"], {})
        _req_names: dict[str, str] = {}
        for _cid in _base_reqs.get("required_courses", []) + _conc_reqs.get("required_courses", []):
            _req_names[_cid] = catalog.get(_cid, {}).get("name", "") or _cid
        for _grp in _base_reqs.get("choice_groups", []) + _conc_reqs.get("choice_groups", []):
            _req_names[_grp["id"]] = _grp.get("description", "") or _grp["id"]
        # Fully satisfied requirements
        for _req_id, _courses_list in audit[_tr]["results"].get("satisfied_map", {}).items():
            _req_label = _req_names.get(_req_id, _req_id)
            for _c in _courses_list:
                _entry = f"{_plbl}: {_req_label}"
                if _entry not in _completed_satisfies.get(_c, []):
                    _completed_satisfies.setdefault(_c, []).append(_entry)
        # Partial contributions for credit-based unsatisfied groups:
        # A course contributed iff it is in the full option set but NOT in the
        # remaining-options list (which only contains options not yet completed).
        from src.planner.requirements_checker import get_rule_based_options as _grbo
        for _grp in _base_reqs.get("choice_groups", []) + _conc_reqs.get("choice_groups", []):
            _gid = _grp["id"]
            if _gid not in audit[_tr]["results"].get("unsatisfied", []):
                continue
            _credits_req = _grp.get("credits_required")
            if not _credits_req:
                continue  # count-based groups: partial not meaningful for single-course slots
            _full_opts   = set(_grp.get("options") or _grbo(_grp.get("rule") or {}, catalog))
            _missing     = audit[_tr]["results"].get("missing_courses", {}).get(_gid, {})
            _remain_opts = set(_missing.get("options", []))
            _still_needed = _missing.get("credits_still_needed", _credits_req)
            _counted      = _credits_req - _still_needed
            if _counted <= 0:
                continue
            _req_label = _req_names.get(_gid, _gid)
            # Courses that were in options AND completed (not in remaining) contributed
            _contributed = _full_opts - _remain_opts
            for _c in _contributed:
                _cr = catalog.get(_c, {}).get("credits", 0)
                _entry = f"{_plbl}: {_req_label} (partial — {_cr:.4g} cr of {_credits_req:.4g} cr needed)"
                if _entry not in _completed_satisfies.get(_c, []):
                    _completed_satisfies.setdefault(_c, []).append(_entry)

    with st.expander(f"✅ Completed Courses ({len(completed)})", expanded=False):
        st.caption("Every course on your transcript and what requirement(s) it satisfies across your selected programs.")
        for c in completed:
            name     = catalog.get(c, {}).get("name", "Unknown course")
            cr       = catalog.get(c, {}).get("credits", "?")
            satisfies = _completed_satisfies.get(c, [])
            spaced_c  = _re.sub(r'([A-Z]{2,4})(\d{3,4}[A-Z]?)', r'\1 \2', c)
            if satisfies:
                reqs_str = " &nbsp;·&nbsp; ".join(satisfies)
                st.markdown(f"- **{spaced_c}** — {name} ({cr} cr) → {reqs_str}")
            else:
                st.markdown(f"- **{spaced_c}** — {name} ({cr} cr) → _Not counted toward selected programs_")

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
        # Build impact map from the audit fulfillment maps (available here before path table).
        _planned_impact: dict[str, list[str]] = {}
        for m in majors_to_check:
            _tr = m["track"]
            if _tr not in audit:
                continue
            _plbl = "Gen Ed" if _tr == GEN_ED_TRACK else fmt(_tr)
            for _c, _desc in audit[_tr].get("fulfillment_map", {}).items():
                if _c in set(planned):
                    _planned_impact.setdefault(_c, []).append(f"{_plbl}: {_desc}")

        with st.expander(f"📌 Planned Courses in Path ({len(planned)})", expanded=True):
            st.caption(
                "These courses are prioritised in your graduation path and marked 📌. "
                "They will appear in the route above."
            )
            _path_planned_set = set(path)
            for c in planned:
                name    = catalog.get(c, {}).get("name", "Unknown course")
                cr      = catalog.get(c, {}).get("credits", "?")
                in_path = c in _path_planned_set
                impacts = _planned_impact.get(c, [])
                status  = "✅ in path" if in_path else "⚠️ not schedulable yet (prereqs missing)"
                if impacts:
                    impact_str = " &nbsp;·&nbsp; ".join(impacts)
                    st.markdown(f"- **{c}** — {name} ({cr} cr) · {status} → {impact_str}")
                else:
                    st.markdown(f"- **{c}** — {name} ({cr} cr) · {status}")

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

    # Global course-usage counter: number of programs each course appears in.
    # Used to flag double-counted courses in the satisfied requirements view.
    global_course_usage: dict[str, int] = Counter(
        c
        for m in majors_to_check if m["track"] in audit
        for c in audit[m["track"]]["results"].get("courses_used", set())
    )

    for tab, program in zip(tabs, majors_to_check):
        with tab:
            track_data = audit.get(program["track"])
            if track_data:
                # Build a req_id → human description map for this program
                req_descriptions: dict[str, str] = {}
                _prog = requirements.get(program["track"], {})
                _base = _prog.get("base_requirements", {})
                _conc = _prog.get("concentrations", {}).get(program["concentration"], {})
                for _cid in _base.get("required_courses", []) + _conc.get("required_courses", []):
                    req_descriptions[_cid] = catalog.get(_cid, {}).get("name", "")
                for _grp in _base.get("choice_groups", []) + _conc.get("choice_groups", []):
                    req_descriptions[_grp["id"]] = _grp.get("description", "")

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
                    path=path,
                    catalog=catalog,
                    planned=planned,
                    global_course_usage=global_course_usage,
                    req_descriptions=req_descriptions,
                )
            else:
                st.warning(f"No audit data found for {fmt(program['track'])}.")

    st.divider()

    # ── Graduation path ────────────────────────────────────────────────────────
    st.subheader("📅 Suggested Graduation Path")

    path_credits    = sum(catalog.get(c, {}).get("credits", 3) for c in path)
    total_projected = total_parsed_credits + path_credits

    if path:
        unknown_in_path = [c for c in path if c not in catalog]

        # ── Course table ───────────────────────────────────────────────────────
        # Build course → fulfillment label using the map returned by get_remaining_courses
        _path_set = set(path)
        _course_fulfillment: dict[str, list[str]] = {}

        for _m in majors_to_check:
            _track = _m["track"]
            if _track not in audit:
                continue
            _plabel = "Gen Ed" if _track == GEN_ED_TRACK else fmt(_track)
            for _c, _desc in audit[_track].get("fulfillment_map", {}).items():
                if _c in _path_set:
                    _course_fulfillment.setdefault(_c, []).append(f"{_plabel}: {_desc}")

        # For prerequisites that unlock path courses, label them accordingly
        _assumed_set = set(completed + in_progress)
        _planned_set = set(planned)
        _prereq_for: dict[str, list[str]] = {}
        for _course in path:
            _pathways = catalog.get(_course, {}).get("prerequisites", [])
            if _pathways:
                _cpaths = [p for p in _pathways if any(c in _assumed_set for c in p)]
                _best   = min(_cpaths or _pathways, key=len)
                for _pre in _best:
                    if _pre in _path_set and _pre != _course:
                        _prereq_for.setdefault(_pre, []).append(_course)

        def _fulfills_label(course: str) -> str:
            if course in _course_fulfillment:
                return " · ".join(_course_fulfillment[course])
            if course in _prereq_for:
                targets = ", ".join(_prereq_for[course][:3])
                return f"Prereq → {targets}"
            return "—"

        _user_swaps = st.session_state.get("user_swaps", set())
        rows = [
            {
                "#":       i,
                "Course":  (
                    f"🔄 {course}" if course in _user_swaps
                    else f"📌 {course}" if course in _planned_set
                    else course
                ),
                "Name":    catalog.get(course, {}).get("name", "—"),
                "Credits": catalog.get(course, {}).get("credits", 3),
                "Fulfills": _fulfills_label(course),
            }
            for i, course in enumerate(path, 1)
        ]
        _path_df = pd.DataFrame(rows)
        _html_table = _path_df.to_html(index=False, escape=False)
        # Replace the plain <table> tag with our styled class
        _html_table = _html_table.replace('<table border="1" class="dataframe">', '<table class="grad-table">')
        st.markdown(
            f"""
<div style="overflow-x: auto; max-width: 100%;">
  <style>
    .grad-table {{
      width: max-content;
      min-width: 100%;
      border-collapse: collapse;
      font-size: 14px;
    }}
    .grad-table th {{
      text-align: left;
      padding: 10px 14px;
      border-bottom: 2px solid rgba(128,128,128,0.3);
      white-space: nowrap;
    }}
    .grad-table td {{
      text-align: left;
      padding: 8px 14px;
      border-bottom: 1px solid rgba(128,128,128,0.15);
      word-wrap: break-word;
      white-space: normal;
      max-width: 480px;
    }}
    .grad-table td:nth-child(1),
    .grad-table td:nth-child(3),
    .grad-table td:nth-child(4) {{
      white-space: nowrap;
    }}
    .grad-table tr:hover td {{
      background: rgba(128,128,128,0.08);
    }}
  </style>
  {_html_table}
</div>
""",
            unsafe_allow_html=True,
        )
        st.caption(f"Remaining path credits: **{path_credits}**")
        if unknown_in_path:
            st.warning(
                f"⚠️ {len(unknown_in_path)} course(s) in the path are not in the catalog "
                f"and assumed 3 credits: {', '.join(unknown_in_path)}"
            )

        # ── Swap a Course ──────────────────────────────────────────────────────
        _avoid_set_swap = set(avoid_courses)
        _alt_map = build_alternatives_map(
            path, audit, requirements, majors_to_check,
            catalog, _assumed_set, _avoid_set_swap,
        )
        _swappable     = [c for c in path if _alt_map.get(c, {}).get("alternatives")]
        _non_swappable = [c for c in path if not _alt_map.get(c, {}).get("alternatives")]

        with st.expander("🔄 Swap a Course", expanded=False):
            st.caption(
                "Replace a recommended course with a valid alternative that satisfies the same "
                "requirement. The swapped-out course is blocked from future recommendations; "
                "the replacement will be marked 🔄 in the graduation path above."
            )
            if not _swappable:
                st.info("Every course in the current path is required with no valid alternatives.")
            else:
                def _clabel(c: str) -> str:
                    name   = catalog.get(c, {}).get("name", "")
                    cr     = catalog.get(c, {}).get("credits", 3)
                    spaced = _re.sub(r'([A-Z]{2,4})(\d{3,4}[A-Z]?)', r'\1 \2', c)
                    return f"{spaced} ({cr} cr) — {name[:40]}" if name else f"{spaced} ({cr} cr)"

                # Step A — pick the course to remove; options come directly from the
                # most recently generated path so ghost courses are impossible.
                _swap_out = st.selectbox(
                    "Step 1 — Select a course to replace",
                    options=_swappable,
                    format_func=_clabel,
                    key="swap_remove_selectbox",
                    index=None,
                    placeholder="Choose a course to swap out…",
                )

                # Step B — show alternatives for that exact slot (only after step A)
                _swap_in: str | None = None
                if _swap_out is not None:
                    _alternatives = _alt_map.get(_swap_out, {}).get("alternatives", [])
                    _req_desc     = _alt_map.get(_swap_out, {}).get("desc", "")

                    _swap_in = st.selectbox(
                        "Step 2 — Choose replacement",
                        options=_alternatives,
                        format_func=_clabel,
                        key="swap_add_selectbox",
                        index=None,
                        placeholder="Choose a replacement…",
                        help=f"Satisfies: {_req_desc}",
                    )

                # Step C — preview + confirm (only after both selections are made)
                if _swap_out is not None and _swap_in is not None:
                    _out_cr   = catalog.get(_swap_out, {}).get("credits", 3)
                    _in_cr    = catalog.get(_swap_in,  {}).get("credits", 3)
                    _cr_delta = _in_cr - _out_cr
                    _cr_note  = (
                        f" &nbsp;·&nbsp; Credits: {_out_cr} → {_in_cr} "
                        + (f"(+{_cr_delta})" if _cr_delta > 0 else f"({_cr_delta})")
                    ) if _cr_delta != 0 else ""

                    _in_prereqs      = catalog.get(_swap_in, {}).get("prerequisites", [])
                    _missing_prereqs: list[str] = []
                    if _in_prereqs:
                        _best_pp = min(_in_prereqs, key=len)
                        _missing_prereqs = [p for p in _best_pp if p not in _assumed_set]

                    st.info(
                        f"**{_swap_out}** → **{_swap_in}** &nbsp;·&nbsp; "
                        f"Satisfies: *{_req_desc}*{_cr_note}"
                    )
                    if _missing_prereqs:
                        st.warning(
                            f"⚠️ **{_swap_in}** requires {', '.join(_missing_prereqs)} "
                            f"— these will be added to your graduation path automatically."
                        )

                    def _do_swap() -> None:
                        # Atomic transaction: read both values from session state with
                        # strict type guards so a stale or unexpected widget value
                        # cannot crash the rerun cycle.
                        old_course_val = st.session_state.get("swap_remove_selectbox")
                        new_course_val = st.session_state.get("swap_add_selectbox")

                        if not old_course_val or not new_course_val:
                            return

                        old_course_id = (
                            old_course_val if isinstance(old_course_val, str)
                            else old_course_val.get("Course")
                        )
                        new_course_id = (
                            new_course_val if isinstance(new_course_val, str)
                            else new_course_val.get("Course")
                        )

                        if not old_course_id or not new_course_id:
                            return

                        # Block the removed course from future recommendations.
                        cur_avoid = list(st.session_state.get("avoid_courses", []))
                        if old_course_id not in cur_avoid:
                            cur_avoid.append(old_course_id)
                        st.session_state["avoid_courses"] = cur_avoid

                        # Mark the replacement as explicitly requested so the greedy
                        # selector strongly prefers it and it appears in the path.
                        # Do NOT add to planned_courses — that would treat it as
                        # already completed and erase it from the generated path.
                        _swaps = set(st.session_state.get("user_swaps", set()))
                        _swaps.add(new_course_id)
                        st.session_state["user_swaps"] = _swaps

                        # Clear both selectboxes so the next render starts clean.
                        st.session_state.pop("swap_remove_selectbox", None)
                        st.session_state.pop("swap_add_selectbox",    None)

                    st.button(
                        "✅ Confirm Swap", key="execute_swap_btn",
                        type="primary", use_container_width=True,
                        on_click=_do_swap,
                    )

            if _non_swappable:
                _ns_items = _non_swappable[:10]
                _ns_more  = f" (+{len(_non_swappable) - 10} more)" if len(_non_swappable) > 10 else ""
                st.caption(
                    f"🔒 **No alternatives:** {', '.join(_ns_items)}{_ns_more}"
                )

        # ── Export CSV ─────────────────────────────────────────────────────────
        csv_buf = io.StringIO()
        csv_buf.write("Course Code,Course Name,Credits,Fulfills\n")
        for row in rows:
            name_escaped     = row["Name"].replace('"', '""')
            fulfills_escaped = row["Fulfills"].replace('"', '""')
            raw_code = _re.sub(r'^[🔄📌]\s*', '', row["Course"])
            csv_buf.write(f'"{raw_code}","{name_escaped}",{row["Credits"]},"{fulfills_escaped}"\n')

        st.download_button(
            label="📥 Download Graduation Plan",
            data=csv_buf.getvalue().encode("utf-8"),
            file_name="graduation_plan.csv",
            mime="text/csv",
            use_container_width=True,
        )

        # ── Prerequisite graph (after table for better context) ────────────────
        assumed_for_graph = list(dict.fromkeys(completed + in_progress + planned))
        with st.expander("🕸️ Prerequisite Tree", expanded=True):
            st.caption(
                "🟢 **Green** = already completed &nbsp;|&nbsp; "
                "🟡 **Amber** = in-progress this semester &nbsp;|&nbsp; "
                "🔵 **Blue** = still needed &nbsp;|&nbsp; "
                "Arrows point from prerequisite → course."
            )
            dot_src = build_prereq_dot(path, catalog, assumed_for_graph, in_progress)
            st.markdown(
                "<style>div[data-testid='stGraphVizChart'] iframe"
                "{ min-height: 640px !important; }</style>",
                unsafe_allow_html=True,
            )
            st.graphviz_chart(dot_src, use_container_width=True)
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
