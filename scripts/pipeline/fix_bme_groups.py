"""
Fix BME gateway_electives and stem_elective groups to match the HTML cache.

Gateway: 9 courses, students choose 3.
Stem: approved upper-level STEM courses, students choose 1.
"""
import json, os

PROD    = "data/degree_requirements.json"
STAGING = "data/staging/test_degree_requirements.json"
CAT     = "data/course_catalog.json"

cat = json.load(open(CAT))

# Full gateway course list from HTML cache (BMME315, BMME325 or CHEM430, etc.)
GATEWAY_OPTIONS = ["BMME315", "BMME325", "CHEM430", "BMME335",
                   "BMME345", "BMME355", "BMME365", "BMME375", "BMME385"]
GATEWAY_OPTIONS = [c for c in GATEWAY_OPTIONS if c in cat]  # keep only catalog courses

# STEM elective options from HTML cache
STEM_OPTIONS = ["APPL465", "BIOL220", "BIOL443", "BIOL451", "CHEM430",
                "MATH347", "MATH381", "PHYS331", "PHYS381"]
STEM_OPTIONS = [c for c in STEM_OPTIONS if c in cat]

print(f"Gateway options ({len(GATEWAY_OPTIONS)}): {GATEWAY_OPTIONS}")
print(f"STEM options ({len(STEM_OPTIONS)}): {STEM_OPTIONS}")

for path in (PROD, STAGING):
    data = json.load(open(path))
    cg = data["Biomedical_Engineering_BS"]["base_requirements"]["choice_groups"]

    for g in cg:
        if g["id"] == "bme_gateway_electives":
            g["options"] = GATEWAY_OPTIONS
            g["courses_required"] = 3
            print(f"  [{path}] Patched bme_gateway_electives: {len(GATEWAY_OPTIONS)} options, cr=3")
        elif g["id"] == "bme_stem_elective":
            g["options"] = STEM_OPTIONS
            g["courses_required"] = 1
            print(f"  [{path}] Patched bme_stem_elective: {len(STEM_OPTIONS)} options, cr=1")

    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)

print("Done.")
