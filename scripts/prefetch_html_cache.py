"""
Pre-fetch and clean UNC catalog pages into data/html_cache/<TRACK_ID>.txt

Each output file contains ONLY:
  - Section headers (h2/h3/h4 inside the requirements block)
  - Rule text paragraphs immediately before course tables
  - Course table rows formatted as: CODE | TITLE | CREDITS
  - OR-alternative rows formatted as: OR CODE | TITLE

Strips all navigation, footer, sidebar, contact info, sample plans boilerplate.
Run once before LLM parsing. Re-run with --force to refresh stale files.

Usage:
    python3 scripts/prefetch_html_cache.py            # skip already-cached
    python3 scripts/prefetch_html_cache.py --force    # re-fetch all
    python3 scripts/prefetch_html_cache.py --track Computer_Science_BS
"""

import argparse
import os
import re
import sys
import time

import requests
from bs4 import BeautifulSoup, NavigableString

HTML_CACHE_DIR = "data/html_cache"
REQUEST_DELAY  = 0.4   # seconds between requests — be polite to the server

TARGET_TRACKS = {
    "Computer_Science_BS":           "https://catalog.unc.edu/undergraduate/programs-study/computer-science-major-bs/",
    "Data_Science_BS":               "https://catalog.unc.edu/undergraduate/programs-study/data-science-major-bs/",
    "Mathematics_BS":                "https://catalog.unc.edu/undergraduate/programs-study/mathematics-major-bs/",
    "Statistics_and_Analytics_BS":   "https://catalog.unc.edu/undergraduate/programs-study/statistics-analytics-majors-bs/",
    "Economics_BS":                  "https://catalog.unc.edu/undergraduate/programs-study/economics-major-bs/",
    "Biology_BS":                    "https://catalog.unc.edu/undergraduate/programs-study/biology-major-bs/",
    "Chemistry_BS":                  "https://catalog.unc.edu/undergraduate/programs-study/chemistry-major-bs/",
    "Physics_BS":                    "https://catalog.unc.edu/undergraduate/programs-study/physics-major-bs/",
    "Neuroscience_BS":               "https://catalog.unc.edu/undergraduate/programs-study/neuroscience-major-bs/",
    "Psychology_BS":                 "https://catalog.unc.edu/undergraduate/programs-study/psychology-major-bs/",
    "Exercise_and_Sport_Science_BS": "https://catalog.unc.edu/undergraduate/programs-study/exercise-sport-science-major-bs/",
    "Biomedical_Engineering_BS":     "https://catalog.unc.edu/undergraduate/programs-study/biomedical-engineering-major-bs/",
    "Biostatistics_BSPH":            "https://catalog.unc.edu/undergraduate/programs-study/biostatistics-major-bsph/",
    "Business_Administration_BSBA":  "https://catalog.unc.edu/undergraduate/programs-study/business-administration-major-bsba/",
    "Applied_Sciences_BS":           "https://catalog.unc.edu/undergraduate/programs-study/applied-sciences-major-bs/",
    "Earth_and_Marine_Sciences_BS":  "https://catalog.unc.edu/undergraduate/programs-study/earth-marine-sciences-major-bs/",
    "Environmental_Science_BS":      "https://catalog.unc.edu/undergraduate/programs-study/environmental-science-bs/",
    "Information_Science_BS":        "https://catalog.unc.edu/undergraduate/programs-study/information-science-major-bs/",
    "Neurodiagnostics_and_Sleep_Science_BS": "https://catalog.unc.edu/undergraduate/programs-study/neurodiagnostics-sleep-sciences-major-bs/",
    "Community_and_Global_Public_Health_BSPH": "https://catalog.unc.edu/undergraduate/programs-study/community-global-public-health-major-bsph/",
    "Health_Policy_and_Management_BSPH": "https://catalog.unc.edu/undergraduate/programs-study/health-policy-management-major-bsph/",
    "Nutrition_BSPH":                "https://catalog.unc.edu/undergraduate/programs-study/nutrition-major-bsph/",
    "Political_Science_BA":          "https://catalog.unc.edu/undergraduate/programs-study/political-science-major-ba/",
    "Public_Policy_BA":              "https://catalog.unc.edu/undergraduate/programs-study/public-policy-major-ba/",
    "Sociology_BA":                  "https://catalog.unc.edu/undergraduate/programs-study/sociology-major-ba/",
    "Economics_BA":                  "https://catalog.unc.edu/undergraduate/programs-study/economics-major-ba/",
    "Psychology_BA":                 "https://catalog.unc.edu/undergraduate/programs-study/psychology-major-ba/",
    "Computer_Science_BA":           "https://catalog.unc.edu/undergraduate/programs-study/computer-science-major-ba/",
    "Data_Science_BA":               "https://catalog.unc.edu/undergraduate/programs-study/data-science-major-ba/",
    "Mathematics_BA":                "https://catalog.unc.edu/undergraduate/programs-study/mathematics-major-ba/",
    "Biology_BA":                    "https://catalog.unc.edu/undergraduate/programs-study/biology-major-ba/",
    "Chemistry_BA":                  "https://catalog.unc.edu/undergraduate/programs-study/chemistry-major-ba/",
    "Physics_BA":                    "https://catalog.unc.edu/undergraduate/programs-study/physics-major-ba/",
    "Linguistics_BA":                "https://catalog.unc.edu/undergraduate/programs-study/linguistics-major-ba/",
    "Anthropology_BA":               "https://catalog.unc.edu/undergraduate/programs-study/anthropology-major-ba/",
    "Medical_Anthropology_BA":       "https://catalog.unc.edu/undergraduate/programs-study/medical-anthropology-major-ba/",
    "Global_Studies_BA":             "https://catalog.unc.edu/undergraduate/programs-study/global-studies-major-ba/",
    "Environmental_Studies_BA":      "https://catalog.unc.edu/undergraduate/programs-study/environmental-studies-major-ba/",
    "Peace_War_and_Defense_BA":      "https://catalog.unc.edu/undergraduate/programs-study/peace-war-defense-major-ba/",
    "Management_and_Society_BA":     "https://catalog.unc.edu/undergraduate/programs-study/management-society-major-ba/",
    "Communication_Studies_BA":      "https://catalog.unc.edu/undergraduate/programs-study/communication-studies-major-ba/",
    "Exercise_and_Sport_Science_Fitness_Professional_BA": "https://catalog.unc.edu/undergraduate/programs-study/exercise-sport-science-major-ba-fitness-professional/",
    "Exercise_and_Sport_Science_General_BA": "https://catalog.unc.edu/undergraduate/programs-study/exercise-sport-science-major-ba-general/",
    "Exercise_and_Sport_Science_Sport_Administration_BA": "https://catalog.unc.edu/undergraduate/programs-study/exercise-sport-science-major-ba-sport-administration/",
    "African_African_American_and_Diaspora_Studies_BA": "https://catalog.unc.edu/undergraduate/programs-study/african-african-american-diaspora-studies-major-ba/",
    "American_Studies_BA":           "https://catalog.unc.edu/undergraduate/programs-study/american-studies-major-ba/",
    "American_Studies_BA_AIIS_Concentration": "https://catalog.unc.edu/undergraduate/programs-study/american-studies-major-baamerican-indian-indigenous-studies-concentration/",
    "Archaeology_BA":                "https://catalog.unc.edu/undergraduate/programs-study/archaeology-major-ba/",
    "Art_History_BA":                "https://catalog.unc.edu/undergraduate/programs-study/art-history-major-ba/",
    "Asian_Studies_BA_Arab_Cultures": "https://catalog.unc.edu/undergraduate/programs-study/asian-studies-major-ba-arab-cultures-concentration/",
    "Asian_Studies_BA_Chinese":      "https://catalog.unc.edu/undergraduate/programs-study/asian-studies-major-ba-chinese-concentration/",
    "Asian_Studies_BA_Interdisciplinary": "https://catalog.unc.edu/undergraduate/programs-study/asian-studies-major-ba-general-concentration/",
    "Asian_Studies_BA_Japanese":     "https://catalog.unc.edu/undergraduate/programs-study/asian-studies-major-ba-japanese-concentration/",
    "Asian_Studies_BA_Korean":       "https://catalog.unc.edu/undergraduate/programs-study/asian-studies-major-ba-korean-concentration/",
    "Asian_Studies_BA_Persian":      "https://catalog.unc.edu/undergraduate/programs-study/asian-studies-major-ba-persian-concentration/",
    "Asian_Studies_BA_South_Asian":  "https://catalog.unc.edu/undergraduate/programs-study/asian-studies-major-ba-south-asian-studies-concentration/",
    "Biology_BS_Quantitative_Biology_Track": "https://catalog.unc.edu/undergraduate/programs-study/biology-major-bs-quantitative-biology-track/",
    "Chemistry_BS_Biochemistry_Track": "https://catalog.unc.edu/undergraduate/programs-study/chemistry-major-bs-biochemistry-track/",
    "Chemistry_BS_Polymer_Track":    "https://catalog.unc.edu/undergraduate/programs-study/chemistry-major-bs-polymer-track/",
    "Classics_BA_Classical_Archaeology": "https://catalog.unc.edu/undergraduate/programs-study/classics-major-ba-classical-archaeology/",
    "Classics_BA_Classical_Civilization": "https://catalog.unc.edu/undergraduate/programs-study/classics-major-ba-classical-civilization/",
    "Classics_BA_Greek_Latin":       "https://catalog.unc.edu/undergraduate/programs-study/classics-major-ba-greek-latin/",
    "Clinical_Laboratory_Science_BS": "https://catalog.unc.edu/undergraduate/programs-study/clinical-laboratory-science-major-bs/",
    "Contemporary_European_Studies_BA": "https://catalog.unc.edu/undergraduate/programs-study/contemporary-european-studies-major-ba/",
    "Dental_Hygiene_BS":             "https://catalog.unc.edu/undergraduate/programs-study/dental-hygiene-major-bs/",
    "Dramatic_Art_BA":               "https://catalog.unc.edu/undergraduate/programs-study/dramatic-art-major-ba/",
    "English_and_Comparative_Literature_BA": "https://catalog.unc.edu/undergraduate/programs-study/english-comparative-major-ba/",
    "Environmental_Health_Sciences_BSPH": "https://catalog.unc.edu/undergraduate/programs-study/environmental-health-sciences-major-bsph/",
    "Geography_and_Environment_BA":  "https://catalog.unc.edu/undergraduate/programs-study/geography-major-ba/",
    "Geological_Sciences_BA_Earth_Science": "https://catalog.unc.edu/undergraduate/programs-study/geological-sciences-major-ba-earth-science-concentration/",
    "Germanic_and_Slavic_BA_German_Studies": "https://catalog.unc.edu/undergraduate/programs-study/germanic-slavic-languages-literatures-major-ba-german-literature-culture-concentration/",
    "Germanic_and_Slavic_BA_Russian": "https://catalog.unc.edu/undergraduate/programs-study/germanic-slavic-languages-literatures-major-ba-russian-language-culture-concentration/",
    "Germanic_and_Slavic_BA_Slavic_and_East_European": "https://catalog.unc.edu/undergraduate/programs-study/germanic-slavic-languages-literatures-major-ba-central-european-studies-concentration/",
    "History_BA":                    "https://catalog.unc.edu/undergraduate/programs-study/history-major-ba/",
    "Human_and_Organizational_Leadership_Development_BA": "https://catalog.unc.edu/undergraduate/programs-study/human-org-leadership-ba/",
    "Human_Development_and_Family_Science_BAEd": "https://catalog.unc.edu/undergraduate/programs-study/human-development-family-studies-baed/",
    "Interdisciplinary_Studies_BA":  "https://catalog.unc.edu/undergraduate/programs-study/interdisciplinary-studies-major-ba/",
    "Latin_American_Studies_BA":     "https://catalog.unc.edu/undergraduate/programs-study/latin-american-studies-major-ba/",
    "Media_and_Journalism_BA":       "https://catalog.unc.edu/undergraduate/programs-study/media-journalism-major-ba/",
    "Music_BA":                      "https://catalog.unc.edu/undergraduate/programs-study/music-major-ba/",
    "Music_BMus":                    "https://catalog.unc.edu/undergraduate/programs-study/music-major-bmus/",
    "Nursing_BSN":                   "https://catalog.unc.edu/undergraduate/programs-study/nursing-major-bsn/",
    "Philosophy_BA":                 "https://catalog.unc.edu/undergraduate/programs-study/philosophy-major-ba/",
    "Radiologic_Science_BS":         "https://catalog.unc.edu/undergraduate/programs-study/radiologic-science-major-bs/",
    "Religious_Studies_BA":          "https://catalog.unc.edu/undergraduate/programs-study/religious-studies-major-ba/",
    "Religious_Studies_BA_Jewish_Studies": "https://catalog.unc.edu/undergraduate/programs-study/religious-studies-major-ba-jewish-studies-concentration/",
    "Romance_Languages_BA_French":   "https://catalog.unc.edu/undergraduate/programs-study/romance-languages-major-ba-french-francophone-studies/",
    "Romance_Languages_BA_Hispanic_Linguistics": "https://catalog.unc.edu/undergraduate/programs-study/romance-languages-major-ba-hispanic-linguistics/",
    "Romance_Languages_BA_Hispanic_Studies": "https://catalog.unc.edu/undergraduate/programs-study/romance-languages-major-ba-hispanic-literatures-cultures/",
    "Romance_Languages_BA_Italian":  "https://catalog.unc.edu/undergraduate/programs-study/romance-languages-major-ba-italian/",
    "Romance_Languages_BA_Portuguese": "https://catalog.unc.edu/undergraduate/programs-study/romance-languages-major-ba-portuguese/",
    "Studio_Art_BA":                 "https://catalog.unc.edu/undergraduate/programs-study/studio-art-major-ba/",
    "Studio_Art_BFA":                "https://catalog.unc.edu/undergraduate/programs-study/studio-art-major-bfa/",
    "Womens_and_Gender_Studies_BA":  "https://catalog.unc.edu/undergraduate/programs-study/womens-gender-studies-major-ba/",
    # Minors
    "Computer_Science_Minor":        "https://catalog.unc.edu/undergraduate/programs-study/computer-science-minor/",
    "Data_Science_Minor":            "https://catalog.unc.edu/undergraduate/programs-study/data-science-minor/",
    "Mathematics_Minor":             "https://catalog.unc.edu/undergraduate/programs-study/mathematics-minor/",
    "Statistics_and_Analytics_Minor": "https://catalog.unc.edu/undergraduate/programs-study/statistics-and-analytics-minor/",
    "Economics_Minor":               "https://catalog.unc.edu/undergraduate/programs-study/economics-minor/",
    "Biology_Minor":                 "https://catalog.unc.edu/undergraduate/programs-study/biology-minor/",
    "Chemistry_Minor":               "https://catalog.unc.edu/undergraduate/programs-study/chemistry-minor/",
    "Physics_Minor":                 "https://catalog.unc.edu/undergraduate/programs-study/physics-minor/",
    "Business_Administration_Minor": "https://catalog.unc.edu/undergraduate/programs-study/business-administration-minor/",
    "Philosophy_Politics_and_Economics_Minor": "https://catalog.unc.edu/undergraduate/programs-study/philosophy-politics-economics-minor/",
    "Public_Policy_Minor":           "https://catalog.unc.edu/undergraduate/programs-study/public-policy-minor/",
    "Entrepreneurship_Minor":        "https://catalog.unc.edu/undergraduate/programs-study/entrepreneurship-minor/",
    "Philosophy_Minor":              "https://catalog.unc.edu/undergraduate/programs-study/philosophy-minor/",
    "Linguistics_Minor":             "https://catalog.unc.edu/undergraduate/programs-study/linguistics-minor/",
    "Environmental_Science_and_Studies_Minor": "https://catalog.unc.edu/undergraduate/programs-study/environmental-science-studies-minor/",
    "Applied_Sciences_and_Engineering_Minor": "https://catalog.unc.edu/undergraduate/programs-study/applied-sciences-engineering-minor/",
    "Anthropology_General_Minor":    "https://catalog.unc.edu/undergraduate/programs-study/general-anthropology-minor/",
    "Medical_Anthropology_Minor":    "https://catalog.unc.edu/undergraduate/programs-study/medical-anthropology-minor/",
    "Marine_Sciences_Minor":         "https://catalog.unc.edu/undergraduate/programs-study/marine-sciences-minor/",
    "Spanish_for_the_Professions_Minor": "https://catalog.unc.edu/undergraduate/programs-study/spanish-professions-minor/",
    "Neuroscience_Minor":            "https://catalog.unc.edu/undergraduate/programs-study/neuroscience-minor/",
    "Exercise_and_Sport_Science_Minor": "https://catalog.unc.edu/undergraduate/programs-study/exercise-sport-science-minor/",
    "Information_Systems_Minor":     "https://catalog.unc.edu/undergraduate/programs-study/information-systems-minor/",
    "Astronomy_Minor":               "https://catalog.unc.edu/undergraduate/programs-study/astronomy-minor/",
    "Business_of_Health_Minor":      "https://catalog.unc.edu/undergraduate/programs-study/business-health-minor/",
    "Real_Estate_Minor":             "https://catalog.unc.edu/undergraduate/programs-study/real-estate-minor/",
    "Health_and_Society_Minor":      "https://catalog.unc.edu/undergraduate/programs-study/health-society-minor/",
    "Sustainability_Studies_Minor":  "https://catalog.unc.edu/undergraduate/programs-study/sustainability-studies-minor/",
    "Sports_Medicine_Minor":         "https://catalog.unc.edu/undergraduate/programs-study/sports-medicine-minor/",
    "Geographic_Information_Sciences_Minor": "https://catalog.unc.edu/undergraduate/programs-study/gis-minor/",
    "Geological_Sciences_Minor":     "https://catalog.unc.edu/undergraduate/programs-study/geological-sciences-minor/",
    "Food_Studies_Minor":            "https://catalog.unc.edu/undergraduate/programs-study/food-studies-minor/",
    "Global_Cinema_Minor":           "https://catalog.unc.edu/undergraduate/programs-study/global-cinema-minor/",
    "Dramatic_Art_Minor":            "https://catalog.unc.edu/undergraduate/programs-study/dramatic-art-minor/",
    "Music_Minor":                   "https://catalog.unc.edu/undergraduate/programs-study/music-minor/",
    "Studio_Art_Minor":              "https://catalog.unc.edu/undergraduate/programs-study/studio-art-minor/",
    "Creative_Writing_Minor":        "https://catalog.unc.edu/undergraduate/programs-study/creative-writing-minor/",
    "Media_and_Journalism_Minor":    "https://catalog.unc.edu/undergraduate/programs-study/media-journalism-minor/",
    "History_Minor":                 "https://catalog.unc.edu/undergraduate/programs-study/history-minor/",
    "Religious_Studies_Minor":       "https://catalog.unc.edu/undergraduate/programs-study/religious-studies-minor/",
    "Conflict_Management_Minor":     "https://catalog.unc.edu/undergraduate/programs-study/conflict-management-minor/",
    "Urban_Studies_and_Planning_Minor": "https://catalog.unc.edu/undergraduate/programs-study/urban-studies-planning-minor/",
    "Environmental_Microbiology_Minor": "https://catalog.unc.edu/undergraduate/programs-study/environmental-microbiology-minor/",
    "Hydrology_Minor":               "https://catalog.unc.edu/undergraduate/programs-study/hydrology-minor/",
    "Climate_Change_Minor":          "https://catalog.unc.edu/undergraduate/programs-study/climate-change-minor/",
    "Aerospace_Studies_Minor":       "https://catalog.unc.edu/undergraduate/programs-study/aerospace-studies-minor/",
    "African_American_and_Diaspora_Studies_Minor": "https://catalog.unc.edu/undergraduate/programs-study/african-american-diaspora-studies-minor/",
    "African_Studies_Minor":         "https://catalog.unc.edu/undergraduate/programs-study/african-studies-minor/",
    "American_Indian_and_Indigenous_Studies_Minor": "https://catalog.unc.edu/undergraduate/programs-study/american-indian-indigenous-studies-minor/",
    "American_Studies_Minor":        "https://catalog.unc.edu/undergraduate/programs-study/american-studies-minor/",
    "Arabic_Minor":                  "https://catalog.unc.edu/undergraduate/programs-study/arabic-minor/",
    "Archaeology_Minor":             "https://catalog.unc.edu/undergraduate/programs-study/archaeology-minor/",
    "BEST_Minor":                    "https://catalog.unc.edu/undergraduate/programs-study/best-minor/",
    "Chinese_Minor":                 "https://catalog.unc.edu/undergraduate/programs-study/chinese-minor/",
    "Civic_Life_and_Leadership_Minor": "https://catalog.unc.edu/undergraduate/programs-study/civic-life-leadership-minor/",
    "Classical_Humanities_Minor":    "https://catalog.unc.edu/undergraduate/programs-study/classical-humanities-minor/",
    "Comparative_Literature_Minor":  "https://catalog.unc.edu/undergraduate/programs-study/comparative-literature-minor/",
    "Education_Minor":               "https://catalog.unc.edu/undergraduate/programs-study/education-minor/",
    "Engineering_for_Environmental_Change_Minor": "https://catalog.unc.edu/undergraduate/programs-study/engineering-environmental-change-climate-health-minor/",
    "English_Minor":                 "https://catalog.unc.edu/undergraduate/programs-study/english-minor/",
    "Environmental_Justice_Minor":   "https://catalog.unc.edu/undergraduate/programs-study/environmental-justice-minor/",
    "French_Minor":                  "https://catalog.unc.edu/undergraduate/programs-study/french-minor/",
    "Geography_Minor":               "https://catalog.unc.edu/undergraduate/programs-study/geography-minor/",
    "German_Studies_Minor":          "https://catalog.unc.edu/undergraduate/programs-study/german-minor/",
    "Greek_Minor":                   "https://catalog.unc.edu/undergraduate/programs-study/greek-minor/",
    "Heritage_and_Global_Engagement_Minor": "https://catalog.unc.edu/undergraduate/programs-study/heritage-global-engagement-minor/",
    "Hindi_Urdu_Minor":              "https://catalog.unc.edu/undergraduate/programs-study/hindi-urdu-minor/",
    "Hispanic_Studies_Minor":        "https://catalog.unc.edu/undergraduate/programs-study/hispanic-studies-minor/",
    "Human_Development_Sustainability_and_Rights_Africa_Minor": "https://catalog.unc.edu/undergraduate/programs-study/human-development-sustainability-rights-africa-african-diaspora-minor/",
    "Islamic_and_Middle_Eastern_Studies_Minor": "https://catalog.unc.edu/undergraduate/programs-study/islamic-middle-eastern-studies-minor/",
    "Italian_Minor":                 "https://catalog.unc.edu/undergraduate/programs-study/italian-minor/",
    "Japanese_Minor":                "https://catalog.unc.edu/undergraduate/programs-study/japanese-minor/",
    "Jewish_Studies_Minor":          "https://catalog.unc.edu/undergraduate/programs-study/jewish-studies-minor/",
    "Korean_Minor":                  "https://catalog.unc.edu/undergraduate/programs-study/korean-minor/",
    "Latin_Minor":                   "https://catalog.unc.edu/undergraduate/programs-study/latin-minor/",
    "Latina_o_Studies_Minor":        "https://catalog.unc.edu/undergraduate/programs-study/latina-latino-studies-minor/",
    "Medicine_Literature_and_Culture_Minor": "https://catalog.unc.edu/undergraduate/programs-study/medicine-literature-culture-minor/",
    "Medieval_and_Early_Modern_Studies_Minor": "https://catalog.unc.edu/undergraduate/programs-study/medieval-early-modern-studies-minor/",
    "Middle_Eastern_Languages_Minor": "https://catalog.unc.edu/undergraduate/programs-study/middle-eastern-languages-minor/",
    "Military_Science_and_Leadership_Minor": "https://catalog.unc.edu/undergraduate/programs-study/military-science-minor/",
    "Modern_Hebrew_Minor":           "https://catalog.unc.edu/undergraduate/programs-study/modern-hebrew-minor/",
    "Musical_Theatre_Performance_Minor": "https://catalog.unc.edu/undergraduate/programs-study/musical-theatre-performance-minor/",
    "Naval_Science_Minor":           "https://catalog.unc.edu/undergraduate/programs-study/naval-science-minor/",
    "Persian_Minor":                 "https://catalog.unc.edu/undergraduate/programs-study/persian-minor/",
    "Pharmaceutical_Sciences_Minor": "https://catalog.unc.edu/undergraduate/programs-study/pharmaceutical-sciences-minor/",
    "Portuguese_Minor":              "https://catalog.unc.edu/undergraduate/programs-study/portuguese-minor/",
    "Risk_Management_Minor":         "https://catalog.unc.edu/undergraduate/programs-study/risk-management-minor/",
    "Russian_Culture_Minor":         "https://catalog.unc.edu/undergraduate/programs-study/russian-culture-minor/",
    "Screenwriting_Minor":           "https://catalog.unc.edu/undergraduate/programs-study/screenwriting-minor/",
    "Sexuality_Studies_Minor":       "https://catalog.unc.edu/undergraduate/programs-study/sexuality-studies-minor/",
    "Slavic_and_East_European_Studies_Minor": "https://catalog.unc.edu/undergraduate/programs-study/slavic-east-european-languages-cultures-minor/",
    "Social_and_Economic_Justice_Minor": "https://catalog.unc.edu/undergraduate/programs-study/social-economic-justice-minor/",
    "Southeast_Asian_Studies_Minor": "https://catalog.unc.edu/undergraduate/programs-study/southeast-asian-studies-minor/",
    "Speech_and_Hearing_Sciences_Minor": "https://catalog.unc.edu/undergraduate/programs-study/speech-hearing-sciences-minor/",
    "Study_of_Christianity_and_Culture_Minor": "https://catalog.unc.edu/undergraduate/programs-study/study-christianity-culture-minor/",
    "Translation_and_Interpreting_Minor": "https://catalog.unc.edu/undergraduate/programs-study/translation-minor/",
    "Womens_and_Gender_Studies_Minor": "https://catalog.unc.edu/undergraduate/programs-study/womens-gender-studies-minor/",
    "Writing_Editing_and_Digital_Publishing_Minor": "https://catalog.unc.edu/undergraduate/programs-study/writing-editing-digital-publishing-minor/",
}

