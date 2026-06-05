"""
Fix all 42 ERROR-level findings from validate_pipeline_output.py --strict.

Errors addressed:
  A) req_ghost_required          — remove ghost courses from base required_courses
  B) req_ghost_conc_required     — remove ghost courses from concentration required_courses
  C) req_cross_section_id_collision — prefix colliding concentration group IDs with 'conc_'
  D) req_required_option_collision (permanently unsatisfiable) — remove stolen options /
     reduce courses_required; drop group when 0 options remain after cleaning
  E) req_identical_groups        — collapse duplicate groups, keeping first occurrence
  F) req_unsatisfiable_group     — remove groups whose only options are ghosts / non-existent
"""

import json
import os

REQ_PATH = "data/degree_requirements.json"
CAT_PATH = "data/course_catalog.json"


def load():
    with open(REQ_PATH) as f:
        return json.load(f)


def save(data):
    tmp = REQ_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, REQ_PATH)


def fix_ghost_required(data, catalog):
    """A) Remove ghost courses from base required_courses."""
    ghosts_by_track = {
        "Physics_BS":                                   ["ASTR519"],
        "Physics_BS_Astrophysics":                      ["ASTR519"],
        "Community_and_Global_Public_Health_BSPH":      ["HBEH571"],
        "American_Indian_and_Indigenous_Studies_Minor": ["SPAN374", "MAYA401"],
        "American_Studies_BA_AIIS_Concentration":       ["SPAN374", "MAYA401"],
        "Geological_Sciences_BA_Earth_Science":         ["PHYS313", "MASC101", "PHYS132"],
        "Medicine_Literature_and_Culture_Minor":        ["ENGL268H"],
    }
    for track, ghosts in ghosts_by_track.items():
        rc = data[track]["base_requirements"]["required_courses"]
        before = len(rc)
        data[track]["base_requirements"]["required_courses"] = [
            c for c in rc if c not in ghosts
        ]
        removed = before - len(data[track]["base_requirements"]["required_courses"])
        print(f"  [A] {track}: removed {removed} ghost required course(s) {ghosts}")


def fix_ghost_conc_required(data, catalog):
    """B) Remove ghost courses from Biomedical_Engineering_BS concentration required_courses."""
    bme_ghosts = {
        "Pharmacoengineering":    ["BME570"],
        "Regenerative_Medicine":  ["MAE201", "MSE301", "CE282", "MAE308",
                                   "BME429", "BME448", "BME483", "BME484", "TE463"],
        "Rehabilitation_Engineering": ["BME418", "BME425", "BME438", "BME444", "BME456"],
        "Biosignals_and_Imaging": ["MA501", "BME412", "BME418", "BME425",
                                   "BME463", "BME464", "ECE456", "ECE505"],
        "Medical_Microdevices":   ["MAE201", "MSE301", "CE282", "MAE308"],
    }
    for conc, ghosts in bme_ghosts.items():
        rc = data["Biomedical_Engineering_BS"]["concentrations"][conc]["required_courses"]
        before = len(rc)
        data["Biomedical_Engineering_BS"]["concentrations"][conc]["required_courses"] = [
            c for c in rc if c not in ghosts
        ]
        removed = before - len(
            data["Biomedical_Engineering_BS"]["concentrations"][conc]["required_courses"]
        )
        print(f"  [B] BME/{conc}: removed {removed} ghost required course(s)")


def fix_cross_section_collisions(data):
    """C) Prefix concentration group IDs that shadow base IDs with 'conc_'."""
    collisions = {
        "Data_Science_BS": {
            "Advanced_Artificial_Intelligence_and_Machine_Learning": ["ai_machine_1"],
        },
        "Environmental_Science_BS": {
            "Ecology_and_Natural_Resources": ["enec_1", "enec_2", "enec_3", "enec_4"],
            "Water_and_Climate":             ["enec_1", "enec_2", "enec_3"],
        },
        "Environmental_Studies_BA": {
            "Agriculture_and_Health": ["enec_1", "enec_2", "envr_1"],
            "Ecology_and_Society":    ["enec_1", "enec_2", "enec_3", "enec_4",
                                       "geog_1", "biol_1", "enec_5"],
            "Environmental_Behavior_and_Decision_Making": ["enec_1", "enec_2", "envr_1",
                                                           "enec_3", "enec_4", "enec_5"],
            "Population_Environment_and_Development": ["enec_1", "enec_2", "enec_3",
                                                        "enec_4", "enec_5"],
        },
    }
    for track, concs in collisions.items():
        base_ids = {g["id"] for g in data[track]["base_requirements"]["choice_groups"]}
        for conc_name, ids_to_prefix in concs.items():
            collision_set = set(ids_to_prefix)
            groups = data[track]["concentrations"][conc_name]["choice_groups"]
            for g in groups:
                if g["id"] in collision_set and not g["id"].startswith("conc_"):
                    old_id = g["id"]
                    g["id"] = "conc_" + old_id
                    print(f"  [C] {track}/{conc_name}: '{old_id}' → '{g['id']}'")


