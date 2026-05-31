import argparse
import json
import logging
import os
import sys
import time
import hashlib
import re

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.scraper.req_scraper import scrape_major_requirements
from src.scraper.req_assembler import assemble_section, classify_section_type
from src.scraper.llm_req_parser import parse_rule_text

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

DEFAULT_MODEL   = "qwen2.5:14b"
OUTPUT_PATH     = "data/test_degree_requirements.json"
CACHE_PATH      = "data/req_cache.json"

# Every program that appears in the live degree_requirements.json, keyed by the
# track_id the app uses.  UNC_General_Education is attribute-rule-based and not
# scrapeable from a sc_courselist page, so it is intentionally excluded here —
# keep maintaining it manually in the production file.
TARGET_TRACKS = {
    # ── BS / BSBA / BSPH Majors ───────────────────────────────────────────────
    "Computer_Science_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/computer-science-major-bs/",
    "Data_Science_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/data-science-major-bs/",
    "Mathematics_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/mathematics-major-bs/",
    "Statistics_and_Analytics_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/statistics-analytics-majors-bs/",
    "Economics_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/economics-major-bs/",
    "Biology_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/biology-major-bs/",
    "Chemistry_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/chemistry-major-bs/",
    "Physics_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/physics-major-bs/",
    "Neuroscience_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/neuroscience-major-bs/",
    "Psychology_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/psychology-major-bs/",
    "Exercise_and_Sport_Science_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/exercise-sport-science-major-bs/",
    "Biomedical_Engineering_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/biomedical-engineering-major-bs/",
    "Biostatistics_BSPH":
        "https://catalog.unc.edu/undergraduate/programs-study/biostatistics-major-bsph/",
    "Business_Administration_BSBA":
        "https://catalog.unc.edu/undergraduate/programs-study/business-administration-major-bsba/",
    "Applied_Sciences_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/applied-sciences-major-bs/",
    "Earth_and_Marine_Sciences_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/earth-marine-sciences-major-bs/",
    "Environmental_Science_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/environmental-science-bs/",
    "Information_Science_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/information-science-major-bs/",
    "Neurodiagnostics_and_Sleep_Science_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/neurodiagnostics-sleep-sciences-major-bs/",
    "Community_and_Global_Public_Health_BSPH":
        "https://catalog.unc.edu/undergraduate/programs-study/community-global-public-health-major-bsph/",
    "Health_Policy_and_Management_BSPH":
        "https://catalog.unc.edu/undergraduate/programs-study/health-policy-management-major-bsph/",
    "Nutrition_BSPH":
        "https://catalog.unc.edu/undergraduate/programs-study/nutrition-major-bsph/",
    # ── BA Majors ─────────────────────────────────────────────────────────────
    "Political_Science_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/political-science-major-ba/",
    "Public_Policy_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/public-policy-major-ba/",
    "Sociology_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/sociology-major-ba/",
    "Economics_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/economics-major-ba/",
    "Psychology_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/psychology-major-ba/",
    "Computer_Science_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/computer-science-major-ba/",
    "Data_Science_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/data-science-major-ba/",
    "Mathematics_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/mathematics-major-ba/",
    "Biology_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/biology-major-ba/",
    "Chemistry_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/chemistry-major-ba/",
    "Physics_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/physics-major-ba/",
    "Linguistics_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/linguistics-major-ba/",
    "Anthropology_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/anthropology-major-ba/",
    "Medical_Anthropology_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/medical-anthropology-major-ba/",
    "Global_Studies_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/global-studies-major-ba/",
    "Environmental_Studies_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/environmental-studies-major-ba/",
    "Peace_War_and_Defense_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/peace-war-defense-major-ba/",
    "Management_and_Society_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/management-society-major-ba/",
    "Communication_Studies_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/communication-studies-major-ba/",
    "Exercise_and_Sport_Science_Fitness_Professional_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/exercise-sport-science-major-ba-fitness-professional/",
    "Exercise_and_Sport_Science_General_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/exercise-sport-science-major-ba-general/",
    "Exercise_and_Sport_Science_Sport_Administration_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/exercise-sport-science-major-ba-sport-administration/",
    # ── Minors ────────────────────────────────────────────────────────────────
    "Computer_Science_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/computer-science-minor/",
    "Data_Science_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/data-science-minor/",
    "Mathematics_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/mathematics-minor/",
    "Statistics_and_Analytics_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/statistics-and-analytics-minor/",
    "Economics_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/economics-minor/",
    "Biology_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/biology-minor/",
    "Chemistry_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/chemistry-minor/",
    "Physics_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/physics-minor/",
    "Business_Administration_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/business-administration-minor/",
    "Philosophy_Politics_and_Economics_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/philosophy-politics-economics-minor/",
    "Public_Policy_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/public-policy-minor/",
    "Entrepreneurship_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/entrepreneurship-minor/",
    "Philosophy_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/philosophy-minor/",
    "Linguistics_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/linguistics-minor/",
    "Environmental_Science_and_Studies_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/environmental-science-studies-minor/",
    "Applied_Sciences_and_Engineering_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/applied-sciences-engineering-minor/",
    "Anthropology_General_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/general-anthropology-minor/",
    "Medical_Anthropology_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/medical-anthropology-minor/",
    "Marine_Sciences_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/marine-sciences-minor/",
    "Spanish_for_the_Professions_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/spanish-professions-minor/",
    "Neuroscience_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/neuroscience-minor/",
    "Exercise_and_Sport_Science_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/exercise-sport-science-minor/",
    "Information_Systems_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/information-systems-minor/",
    "Astronomy_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/astronomy-minor/",
    "Business_of_Health_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/business-health-minor/",
    "Real_Estate_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/real-estate-minor/",
    "Health_and_Society_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/health-society-minor/",
    "Sustainability_Studies_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/sustainability-studies-minor/",
    "Sports_Medicine_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/sports-medicine-minor/",
    "Coaching_Education_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/coaching-education-minor/",
    "Geographic_Information_Sciences_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/gis-minor/",
    "Geological_Sciences_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/geological-sciences-minor/",
    "Food_Studies_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/food-studies-minor/",
    "Global_Cinema_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/global-cinema-minor/",
    "Dramatic_Art_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/dramatic-art-minor/",
    "Music_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/music-minor/",
    "Studio_Art_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/studio-art-minor/",
    "Art_History_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/art-history-minor/",
    "Creative_Writing_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/creative-writing-minor/",
    "Media_and_Journalism_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/media-journalism-minor/",
    "History_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/history-minor/",
    "Religious_Studies_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/religious-studies-minor/",
    "Conflict_Management_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/conflict-management-minor/",
    "Urban_Studies_and_Planning_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/urban-studies-planning-minor/",
    "Environmental_Microbiology_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/environmental-microbiology-minor/",
    "Hydrology_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/hydrology-minor/",
    "Climate_Change_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/climate-change-minor/",
    # ── Additional majors and minors from the full catalog ────────────────────
    "Aerospace_Studies_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/aerospace-studies-minor/",
    "African_American_and_Diaspora_Studies_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/african-american-diaspora-studies-minor/",
    "African_Studies_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/african-studies-minor/",
    "African_African_American_and_Diaspora_Studies_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/african-african-american-diaspora-studies-major-ba/",
    "American_Indian_and_Indigenous_Studies_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/american-indian-indigenous-studies-minor/",
    "American_Studies_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/american-studies-major-ba/",
    "American_Studies_BA_AIIS_Concentration":
        "https://catalog.unc.edu/undergraduate/programs-study/american-studies-major-baamerican-indian-indigenous-studies-concentration/",
    "American_Studies_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/american-studies-minor/",
    "Arabic_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/arabic-minor/",
    "Archaeology_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/archaeology-major-ba/",
    "Archaeology_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/archaeology-minor/",
    "Art_History_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/art-history-major-ba/",
    "Art_History_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/art-history-minor/",
    "Asian_Studies_BA_Arab_Cultures":
        "https://catalog.unc.edu/undergraduate/programs-study/asian-studies-major-ba-arab-cultures-concentration/",
    "Asian_Studies_BA_Chinese":
        "https://catalog.unc.edu/undergraduate/programs-study/asian-studies-major-ba-chinese-concentration/",
    "Asian_Studies_BA_Interdisciplinary":
        "https://catalog.unc.edu/undergraduate/programs-study/asian-studies-major-ba-general-concentration/",
    "Asian_Studies_BA_Japanese":
        "https://catalog.unc.edu/undergraduate/programs-study/asian-studies-major-ba-japanese-concentration/",
    "Asian_Studies_BA_Korean":
        "https://catalog.unc.edu/undergraduate/programs-study/asian-studies-major-ba-korean-concentration/",
    "Asian_Studies_BA_Persian":
        "https://catalog.unc.edu/undergraduate/programs-study/asian-studies-major-ba-persian-concentration/",
    "Asian_Studies_BA_South_Asian":
        "https://catalog.unc.edu/undergraduate/programs-study/asian-studies-major-ba-south-asian-studies-concentration/",
    "Asian_Studies_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/asian-studies-minor/",
    "BEST_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/best-minor/",
    "Biology_BS_Quantitative_Biology_Track":
        "https://catalog.unc.edu/undergraduate/programs-study/biology-major-bs-quantitative-biology-track/",
    "Chemistry_BS_Biochemistry_Track":
        "https://catalog.unc.edu/undergraduate/programs-study/chemistry-major-bs-biochemistry-track/",
    "Chemistry_BS_Polymer_Track":
        "https://catalog.unc.edu/undergraduate/programs-study/chemistry-major-bs-polymer-track/",
    "Chinese_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/chinese-minor/",
    "Civic_Life_and_Leadership_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/civic-life-leadership-minor/",
    "Classical_Humanities_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/classical-humanities-minor/",
    "Classics_BA_Classical_Archaeology":
        "https://catalog.unc.edu/undergraduate/programs-study/classics-major-ba-classical-archaeology/",
    "Classics_BA_Classical_Civilization":
        "https://catalog.unc.edu/undergraduate/programs-study/classics-major-ba-classical-civilization/",
    "Classics_BA_Greek_Latin":
        "https://catalog.unc.edu/undergraduate/programs-study/classics-major-ba-greek-latin/",
    "Clinical_Laboratory_Science_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/clinical-laboratory-science-major-bs/",
    "Comparative_Literature_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/comparative-literature-minor/",
    "Contemporary_European_Studies_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/contemporary-european-studies-major-ba/",
    "Dental_Hygiene_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/dental-hygiene-major-bs/",
    "Dramatic_Art_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/dramatic-art-major-ba/",
    "Education_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/education-minor/",
    "Engineering_for_Environmental_Change_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/engineering-environmental-change-climate-health-minor/",
    "English_and_Comparative_Literature_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/english-comparative-major-ba/",
    "English_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/english-minor/",
    "Environmental_Health_Sciences_BSPH":
        "https://catalog.unc.edu/undergraduate/programs-study/environmental-health-sciences-major-bsph/",
    "Environmental_Justice_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/environmental-justice-minor/",
    "French_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/french-minor/",
    "Geography_and_Environment_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/geography-major-ba/",
    "Geography_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/geography-minor/",
    "Geological_Sciences_BA_Earth_Science":
        "https://catalog.unc.edu/undergraduate/programs-study/geological-sciences-major-ba-earth-science-concentration/",
    "German_Studies_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/german-minor/",
    "Germanic_and_Slavic_BA_German_Studies":
        "https://catalog.unc.edu/undergraduate/programs-study/germanic-slavic-languages-literatures-major-ba-german-literature-culture-concentration/",
    "Germanic_and_Slavic_BA_Russian":
        "https://catalog.unc.edu/undergraduate/programs-study/germanic-slavic-languages-literatures-major-ba-russian-language-culture-concentration/",
    "Germanic_and_Slavic_BA_Slavic_and_East_European":
        "https://catalog.unc.edu/undergraduate/programs-study/germanic-slavic-languages-literatures-major-ba-central-european-studies-concentration/",
    "Greek_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/greek-minor/",
    "Heritage_and_Global_Engagement_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/heritage-global-engagement-minor/",
    "Hindi_Urdu_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/hindi-urdu-minor/",
    "Hispanic_Studies_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/hispanic-studies-minor/",
    "History_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/history-major-ba/",
    "Human_and_Organizational_Leadership_Development_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/human-org-leadership-ba/",
    "Human_Development_and_Family_Science_BAEd":
        "https://catalog.unc.edu/undergraduate/programs-study/human-development-family-studies-baed/",
    "Human_Development_Sustainability_and_Rights_Africa_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/human-development-sustainability-rights-africa-african-diaspora-minor/",
    "Interdisciplinary_Studies_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/interdisciplinary-studies-major-ba/",
    "Islamic_and_Middle_Eastern_Studies_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/islamic-middle-eastern-studies-minor/",
    "Italian_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/italian-minor/",
    "Japanese_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/japanese-minor/",
    "Jewish_Studies_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/jewish-studies-minor/",
    "Korean_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/korean-minor/",
    "Latin_American_Studies_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/latin-american-studies-major-ba/",
    "Latin_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/latin-minor/",
    "Latina_o_Studies_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/latina-latino-studies-minor/",
    "Media_and_Journalism_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/media-journalism-major-ba/",
    "Medicine_Literature_and_Culture_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/medicine-literature-culture-minor/",
    "Medieval_and_Early_Modern_Studies_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/medieval-early-modern-studies-minor/",
    "Middle_Eastern_Languages_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/middle-eastern-languages-minor/",
    "Military_Science_and_Leadership_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/military-science-minor/",
    "Modern_Hebrew_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/modern-hebrew-minor/",
    "Music_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/music-major-ba/",
    "Music_BMus":
        "https://catalog.unc.edu/undergraduate/programs-study/music-major-bmus/",
    "Musical_Theatre_Performance_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/musical-theatre-performance-minor/",
    "Naval_Science_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/naval-science-minor/",
    "Nursing_BSN":
        "https://catalog.unc.edu/undergraduate/programs-study/nursing-major-bsn/",
    "Persian_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/persian-minor/",
    "Pharmaceutical_Sciences_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/pharmaceutical-sciences-minor/",
    "Philosophy_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/philosophy-major-ba/",
    "Portuguese_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/portuguese-minor/",
    "Psychology_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/psychology-major-ba/",
    "Radiologic_Science_BS":
        "https://catalog.unc.edu/undergraduate/programs-study/radiologic-science-major-bs/",
    "Religious_Studies_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/religious-studies-major-ba/",
    "Religious_Studies_BA_Jewish_Studies":
        "https://catalog.unc.edu/undergraduate/programs-study/religious-studies-major-ba-jewish-studies-concentration/",
    "Risk_Management_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/risk-management-minor/",
    "Romance_Languages_BA_French":
        "https://catalog.unc.edu/undergraduate/programs-study/romance-languages-major-ba-french-francophone-studies/",
    "Romance_Languages_BA_Hispanic_Linguistics":
        "https://catalog.unc.edu/undergraduate/programs-study/romance-languages-major-ba-hispanic-linguistics/",
    "Romance_Languages_BA_Hispanic_Studies":
        "https://catalog.unc.edu/undergraduate/programs-study/romance-languages-major-ba-hispanic-literatures-cultures/",
    "Romance_Languages_BA_Italian":
        "https://catalog.unc.edu/undergraduate/programs-study/romance-languages-major-ba-italian/",
    "Romance_Languages_BA_Portuguese":
        "https://catalog.unc.edu/undergraduate/programs-study/romance-languages-major-ba-portuguese/",
    "Russian_Culture_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/russian-culture-minor/",
    "Screenwriting_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/screenwriting-minor/",
    "Sexuality_Studies_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/sexuality-studies-minor/",
    "Slavic_and_East_European_Studies_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/slavic-east-european-languages-cultures-minor/",
    "Social_and_Economic_Justice_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/social-economic-justice-minor/",
    "Southeast_Asian_Studies_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/southeast-asian-studies-minor/",
    "Speech_and_Hearing_Sciences_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/speech-hearing-sciences-minor/",
    "Studio_Art_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/studio-art-major-ba/",
    "Studio_Art_BFA":
        "https://catalog.unc.edu/undergraduate/programs-study/studio-art-major-bfa/",
    "Study_of_Christianity_and_Culture_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/study-christianity-culture-minor/",
    "Translation_and_Interpreting_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/translation-minor/",
    "Womens_and_Gender_Studies_BA":
        "https://catalog.unc.edu/undergraduate/programs-study/womens-gender-studies-major-ba/",
    "Womens_and_Gender_Studies_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/womens-gender-studies-minor/",
    "Writing_Editing_and_Digital_Publishing_Minor":
        "https://catalog.unc.edu/undergraduate/programs-study/writing-editing-digital-publishing-minor/",
}


