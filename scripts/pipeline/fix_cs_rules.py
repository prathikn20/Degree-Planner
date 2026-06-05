"""
Fix two rule-based group issues introduced by the LLM catalog refresh:
  1. CS BS comp_electives_1: add COMP690 to exclude list
  2. CS Minor comp_upper_1: restore as rule_based (COMP311+) so COMP420+ satisfies it
"""
import json, os

PROD = "data/degree_requirements.json"
data = json.load(open(PROD))

# ── 1. CS BS: add COMP690 to the COMP420+ exclusion list ──────────────────────
cg_bs = data["Computer_Science_BS"]["base_requirements"]["choice_groups"]
for g in cg_bs:
    if g.get("type") == "rule_based" and g.get("rule", {}).get("department") == "COMP":
        rule = g["rule"]
        excl = rule.get("exclude") or []
        if "COMP690" not in excl:
            rule["exclude"] = sorted(set(excl) | {"COMP690"})
            print(f"CS_BS/{g['id']}: added COMP690 to exclude list → {rule['exclude']}")

# ── 2. CS Minor: comp_upper_1 should be rule_based COMP311+ (not just COMP311) ─
# Per test comment: "list_1 is now rule_based: COMP311 or COMP420+"
# The group accepts COMP311 OR any COMP420+, which is equivalent to min_number=311
# with the same exclusions as comp_upper_2.
cg_min = data["Computer_Science_Minor"]["base_requirements"]["choice_groups"]
for g in cg_min:
    if g["id"] == "comp_upper_1" and g.get("type") == "explicit":
        # Find the exclusions from comp_upper_2 for consistency
        excl_set = set()
        for g2 in cg_min:
            if g2["id"] == "comp_upper_2" and g2.get("type") == "rule_based":
                excl_set = set(g2["rule"].get("exclude") or [])
                break
        g["type"] = "rule_based"
        g["options"] = []
        g["rule"] = {
            "department": "COMP",
            "min_number": 311,
            "min_credits": None,
            "exclude": sorted(excl_set),
        }
        print(f"CS_Minor/comp_upper_1: converted to rule_based COMP311+ (excl={sorted(excl_set)})")

tmp = PROD + ".tmp"
with open(tmp, "w") as f:
    json.dump(data, f, indent=2)
os.replace(tmp, PROD)
print("Saved.")
