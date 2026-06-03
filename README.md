# UNC Degree Planner

An interactive degree-planning engine for UNC Chapel Hill that models course prerequisites as a directed graph and uses Iterated Local Search to generate optimized semester-by-semester schedules toward graduation. Given a student's completed coursework, declared major, and credit-hour preferences, the solver enforces prerequisite chains, concentration rules, and university policies to produce a constraint-satisfying four-year plan in seconds.

> **Live app:** [degree-planner.streamlit.app](https://degree-planner.streamlit.app) *(replace with your Streamlit Cloud URL)*

---

## Local Setup

**Requirements:** Python 3.11+

```bash
# 1. Clone the repo
git clone https://github.com/<your-org>/Degree-Planner.git
cd Degree-Planner

# 2. Install dependencies
pip install -r requirements.txt

# 3. (Optional) Configure secrets for Google Sheets feedback
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Edit secrets.toml with your GCP service account credentials

# 4. Run the app
streamlit run app.py
```

The app loads entirely from static JSON data files in `data/` — no database or external API calls are required to run the planner itself.

---

## Secrets (Streamlit Community Cloud)

The feedback form writes to Google Sheets via a GCP service account. If you are deploying to Streamlit Cloud, add the following keys in **Settings → Secrets**:

| Key | Description |
|---|---|
| `FEEDBACK_SHEET_ID` | Google Sheet ID (from the sheet URL) |
| `gcp_service_account` | Full contents of a GCP service account JSON key (as a TOML table) |

See `.streamlit/secrets.toml.example` for the exact structure. If these secrets are absent, the app falls back to writing feedback to a local `logs/feedback.json` file — the planner remains fully functional.

---

## Architecture

```
app.py                      # Streamlit UI
src/
  planner/
    graph.py                # Prerequisite graph construction
    path_generator.py       # ILS constraint solver
    requirements_checker.py # Degree audit / rule validation
    transcript_parser.py    # PDF transcript parser (Tar Heel Tracker)
    topological_sort.py     # Topological sort (Kahn's algorithm)
data/
  course_catalog.json       # Course catalog (scraped + enriched)
  degree_requirements.json  # Degree requirement rules
  backup/                   # Archived production snapshots
  staging/                  # Working files during catalog refresh
  .cache/                   # Ephemeral scraper caches (safe to delete)
```

---

## License

MIT — see [LICENSE](LICENSE).