def load_json_file(filepath):
    if os.path.exists(filepath):
        try:
            with open(filepath) as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to read {filepath}: {e}")
    return {}


def save_json_file(data, filepath):
    """Atomic write: write to .tmp then rename — same pattern as catalog pipeline."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    try:
        tmp_path = filepath + '.tmp'
        with open(tmp_path, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, filepath)
    except Exception as e:
        logger.error(f"Failed to write to {filepath}: {e}")


def clean_conc_name(header_text: str) -> str:
    """
    'Economics Concentration' → 'Economics'
    'Machine Learning and AI Concentration' → 'Machine_Learning_and_AI'
    Preserves Title Case so IDs are readable.
    """
    text = re.sub(r'[^A-Za-z0-9\s]', '', header_text)
    for kw in ('Concentration', 'Plan', 'Option', 'Track'):
        text = re.sub(rf'\b{kw}\b', '', text, flags=re.IGNORECASE)
    text = text.strip()
    return text.replace(' ', '_') if text else 'None'


def reindex_choice_groups(groups: list) -> list:
    """
    Give every choice group in a merged list a unique, sequential ID.

    assemble_section() uses a per-section counter, so two sections both start
    at choice_1 / list_1 / rule_1.  When their groups are concatenated into one
    base_requirements list the duplicates would silently mask each other in the
    requirements checker (which keys satisfied/unsatisfied by group id).

    Also drops `credits_required` from groups that already have a meaningful
    `courses_required` — the assembler can set both when the list-header row has
    an hours column, but the requirements checker treats credits_required as
    authoritative and would ignore courses_required.
    """
    seen: dict[str, int] = {}
    result = []
    for g in groups:
        base = re.sub(r'_\d+$', '', g['id'])         # strip existing suffix
        seen[base] = seen.get(base, 0) + 1
        g = dict(g)                                    # shallow copy — don't mutate original
        g['id'] = f"{base}_{seen[base]}"

        # If both counts are present, keep only courses_required (count-based wins)
        if g.get('courses_required') and g.get('credits_required'):
            del g['credits_required']

        result.append(g)
    return result


def propagate_reference_lists(sections: list) -> list:
    """
    One propagation pass: if a section sits between two reference_list sections
    AND it has no or_alternative rows and no real rule_texts, it is almost
    certainly part of the same reference cluster (e.g. a 1-course Sociology
    career-cluster sub-section).  Mark it reference_list too.

    Also marks any section whose title is exactly "Requirements" (the generic
    catch-all name used by many concentration sub-blocks) that has no real rules
    as a reference_list when its neighbors are all reference_lists.
    """
    _BOILERPLATE = re.compile(
        r'^(code\s*[\|]?\s*title|total\s*hours?)\s*$', re.IGNORECASE
    )

    def is_pool_candidate(sec):
        """
        True when a section looks like a reference pool rather than a real requirements block.
        Conditions:
          - No real rule_texts (only Code|Title / Total Hours boilerplate)
          - AND either: no or_alternatives at all,
                   or: or_alternatives are rare (< 20% of course rows) indicating
                       they are cross-listed equivalences, not genuine student choices.
        """
        has_real_rule = any(
            r['kind'] == 'rule_text' and not _BOILERPLATE.match(r['text'].strip())
            for r in sec['rows']
        )
        if has_real_rule:
            return False
        course_rows = sum(1 for r in sec['rows'] if r['kind'] == 'course')
        or_alt_rows = sum(1 for r in sec['rows'] if r['kind'] == 'or_alternative')
        total = course_rows + or_alt_rows
        if total == 0:
            return False
        return (or_alt_rows / total) < 0.20

    # Keep old name as an alias for legacy call sites
    is_pure_pool = is_pool_candidate

    # First pass: classify each section
    types = [classify_section_type(s['title'], s['rows']) for s in sections]

    # Second pass: propagate reference_list outward, two rules:
    #   Rule A — a pure-pool section adjacent to a reference_list section inherits it.
    #   Rule B — any section following a reference_list EMPTY header (0 course rows)
    #            inherits reference_list regardless of its own content, because the header
    #            names a container (e.g. "Sample Plan of Study") whose children are all
    #            informational rather than mandatory.
    changed = True
    while changed:
        changed = False
        for i in range(len(sections)):
            if types[i] == 'reference_list':
                continue

            def _sec_has_courses(sec):
                return any(r['kind'] in ('course', 'or_alternative') for r in sec['rows'])

            # Rule A: pure pool beside a CONTENT-BEARING reference_list neighbour.
            # Require the neighbour to have course rows — an empty reference_list header
            # (e.g. "Sample Plan of Study") must not bleed into preceding required sections.
            if is_pure_pool(sections[i]):
                prev_ref = (i > 0
                            and types[i - 1] == 'reference_list'
                            and _sec_has_courses(sections[i - 1]))
                next_ref = (i < len(types) - 1
                            and types[i + 1] == 'reference_list'
                            and _sec_has_courses(sections[i + 1]))
                if prev_ref or next_ref:
                    types[i] = 'reference_list'
                    changed = True
                    continue

            # Rule B: directly follows a reference_list EMPTY header (no course rows).
            # Handles children of containers like "Sample Plan of Study" that aren't
            # pure pools themselves (they may have real rule_texts describing the year).
            if i > 0 and types[i - 1] == 'reference_list' and not _sec_has_courses(sections[i - 1]):
                types[i] = 'reference_list'
                changed = True

    # Inject pre-computed type so assemble_section doesn't recompute
    result = []
    for sec, t in zip(sections, types):
        sec = dict(sec)
        sec['_type'] = t
        result.append(sec)
    return result


def make_cached_rule_parser(req_cache: dict, model_name: str):
    """
    Returns a caching wrapper around parse_rule_text.
    Rule text like 'Five additional COMP courses 420 or higher' repeats across
    many degree pages — caching avoids redundant LLM calls.
    Same hash + atomic-save pattern as the catalog pipeline's course_cache.
    """
    _REJECTED = "__rejected__"

    def parse_with_cache(text: str):
        key = hashlib.md5(text.encode('utf-8')).hexdigest()
        cached = req_cache.get(key)
        if cached == _REJECTED:
            return None
        if cached is not None:
            return cached

        logger.info(f"  -> Cache miss, calling LLM: {text[:80]}")
        parsed = parse_rule_text(text, model_name=model_name)
        # Cache both successes and rejections so we never call the LLM twice for
        # the same text, even when the LLM/validator rejects the output.
        req_cache[key] = parsed if parsed is not None else _REJECTED
        save_json_file(req_cache, CACHE_PATH)
        time.sleep(0.5)
        return parsed

    return parse_with_cache


def make_no_llm_rule_parser(skipped_log: dict, current_track: list):
    """
    Returns a stub rule parser that logs skipped rule texts instead of calling
    the LLM.  current_track is a one-element list so the closure can see the
    track_id set by the outer loop without rebinding.
    """
    def stub(text: str):
        track_id = current_track[0]
        skipped_log.setdefault(track_id, [])
        if text not in skipped_log[track_id]:
            skipped_log[track_id].append(text)
        logger.info(f"  [no-llm] Skipping rule text: {text[:80]}")
        return None

    return stub


SKIPPED_RULES_PATH    = "data/skipped_rules.json"
MANUAL_PATCHES_PATH   = "data/req_manual_patches.json"


def run_req_pipeline(model_name: str, force: bool = False, no_llm: bool = False):
    logger.info("Starting Requirements Pipeline  model=%s  output=%s  no_llm=%s",
                model_name, OUTPUT_PATH, no_llm)

    # Seed with existing output so a partial re-run doesn't wipe already-done tracks.
    master_reqs = load_json_file(OUTPUT_PATH)
    req_cache   = load_json_file(CACHE_PATH)

    skipped_log: dict = {}
    current_track: list = [None]

    if no_llm:
        rule_parser = make_no_llm_rule_parser(skipped_log, current_track)
    else:
        rule_parser = make_cached_rule_parser(req_cache, model_name)

    for track_id, url in TARGET_TRACKS.items():
        current_track[0] = track_id
        if not force and track_id in master_reqs:
            logger.info("Skipping %s (already in output — use --force to reprocess)", track_id)
            continue

        logger.info("Processing %s ...", track_id)

        scraped = scrape_major_requirements(url)
        if not scraped:
            logger.warning("  No sc_courselist tables found — skipping %s", track_id)
            continue

        logger.info("  %d sections under header: '%s'", len(scraped['sections']), scraped['main_header'])

        # Pre-classify sections and propagate reference_list to neighbor pure pools.
        sections = propagate_reference_lists(scraped['sections'])

        base_core   = {"required_courses": [], "choice_groups": []}
        conc_blocks = []

        for section in sections:
            # Short-circuit reference_list sections: no LLM calls, no assembly needed.
            if section.get('_type') == 'reference_list':
                logger.info("  [%-13s] '%s' | req: 0 | groups: 0", 'reference_list', section['title'])
                continue

            block  = assemble_section(section, rule_parser)
            b_type = block['block_type']

            logger.info(
                "  [%-13s] '%s' | req: %d | groups: %d",
                b_type, block['block_title'],
                len(block['required_courses']), len(block['choice_groups']),
            )

            if b_type == 'reference_list':
                continue
            elif b_type == 'core':
                seen = set(base_core['required_courses'])
                for code in block['required_courses']:
                    if code not in seen:
                        base_core['required_courses'].append(code)
                        seen.add(code)
                base_core['choice_groups'].extend(block['choice_groups'])
            elif b_type == 'concentration':
                conc_blocks.append(block)

        # Build the nested structure the app's requirements_checker expects:
        #   base_requirements holds the shared core.
        #   concentrations holds ONLY concentration-specific additions.
        #   The checker merges them at runtime — don't pre-merge here.
        #
        # reindex_choice_groups() fixes duplicate IDs that arise when groups
        # from multiple sections are merged, and drops credits_required on
        # groups that already have a meaningful courses_required.
        base_core['choice_groups'] = reindex_choice_groups(base_core['choice_groups'])

        concentrations: dict = {"None": {"required_courses": [], "choice_groups": []}}
        for conc in conc_blocks:
            name = clean_conc_name(conc['block_title'])
            if name in concentrations:
                logger.warning("  Duplicate concentration name '%s' in %s — merging", name, track_id)
                concentrations[name]['required_courses'].extend(conc['required_courses'])
                concentrations[name]['choice_groups'].extend(conc['choice_groups'])
            else:
                concentrations[name] = {
                    "required_courses": conc['required_courses'],
                    "choice_groups":    reindex_choice_groups(conc['choice_groups']),
                }

        master_reqs[track_id] = {
            "base_requirements": base_core,
            "concentrations":    concentrations,
        }

        # Checkpoint after every track — same philosophy as catalog pipeline
        # flushing after every LLM call: never lose completed work to a crash.
        save_json_file(master_reqs, OUTPUT_PATH)
        logger.info(
            "  Saved %s  (%d req, %d groups, %d concentration(s))",
            track_id,
            len(base_core['required_courses']),
            len(base_core['choice_groups']),
            len(concentrations) - 1,  # exclude the implicit 'None'
        )

    # Apply manual patches so hand-curated explicit lists survive --force reruns.
    manual_patches = load_json_file(MANUAL_PATCHES_PATH)
    if manual_patches:
        applied = 0
        for track_id, patch_data in manual_patches.items():
            if track_id not in master_reqs:
                continue
            for group_id, patch in (patch_data.get('base_requirements', {})
                                            .get('choice_group_patches', {}).items()):
                cg = master_reqs[track_id]['base_requirements']['choice_groups']
                for g in cg:
                    if g['id'] == group_id:
                        g['type'] = patch['type']
                        g['options'] = patch.get('options', [])
                        g['courses_required'] = patch.get('courses_required', g['courses_required'])
                        g['rule'] = patch.get('rule', None)
                        g.pop('credits_required', None)
                        applied += 1
                        break
        if applied:
            logger.info("Applied %d manual patches from %s", applied, MANUAL_PATCHES_PATH)
            save_json_file(master_reqs, OUTPUT_PATH)

    logger.info("Pipeline complete. %d tracks written to %s", len(master_reqs), OUTPUT_PATH)

    if no_llm and skipped_log:
        save_json_file(skipped_log, SKIPPED_RULES_PATH)
        total_skipped = sum(len(v) for v in skipped_log.values())
        logger.info(
            "Skipped %d rule texts across %d tracks — saved to %s",
            total_skipped, len(skipped_log), SKIPPED_RULES_PATH,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Build degree requirements JSON from UNC catalog')
    parser.add_argument('--model', default=DEFAULT_MODEL,
                        help=f'Ollama model name (default: {DEFAULT_MODEL})')
    parser.add_argument('--force', action='store_true',
                        help='Reprocess tracks already present in the output file')
    parser.add_argument('--no-llm', action='store_true',
                        help='Skip LLM rule parsing; log skipped rule texts to data/skipped_rules.json')
    args = parser.parse_args()
    run_req_pipeline(model_name=args.model, force=args.force, no_llm=args.no_llm)