def fix_option_collisions_and_unsatisfiable(data, catalog):
    """D+F) Fix permanently unsatisfiable groups (remove stolen options, drop empty groups)."""

    def clean_group(track, section_label, groups, req_set):
        keep = []
        for g in groups:
            opts = g.get("options") or []
            stolen = [o for o in opts if o in req_set]
            if not stolen:
                keep.append(g)
                continue
            remaining = [o for o in opts if o in catalog and o not in req_set]
            cr = g.get("courses_required", 1)
            if cr > len(remaining):
                # Permanently unsatisfiable → drop the group entirely
                print(f"  [D] {track}/{section_label}/{g['id']}: dropped "
                      f"(need {cr}, only {len(remaining)} valid after removing "
                      f"{len(stolen)} stolen options)")
            else:
                # Satisfiable after removing stolen options → patch options list
                g = dict(g)
                g["options"] = [o for o in opts if o not in req_set]
                g["courses_required"] = min(cr, len(g["options"]))
                keep.append(g)
                print(f"  [D] {track}/{section_label}/{g['id']}: removed "
                      f"{len(stolen)} stolen options, kept {len(g['options'])}")
        return keep

    # Biomedical_Engineering_BS/base/bme_gateway_electives
    bme_base = data["Biomedical_Engineering_BS"]["base_requirements"]
    req_bme = set(bme_base["required_courses"])
    bme_base["choice_groups"] = clean_group(
        "BME", "base", bme_base["choice_groups"], req_bme
    )

    # Nutrition_BSPH/base/core_capstone_1
    nutr_base = data["Nutrition_BSPH"]["base_requirements"]
    req_nutr = set(nutr_base["required_courses"])
    nutr_base["choice_groups"] = clean_group(
        "Nutrition_BSPH", "base", nutr_base["choice_groups"], req_nutr
    )

    # Physics_BA/base/phys_9 (all options stolen)
    pba_base = data["Physics_BA"]["base_requirements"]
    req_pba = set(pba_base["required_courses"])
    pba_base["choice_groups"] = clean_group(
        "Physics_BA", "base", pba_base["choice_groups"], req_pba
    )

    # Environmental_Health_Sciences_BSPH/base/biol_1 and biol_2
    ehs_base = data["Environmental_Health_Sciences_BSPH"]["base_requirements"]
    req_ehs = set(ehs_base["required_courses"])
    ehs_base["choice_groups"] = clean_group(
        "EHS_BSPH", "base", ehs_base["choice_groups"], req_ehs
    )

    # Musical_Theatre_Performance_Minor: drop musc_1, musc_2, musc_3,
    # core_requirements_remaining_1 (all options stolen, all 4 are duplicates)
    mt_base = data["Musical_Theatre_Performance_Minor"]["base_requirements"]
    req_mt = set(mt_base["required_courses"])
    mt_base["choice_groups"] = clean_group(
        "Musical_Theatre_Minor", "base", mt_base["choice_groups"], req_mt
    )

    # Applied_Sciences_BS/base/core_requirements_tracks_1 (options not in catalog)
    asbs_base = data["Applied_Sciences_BS"]["base_requirements"]
    asbs_base["choice_groups"] = [
        g for g in asbs_base["choice_groups"]
        if not (g["id"] == "core_requirements_tracks_1"
                and not any(o in catalog for o in g.get("options", [])))
    ]
    print("  [F] Applied_Sciences_BS/core_requirements_tracks_1: dropped (no options in catalog)")

    # Latin_American_Studies_BA/base/POLI435H_1 (POLI435H not in catalog; POLI435_1 already present)
    la_base = data["Latin_American_Studies_BA"]["base_requirements"]
    la_base["choice_groups"] = [
        g for g in la_base["choice_groups"]
        if not (g["id"] == "POLI435H_1"
                and not any(o in catalog for o in g.get("options", [])))
    ]
    print("  [F] Latin_American_Studies_BA/POLI435H_1: dropped (POLI435H not in catalog)")


def fix_identical_groups(data):
    """E) Physics_BA: collapse 7+7 duplicate groups into 1 each."""
    pba_base = data["Physics_BA"]["base_requirements"]
    groups = pba_base["choice_groups"]

    # Build fingerprint map
    seen_fps: dict[tuple, str] = {}
    keep = []
    removed = 0
    for g in groups:
        if not g.get("options"):
            keep.append(g)
            continue
        fp = tuple(sorted(g["options"]))
        if fp in seen_fps:
            # Duplicate — discard
            removed += 1
        else:
            seen_fps[fp] = g["id"]
            keep.append(g)

    pba_base["choice_groups"] = keep
    print(f"  [E] Physics_BA: removed {removed} duplicate choice groups")


def main():
    data = load()
    catalog = json.load(open(CAT_PATH))

    print("Applying fixes...")
    fix_ghost_required(data, catalog)
    fix_ghost_conc_required(data, catalog)
    fix_cross_section_collisions(data)
    fix_option_collisions_and_unsatisfiable(data, catalog)
    fix_identical_groups(data)

    save(data)
    print("\nSaved. Run validate_pipeline_output.py --strict to confirm 0 errors.")


if __name__ == "__main__":
    main()
