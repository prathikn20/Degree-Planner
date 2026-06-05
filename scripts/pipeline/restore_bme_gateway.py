"""Restore bme_gateway_electives group from backup — it was dropped by fix_validation_errors.py
but tests expect it to exist with all 9 options and courses_required=3."""
import json, os

PROD    = "data/degree_requirements.json"
STAGING = "data/staging/test_degree_requirements.json"
BACKUP  = "data/backup/degree_requirements_pre_comm_ba_patch.json"

bak = json.load(open(BACKUP))
bme_bak_base = bak["Biomedical_Engineering_BS"]["base_requirements"]
gateway_bak = next(
    g for g in bme_bak_base["choice_groups"] if g["id"] == "bme_gateway_electives"
)
print("Restoring bme_gateway_electives:", gateway_bak)

for path in (PROD, STAGING):
    data = json.load(open(path))
    cg = data["Biomedical_Engineering_BS"]["base_requirements"]["choice_groups"]
    # Remove any partial/dropped version first, then insert at original position
    cg_no_gateway = [g for g in cg if g["id"] != "bme_gateway_electives"]
    # Find the position where bme_stem_elective sits (put gateway before it)
    stem_idx = next((i for i, g in enumerate(cg_no_gateway) if "stem" in g["id"].lower()), len(cg_no_gateway))
    cg_no_gateway.insert(stem_idx, gateway_bak)
    data["Biomedical_Engineering_BS"]["base_requirements"]["choice_groups"] = cg_no_gateway
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, path)
    print(f"Saved {path}")
