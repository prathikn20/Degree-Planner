# UNC Degree Planner

An interactive degree-planning engine for UNC Chapel Hill that models course prerequisites as a directed graph and uses Iterated Local Search to generate optimized courses to take toward graduation. Given a student's completed coursework via an uploaded Tar Heel Tracker and declared majors or minors, the solver enforces prerequisite chains, concentration rules, and university policies to produce a constraint-satisfying plan in seconds.

> **Live app:** [unc-degree-planner.streamlit.app](https://unc-degree-planner.streamlit.app/) 

## Future Features to be Implemented

- Move hosting off Streamlit to a custom app built with Next.js
- Allow users to plan courses across semesters interactively and download the full semester-by-semester CSV, not just the flat course list
- Give users the ability to manually override or correct degree requirements directly in the UI, to compensate for scraping inaccuracies

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
app.py                              # Streamlit UI + pipeline orchestration
src/
  planner/
    graph.py                        # Prerequisite graph construction + is_available
    path_generator.py               # Phase 1 greedy + Phase 2 ILS constraint solver
    requirements_checker.py         # Degree audit, slot generation, canonical catalog
    transcript_parser.py            # PDF transcript parser (Tar Heel Tracker)
    topological_sort.py             # Kahn's algorithm → semester layout
data/
  course_catalog.json               # 8,500+ courses (scraped, enriched, prereq-parsed)
  degree_requirements.json          # 197 degree/minor tracks with requirement rules
  overrides.json                    # Manual prerequisite overrides
  requirements_manual_patches.json  # Hand-curated patches (survive re-scrapes)
  backup/                           # Archived production snapshots
  staging/                          # Working files during catalog refresh
  .cache/                           # Ephemeral scraper caches (safe to delete)
scripts/
  run_catalog_pipeline.py           # Scrape UNC course catalog → course_catalog.json
  run_requirements_pipeline.py      # Scrape UNC degree pages → degree_requirements.json
  validate_pipeline_output.py       # Data quality validator — run after every pipeline update
tests/
  test_pre_deployment_sweep.py      # 1,290-test QA gauntlet (data + solver + formatting)
```

### Refreshing data

> **Warning:** The data pipeline is complex and the output requires significant testing and manual review before deploying. The scraper frequently misclassifies requirement sections, collapses elective pools into required-course lists, or omits courses entirely. Always run the validator and the full test suite, and spot-check affected tracks by hand before pushing any pipeline output to production.

```bash
# 1. Re-scrape the course catalog (picks up new departments, updated prereqs)
python3 scripts/run_catalog_pipeline.py

# 2. Re-scrape degree requirements using the local LLM (qwen2.5:14b via Ollama)
#    Full run — processes all tracks, skips already-present ones:
python3 scripts/run_requirements_pipeline.py
#    Force re-scrape specific tracks (e.g. after a scraper fix):
python3 scripts/run_requirements_pipeline.py --tracks Physics_BA Latin_American_Studies_BA --force
#    Skip LLM for a fast regex-only pass (simpler rules only):
python3 scripts/run_requirements_pipeline.py --no-llm

# 3. Validate — must show 0 errors before deploying
python3 scripts/validate_pipeline_output.py --strict

# 4. Run the QA test suite
python3 -m pytest tests/test_pre_deployment_sweep.py -q
```

---

## License

MIT — see [LICENSE](LICENSE).