# These tracks have no sc_courselist and are handled manually — skip fetching.
NO_SCRAPE = {
    "Art_History_Minor",
    "Asian_Studies_Minor",
    "Coaching_Education_Minor",
    "UNC_General_Education",
    "Physics_BS_Astrophysics",
}

# Boilerplate phrases that appear in the catalog footer/sidebar — strip paragraphs
# that consist entirely of these.
_BOILERPLATE_RE = re.compile(
    r'^(about unc|admissions|resources|policies|tuition|academic calendar|'
    r'office of the (university )?registrar|chapel hill|feedback|copyright|'
    r'print this page|the pdf will|all pages in|visit program website|'
    r'chair|director of|student services|contact|cb#\s*\d+|\(\d{3}\)|'
    r'majors|minors|graduate program|courses)\b',
    re.IGNORECASE,
)

_SAMPLE_PLAN_RE = re.compile(
    r'\b(sample plan|advising note|typical schedule|year \d)\b',
    re.IGNORECASE,
)


def _cell_text(td) -> str:
    return td.get_text(" ", strip=True).replace(" ", " ").strip()


def extract_requirements(html: str, url: str) -> str:
    """
    Parse the raw HTML and return a compact plain-text representation of
    ONLY the requirements content — section headers, rule texts, and
    course table rows.
    """
    soup = BeautifulSoup(html, "html.parser")
    lines = []

    # ── Locate the requirements container ────────────────────────────────────
    container = (
        soup.find("div", id="requirementstextcontainer")
        or soup.find("div", id="requirementstext")
        or soup.find("div", class_="tab_content")
        or soup.find("main")
        or soup.body
    )
    if not container:
        return "[NO CONTENT FOUND]"

    # ── Walk the container top-to-bottom ─────────────────────────────────────
    in_sample_plan = False

    for elem in container.descendants:
        if not hasattr(elem, "name"):
            continue   # skip NavigableString nodes at top level

        name = elem.name

        # Section headers
        if name in ("h2", "h3", "h4"):
            text = elem.get_text(" ", strip=True).replace(" ", " ")
            if _SAMPLE_PLAN_RE.search(text):
                in_sample_plan = True
                continue
            in_sample_plan = False
            if text and not _BOILERPLATE_RE.match(text):
                lines.append(f"\n## {text}")
            continue

        if in_sample_plan:
            continue

        # Rule-text paragraphs (not inside a table)
        if name == "p":
            # Skip if this <p> is inside a table
            if elem.find_parent("table"):
                continue
            text = elem.get_text(" ", strip=True).replace(" ", " ")
            if not text or _BOILERPLATE_RE.match(text) or len(text) < 8:
                continue
            if _SAMPLE_PLAN_RE.search(text):
                in_sample_plan = True
                continue
            lines.append(f"NOTE: {text}")
            continue

        # Course list tables
        if name == "table" and "sc_courselist" in (elem.get("class") or []):
            in_sample_plan = False
            rows = elem.find_all("tr")
            for row in rows:
                cells = row.find_all(["td", "th"])
                if not cells:
                    continue

                # Skip pure header rows (th cells only, e.g. "Code | Title | Hours")
                if all(c.name == "th" for c in cells):
                    continue

                # Detect row type by CSS class on the <tr>
                tr_classes = set(row.get("class") or [])

                # "orclass" rows — OR alternative
                if "orclass" in tr_classes:
                    code_td = row.find("td", class_="codecol")
                    title_td = cells[1] if len(cells) > 1 else None
                    code = _cell_text(code_td) if code_td else ""
                    title = _cell_text(title_td) if title_td else ""
                    if code:
                        lines.append(f"  OR {code} | {title}")
                    continue

                # "areaheader" / "subheader" rows — section sub-headers inside a table
                if tr_classes & {"areaheader", "subheader"}:
                    text = " ".join(_cell_text(c) for c in cells if _cell_text(c))
                    if text:
                        lines.append(f"### {text}")
                    continue

                # "listsum" rows — "Total Hours X" footer — skip
                if "listsum" in tr_classes:
                    continue

                # Regular course row or rule-text row
                code_td = row.find("td", class_="codecol")
                if code_td:
                    code = _cell_text(code_td)
                    # title is the next sibling td
                    title_td = code_td.find_next_sibling("td")
                    title = _cell_text(title_td) if title_td else ""
                    # hours — last td
                    hours = _cell_text(cells[-1]) if len(cells) >= 3 else ""
                    if code:
                        lines.append(f"  {code} | {title} | {hours}hrs")
                else:
                    # No codecol — this is a rule/header text span
                    text = " ".join(_cell_text(c) for c in cells if _cell_text(c))
                    if text and not _BOILERPLATE_RE.match(text):
                        lines.append(f"RULE: {text}")

    result = "\n".join(lines).strip()
    return result if result else "[NO REQUIREMENTS TABLE FOUND — text-only page]"


