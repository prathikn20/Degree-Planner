import datetime
import hashlib
import io
import json
import os
import re as _re
import tempfile
from collections import Counter

import pandas as pd
import streamlit as st

from src.planner.graph import build_graph, load_catalog, load_requirements
from src.planner.path_generator import solve_optimal_path
from src.data_pipeline.kahns_algorithm import kahns_algorithm
from src.planner.requirements_checker import check_requirements, get_rule_based_options, generate_slots_and_candidates
from src.planner.tracker_parser import parse_tarheel_tracker

CATALOG_PATH      = "data/course_catalog.json"
REQUIREMENTS_PATH = "data/degree_requirements.json"
UNC_MIN_CREDITS   = 120

# ── Presentation-layer label formatter ────────────────────────────────────────
_PROGRAM_SHORT_LABELS: dict[str, str] = {
    "UNC_General_Education":                          "Gen Ed",
    "Computer_Science_BS":                            "CS BS",
    "Computer_Science_BA":                            "CS BA",
    "Computer_Science_Minor":                         "CS Minor",
    "Data_Science_BS":                                "DS BS",
    "Data_Science_BA":                                "DS BA",
    "Data_Science_Minor":                             "DS Minor",
    "Mathematics_BS":                                 "Math BS",
    "Mathematics_BA":                                 "Math BA",
    "Mathematics_Minor":                              "Math Minor",
    "Statistics_and_Analytics_BS":                    "Stats BS",
    "Statistics_and_Analytics_Minor":                 "Stats Minor",
    "Economics_BS":                                   "Econ BS",
    "Economics_BA":                                   "Econ BA",
    "Economics_Minor":                                "Econ Minor",
    "Biology_BS":                                     "Bio BS",
    "Biology_BA":                                     "Bio BA",
    "Biology_Minor":                                  "Bio Minor",
    "Biology_BS_Quantitative_Biology_Track":          "Bio BS (QB)",
    "Chemistry_BS":                                   "Chem BS",
    "Chemistry_BA":                                   "Chem BA",
    "Chemistry_Minor":                                "Chem Minor",
    "Chemistry_BS_Biochemistry_Track":                "Chem BS (Biochem)",
    "Chemistry_BS_Polymer_Track":                     "Chem BS (Polymer)",
    "Physics_BS":                                     "Phys BS",
    "Physics_BS_Astrophysics":                        "Phys BS (Astro)",
    "Physics_BA":                                     "Phys BA",
    "Physics_Minor":                                  "Phys Minor",
    "Neuroscience_BS":                                "Neuro BS",
    "Neuroscience_Minor":                             "Neuro Minor",
    "Psychology_BS":                                  "Psych BS",
    "Psychology_BA":                                  "Psych BA",
    "Political_Science_BA":                           "Pol Sci BA",
    "Public_Policy_BA":                               "Pub Pol BA",
    "Public_Policy_Minor":                            "Pub Pol Minor",
    "Exercise_and_Sport_Science_BS":                  "ESS BS",
    "Exercise_and_Sport_Science_Minor":               "ESS Minor",
    "Exercise_and_Sport_Science_Fitness_Professional_BA": "ESS Fitness BA",
    "Exercise_and_Sport_Science_General_BA":          "ESS General BA",
    "Exercise_and_Sport_Science_Sport_Administration_BA": "ESS Sport Admin BA",
    "Biomedical_Engineering_BS":                      "BME BS",
    "Business_Administration_Minor":                  "Bus Admin Minor",
    "Business_Administration_BSBA":                   "Bus Admin BSBA",
    "Biostatistics_BSPH":                             "Biostat BSPH",
    "Information_Science_BS":                         "Info Sci BS",
    "Sociology_BA":                                   "Soc BA",
    "Anthropology_BA":                                "Anth BA",
    "Anthropology_General_Minor":                     "Anth Minor",
    "Medical_Anthropology_BA":                        "Med Anth BA",
    "Medical_Anthropology_Minor":                     "Med Anth Minor",
    "Philosophy_BA":                                  "Phil BA",
    "Philosophy_Minor":                               "Phil Minor",
    "Philosophy_Politics_and_Economics_Minor":        "PPE Minor",
    "Linguistics_BA":                                 "Ling BA",
    "Linguistics_Minor":                              "Ling Minor",
    "Environmental_Science_BS":                       "Env Sci BS",
    "Environmental_Studies_BA":                       "Env Stud BA",
    "Environmental_Science_and_Studies_Minor":        "Env Sci Minor",
    "Environmental_Health_Sciences_BSPH":             "Env Health BSPH",
    "Environmental_Justice_Minor":                    "Env Justice Minor",
    "Global_Studies_BA":                              "Global BA",
    "Communication_Studies_BA":                       "Comm BA",
    "Applied_Sciences_BS":                            "App Sci BS",
    "Applied_Sciences_and_Engineering_Minor":         "App Sci & Eng Minor",
    "Earth_and_Marine_Sciences_BS":                   "EMS BS",
    "Marine_Sciences_Minor":                          "Marine Sci Minor",
    "Neurodiagnostics_and_Sleep_Science_BS":          "NSS BS",
    "Community_and_Global_Public_Health_BSPH":        "CGPH BSPH",
    "Health_Policy_and_Management_BSPH":              "HPM BSPH",
    "Nutrition_BSPH":                                 "Nutr BSPH",
    "Entrepreneurship_Minor":                         "Entrep Minor",
    "Business_of_Health_Minor":                       "Bus Health Minor",
    "Real_Estate_Minor":                              "Real Estate Minor",
    "Health_and_Society_Minor":                       "Health & Soc Minor",
    "Sustainability_Studies_Minor":                   "Sustain Minor",
    "Sports_Medicine_Minor":                          "Sports Med Minor",
    "Geographic_Information_Sciences_Minor":          "GIS Minor",
    "Geological_Sciences_Minor":                      "Geol Sci Minor",
    "Geological_Sciences_BA_Earth_Science":           "Geol Sci BA",
    "Information_Systems_Minor":                      "Info Sys Minor",
    "Astronomy_Minor":                                "Astro Minor",
    "Spanish_for_the_Professions_Minor":              "Spanish Prof Minor",
    "Management_and_Society_BA":                      "Mgmt & Soc BA",
    "Peace_War_and_Defense_BA":                       "PWD BA",
    "Statistics_and_Analytics_BS":                    "Stats BS",
    "Interdisciplinary_Studies_BA":                   "IDST BA",
    "History_BA":                                     "History BA",
    "History_Minor":                                  "History Minor",
    "Media_and_Journalism_BA":                        "Journalism BA",
    "Media_and_Journalism_Minor":                     "Journalism Minor",
    "Dramatic_Art_BA":                                "Dramatic Art BA",
    "Dramatic_Art_Minor":                             "Dramatic Art Minor",
    "Music_BA":                                       "Music BA",
    "Music_BMus":                                     "Music BMus",
    "Music_Minor":                                    "Music Minor",
    "Studio_Art_BA":                                  "Studio Art BA",
    "Studio_Art_BFA":                                 "Studio Art BFA",
    "Studio_Art_Minor":                               "Studio Art Minor",
    "Art_History_BA":                                 "Art History BA",
    "Creative_Writing_Minor":                         "Creative Writing Minor",
    "Human_and_Organizational_Leadership_Development_BA": "HOLD BA",
    "Geography_and_Environment_BA":                   "Geog & Env BA",
    "Geography_Minor":                                "Geog Minor",
    "Latin_American_Studies_BA":                      "Latin Am BA",
    "Global_Studies_BA":                              "Global BA",
    "American_Studies_BA":                            "Am Studies BA",
    "African_African_American_and_Diaspora_Studies_BA": "AAAD BA",
    "Womens_and_Gender_Studies_BA":                   "WGS BA",
    "Womens_and_Gender_Studies_Minor":                "WGS Minor",
    "Religious_Studies_BA":                           "Rel Studies BA",
    "Religious_Studies_Minor":                        "Rel Studies Minor",
    "Philosophy_BA":                                  "Phil BA",
    "English_and_Comparative_Literature_BA":          "Eng & Comp Lit BA",
    "English_Minor":                                  "English Minor",
    "Clinical_Laboratory_Science_BS":                 "CLS BS",
    "Dental_Hygiene_BS":                              "Dental Hygiene BS",
    "Radiologic_Science_BS":                          "Rad Sci BS",
    "Nursing_BSN":                                    "Nursing BSN",
    "Human_Development_and_Family_Science_BAEd":      "HDFS BAEd",
}

