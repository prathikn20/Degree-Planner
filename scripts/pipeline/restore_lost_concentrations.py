"""
Restore concentrations that were lost when the LLM catalog-refresh staging
was promoted to production. For each track where the current production has
only {'None'} but the backup had real concentrations, copy the concentrations
dict from the backup — keeping the current (refreshed) base_requirements.
"""
import json
import os

PROD   = "data/degree_requirements.json"
BACKUP = "data/backup/degree_requirements_pre_comm_ba_patch.json"

curr = json.load(open(PROD))
bak  = json.load(open(BACKUP))

restored = []
for track in bak:
    if track not in curr:
        continue
    bak_concs  = set(bak[track].get("concentrations", {}).keys()) - {"None"}
    curr_concs = set(curr[track].get("concentrations", {}).keys()) - {"None"}
    if bak_concs and not curr_concs:
        # Keep current base_requirements; restore concentrations from backup
        curr[track]["concentrations"] = bak[track]["concentrations"]
        restored.append(track)
        print(f"  Restored {len(bak_concs)} concentration(s) for {track}")

if not restored:
    print("No regressions found — nothing to do.")
else:
    tmp = PROD + ".tmp"
    with open(tmp, "w") as f:
        json.dump(curr, f, indent=2)
    os.replace(tmp, PROD)
    print(f"\nSaved. Restored {len(restored)} track(s).")