def cache_path(track_id: str) -> str:
    return os.path.join(HTML_CACHE_DIR, f"{track_id}.txt")


def fetch_and_cache(track_id: str, url: str) -> bool:
    """Fetch, clean, and write to cache. Returns True on success."""
    try:
        r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
    except Exception as e:
        print(f"  ERROR fetching {url}: {e}")
        return False

    cleaned = extract_requirements(r.text, url)
    out = cache_path(track_id)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(f"TRACK: {track_id}\nURL: {url}\n\n")
        f.write(cleaned)
    os.replace(tmp, out)
    size = len(cleaned)
    print(f"  ✓ {track_id} ({size:,} chars)")
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true",
                        help="Re-fetch even if cache file already exists")
    parser.add_argument("--track", metavar="TRACK_ID",
                        help="Only fetch this one track")
    args = parser.parse_args()

    os.makedirs(HTML_CACHE_DIR, exist_ok=True)

    tracks = (
        {args.track: TARGET_TRACKS[args.track]}
        if args.track and args.track in TARGET_TRACKS
        else TARGET_TRACKS
    )

    done = skipped = errors = 0
    for track_id, url in tracks.items():
        if track_id in NO_SCRAPE:
            print(f"  -- {track_id} (no-scrape, skipping)")
            skipped += 1
            continue

        out = cache_path(track_id)
        if not args.force and os.path.exists(out):
            skipped += 1
            continue

        print(f"Fetching {track_id}...")
        ok = fetch_and_cache(track_id, url)
        if ok:
            done += 1
        else:
            errors += 1
        time.sleep(REQUEST_DELAY)

    print(f"\nDone: {done} fetched, {skipped} skipped, {errors} errors")
    print(f"Cache dir: {HTML_CACHE_DIR}/")


if __name__ == "__main__":
    main()
