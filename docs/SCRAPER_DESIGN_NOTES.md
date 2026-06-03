# Scraper Thoughts — Degree Requirements Pipeline Fixes

## Session Goal
Make the 5-step pipeline fully automatic for all 36 TARGET_TRACKS, with no manual
post-processing. Previously 15+ programs had catastrophically inflated `required_courses`
counts (82–231) caused by reference/elective pool sections being classified as required.

---

## Root Cause Analysis

The pipeline's `classify_section_type()` only had three return values (`core`, `concentration`,
`reference_list`) and used a small set of title keywords to decide. This missed:

1. **Grouped reference pools**: Allied Science Electives pages have N department sub-sections
   each appearing as a separate `core` section → N×(section_size) courses added to required.
2. **Elective size sections**: "Knowledge Electives (6 Credit Hours)" is a pick-from pool
   but contains "Core" ancestry, so was classified `core`.
3. **Elective course lists**: "Public Policy Elective Course List" was correctly handled by
   keyword, but stale cache showed old results.
4. **Sample plan sub-sections**: Chemistry/Statistics sample-plan years were processed as
   real requirements.
5. **Department descriptor rules**: "ASTR --- | Any ASTR course above 99" type rule_texts
   were treated as real selection rules, preventing pure-pool detection.
6. **Missing URL bugs**: Statistics, Biostatistics, Business BSBA, Anthropology General all
   404'd because the catalog URLs had changed.

---

## Changes Made

### `run_requirements_pipeline.py`
- **Fixed 4 broken URLs**: Statistics, Biostatistics, Business BSBA, Anthropology General.
- **Added `propagate_reference_lists(sections)`**: Two-pass classification propagation.
  - Rule A: a pool-candidate section adjacent to a content-bearing reference_list inherits it.
    (Only content-bearing neighbours trigger propagation — empty reference_list headers must
    not bleed backward into genuine required sections.)
  - Rule B: any section directly following a reference_list empty header inherits it.
    (Handles sample-plan children like "First Year", "Major Courses" inside "Sample Plan of Study".)
  - `is_pool_candidate()`: allows low or_alt density (< 20%) so Group A/Group B in Statistics
    are recognised as pools even though they have a couple of cross-listed course alternatives.
- **Called `propagate_reference_lists` before assembly** so each section carries `_type`.

### `src/scraper/requirements_scraper.py`
- **Updated `_BOILERPLATE_RE`**: Added patterns for department pool-descriptor rule_texts:
  - `^[A-Z]{2,5}\s*[-| ]+any\s+\w+\s+course` → "COMP | Any COMP course", "ASTR --- | Any ASTR course above 99"
  - `^any\s+[A-Z]{2,5}\s+course\b` → "Any STOR course above 155", "Any NSCI course"
  These must be boilerplate (not real rules) so that Allied Science sub-sections with only
  these descriptors are correctly classified as pure pools.
