# UNC Degree Planner — Catalog Refresh: LLM Parsing Engine

**Role:** LLM Parsing Engine. Re-parse degree requirements from updated HTML cache and sync them into `data/degree_requirements.json`.

Working directory: `/Users/prathik/code/Degree-Planner`

---

## CONTEXT: What This Project Is

`data/degree_requirements.json` stores structured course requirements for every UNC degree/minor. The planner's entire algorithm depends on this data being accurate. The UNC catalog was recently re-scraped into `data/.cache/html/<TRACK_ID>.txt`. This session exists to find every track where the catalog content differs from the stored requirements and re-parse those tracks to reflect the current catalog.

**Files:**
- `data/.cache/html/<TRACK_ID>.txt` — current scraped catalog content (source of truth)
- `data/degree_requirements.json` — structured requirements (what we're updating)
- `data/staging/test_degree_requirements.json` — working copy (write here first, swap at end)
- `data/staging/parse_status.json` — tracks progress: `pending`=needs work, `done`=finished this session, `verified`/`seeded`=skip

**DO NOT touch:** `data/course_catalog.json`, `data/.cache/course_cache.json`, `src/planner/`

---

## SESSION START — RUN THIS FIRST

```python
python3 -c "
import json
s = json.load(open('data/staging/parse_status.json'))
pending = [t for t,v in s.items() if v == 'pending']
done    = [t for t,v in s.items() if v == 'done']
vs      = [t for t,v in s.items() if v in ('verified','seeded')]
print(f'Remaining: {len(pending)}  Done this session: {len(done)}  Skip: {len(vs)}')
for t in pending: print(' ', t)
"
```

If there are 0 pending tracks, jump to **FINAL SWAP**.

---

## HOW TO CHECK IF A TRACK ACTUALLY CHANGED (diff check)

Before re-parsing, verify the discrepancy is real:

```python
python3 -c "
import json, os, re

def courses_in_cache(track_id):
    path = f'data/.cache/html/{track_id}.txt'
    if not os.path.exists(path): return set()
    codes = set()
    with open(path) as f:
        for line in f:
            for m in re.finditer(r'([A-Z]{2,5})\s+(\d{3}[A-Z0-9]*)', line):
                codes.add(m.group(1)+m.group(2))
    return codes

def courses_in_req(entry):
    codes = set()
    def walk(obj):
        if isinstance(obj, list):
            for x in obj:
                if isinstance(x, str) and re.match(r'^[A-Z]{2,4}\d{3}', x): codes.add(x)
                elif isinstance(x, dict): walk(x)
        elif isinstance(obj, dict):
            for v in obj.values(): walk(v)
    walk(entry)
    return codes

data = json.load(open('data/degree_requirements.json'))
TRACK = 'Data_Science_BS'   # <-- change per track
cache = courses_in_cache(TRACK)
req   = courses_in_req(data.get(TRACK, {}))
print('In cache, not in req (possibly missing):', sorted(cache - req))
print('In req, not in cache (possibly stale):', sorted(req - cache))
"
```

---

## THE LOOP — for each pending track

**a.** Read `data/.cache/html/<TRACK_ID>.txt`  
**b.** Also look at the existing entry: `data/degree_requirements.json[TRACK_ID]` to understand current structure  
**c.** Parse using the schema below — keep structure identical, update only course codes and options lists to match html_cache  
**d.** Save atomically (pattern below)  
**e.** Mark done in parse_status.json (same atomic pattern)  
**f.** Print: `✓ TRACK_ID | changed: X courses added, Y removed`

### ATOMIC SAVE PATTERN (use every time, no exceptions):

```python
import json, os

out = json.load(open('data/staging/test_degree_requirements.json'))
out['TRACK_ID'] = { <your parsed entry> }
with open('data/staging/test_degree_requirements.json.tmp', 'w') as f:
    json.dump(out, f, indent=2)
os.replace('data/staging/test_degree_requirements.json.tmp',
           'data/staging/test_degree_requirements.json')

status = json.load(open('data/staging/parse_status.json'))
status['TRACK_ID'] = 'done'
with open('data/staging/parse_status.json.tmp', 'w') as f:
    json.dump(status, f, indent=2)
os.replace('data/staging/parse_status.json.tmp', 'data/staging/parse_status.json')
```

---

## PARSING PHILOSOPHY — what to update vs preserve

**Update:**
- Course codes in `options[]` lists — add courses in html_cache, remove courses no longer there
- `required_courses` — must match what html_cache shows as always-required (no OR)
- `courses_required` count — if the html_cache rule changed (e.g., "choose 3" → "choose 4")
- New choice groups if the html_cache added new requirement blocks
- New concentrations if html_cache added new concentration sections

**Preserve:**
- The overall structure (`base_requirements` / `concentrations` split) unless the major was fundamentally restructured
- Group `id` values — only change if the group itself was removed/replaced
- `type` (explicit vs rule_based) — only change if the rule type changed
- `is_core` values
- `rule` objects for rule_based groups — only update `exclude` if courses were added/removed from exclusion list

**Key rule:** If a course appears in html_cache under a section → it belongs in `options[]` for that group. If a course was in `options[]` but is NOT in html_cache at all → remove it. If structure changed (e.g., new concentration added) → add the new concentration, keep old ones unless they're gone from html_cache.

---

## CRITICAL: REQUIRED_COURSES vs CHOICE_GROUPS — DOUBLE-COUNTING RULE

**The single most common scraping mistake:** putting the SAME course in both `required_courses[]` AND a choice group's `options[]` for the same program. This forces the planner to count the course twice (once for each slot), inflating credit totals.

### The rule:
> A course belongs in `required_courses[]` **OR** in a choice group's `options[]` — **never both** for the same program scope (base + same concentration).

### When it happens:
The UNC catalog often lists gateway/elective pools as "Requirements" sections. The scraper sees both the pool header ("Choose 3 gateway electives") and an all-courses section ("Requirements"), and incorrectly puts every pool option into `required_courses`.

### How to identify it:
Run this validation after parsing any track:
```python
python3 << 'EOF'
import json
data = json.load(open('data/degree_requirements.json'))
TRACK = 'Biomedical_Engineering_BS'   # <-- change per track
entry = data[TRACK]
base_req = set(entry['base_requirements'].get('required_courses', []))
for group in entry['base_requirements'].get('choice_groups', []):
    overlap = base_req & set(group.get('options', []))
    if overlap:
        print(f"OVERLAP in base [{group['id']}] needs {group['courses_required']}: {sorted(overlap)}")
for cname, cdata in entry.get('concentrations', {}).items():
    if cname == 'None': continue
    conc_req = set(cdata.get('required_courses', []))
    for group in entry['base_requirements'].get('choice_groups', []):
        overlap = conc_req & set(group.get('options', []))
        if overlap:
            print(f"OVERLAP in {cname} vs base [{group['id']}] needs {group['courses_required']}: {sorted(overlap)}")
EOF
```
**Any output = a bug.** Fix it before finalising the parse.

### Fix patterns:

**Pattern A — elective pool wrongly in required_courses:**
The catalog says "Choose 3 gateway electives from: BMME315, BMME325, …" but the scraper put all 7 into `required_courses`. Fix: remove them from `required_courses`; they already live in the choice group.

**Pattern B — concentration courses overlap with a base elective group:**
Pharmacoengineering concentration requires BMME511, BMME523, etc. Those courses also appear in the base `bme_specialty_electives` group (choose 4). The algorithm handles this automatically — concentration required courses satisfy the base elective group — but only if the courses are NOT also in base `required_courses`. Do NOT copy concentration required courses into base `required_courses`.

**Pattern C — prerequisite/foundation courses listed twice:**
Some programs list MATH231 in both `required_courses` and as an option in a "Mathematics requirement" choice group. Fix: keep it in `required_courses` only and remove it from the choice group options (or use `scripts/data/fix_additional_required_courses.py` which moves them the other way for is_core accounting).

---

## BME-SPECIFIC NOTES (Biomedical_Engineering_BS)

The BME program was fixed manually (2026-06) to correct a severe scraping mistake. When re-parsing BME from html_cache, preserve these hard-won corrections:

**required_courses (base)** should contain ONLY the 15 always-required courses:
```
BMME150, BMME160, BMME201, BMME205, BMME207, BMME209, BMME215L, BMME217L, BMME219L,
BMME298, BMME301, BMME302, BMME398, BMME697, BMME698
```
(The labs BMME215L/217L/219L pair with the 4-credit courses BMME205/207/209 and are separately required.)

**DO NOT add to required_courses:**
- BMME315/335/345/355/365/375/385 — these are options in `bme_gateway_electives` (choose 3)
- APPL465, BIOL220, BIOL443, BIOL451, MATH347, MATH381, PHYS331, PHYS381, PHYS461 — options in `bme_stem_elective` (choose 1)
- ENVR451, EXSS380, EXSS385 — these appeared in the catalog's "Allied Science" reference list; they are NOT BME requirements
- Concentration courses (BMME495, BMME511, etc.) — they belong only in concentration `required_courses`, not in base

**Foundation courses** (CHEM101/102/261, MATH231-383, PHYS118/119, BIOL101) live in `choice_groups` as single-option `is_core: False` groups, not in `required_courses`. This is intentional — it keeps them out of the C4 50%-exclusivity core count while still requiring them.

---

## OUTPUT JSON SCHEMA

```json
{
  "base_requirements": {
    "required_courses": ["DEPT123"],
    "choice_groups": [ <group>, ... ]
  },
  "concentrations": {
    "None": { "required_courses": [], "choice_groups": [] },
    "Conc_Name": { "required_courses": [], "choice_groups": [] }
  }
}
```

**explicit group** (named course list):
```json
{
  "id": "dept_1",
  "description": "exact rule text from html_cache",
  "type": "explicit",
  "courses_required": 1,
  "options": ["DEPT123", "DEPT456"],
  "rule": null,
  "is_core": true
}
```

**rule_based group** (open pool — "any N DEPT courses above X"):
```json
{
  "id": "dept_electives_1",
  "description": "exact rule text",
  "type": "rule_based",
  "courses_required": 3,
  "credits_required": null,
  "options": [],
  "rule": {
    "department": "COMP",
    "min_number": 420,
    "min_credits": 3,
    "exclude": ["COMP496"]
  },
  "is_core": true
}
```

**Rules:**
- Named course list in txt → `"explicit"` with those courses in `options[]`
- "any N DEPT courses above X" → `"rule_based"`
- Always required (no OR) → `required_courses[]`
- OR rows = alternatives → one explicit group, both codes in `options[]`
- Cross-listed (DEPT1/DEPT2 123) → explicit group, both codes in `options[]`
- Course codes: no spaces — "COMP 110" → "COMP110"
- "None" concentration always present even if empty

---

## READING html_cache FILES

```
## Section Name        → structural block (base vs concentration)
NOTE: some rule text   → context only
RULE: choose N from: X → a choice_group rule
  DEPT 123 | Title | 3hrs  → course in current block
  OR or DEPT 456 | Title   → alternative for course above it
### Sub-header         → sub-section within current block
```

---

## EFFICIENT BATCHING STRATEGY

Process in batches of 5–8 tracks per message. For each batch:
1. Read all html_cache files for that batch in parallel (use multiple Read tool calls in one message)
2. Write one Python script that processes the entire batch atomically
3. Run it, verify output
4. Move to next batch

**Reading current entry before re-parsing** (for each track):
```python
python3 -c "
import json, pprint
d = json.load(open('data/degree_requirements.json'))
pprint.pprint(d['TRACK_ID'])
" 2>&1 | head -80
```

This lets you see exactly what structure exists so you only change what the html_cache says changed, not the whole structure.

---

## TRACKS CURRENTLY PENDING (86 total)

```
Aerospace_Studies_Minor
African_American_and_Diaspora_Studies_Minor
African_Studies_Minor
American_Indian_and_Indigenous_Studies_Minor
American_Studies_BA_AIIS_Concentration
Applied_Sciences_BS
Arabic_Minor
Archaeology_BA
Archaeology_Minor
Asian_Studies_BA_Chinese
Asian_Studies_BA_Japanese
Asian_Studies_BA_Korean
Astronomy_Minor
Biology_BA
Biology_BS
Biomedical_Engineering_BS
Biostatistics_BSPH
Business_Administration_BSBA
Business_of_Health_Minor
Chemistry_BA
Chemistry_BS
Chemistry_BS_Biochemistry_Track
Chemistry_BS_Polymer_Track
Chinese_Minor
Climate_Change_Minor
Comparative_Literature_Minor
Creative_Writing_Minor
Data_Science_BA
Data_Science_BS
Data_Science_Minor
Dental_Hygiene_BS
Earth_and_Marine_Sciences_BS
Economics_BS
English_and_Comparative_Literature_BA
Environmental_Health_Sciences_BSPH
Environmental_Microbiology_Minor
Environmental_Science_BS
Environmental_Studies_BA
Exercise_and_Sport_Science_Fitness_Professional_BA
Exercise_and_Sport_Science_General_BA
Exercise_and_Sport_Science_Sport_Administration_BA
Food_Studies_Minor
Geographic_Information_Sciences_Minor
Geological_Sciences_BA_Earth_Science
Geological_Sciences_Minor
Germanic_and_Slavic_BA_Russian
Greek_Minor
Heritage_and_Global_Engagement_Minor
Hindi_Urdu_Minor
History_BA
Human_Development_Sustainability_and_Rights_Africa_Minor
Human_Development_and_Family_Science_BAEd
Islamic_and_Middle_Eastern_Studies_Minor
Japanese_Minor
Korean_Minor
Latin_American_Studies_BA
Latina_o_Studies_Minor
Linguistics_BA
Management_and_Society_BA
Mathematics_Minor
Media_and_Journalism_BA
Media_and_Journalism_Minor
Medical_Anthropology_Minor
Medicine_Literature_and_Culture_Minor
Middle_Eastern_Languages_Minor
Military_Science_and_Leadership_Minor
Modern_Hebrew_Minor
Music_BMus
Musical_Theatre_Performance_Minor
Nutrition_BSPH
Persian_Minor
Philosophy_Politics_and_Economics_Minor
Physics_BA
Public_Policy_BA
Real_Estate_Minor
Religious_Studies_BA_Jewish_Studies
Romance_Languages_BA_Hispanic_Linguistics
Romance_Languages_BA_Hispanic_Studies
Romance_Languages_BA_Portuguese
Screenwriting_Minor
Southeast_Asian_Studies_Minor
Statistics_and_Analytics_BS
Statistics_and_Analytics_Minor
Sustainability_Studies_Minor
Womens_and_Gender_Studies_BA
Womens_and_Gender_Studies_Minor
```

**Start with the first pending track in the list above.** Run the session-start script to confirm current state, then begin.

---

## FINAL SWAP (when all tracks are done — 0 pending)

```bash
# Backup current production
cp data/degree_requirements.json data/backup/degree_requirements_pre_refresh_bak.json

# Swap test into production
cp data/staging/test_degree_requirements.json data/degree_requirements.json

# Run tests
python3 -m unittest tests/test_exhaustive_backend.py 2>&1 | tail -5
```

If tests fail: identify track from error, fix that entry, re-run.  
If all pass: done. Swap is permanent.  
If total failure: `cp data/backup/degree_requirements_pre_refresh_bak.json data/degree_requirements.json`

---

## IMPORTANT NOTES

1. **test_degree_requirements.json already has the first 197 entries seeded** from the previous session. You are updating specific entries within it — not building from scratch.

2. **The diff check proved 86 entries have real discrepancies** between html_cache and stored requirements. These are all marked `pending` in `parse_status.json`. Do not skip any of them.

3. **"Stale" courses** (in requirements but not in html_cache) were removed from the catalog. Remove them from `options[]`. Do not remove the entire group — just the specific course codes.

4. **"Missing" courses** (in html_cache but not in requirements) were added to the catalog. Add them to the appropriate `options[]` in the correct group.

5. **When a concentration is completely new** (appears in html_cache but not in the current entry), add it as a new concentration key. Keep all existing concentrations unless the html_cache shows they were removed entirely.

6. **Token efficiency:** Read the current entry + the html_cache file together, identify specific changes, write a targeted Python script that makes only those changes. Avoid re-reading files unnecessarily.
