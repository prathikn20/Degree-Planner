"""Fix empty options in EMES/ENEC cross-listed groups that the LLM scrape missed."""
import json, os

PROD    = "data/degree_requirements.json"
STAGING = "data/staging/test_degree_requirements.json"

for path in (PROD, STAGING):
    data = json.load(open(path))

    fixes = [
        # (track, concentration_or_base, group_id, correct_options)
        ("Environmental_Studies_BA",  "base",                 "enec_3",    ["EMES220", "ENEC220"]),
        ("Environmental_Studies_BA",  "base",                 "enec_4",    ["EMES411", "ENEC411"]),
        ("Environmental_Studies_BA",  "Agriculture_and_Health", "emes_324L_1", ["EMES324L", "ENEC324L"]),
        ("Environmental_Science_BS",  "Water_and_Climate",    "emes_2",    ["ENEC411", "EMES411"]),
    ]

    for track, section, gid, options in fixes:
        if section == "base":
            groups = data[track]["base_requirements"]["choice_groups"]
        else:
            groups = data[track]["concentrations"][section]["choice_groups"]
        for g in groups:
            if g["id"] == gid:
                g["options"] = options
                print(f"  {track}/{section}/{gid}: set options={options}")

    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
    print(f"Saved {path}")