- **Added `group_pool_sections(sections)`**: Pre-processor that collapses child sections under
  their parent header before the assembler sees them.
  - Mode A (multi-child merge): Header section + ≥2 consecutive pure-pool children → one merged
    section. If children have a "campus" signal (UNC Campus / N.C. State Campus), appends
    " Concentration" to the title so `classify_section_type` detects it.
  - Mode A (single-child generic): If parent has a generic title like "Requirements" and there
    is exactly one pure-pool child, the child's title is promoted (preserves "Course List"
    keywords for reference_list detection).
  - Mode B (concentration detection): Header (0 courses) immediately followed by a section
    named exactly "Requirements" → renamed to `"<title> Concentration"`.
  - Threshold: single-child, non-generic parent headers do NOT merge (prevents standalone
    pool like "Experiential Education" from being consumed by the adjacent "Statistics and
    Operations Research" dept-descriptor header).

### `src/scraper/requirements_assembler.py`
- **Extended `_EXPLICIT_RULE_RE`**: Added broader count + course/elective patterns.
  - `_COUNT_WORDS + .{0,60} + courses?/electives?` — catches "Four POLI electives at 100+",
    "Five three-hour ANTH courses taken in the department"
  - `_COUNT_WORDS + .{0,40} + credits?/hours?` — catches "Fifteen hours of advanced chemistry"
  - `at\s+least + count + courses?/credits?` — catches "At least three credits from..."
  Added a quick-reject for boilerplate lines so they are never sent to the LLM.
- **Extended `LIST_HEADER_PATTERNS`**: Added:
  - `see list(s)/requirements below` — "Four specialty electives - see requirements below"
  - `from (the) list(s)/requirements below`
  - `remaining \w+ from` — "Remaining credits from list below"
  - `at least N credits/courses from`
  - `N credits/hours from`
- **Updated `_BOILERPLATE_ROW_RE`**: Same dept-descriptor patterns as in requirements_scraper.py.
  Used by `_count_real_rules` (the assembler's equivalent of `_is_real_rule`).
- **Added reference_list keywords** to `_REF_TITLE`:
  - `'course list'` — "Organismal Structure and Diversity Course List"
  - `'major courses'` — Chemistry/Statistics sample-plan listing
  - `'sample plan'`, `'plan of study'`
- **Added pattern checks**:
  - `^note\s*:` titles → reference_list (footnotes/clarifications, e.g. "Note: CHEM 481...")
  - `^(first|second|third|fourth|fifth)\s+(year|semester)` → reference_list (sample-plan years)
- **Improved `classify_section_type(title, rows=None)`**:
  - `(N credit hours)` in title → reference_list (pick-from pool headers)
  - "electives" in title + no required/core qualifier + no real rules → reference_list
    (added `rr == 0` guard so "Business Electives" with a real rule stays core)
  - Content-based tiered fallback (no real rules, no hard required signal in title):
    - course_count ≥ 5 + no or_alts + no soft required signal → reference_list
    - course_count ≥ 5 + no or_alts + soft required signal (title has "requirements") → only if ≥ 15
    - course_count ≥ 15 (any or_alt count) + no hard required signal → reference_list
      (handles merged "Requirements" sections containing multiple reference pools with or_alts)
- **Updated `assemble_section`**: passes `rows` to `classify_section_type`; also reads
  `_type` injected by `propagate_reference_lists` so no double-classification.

---

## Programs Fixed

| Program | Old req | Expected | Root Cause Fixed |
|---|---|---|---|
| Psychology_BS | 204 | ~5 | Allied Science department sub-sections grouped → ref_list |
| Public_Policy_BA | 231 | ~9 | Elective Course List keyword (was cached stale) |
| Neuroscience_BS | 122 | ~5 | Knowledge/Math Electives (credit hours) → ref_list |
| Exercise_and_Sport_Science_BS | 134 | ~6 | Allied Science grouped; dept descriptors as boilerplate |
| Political_Science_BA | 107 | ~5 | Subfield sections grouped → ref_list |
| Sociology_BA | 24 | ~5 | Career cluster sections propagated → ref_list |
| Biomedical_Engineering_BS | 82 | ~20 + concs | Campus sub-sections → concentrations via Mode A |
| Biology_BS | 82 | ~5 | Organismal+Allied merged as ref_list |
| Data_Science_Minor | 110 | ~5 | Elective List keyword (was cached stale) |
| Public_Policy_Minor | 225 | ~3 | Elective Course List keyword (stale cache) |
| Applied_Sciences_and_Engineering_Minor | 63 | ~10 | Topic sub-sections grouped → ref_list |
| Statistics_and_Analytics_BS | 404 | ✓ | URL bug fixed |
| Biostatistics_BSPH | 404 | ✓ | URL bug fixed |
| Business_Administration_BSBA | 404 | ✓ | URL bug fixed |
| Anthropology_General_Minor | 404 | ✓ | URL bug fixed |

---

## Known Remaining Limitations

1. **Physics_BS**: Both "Standard" and "Astrophysics" options merge into one `base_requirements`
   (two empty concentration headers). Required count will be ~20 instead of 11.
2. **Biomedical_Engineering_BS**: "Requirements" sub-section (13 courses) still contributes
   some to required_courses; overall req may be ~20-25 vs production's 9.
3. **Chemistry_BS**: Additional Requirements (6 MATH/PHYS prereqs) stays in required; req ~18
   vs production's 9.
4. **Biostatistics_BSPH**: Prerequisite courses (6) stay in required alongside Core (10) → req ~19.
5. **Cross-section list references**: Rules like "see list below" that point to courses in the
   NEXT section fall to LLM (rule_based group) since list_header only looks within the current
   section. This is acceptable — the requirement is captured even if options aren't enumerated.

---

## Architecture Summary (after fixes)

```
HTML page
  └── requirements_scraper.scrape_major_requirements()
        └── group_pool_sections()  ← NEW: collapse dept sub-sections
  ↓
  sections list
  └── run_requirements_pipeline.propagate_reference_lists()  ← NEW: propagate ref_list types
  ↓
  sections with _type injected
  └── requirements_assembler.assemble_section()
        └── classify_section_type(title, rows)  ← IMPROVED: rows-aware content check
        └── is_list_header()  ← IMPROVED: more patterns
        └── _is_explicit_rule()  ← IMPROVED: broader count+course patterns
  ↓
  block (required_courses, choice_groups, block_type)
  ↓
  run_requirements_pipeline merges blocks → degree_requirements JSON
```
