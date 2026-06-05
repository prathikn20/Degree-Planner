"""Fix 4 remaining cross-section ID collisions in Romance_Languages_BA_Hispanic_Studies."""
import json, os

PROD = "data/degree_requirements.json"
data = json.load(open(PROD))

track = "Romance_Languages_BA_Hispanic_Studies"
base_ids = {g["id"] for g in data[track]["base_requirements"]["choice_groups"]}

collisions = {
    "Hispanic_Literatures_and_Cultures": ["hispanic_literatures_electives_1"],
    "Spanish_for_the_Professions":       ["spanish_professions_pairs_1"],
    "Translation_and_Interpreting":      ["translation_interpreting_electives_1"],
    "Hispanic_Linguistics":              ["hispanic_linguistics_electives_1"],
}

for conc_name, ids_to_prefix in collisions.items():
    collision_set = set(ids_to_prefix)
    for g in data[track]["concentrations"][conc_name]["choice_groups"]:
        if g["id"] in collision_set and not g["id"].startswith("conc_"):
            old_id = g["id"]
            g["id"] = "conc_" + old_id
            print(f"  {track}/{conc_name}: '{old_id}' → '{g['id']}'")

tmp = PROD + ".tmp"
with open(tmp, "w") as f:
    json.dump(data, f, indent=2)
os.replace(tmp, PROD)
print("Saved.")