# ── UNC Gen Ed requirement abbreviations ──────────────────────────────────────
# Applied to every surface: graduation path, accordions, double-counted cards.
_GEN_ED_REQ_LABELS: dict[str, str] = {
    "FY-SEMINAR":        "FY Seminar",
    "FC-AESTH":          "FC: Aesthetic",
    "FC-CREATE":         "FC: Creative",
    "FC-PAST":           "FC: Human Past",
    "FC-VALUES":         "FC: Ethics",
    "FC-GLOBAL":         "FC: Global",
    "FC-NATSCI":         "FC: Nat Sci",
    "FC-LAB":            "FC: Lab",
    "FC-POWER":          "FC: Power & Society",
    "FC-QUANT":          "FC: Quant",
    "FC-KNOW":           "FC: Ways of Knowing",
    "RESEARCH":          "Research",
    "HI-EXP":            "High-Impact Exp",
    "COMM":              "Comm Beyond Carolina",
    "LFIT":              "Lifetime Fitness",
    "FAD":               "FAD",
    "INTERDISCIPLINARY": "IDST",
}

def _req_short_desc(req_id: str, raw_desc: str) -> str:
    """Return the canonical short label for a requirement group.
    Gen Ed groups get a fixed abbreviation; all others go through _shorten_desc."""
    if req_id in _GEN_ED_REQ_LABELS:
        return _GEN_ED_REQ_LABELS[req_id]
    return _shorten_desc(raw_desc) if raw_desc else (raw_desc or req_id)


_DEGREE_SUFFIXES: frozenset[str] = frozenset({
    "BS", "BA", "Minor", "BSPH", "BSBA", "BMus", "BSN", "BAEd", "BFA",
})
_STOP_WORDS: frozenset[str] = frozenset({
    "and", "the", "of", "for", "in", "unc",
})

def _program_short_label(program_id: str) -> str:
    """Convert a track ID like 'Computer_Science_BS' to a concise display label."""
    if program_id in _PROGRAM_SHORT_LABELS:
        return _PROGRAM_SHORT_LABELS[program_id]
    parts = program_id.split("_")
    suffix = parts[-1] if parts and parts[-1] in _DEGREE_SUFFIXES else ""
    name_parts = [p for p in (parts[:-1] if suffix else parts) if p.lower() not in _STOP_WORDS]
    if not name_parts:
        return program_id.replace("_", " ")
    short = "".join(p[0].upper() for p in name_parts) if len(name_parts) > 1 else name_parts[0][:6]
    return f"{short} {suffix}".strip() if suffix else short


_WRITTEN_NUMS = (
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten"
    r"|eleven|twelve|fifteen|sixteen|twenty)"
)
_WORD_NUM_RE = _re.compile(
    r"^" + _WRITTEN_NUMS + r"(?:\s*\(\d+\))?\s+",
    _re.IGNORECASE,
)


def _strip_leading_once(d: str) -> str:
    d = _re.sub(r"^\d+\s+", "", d)
    d = _WORD_NUM_RE.sub("", d)
    d = _re.sub(r"^[Aa]\s+(?:choice|coherent\s+set)\s+of\s+", "", d)
    d = _re.sub(r"^[Aa]n?\s+(?=\w+\s)", "", d)
    d = _re.sub(r"^(?:first|second|third|fourth|fifth|sixth)\s+", "", d, flags=_re.IGNORECASE)
    d = _re.sub(r"^(?:And|At\s+least|No\s+more\s+than)\s+", "", d, flags=_re.IGNORECASE)
    d = _re.sub(
        r"^(?:additional|optional|other|consider(?:\s+adding\s+optional)?)\s+",
        "", d, flags=_re.IGNORECASE,
    )
    d = _re.sub(r"^to\s+" + _WRITTEN_NUMS + r"\s+", "", d, flags=_re.IGNORECASE)
    d = _re.sub(r"^of\s+the\s+following\b.*$", "Elective", d, flags=_re.IGNORECASE)
    d = _re.sub(r"^from\s+among\b.*$", "Elective", d, flags=_re.IGNORECASE)
    d = _re.sub(r"^[A-Z]\w+\s+requires\b.*$", "Elective", d, flags=_re.IGNORECASE)
    d = _re.sub(r"^[Ss]tudents?\s+(?:must|should)\b.*$", "Elective", d, flags=_re.IGNORECASE)
    return d


def _sanitize_desc(raw: str) -> str:
    """Clean a raw requirement description for concise UI display."""
    if not raw or raw == "Required Course":
        return raw
    d = raw.strip()
    # fix typos and strip footnote/dagger markers
    d = _re.sub(r"\bdive\b", "div", d, flags=_re.IGNORECASE)
    d = _re.sub(r"\s*[†]\s*", " ", d).strip()
    # cascade leading-strip rules (3 passes handles nested cases like "A choice of four additional…")
    for _ in range(3):
        prev = d
        d = _strip_leading_once(d)
        if d == prev:
            break
    # normalize upper-division / upper-level
    d = _re.sub(r"\bupper[- ]div(?:ision)?\b", "Upper Div", d, flags=_re.IGNORECASE)
    d = _re.sub(r"\bupper[- ]level\b", "Upper Level", d, flags=_re.IGNORECASE)
    # strip parenthetical dept abbreviations like (ANTH), (HIST), (RUSS)
    d = _re.sub(r"\s*\([A-Z]{3,8}\)\s*", " ", d)
    # strip N-hour and N-or-more-credit-hour prefixes
    d = _re.sub(r"^[\w-]+\s+credit\s+hours?\s+", "", d, flags=_re.IGNORECASE)
    d = _re.sub(r"(?:^|\s+)\w+-hour\s+", " ", d, flags=_re.IGNORECASE).strip()
    # handle "hours of X" → X and "hours can/are" → Credits
    d = _re.sub(r"^hours?\s+of\s+", "", d, flags=_re.IGNORECASE)
    d = _re.sub(
        r"^hours?\s+(?:can\s+come\s+from|are\s+to\s+be\s+taken\s+from\s+(?:other\s+)?).*$",
        "Credits", d, flags=_re.IGNORECASE,
    )
    # handle bare credit patterns
    d = _re.sub(r"^credit\s+hours?\s*$", "Credits", d, flags=_re.IGNORECASE)
    d = _re.sub(r"^credit\s+hours?\s+(?:of\s+)?", "", d, flags=_re.IGNORECASE)
    d = _re.sub(r"^credits?\s*$", "Credits", d, flags=_re.IGNORECASE)
    d = _re.sub(r"^credits?\s+(?:from|of)\s+", "", d, flags=_re.IGNORECASE)
    # strip trailing boilerplate BEFORE course-from rules so they don't leave bare "the X"
    for _pat in (
        r"\s+numbered\b.*$",
        r"\s+at\s+the\s+\d+.*$",
        r"\s+above\s+(?:\d+|[A-Z]{2,8}\s*\d+).*$",
        r"\s+beyond\s+[A-Z]{2,8}\s*\d+.*$",
        r"\s+taken\s+(?:in|from)\s+.*$",
        r"\s+taken\s*$",
        r"\s+at\s*$",
        r"\s+from\s+the\s+(?:list|approved|following|School|Department|College|other)\b.*$",
        r"\s+from\s+any\s+(?:track|list)\b.*$",
        r"\s+from\s+among\b.*$",
        r"\s+from\s+this\s+list\s*$",
        r"\s+from\s+the\s+list\s+below\b.*$",
        r"\s+selected\s+from\b.*$",
        r"\s+outside\s+the\s+.*$",
        r"\s+must\s+be\s+.*$",
        r"\s+of\s+the\s+following\b.*$",
        r"\s+covering\s+any\b.*$",
        r"\s+representing\s+at\s+least\b.*$",
        r"\s+from\s+at\s+least\b.*$",
        r"\s+emphasizing\b.*$",
        r",\s*two\s+of\s+which\b.*$",
        r"\s+on\s+the\s+social\b.*$",
        r"\s+are\s+language\s+courses?\b.*$",
        r"\s+in\s+BCS,.*$",
        r"\s+\(at\s+least\b.*$",
        r"\s+of\s+" + _WRITTEN_NUMS + r"\s*$",
        r"\s+[-]\s+see\b.*$",
        r"\s+to\s+reach\b.*$",
        r"\s+is\s+required\s*$",
        r"\s+in\s+a\s+(?:field|language)\s+.*$",
        r"\s+relevant\s+to\s+.*$",
        r"\s+" + _WRITTEN_NUMS + r"\s*$",
    ):
        d = _re.sub(_pat, "", d, flags=_re.IGNORECASE)
    # strip unclosed parentheses left by _shorten_desc truncation: "(gatew…" → nothing
    d = _re.sub(r"\s*\([^)]*$", "", d)
    # "course(s) in/on/from/emphasizing X" → X, then strip residual leading "the"
    d = _re.sub(
        r"^courses?\s+(?:in|on|from|emphasizing|each\s+from|at\s+any\s+level\b.*|selected\s+from)\s*",
        "", d, flags=_re.IGNORECASE,
    )
    d = _re.sub(r"^the\s+", "", d, flags=_re.IGNORECASE)
    # strip remaining parenthetical qualifiers
    d = _re.sub(r"\s*\(" + _WRITTEN_NUMS + r"\s+(?:hours?|courses?)\)", "", d, flags=_re.IGNORECASE)
    d = _re.sub(r"\s*\(one\s+[^)]+\)", "", d, flags=_re.IGNORECASE)
    d = _re.sub(r"\s*\(two\s+[^)]+\)", "", d, flags=_re.IGNORECASE)
    d = _re.sub(r"\s*\(\d+\s+[^)]+\)", "", d, flags=_re.IGNORECASE)
    d = _re.sub(r"\s*\(and\s+up\s+to\s+[^)]+\)\s*", " ", d, flags=_re.IGNORECASE)
    d = _re.sub(r"\s*\(select\s+\w+\)\s*", "", d, flags=_re.IGNORECASE)
    d = _re.sub(r"\s*\(\d+\)\s*", " ", d)
    # normalize electives (singular and plural, lone and compound)
    d = _re.sub(r"\belective\s+courses?\b", "Elective", d, flags=_re.IGNORECASE)
    d = _re.sub(r"\belectives\b", "Elective", d, flags=_re.IGNORECASE)
    d = _re.sub(r"\belective\b", "Elective", d, flags=_re.IGNORECASE)
    # dept code (3+ uppercase letters) + courses → dept Elective
    d = _re.sub(r"\b([A-Z]{3,8})\s+courses?\s*$", r"\1 Elective", d)
    # strip bare trailing "courses"/"course"
    d = _re.sub(r"\s+courses?\s*$", "", d, flags=_re.IGNORECASE)
    # bare "courses" → Elective; lone written-number → Elective
    d = _re.sub(r"^courses?\s*$", "Elective", d, flags=_re.IGNORECASE)
    d = _re.sub(r"^" + _WRITTEN_NUMS + r"\s*$", "Elective", d, flags=_re.IGNORECASE)
    # strip trailing ellipsis artifact from _shorten_desc truncation
    d = d.rstrip("…").strip()
    # final whitespace normalisation, capitalise, strip trailing punctuation
    d = _re.sub(r"\s+", " ", d).strip().rstrip(".:,-/()")
    if d:
        d = d[0].upper() + d[1:]
    return d or raw


