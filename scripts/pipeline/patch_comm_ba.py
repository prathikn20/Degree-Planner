"""One-off patch: add 5 pathway concentrations to Communication_Studies_BA in staging."""
import json
import os

STAGING = "data/staging/test_degree_requirements.json"
STATUS  = "data/staging/parse_status.json"

out = json.load(open(STAGING))

concentrations = {
    "None": {"required_courses": [], "choice_groups": []},
    "Communication_and_Everyday_Life": {
        "required_courses": [],
        "choice_groups": [{
            "id": "comm_cel_starting_1",
            "description": "Students should select a minimum of two courses from the following list (Pathway Starting Point Courses)",
            "type": "explicit",
            "courses_required": 2,
            "options": ["COMM113","COMM120","COMM130","COMM140","COMM160",
                        "COMM171","COMM224","COMM249","COMM260","COMM325"],
            "rule": None,
            "is_core": True
        }]
    },
    "Media_Art_Performance_and_Critical_Practice": {
        "required_courses": [],
        "choice_groups": [{
            "id": "comm_map_starting_1",
            "description": "Students should select a minimum of two courses from the following list (Pathway Starting Point Courses)",
            "type": "explicit",
            "courses_required": 2,
            "options": ["COMM130","COMM140","COMM150","COMM160",
                        "COMM224","COMM260","COMM263","COMM330"],
            "rule": None,
            "is_core": True
        }]
    },
    "Media_Technology_and_Public_Culture": {
        "required_courses": [],
        "choice_groups": [{
            "id": "comm_mtp_starting_1",
            "description": "Students should select a minimum of two courses from the list below (Pathway Starting Point Courses)",
            "type": "explicit",
            "courses_required": 2,
            "options": ["COMM130","COMM140","COMM150","COMM224","COMM249","COMM330"],
            "rule": None,
            "is_core": True
        }]
    },
    "Organization_Communication_and_Work": {
        "required_courses": [],
        "choice_groups": [{
            "id": "comm_ocw_starting_1",
            "description": "Students should select a minimum of two courses from the list below (Pathway Starting Point Courses)",
            "type": "explicit",
            "courses_required": 2,
            "options": ["COMM113","COMM120","COMM130","COMM140",
                        "COMM170","COMM224","COMM249","COMM325"],
            "rule": None,
            "is_core": True
        }]
    },
    "Rhetoric_Activism_and_Advocacy": {
        "required_courses": [],
        "choice_groups": [{
            "id": "comm_raa_starting_1",
            "description": "Students should select a minimum of two courses from the list below (Pathway Starting Point Courses)",
            "type": "explicit",
            "courses_required": 2,
            "options": ["COMM113","COMM130","COMM140","COMM170",
                        "COMM171","COMM224","COMM249","COMM260"],
            "rule": None,
            "is_core": True
        }]
    },
}

out["Communication_Studies_BA"]["concentrations"] = concentrations

tmp = STAGING + ".tmp"
with open(tmp, "w") as f:
    json.dump(out, f, indent=2)
os.replace(tmp, STAGING)

status = json.load(open(STATUS))
status["Communication_Studies_BA"] = "done"
tmp2 = STATUS + ".tmp"
with open(tmp2, "w") as f:
    json.dump(status, f, indent=2)
os.replace(tmp2, STATUS)

print("Communication_Studies_BA | 5 pathway concentrations added to staging")
print("Concentrations:", [k for k in concentrations if k != "None"])
