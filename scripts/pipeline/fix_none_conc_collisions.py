"""Clear stale choice_groups from 'None' concentrations that shadow base IDs."""
import json, os

PROD = "data/degree_requirements.json"
data = json.load(open(PROD))

tracks_with_bad_none = [
    "Computer_Science_BS", "Political_Science_BA", "Sociology_BA",
    "Statistics_and_Analytics_BS", "Computer_Science_BA",
    "Global_Studies_BA", "Geography_and_Environment_BA",
]

for track in tracks_with_bad_none:
    base_ids = {g["id"] for g in data[track]["base_requirements"]["choice_groups"]}
    none_conc = data[track]["concentrations"].get("None", {})
    groups = none_conc.get("choice_groups", [])
    before = len(groups)
    # Remove any groups whose IDs shadow base group IDs (they're already in base)
    none_conc["choice_groups"] = [g for g in groups if g["id"] not in base_ids]
    removed = before - len(none_conc["choice_groups"])
    data[track]["concentrations"]["None"] = none_conc
    print(f"  {track}: removed {removed} duplicate group(s) from None concentration")

tmp = PROD + ".tmp"
with open(tmp, "w") as f:
    json.dump(data, f, indent=2)
os.replace(tmp, PROD)
print("Saved.")