def format_fulfillment_label(program_id: str, raw_desc: str) -> str:
    """Return a clean 'Short Program: Concise Desc' label for the Fulfills column."""
    clean = _sanitize_desc(raw_desc) if raw_desc else ""
    return f"{_program_short_label(program_id)}: {clean or 'Elective'}"

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
    import gspread
    gc = gspread.service_account_from_dict(dict(st.secrets["gcp_service_account"]))
    ws = gc.open_by_key(st.secrets["FEEDBACK_SHEET_ID"]).sheet1
    if not ws.get_all_values():
        ws.append_row(["Timestamp", "Type", "Title", "Description", "Email"])
    return ws

def _write_feedback(entry: dict) -> None:
    if "gcp_service_account" in st.secrets:
        ws = _get_feedback_sheet()
        ws.append_row([
            entry["timestamp"], entry["type"], entry["title"],
            entry["description"], entry.get("email") or "",
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
    return key.replace("_", " ")

def is_minor(track_id: str) -> bool:
    return "minor" in track_id.lower()

def _shorten_desc(raw: str) -> str:
    """Condense a verbose requirement description to a concise display label."""
    if not raw or raw == "Required Course":
        return raw

    d = raw.replace("\xa0", " ")

    # "DEPT NNN | Full Course Name flags" → keep only the name part
    if " | " in d:
        d = d.split(" | ", 1)[1]

    # Multi-sentence blurbs: keep only the first sentence
    d = _re.sub(r"\.\s+[A-Z].*$", "", d)

    # Remove boilerplate parentheticals FIRST so "or" inside them
    # doesn't get caught by the OR-alternative strip below
    _strip_parens = [
        r"\(select one\):?",
        r"\(required when[^)]*\)",
        r"\(see list[^)]*\)",
        r"\(each of[^)]*\)",
        r"\(not including[^)]*\)",
        r"\(excluding[^)]*\)",
        r"\(which may[^)]*\)",
        r"\(taken in[^)]*\)",
        r"\(some courses[^)]*\)",
        r"\(no more than[^)]*\)",
        r"\(the first (?:semester|year)[^)]*\)",
        r"\([\d.]+ credit[^)]*\)",
        r"\([\d.]+ hours[^)]*\)",
        r"\([A-Z][A-Z0-9-]+ —[^)]*\)",  # "(CODE — explanation)" e.g. "(FC-LAB — …)"
        r"\([^)]{30,}\)",  # any remaining long parenthetical
    ]
    for pat in _strip_parens:
        d = _re.sub(r"\s*" + pat, "", d, flags=_re.IGNORECASE)

    # Strip "… OR …" alternatives (after parens are gone so inner "or" isn't matched)
    d = _re.sub(r"\s+OR\s+.*", "", d, flags=_re.IGNORECASE)

    # Strip trailing "chosen from …" and "from the following …"
    d = _re.sub(r"\s+chosen from.*$", "", d, flags=_re.IGNORECASE)
    d = _re.sub(r"\s+from the following.*$", "", d, flags=_re.IGNORECASE)
    d = _re.sub(r",?\s*from:?\s*$", "", d, flags=_re.IGNORECASE)

    # Strip leading verbose openers
    d = _re.sub(
        r"^(Choose|Select|At least|A minimum of|Minimum|"
        r"A major in|A minor in|The remaining|All students must complete)\s+",
        "", d, flags=_re.IGNORECASE,
    )

    # Strip trailing catalog attribute flags: ", H", " F", ", 1, H, F"
    d = _re.sub(r"((?:[,\s]+\b[HF]\b)+)\s*$", "", d)
    # Strip trailing standalone footnote numbers: " 1", ", 4,5"
    d = _re.sub(r"(\s*,?\s*\b\d\b)+\s*$", "", d)

    # Strip trailing punctuation
    d = d.rstrip(".:, ")

    # Normalize whitespace and capitalise
    d = _re.sub(r"\s+", " ", d).strip()
    if d:
        d = d[0].upper() + d[1:]

    # Truncate to 55 characters
    if len(d) > 55:
        d = d[:53].rstrip(" ,:(") + "…"

    return d or raw

def available_concentrations(requirements: dict, track: str) -> list[str]:
    concs = list(requirements.get(track, {}).get("concentrations", {}).keys())
    return concs if concs else ["None"]

def has_real_concentrations(concs: list[str]) -> bool:
    return any(c != "None" for c in concs)

def _concentration_widget(requirements: dict, track: str, key: str) -> str:
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

    _selection_avoid = list(set(assumed + avoid))

    # --- PASS 1: The Audit ---
    results_by_track: dict[str, dict] = {}
    for m in majors_to_check:
        track, conc = m["track"], m["concentration"]
        results_by_track[track] = check_requirements(
            requirements, catalog, assumed,
            avoid_courses=avoid,
            track_id=track, concentration_id=conc,
        )

    # --- PASS 2: The New CSP Solver ---
    slots, canon_catalog, credit_ledger, macro_bindings, blacklist = generate_slots_and_candidates(
        requirements=requirements,
        catalog=catalog,
        majors_to_check=majors_to_check,
        completed_courses=assumed,
        avoid_courses=_selection_avoid,
    )
    
    best_path, course_to_slots_map = solve_optimal_path(
        slots=slots, 
        canon_catalog=canon_catalog, 
        credit_ledger=credit_ledger,
        macro_bindings=macro_bindings,
        blacklist=blacklist,
        remaining_semesters=8
    )

    # --- PASS 3: Build the UI Dictionary ---
    audit: dict[str, dict] = {}
    for m in majors_to_check:
        track = m["track"]
        audit[track] = {
            "results":         results_by_track[track],
            "remaining":       [],
            "fulfillment_map": {},
        }

    # Build group_id → human-readable description lookup per program
    _group_desc_map: dict[str, dict[str, str]] = {}
    for _m in majors_to_check:
        _t, _c = _m["track"], _m["concentration"]
        _base_g = requirements.get(_t, {}).get("base_requirements", {}).get("choice_groups", [])
        _conc_g = requirements.get(_t, {}).get("concentrations", {}).get(_c, {}).get("choice_groups", [])
        _group_desc_map[_t] = {g["id"]: _req_short_desc(g["id"], g.get("description") or g["id"]) for g in _base_g + _conc_g}

    for course, slot_ids in course_to_slots_map.items():
        for slot_id in slot_ids:
            parts = slot_id.split("__")
            if len(parts) >= 2:
                program_id = parts[0]
                if program_id in audit:
                    group_id = parts[1]
                    if group_id == "req":
                        desc = "Required Course"
                    else:
                        desc = _group_desc_map.get(program_id, {}).get(group_id, group_id)
                    if course not in audit[program_id]["remaining"]:
                        audit[program_id]["remaining"].append(course)
                    existing = audit[program_id]["fulfillment_map"].get(course, "")
                    if not existing:
                        audit[program_id]["fulfillment_map"][course] = desc
                    elif desc not in existing:
                        audit[program_id]["fulfillment_map"][course] += f" · {desc}"

    semester_path = kahns_algorithm(best_path, catalog)
    flat_path: list[str] = []
    for _sem_courses in semester_path.values():
        flat_path.extend(_sem_courses)

    return {
        "completed":     completed,
        "in_progress":   in_progress,
        "course_terms":  parsed.get("course_terms", {}),
        "planned":       planned,
        "audit":         audit,
        "path":          flat_path,
        "semester_path": semester_path,
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

    nodes_with_edges: set[str] = set()
    for src, dst in edges:
        nodes_with_edges.add(src)
        nodes_with_edges.add(dst)

    def _node(c: str) -> str:
        name  = catalog.get(c, {}).get("name", "")
        short = (name[:26] + "…") if len(name) > 26 else name
        label = f"{c}\\n{short}" if short else c
        label = label.replace('"', '\\"')
        if c in in_prog_set:
            fill, border = "#FFD966", "#7d6608"
        elif c in completed_set:
            fill, border = "#93C47D", "#2d5f2d"
        else:
            fill, border = "#6FA8DC", "#1a4a6b"
        return f'    "{c}" [label="{label}", fillcolor="{fill}", color="{border}", penwidth=1.6];'

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
    req_groups_meta: dict | None = None,
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
    groups_meta   = req_groups_meta or {}

    def _spaced(code: str) -> str:
        return _re.sub(r'([A-Z]{2,4})(\d{3,4}[A-Z]?)', r'\1 \2', code)

    def _req_header(req_id: str) -> str:
        if req_id in _GEN_ED_REQ_LABELS:
            return f"**{_GEN_ED_REQ_LABELS[req_id]}**"
        name = descriptions.get(req_id, "")
        return f"**{req_id}** — {name}" if name and name != req_id else f"**{req_id}**"

    with st.expander(f"✅ Satisfied Requirements ({len(satisfied)})", expanded=False):
        if satisfied:
            for req in satisfied:
                courses_used = satisfied_map.get(req, [])
                meta         = groups_meta.get(req, {})
                cr_req       = meta.get("credits_required")
                co_req       = meta.get("courses_required")
                if courses_used:
                    chips      = []
                    is_double  = False
                    for c in courses_used:
                        pl = " _(planned)_" if c in planned_set else ""
                        chips.append(f"**{_spaced(c)}**{pl}")
                        if usage.get(c, 0) > 1:
                            is_double = True
                    fulfilled = ", ".join(chips)
                    badge     = " &nbsp;🔄 **[Double-Counted]**" if is_double else ""
                    if cr_req:
                        total_cr   = sum(catalog.get(c, {}).get("credits", 0) for c in courses_used)
                        pool_badge = f" _({total_cr:.4g}/{cr_req:.4g} cr)_"
                    elif co_req and co_req > 1:
                        pool_badge = f" _({len(courses_used)}/{co_req} courses)_"
                    else:
                        pool_badge = ""
                    st.markdown(f"- ✅ {_req_header(req)} — Fulfilled by: {fulfilled}{pool_badge}{badge}")
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

                    meta   = groups_meta.get(req_id, {})
                    cr_req = meta.get("credits_required")
                    co_req = meta.get("courses_required")

                    if cr_req:
                        counted = max(0, cr_req - needed)
                        frac    = (f"partial — {counted:.4g}/{cr_req:.4g} cr"
                                   if counted > 0 else f"Need {needed:.4g} cr")
                        rec_part = (f" — Recommended: **{_spaced(recommended)}** ({frac})"
                                    if recommended else f" — {frac}")
                    elif co_req and co_req > 1:
                        counted = max(0, co_req - needed)
                        frac    = (f"partial — {counted}/{co_req} courses"
                                   if counted > 0 else f"Need {needed} more course(s)")
                        rec_part = (f" — Recommended: **{_spaced(recommended)}** ({frac})"
                                    if recommended else f" — {frac}")
                    else:
                        rec_part = (f" — Recommended: **{_spaced(recommended)}**"
                                    if recommended else f" — Need **{needed}** more {suffix}")

                    alt_part = (f" *(Alternatives: {', '.join(_spaced(o) for o in alternatives)})*"
                                if alternatives and recommended else "")
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
            # desc may be multi-program ("desc1 · desc2") for double-counted courses
            desc_parts = {part.strip() for part in desc.split(" · ")}
            found = True

            if "Required Course" in desc_parts:
                result[course] = {"desc": desc, "track": track, "alternatives": []}
                break

            track_req  = requirements.get(track, {})
            base       = track_req.get("base_requirements", {})
            conc_data  = track_req.get("concentrations", {}).get(conc, {})
            all_groups = base.get("choice_groups", []) + conc_data.get("choice_groups", [])

            for group in all_groups:
                g_desc = _req_short_desc(group["id"], group.get("description") or group["id"])
                if g_desc not in desc_parts:
                    continue

                if group.get("options"):
                    full_options = list(group["options"])
                elif group.get("type") == "rule_based":
                    full_options = get_rule_based_options(group.get("rule", {}), catalog)
                else:
                    full_options = []

                alternatives = [
                    o for o in full_options
                    if o not in assumed_set and o not in avoid_set and o not in path_set and o != course and o in catalog
                ]
                result[course] = {"desc": g_desc, "track": track, "alternatives": alternatives}
                break
            break

        if not found:
            result[course] = {"desc": "Prerequisite", "track": None, "alternatives": []}

    return result

# ══════════════════════════════════════════════════════════════════════════════
# App layout
# ══════════════════════════════════════════════════════════════════════════════
st.set_page_config(page_title="UNC Tar Heel Tracker Degree Planner", page_icon="🐏", layout="wide")

catalog, requirements, graph = load_static_data()

if "user_swaps" not in st.session_state:
    st.session_state.user_swaps = {}
if "planned_courses_committed" not in st.session_state:
    st.session_state.planned_courses_committed = []
if "avoid_courses_committed" not in st.session_state:
    st.session_state.avoid_courses_committed = []

all_tracks    = list(requirements.keys())
GEN_ED_TRACK  = "UNC_General_Education"
major_tracks  = [t for t in all_tracks if not is_minor(t) and t != GEN_ED_TRACK]
minor_tracks  = [t for t in all_tracks if is_minor(t) and t != GEN_ED_TRACK]

# ── Sidebar — degree configuration ────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Degree Configuration")
    st.caption("Select programs, then upload your transcript.")

    st.subheader("🎓 Majors")
    major1 = st.selectbox("Primary Major", options=major_tracks, format_func=fmt, key="major1", index=None, placeholder="Choose your major…", label_visibility="collapsed")
    conc1 = _concentration_widget(requirements, major1, key="conc1") if major1 else "None"

    dual = st.toggle("Add Second Major", key="dual")
    major2, conc2 = None, None
    if dual:
        major2 = st.selectbox("Second Major", options=major_tracks, format_func=fmt, index=None, placeholder="Choose your second major…", key="major2", label_visibility="collapsed")
        conc2 = _concentration_widget(requirements, major2, key="conc2") if major2 else "None"
        if major2 == major1 and conc2 == conc1:
            st.warning("Primary and second major are identical — select different programs.")
            dual, major2, conc2 = False, None, None

    st.divider()
    st.subheader("📖 Minors")

    minor1, minor2 = None, None
    conc_minor1, conc_minor2 = "None", "None"
    add_minor1 = add_minor2 = False

    if not minor_tracks:
        st.caption("No minors available in requirements data yet.")
    else:
        add_minor1 = st.toggle("Add a Minor", key="add_minor1")
        if add_minor1:
            minor1 = st.selectbox("First Minor", options=minor_tracks, format_func=fmt, key="minor1", index=None, placeholder="Choose your minor…", label_visibility="collapsed")
            conc_minor1 = _concentration_widget(requirements, minor1, key="conc_minor1") if minor1 else "None"
            second_minor_blocked = dual
            add_minor2_raw = st.toggle("Add Second Minor", key="add_minor2", disabled=second_minor_blocked, help="Requires only 1 major.")
            add_minor2 = add_minor2_raw and not second_minor_blocked

            if add_minor2:
                minor2 = st.selectbox("Second Minor", options=minor_tracks, format_func=fmt, index=None, placeholder="Choose your minor…", key="minor2", label_visibility="collapsed")
                conc_minor2 = _concentration_widget(requirements, minor2, key="conc_minor2") if minor2 else "None"
                if minor2 == minor1:
                    st.warning("Both minors are identical — select different programs.")
                    add_minor2, minor2 = False, None

    st.divider()
    with st.expander("🔮 What-If Scenarios", expanded=False):
        st.caption("Stage courses below, then click **Apply** to update the plan.")

        def _course_label(c: str) -> str:
            name = catalog.get(c, {}).get("name", "")
            spaced = _re.sub(r'([A-Z]{2,4})(\d{3,4}[A-Z]?)', r'\1 \2', c)
            display = spaced if spaced != c else c
            return f"{display} — {name[:42]}" if name else display

        with st.form(key="whatif_form", clear_on_submit=False):
            _staged_planned = st.multiselect(
                "Planned Courses (simulate taking these)",
                options=sorted(catalog.keys()),
                default=st.session_state.planned_courses_committed,
                format_func=_course_label,
                key="planned_courses_staged",
                placeholder="Type a course ID or name…",
            )
            _staged_avoid = st.multiselect(
                "Courses to Avoid (do not recommend these)",
                options=sorted(catalog.keys()),
                default=st.session_state.avoid_courses_committed,
                format_func=_course_label,
                key="avoid_courses_staged",
                placeholder="Type a course ID or name…",
            )
            _whatif_applied = st.form_submit_button("✅ Apply What-If Scenarios", use_container_width=True, type="primary")

        if _whatif_applied:
            st.session_state.planned_courses_committed = _staged_planned
            st.session_state.avoid_courses_committed   = _staged_avoid

        planned_courses: list[str] = st.session_state.planned_courses_committed
        avoid_courses:   list[str] = st.session_state.avoid_courses_committed

        if planned_courses or avoid_courses:
            st.caption(f"Active: **{len(planned_courses)}** planned · **{len(avoid_courses)}** avoided")

    st.divider()
    n_majors = 1 + (1 if dual and major2 else 0)
    n_minors = (1 if add_minor1 and minor1 else 0) + (1 if add_minor2 and minor2 else 0)
    st.caption(f"📋 **{n_majors}** major(s) + **{n_minors}** minor(s) + General Education (always)")

    st.divider()
    with st.expander("💬 Suggest a Feature / Report a Bug", expanded=False):
        with st.form(key="feedback_form", clear_on_submit=True):
            fb_type = st.radio("Type", ["Request a Major/Minor", "Feature Request", "Bug Report"], horizontal=True, label_visibility="collapsed")
            fb_title = st.text_input("Brief title", placeholder="One-line summary…")
            fb_desc = st.text_area("Details", placeholder="Describe the feature or bug…", height=110)
            fb_email = st.text_input("Email (optional)", placeholder="so I can follow up")
            st.caption("⚠️ Do not submit sensitive information, PIDs, or transcript data here.")
            _fb_submitted = st.form_submit_button("Submit", use_container_width=True)

        if _fb_submitted:
            if fb_title.strip() and fb_desc.strip():
                try:
                    _write_feedback({"type": fb_type, "title": fb_title.strip(), "description": fb_desc.strip(), "email": fb_email.strip() or None, "timestamp": datetime.datetime.now().isoformat()})
                    st.success("✅ Thanks! Your feedback has been submitted.")
                except Exception as _fb_err:
                    st.error(f"Submission failed: {_fb_err}")
            else:
                st.warning("Please fill in both the title and description.")

    st.divider()
    st.caption(
        "**Disclaimer:** This is an unofficial, student-built tool. "
        "It is not affiliated with, endorsed by, or connected to the University of North Carolina at Chapel Hill. "
        "Always consult your official Tar Heel Tracker and academic advisor."
    )

# ── Build generic majors_to_check list ─────────────
majors_to_check: list[dict] = []
if major1: majors_to_check.append({"track": major1, "concentration": conc1})
if dual and major2: majors_to_check.append({"track": major2, "concentration": conc2})
if add_minor1 and minor1: majors_to_check.append({"track": minor1, "concentration": conc_minor1})
if add_minor2 and minor2: majors_to_check.append({"track": minor2, "concentration": conc_minor2})
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

_privacy_consent = st.checkbox(
    "I understand that my transcript is processed securely in-memory and is never saved, stored, or viewed by humans or AI."
)
uploaded = st.file_uploader("Upload Tar Heel Tracker PDF", type=["pdf"], label_visibility="collapsed", disabled=not _privacy_consent)

if uploaded is not None:
    _file_bytes = uploaded.read()
    _key_src = json.dumps({
        "file": hashlib.md5(_file_bytes).hexdigest(),
        "majors": majors_to_check,
        "planned": sorted(planned_courses or []),
        "avoid": sorted(avoid_courses or []),
    }, sort_keys=True).encode()
    _pipeline_key = hashlib.md5(_key_src).hexdigest()

    if st.session_state.get("_pipeline_key") != _pipeline_key:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
            tmp.write(_file_bytes)
            tmp_path = tmp.name
        try:
            with st.status("Analyzing your degree plan… (up to 30 seconds)", expanded=False) as _status:
                _status.write("Parsing Tar Heel Tracker transcript…")
                data = run_pipeline(
                    tmp_path, majors_to_check, catalog, requirements, graph,
                    planned_courses=planned_courses,
                    avoid_courses=avoid_courses,
                )
                _status.update(label="Degree plan ready!", state="complete", expanded=False)
        except Exception as exc:
            st.error(f"Pipeline error: {exc}")
            st.stop()
        finally:
            os.unlink(tmp_path)
        st.session_state["_pipeline_key"] = _pipeline_key
        st.session_state["_pipeline_data"] = data
        st.session_state["user_swaps"] = {}
    else:
        data = st.session_state["_pipeline_data"]

    completed     = data["completed"]
    in_progress   = data["in_progress"]
    course_terms  = data.get("course_terms", {})
    planned       = data["planned"]
    audit         = data["audit"]
    path          = data["path"]
    semester_path = data.get("semester_path", {})

    _user_swaps = st.session_state.get("user_swaps", {})
    if _user_swaps:
        def _apply_swap(c: str) -> str:
            seen: set = set()
            while c in _user_swaps and c not in seen:
                seen.add(c)
                c = _user_swaps[c]
            return c
        path = [_apply_swap(c) for c in path]
        semester_path = {k: [_apply_swap(c) for c in v] for k, v in semester_path.items()}

    completed_credits    = sum(catalog.get(c, {}).get("credits", 0) for c in completed)
    in_progress_credits  = sum(catalog.get(c, {}).get("credits", 0) for c in in_progress)
    planned_credits      = sum(catalog.get(c, {}).get("credits", 0) for c in planned)
    total_parsed_credits = completed_credits + in_progress_credits

    mc1, mc2, mc3, mc4 = st.columns(4)
    mc1.metric("Courses Completed", len(completed))
    mc2.metric("Courses In-Progress", len(in_progress))
    mc3.metric("Planned (Pinned to Path)", len(planned), delta=f"+{planned_credits} cr" if planned else None, delta_color="normal")
    mc4.metric("Total Credits (Parsed)", total_parsed_credits)

    st.warning("⚠️ **Always cross-check with your academic advisor and the official Tar Heel Tracker.**")

    _completed_satisfies: dict[str, list[str]] = {}
    for _m in majors_to_check:
        _tr = _m["track"]
        if _tr not in audit: continue
        _plbl = _program_short_label(_tr)
        _prog_reqs = requirements.get(_tr, {})
        _base_reqs = _prog_reqs.get("base_requirements", {})
        _conc_reqs = _prog_reqs.get("concentrations", {}).get(_m["concentration"], {})
        _req_names: dict[str, str] = {}
        for _cid in _base_reqs.get("required_courses", []) + _conc_reqs.get("required_courses", []):
            _req_names[_cid] = catalog.get(_cid, {}).get("name", "") or _cid
        for _grp in _base_reqs.get("choice_groups", []) + _conc_reqs.get("choice_groups", []):
            _gid2 = _grp["id"]
            _req_names[_gid2] = _req_short_desc(_gid2, _grp.get("description") or _gid2)
        for _req_id, _courses_list in audit[_tr]["results"].get("satisfied_map", {}).items():
            _req_label = _req_names.get(_req_id, _req_id)
            for _c in _courses_list:
                _entry = format_fulfillment_label(_tr, _req_label)
                if _entry not in _completed_satisfies.get(_c, []):
                    _completed_satisfies.setdefault(_c, []).append(_entry)

        for _grp in _base_reqs.get("choice_groups", []) + _conc_reqs.get("choice_groups", []):
            _gid = _grp["id"]
            if _gid not in audit[_tr]["results"].get("unsatisfied", []): continue
            _credits_req = _grp.get("credits_required")
            _courses_req = _grp.get("courses_required", 1)
            _full_opts   = set(_grp.get("options") or get_rule_based_options(_grp.get("rule") or {}, catalog))
            _missing     = audit[_tr]["results"].get("missing_courses", {}).get(_gid, {})
            _remain_opts = set(_missing.get("options", []))
            _req_label   = _req_names.get(_gid, _gid)
            _contributed = _full_opts - _remain_opts
            if not _contributed: continue
            if _credits_req:
                _still_needed = _missing.get("credits_still_needed", _credits_req)
                _counted      = _credits_req - _still_needed
                if _counted <= 0: continue
                for _c in _contributed:
                    _cr = catalog.get(_c, {}).get("credits", 0)
                    _entry = f"{_plbl}: {_sanitize_desc(_req_label)} (partial — {_cr:.4g} cr of {_credits_req:.4g} cr needed)"
                    if _entry not in _completed_satisfies.get(_c, []):
                        _completed_satisfies.setdefault(_c, []).append(_entry)
            elif _courses_req > 1:
                _still_needed = _missing.get("still_needed", _courses_req)
                _counted      = _courses_req - _still_needed
                if _counted <= 0: continue
                for _c in _contributed:
                    _entry = f"{_plbl}: {_sanitize_desc(_req_label)} (partial — {_counted}/{_courses_req} courses)"
                    if _entry not in _completed_satisfies.get(_c, []):
                        _completed_satisfies.setdefault(_c, []).append(_entry)

    with st.expander(f"✅ Completed Courses ({len(completed)})", expanded=False):
        for c in completed:
            name = catalog.get(c, {}).get("name", "Unknown course")
            cr   = catalog.get(c, {}).get("credits", "?")
            satisfies = _completed_satisfies.get(c, [])
            spaced_c  = _re.sub(r'([A-Z]{2,4})(\d{3,4}[A-Z]?)', r'\1 \2', c)
            if satisfies:
                reqs_str = " &nbsp;·&nbsp; ".join(satisfies)
                st.markdown(f"- **{spaced_c}** — {name} ({cr} cr) → {reqs_str}")
            else:
                st.markdown(f"- **{spaced_c}** — {name} ({cr} cr) → _Not counted toward selected programs_")

    if in_progress:
        with st.expander(f"📘 In-Progress Courses ({len(in_progress)})", expanded=True):
            for c in in_progress:
                name  = catalog.get(c, {}).get("name", "Unknown course")
                cr    = catalog.get(c, {}).get("credits", "?")
                term  = course_terms.get(c)
                label = f" `{term}`" if term else ""
                spaced = f"{c[:4]} {c[4:]}" if len(c) > 4 else c
                st.markdown(f"- **{spaced}**{label} — {name} ({cr} cr)")

    if planned:
        _planned_impact: dict[str, list[str]] = {}
        for m in majors_to_check:
            _tr = m["track"]
            if _tr not in audit: continue
            for _c, _raw in audit[_tr].get("fulfillment_map", {}).items():
                if _c in set(planned):
                    for _part in _raw.split(" · "):
                        _lbl = format_fulfillment_label(_tr, _part.strip())
                        if _lbl not in _planned_impact.get(_c, []):
                            _planned_impact.setdefault(_c, []).append(_lbl)

        with st.expander(f"📌 Planned Courses in Path ({len(planned)})", expanded=True):
            _path_planned_set = set(path)
            for c in planned:
                name    = catalog.get(c, {}).get("name", "Unknown course")
                cr      = catalog.get(c, {}).get("credits", "?")
                in_path = c in _path_planned_set
                impacts = _planned_impact.get(c, [])
                status  = "✅ in path" if in_path else "⚠️ not schedulable yet (prereqs missing)"
                if impacts:
                    st.markdown(f"- **{c}** — {name} ({cr} cr) · {status} → {' &nbsp;·&nbsp; '.join(impacts)}")
                else:
                    st.markdown(f"- **{c}** — {name} ({cr} cr) · {status}")

    st.divider()

    total_req_all = sum(audit[m["track"]]["results"].get("total_requirements", 0) for m in majors_to_check if m["track"] in audit)
    total_sat_all = sum(audit[m["track"]]["results"].get("total_satisfied", 0) for m in majors_to_check if m["track"] in audit)
    global_pct = total_sat_all / total_req_all if total_req_all else 0.0
    st.subheader("📊 Overall Degree Progress")
    gcol1, gcol2 = st.columns([5, 1])
    with gcol1: st.progress(min(global_pct, 1.0))
    with gcol2: st.metric("Overall", f"{global_pct:.0%}")
    st.caption(f"{total_sat_all} of {total_req_all} requirements satisfied across all programs")

    st.divider()

    def _tab_label(m: dict) -> str:
        if m["track"] == GEN_ED_TRACK: return "🎓 General Education"
        label = fmt(m["track"])
        if m["concentration"] != "None": label += f" — {fmt(m['concentration'])}"
        return label

    tabs = st.tabs([_tab_label(m) for m in majors_to_check])
    global_course_usage = Counter(c for m in majors_to_check if m["track"] in audit for c in audit[m["track"]]["results"].get("courses_used", set()))

    for tab, program in zip(tabs, majors_to_check):
        with tab:
            track_data = audit.get(program["track"])
            if track_data:
                req_descriptions: dict[str, str] = {}
                req_groups_meta:  dict[str, dict] = {}
                _prog = requirements.get(program["track"], {})
                _base = _prog.get("base_requirements", {})
                _conc = _prog.get("concentrations", {}).get(program["concentration"], {})
                for _cid in _base.get("required_courses", []) + _conc.get("required_courses", []):
                    req_descriptions[_cid] = catalog.get(_cid, {}).get("name", "") or ""
                for _grp in _base.get("choice_groups", []) + _conc.get("choice_groups", []):
                    _gid = _grp["id"]
                    req_descriptions[_gid] = _req_short_desc(_gid, _grp.get("description") or _gid)
                    _gmeta: dict = {}
                    if _grp.get("credits_required"):
                        _gmeta["credits_required"] = _grp["credits_required"]
                    if _grp.get("courses_required", 1) > 1:
                        _gmeta["courses_required"] = _grp["courses_required"]
                    req_groups_meta[_gid] = _gmeta

                pct = track_data["results"].get("completion_pct", 0.0)
                satisfied_n = len(track_data["results"].get("satisfied", []))
                total_n     = satisfied_n + len(track_data["results"].get("unsatisfied", []))
                pcol1, pcol2 = st.columns([5, 1])
                with pcol1: st.progress(min(pct, 1.0))
                with pcol2: st.metric("Complete", f"{pct:.0%}")
                st.caption(f"{satisfied_n} of {total_n} requirements satisfied")
                render_audit(track_data["results"], path=path, catalog=catalog, planned=planned,
                             global_course_usage=global_course_usage,
                             req_descriptions=req_descriptions,
                             req_groups_meta=req_groups_meta)
            else:
                st.warning(f"No audit data found for {fmt(program['track'])}.")

    st.divider()

    # ── Double-Counted Courses ─────────────────────────────────────────────────
    _dc_map: dict[str, list[str]] = {}

    # Completed/in-progress courses that satisfy ≥2 program requirements
    for _c, _entries in _completed_satisfies.items():
        if len(_entries) >= 2:
            _dc_map[_c] = list(_entries)

    # Path courses that appear in ≥2 programs' fulfillment maps
    _path_set_dc = set(path)
    _path_dc_raw: dict[str, list[str]] = {}
    for _m in majors_to_check:
        _tr = _m["track"]
        if _tr not in audit:
            continue
        for _c, _raw in audit[_tr].get("fulfillment_map", {}).items():
            if _c in _path_set_dc:
                for _part in _raw.split(" · "):
                    _lbl = format_fulfillment_label(_tr, _part.strip())
                    if _lbl not in _path_dc_raw.get(_c, []):
                        _path_dc_raw.setdefault(_c, []).append(_lbl)
    for _c, _entries in _path_dc_raw.items():
        if len(_entries) >= 2 and _c not in _dc_map:
            _dc_map[_c] = _entries

    if _dc_map:
        # Assign a distinct color to each program label for badges
        _dc_palette = ["#6FA8DC", "#93C47D", "#B39DDB", "#FFD966", "#E06666"]
        _dc_prog_labels = sorted({
            e.split(": ", 1)[0] for _entries in _dc_map.values() for e in _entries
        })
        _dc_prog_colors = {lbl: _dc_palette[i % len(_dc_palette)] for i, lbl in enumerate(_dc_prog_labels)}

        def _hex_to_rgb(h: str) -> str:
            h = h.lstrip("#")
            return f"{int(h[0:2],16)},{int(h[2:4],16)},{int(h[4:6],16)}"

        _dc_completed_set   = set(completed)
        _dc_in_progress_set = set(in_progress)

        def _dc_sort_key(c: str) -> tuple:
            if c in _dc_completed_set:   return (0, c)
            if c in _dc_in_progress_set: return (1, c)
            return (2, c)

        _dc_cards: list[str] = []
        for _c in sorted(_dc_map, key=_dc_sort_key):
            _entries = _dc_map[_c]
            _name     = catalog.get(_c, {}).get("name", "")
            _cr       = catalog.get(_c, {}).get("credits", "?")
            _spaced_c = _re.sub(r'([A-Z]{2,4})(\d{3,4}[A-Z]?)', r'\1 \2', _c)
            _name_short = (_name[:52] + "…") if len(_name) > 52 else _name

            if _c in _dc_completed_set:
                _status_icon  = "✅"
                _status_label = "Completed"
                _status_style = "background:rgba(76,175,80,0.12);color:#4CAF50;border:1px solid rgba(76,175,80,0.35);"
                _card_style   = "border-color:rgba(76,175,80,0.25);background:rgba(76,175,80,0.03);"
            elif _c in _dc_in_progress_set:
                _status_icon  = "📘"
                _status_label = "In Progress"
                _status_style = "background:rgba(33,150,243,0.12);color:#2196F3;border:1px solid rgba(33,150,243,0.35);"
                _card_style   = "border-color:rgba(33,150,243,0.25);background:rgba(33,150,243,0.03);"
            else:
                _status_icon  = "📅"
                _status_label = "Planned"
                _status_style = "background:rgba(128,128,128,0.1);color:rgba(150,150,150,1);border:1px solid rgba(128,128,128,0.25);"
                _card_style   = ""

            _rows: list[str] = []
            for _entry in _entries:
                _parts    = _entry.split(": ", 1)
                _prog_lbl = _parts[0]
                _req_lbl  = _parts[1] if len(_parts) > 1 else _entry
                _color    = _dc_prog_colors.get(_prog_lbl, "#9E9E9E")
                _rgb      = _hex_to_rgb(_color)
                _rows.append(
                    f'<div class="dc-row">'
                    f'<span class="dc-prog" style="background:rgba({_rgb},0.14);color:{_color};border-color:rgba({_rgb},0.35);">{_prog_lbl}</span>'
                    f'<span class="dc-req">{_req_lbl}</span>'
                    f'</div>'
                )

            _dc_cards.append(
                f'<div class="dc-card" style="{_card_style}">'
                f'<div class="dc-header">'
                f'<span class="dc-code">{_spaced_c}</span>'
                f'<span class="dc-name">{_name_short}</span>'
                f'<span class="dc-cr">{_cr} cr</span>'
                f'<span class="dc-status" style="{_status_style}">{_status_icon} {_status_label}</span>'
                f'</div>'
                + "".join(_rows)
                + f'</div>'
            )

        _dc_css = """<style>
.dc-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:12px;margin:10px 0 6px}
.dc-card{border:1px solid rgba(128,128,128,0.2);border-radius:10px;padding:14px 16px;background:rgba(128,128,128,0.03)}
.dc-header{display:flex;align-items:center;gap:8px;margin-bottom:8px;flex-wrap:wrap}
.dc-code{font-weight:700;font-size:15px;white-space:nowrap}
.dc-name{color:rgba(150,150,150,1);font-size:13px;flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.dc-cr{font-size:11px;padding:2px 8px;border-radius:10px;background:rgba(128,128,128,0.1);white-space:nowrap;flex-shrink:0}
.dc-status{font-size:11px;font-weight:600;padding:3px 9px;border-radius:20px;white-space:nowrap;flex-shrink:0}
.dc-row{display:flex;align-items:center;gap:9px;padding:5px 0;border-top:1px solid rgba(128,128,128,0.1)}
.dc-prog{font-size:11px;font-weight:600;white-space:nowrap;padding:3px 10px;border-radius:20px;border:1px solid;flex-shrink:0}
.dc-req{font-size:13px}
</style>"""

        with st.expander(f"🔄 Double-Counted Courses ({len(_dc_map)})", expanded=True):
            st.caption(
                "Each course below simultaneously satisfies requirements for **multiple programs**, "
                "reducing your total course load."
            )
            st.markdown(
                _dc_css + f'<div class="dc-grid">{"".join(_dc_cards)}</div>',
                unsafe_allow_html=True,
            )
            st.markdown("")  # breathing room

    st.subheader("📅 Suggested Graduation Path")

    path_credits    = sum(catalog.get(c, {}).get("credits", 3) for c in path)
    total_projected = total_parsed_credits + path_credits

    if path:
        unknown_in_path = [c for c in path if c not in catalog]
        _path_set = set(path)
        _swap_orig_set = set(_user_swaps.keys())
        _course_fulfillment: dict[str, list[str]] = {}

        for _m in majors_to_check:
            _track = _m["track"]
            if _track not in audit: continue
            for _c, _raw in audit[_track].get("fulfillment_map", {}).items():
                if _c in _path_set or _c in _swap_orig_set:
                    for _part in _raw.split(" · "):
                        _lbl = format_fulfillment_label(_track, _part.strip())
                        if _lbl not in _course_fulfillment.get(_c, []):
                            _course_fulfillment.setdefault(_c, []).append(_lbl)

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
            if course in _course_fulfillment: return " · ".join(_course_fulfillment[course])
            if course in _prereq_for: return f"Prereq → {', '.join(_prereq_for[course][:3])}"
            for _orig, _repl in _user_swaps.items():
                if _repl == course and _orig in _course_fulfillment:
                    return " · ".join(_course_fulfillment[_orig])
            return "—"

        _swapped_in = set(_user_swaps.values())
        rows = [{"#": i, "Course": (f"🔄 {course}" if course in _swapped_in else f"📌 {course}" if course in _planned_set else course), "Name": catalog.get(course, {}).get("name", "—"), "Credits": catalog.get(course, {}).get("credits", 3), "Fulfills": _fulfills_label(course)} for i, course in enumerate(path, 1)]
        _path_df = pd.DataFrame(rows)
        try:
            _html_table = _path_df.to_html(index=False, escape=False).replace('<table border="1" class="dataframe">', '<table class="grad-table">')
        except Exception:
            _html_table = _path_df.to_html(index=False, escape=True).replace('<table border="1" class="dataframe">', '<table class="grad-table">')
        st.markdown(f"""
<div style="overflow-x: auto; max-width: 100%;">
  <style>
    .grad-table {{ width: max-content; min-width: 100%; border-collapse: collapse; font-size: 14px; }}
    .grad-table th {{ text-align: left; padding: 10px 14px; border-bottom: 2px solid rgba(128,128,128,0.3); white-space: nowrap; }}
    .grad-table td {{ text-align: left; padding: 8px 14px; border-bottom: 1px solid rgba(128,128,128,0.15); word-wrap: break-word; white-space: normal; max-width: 480px; }}
    .grad-table td:nth-child(1), .grad-table td:nth-child(2), .grad-table td:nth-child(4) {{ white-space: nowrap; }}
    .grad-table tr:hover td {{ background: rgba(128,128,128,0.08); }}
  </style>
  {_html_table}
</div>
""", unsafe_allow_html=True)
        st.caption(f"Remaining path credits: **{path_credits}**")

        _avoid_set_swap = set(avoid_courses)
        _alt_map = build_alternatives_map(path, audit, requirements, majors_to_check, catalog, _assumed_set, _avoid_set_swap)
        _swappable     = [c for c in path if _alt_map.get(c, {}).get("alternatives")]
        _non_swappable = [c for c in path if not _alt_map.get(c, {}).get("alternatives")]

        with st.expander("🔄 Swap a Course", expanded=False):
            if not _swappable:
                st.info("Every course in the current path is required with no valid alternatives.")
            else:
                def _clabel(c: str) -> str:
                    name   = catalog.get(c, {}).get("name", "")
                    cr     = catalog.get(c, {}).get("credits", 3)
                    spaced = _re.sub(r'([A-Z]{2,4})(\d{3,4}[A-Z]?)', r'\1 \2', c)
                    return f"{spaced} ({cr} cr) — {name[:40]}" if name else f"{spaced} ({cr} cr)"

                _swap_out = st.selectbox("Step 1 — Select a course to replace", options=_swappable, format_func=_clabel, key="swap_remove_selectbox", index=None, placeholder="Choose a course to swap out…")
                _swap_in: str | None = None
                if _swap_out is not None:
                    _alternatives = _alt_map.get(_swap_out, {}).get("alternatives", [])
                    _req_desc     = _alt_map.get(_swap_out, {}).get("desc", "")
                    _swap_in = st.selectbox("Step 2 — Choose replacement", options=_alternatives, format_func=_clabel, key="swap_add_selectbox", index=None, placeholder="Choose a replacement…", help=f"Satisfies: {_req_desc}")

                if _swap_out is not None and _swap_in is not None:
                    _out_cr   = catalog.get(_swap_out, {}).get("credits", 3)
                    _in_cr    = catalog.get(_swap_in,  {}).get("credits", 3)
                    _cr_delta = _in_cr - _out_cr
                    _cr_note  = (f" &nbsp;·&nbsp; Credits: {_out_cr} → {_in_cr} " + (f"(+{_cr_delta})" if _cr_delta > 0 else f"({_cr_delta})")) if _cr_delta != 0 else ""

                    _in_prereqs      = catalog.get(_swap_in, {}).get("prerequisites", [])
                    _missing_prereqs: list[str] = []
                    if _in_prereqs:
                        _best_pp = min(_in_prereqs, key=len)
                        _missing_prereqs = [p for p in _best_pp if p not in _assumed_set]

                    st.info(f"**{_swap_out}** → **{_swap_in}** &nbsp;·&nbsp; Satisfies: *{_req_desc}*{_cr_note}")
                    if _missing_prereqs:
                        st.warning(f"⚠️ **{_swap_in}** requires {', '.join(_missing_prereqs)} — these will be added to your graduation path automatically.")

                    def _do_swap() -> None:
                        old_course_val = st.session_state.get("swap_remove_selectbox")
                        new_course_val = st.session_state.get("swap_add_selectbox")
                        if not old_course_val or not new_course_val: return

                        swaps = dict(st.session_state.get("user_swaps", {}))
                        swaps[old_course_val] = new_course_val
                        st.session_state["user_swaps"] = swaps

                        st.session_state.pop("swap_remove_selectbox", None)
                        st.session_state.pop("swap_add_selectbox",    None)

                    st.button("✅ Confirm Swap", key="execute_swap_btn", type="primary", use_container_width=True, on_click=_do_swap)

            if _non_swappable:
                _ns_items = _non_swappable[:10]
                _ns_more  = f" (+{len(_non_swappable) - 10} more)" if len(_non_swappable) > 10 else ""
                st.caption(f"🔒 **No alternatives:** {', '.join(_ns_items)}{_ns_more}")

        csv_buf = io.StringIO()
        csv_buf.write("Course Code,Course Name,Credits,Fulfills\n")
        for row in rows:
            name_escaped     = row["Name"].replace('"', '""')
            fulfills_escaped = row["Fulfills"].replace('"', '""')
            raw_code = _re.sub(r'^[🔄📌]\s*', '', row["Course"])
            csv_buf.write(f'"{raw_code}","{name_escaped}",{row["Credits"]},"{fulfills_escaped}"\n')

        st.download_button(label="📥 Download Graduation Plan", data=csv_buf.getvalue().encode("utf-8"), file_name="graduation_plan.csv", mime="text/csv", use_container_width=True)

        assumed_for_graph = list(dict.fromkeys(completed + in_progress + planned))
        with st.expander("🕸️ Prerequisite Tree", expanded=True):
            try:
                dot_src = build_prereq_dot(path, catalog, assumed_for_graph, in_progress)
                st.markdown("<style>div[data-testid='stGraphVizChart'] iframe { min-height: 640px !important; }</style>", unsafe_allow_html=True)
                st.graphviz_chart(dot_src, use_container_width=True)
            except Exception as _graph_err:
                st.warning(f"⚠️ Prerequisite graph could not be rendered: {_graph_err}")
                st.caption("This can happen when the path contains courses with no prerequisite connections. The course list above is still accurate.")
    else:
        st.success("No remaining required courses — all requirements are covered by your transcript!")

    st.divider()
    st.subheader("🎓 Credit Progress")
    credit_pct = min(total_projected / UNC_MIN_CREDITS, 1.0)
    ccol1, ccol2 = st.columns([5, 1])
    with ccol1: st.progress(credit_pct)
    with ccol2: st.metric("Credits", f"{total_projected} / {UNC_MIN_CREDITS}")
    if total_projected < UNC_MIN_CREDITS:
        st.warning(f"**{UNC_MIN_CREDITS - total_projected} credits short** of the UNC {UNC_MIN_CREDITS}-hour graduation minimum. Complete additional general electives to close the gap.")
    else:
        st.success(f"✅ Projected total meets the UNC {UNC_MIN_CREDITS}-hour graduation minimum.")

else:
    st.info("👆 Upload a Tar Heel Tracker PDF above to get started.")