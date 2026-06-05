"""
Phase 1 audit: identify tracks in degree_requirements.json that likely have missed concentrations.

Four heuristics applied together:
  A) Catalog page has sc_courselist tables AFTER the core requirements table and BEFORE
     the sample plan section — each with distinct headers suggesting alternative concentration
     blocks. This catches CS-style pages where concentrations are h3-headed tables.
  B) Section headers (h2/h3/h4 or areaheader rows inside tables) after the core block
     contain concentration alias keywords that the scraper doesn't currently recognise:
     emphasis, specialization, pathway, strand, focus area, sequence, program area.
  C) The section following the first requirements table contains post-core course lists
     that are not reference lists or sample plans — thin or absent choice_group data in
     the current JSON is a red flag.
  D) For tracks that already have concentrations, cross-check that the names on the
     live page roughly match (detect partial captures).

False-positive suppression:
  - Ignore page navigation elements: "Print Options", "Sample Plan", "Notes on the Plan",
    "Special Opportunities", "Honors in", "Department Programs", "Study Abroad",
    "Experiential Education", "High-Impact", "Dual Bachelor", "Undergraduate Awards",
    "Research Opportunities", "EconAid", "Clubs", "Competitions" etc.
  - Ignore tables that are clearly reference/elective pools (title contains "elective" or
    "course list" and no alias keyword).

Produces a prioritized JSON report:
  data/staging/concentration_audit.json

Usage:
  python3 scripts/pipeline/audit_missed_concentrations.py [--tracks TRACK_ID ...]
"""

import argparse
import json
import logging
import os
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.scraper.requirements_scraper import fetch_html
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

REQUIREMENTS_PATH = "data/degree_requirements.json"
AUDIT_OUTPUT_PATH = "data/staging/concentration_audit.json"

# ── Alias keywords that mean "concentration" on live catalog pages ─────────────
# The scraper already handles: 'concentration', ' plan', ' option', ' track'
KNOWN_ALIASES = ['concentration', 'plan', 'option', 'track']
# Aliases the scraper does NOT yet handle — these are the ones we're hunting
MISSING_ALIASES = [
    'emphasis', 'specialization', 'specialisation',
    'pathway', 'strand', 'focus area', 'area of focus',
    'area of emphasis', 'program area',
]
ALL_ALIAS_KEYWORDS = KNOWN_ALIASES + MISSING_ALIASES

# ── Non-concentration page elements to ignore ─────────────────────────────────
# Headers/titles that are definitely NOT concentration blocks
_NOISE_PATTERNS = re.compile(
    r'\bprint\s+options?\b'             # "Print Options"
    r'|\bsample\s+plan\b'               # "Sample Plan of Study", "Sample Plan 1"
    r'|\bnotes?\s+on\b'                 # "Notes on the Suggested Plan"
    r'|\bsuggested\s+plan\b'            # "Notes on the Suggested Plan of Study"
    r'|\bspecial\s+opportunities?\b'    # "Special Opportunities in CS"
    r'|\bhonors\s+in\b'                 # "Honors in Biology"
    r'|\bdepartment\s+programs?\b'      # "Department Programs"
    r'|\bstudy\s+abroad\b'              # "Study Abroad"
    r'|\bexperiential\s+education\b'    # "Experiential Education"
    r'|\bhigh.?impact\b'                # "High-Impact Experience"
    r'|\bdual\s+bachelor\b'             # "Dual Bachelor's..."
    r'|\bundergraduate\s+award\b'       # "Undergraduate Awards"
    r'|\bundergraduate\s+research\b'    # "Undergraduate Research"
    r'|\bresearch\s+opportunit\b'       # "Research Opportunities"
    r'|\blaboratory\s+teaching\b'       # "Laboratory Teaching Internships"
    r'|\bsuggest\b'                     # "Suggested Program of Study"
    r'|\bclub\b'                        # "Clubs"
    r'|\bcompetition\b'                 # "Competitions"
    r'|\bhonor\s+societ\b'              # "Honor Society"
    r'|\baward\b'                       # "Undergraduate Awards"
    r'|\binternship\b'                  # "Internships"
    r'|\bassistantship\b'               # "Assistantships"
    r'|\bconference\b'                  # "Conferences"
    r'|\bseminar\b'                     # "Seminars"
    r'|\bprogram\s+of\s+study\b'        # "Program of Study"
    r'|\badmission\s+to\b'              # "Admission to the Major"
    r'|\bstudent\s+learning\s+outcome\b'# "Student Learning Outcomes"
    r'|\badvising\b'                    # "Advising"
    r'|\bfacult\b'                      # "Faculty"
    r'|\bsemester\b'                    # "Fall Semester", "Spring Semester"
    r'|\byear\s*\d\b'                   # "Year 1", "Year 2" (sample plans)
    r'|\bfirst\s+year\b|\bsecond\s+year\b|\bthird\s+year\b|\bfourth\s+year\b'
    r'|\bmaster\b|\bdoctoral\b'         # "Master's", "Doctoral"
    r'|\bdouble\s+major\b'              # "Double Major"
    r'|\bminor\b'                       # stray "Minor" headers on major pages
    r'|\brelated\s+fields?\b'           # "Related Fields"
    r'|\bfinancial\s+aid\b'             # "Financial Aid"
    r'|\bcareer\b'                      # "Career paths"
    r'|\bprofessional\b.{0,20}\bopport' # "Professional Opportunities"
    r'|\bplaymakers\b'                  # "PlayMakers Repertory"
    r'|\bintroduction\b.{0,20}\bmajor\b'# "Introduction to the Major"
    r'|\balumni\b'                      # "Alumni"
    r'|\bcertificat\b'                  # "Certificate"
    r'|\bexternship\b'                  # "Externship"
    r'|\btransfer\b'                    # "Transfer"
    r'|\bwaiver\b'                      # "Waiver"
    r'|\badvanced\s+placement\b'        # "Advanced Placement"
    r'|\bcertification\b'               # "Certification"
    r'|\bautomatic\b'                   # "Automatic"
    r'|\bscholars\s+program\b'          # "Scholars Program"
    r'|\bexchange\b'                    # "Exchange"
    r'|\blearning\s+outcomes?\b'        # "Learning Outcomes"
    r'|\bpayment\b'                     # "Payment"
    r'|\bapplication\b'                 # "Application"
    r'|\bfrequently\b'                  # "Frequently Asked Questions"
    r'|\benrollment\b'                  # "Enrollment"
    r'|\bregistration\b'                # "Registration",
    r'|\bcourse\s+list\b'               # pure course list tables
    r'|\belective\s+list\b'             # pure elective list
    r'|\bally\s+science\b'              # "Allied Science Electives"
    r'|\ballied\s+science\b'            # "Allied Science Electives"
    r'|\bexperiment\b'                  # "Experimental"
    r'|\bperformance\b'                 # "Performance Opportunities"
    r'|\bproduction\b'                  # "Production Opportunities"
    r'|\brehearsal\b'                   # "Rehearsal"
    r'|\bapprenticeship\b'              # "Apprenticeships"
    r'|\becono\b'                       # "EconAid"
    r'|\bceteris\b'                     # "Ceteris Paribus"
    r'|\bqualif\b'                      # "Qualifying"
    r'|\baddendum\b'                    # "Addendum"
    r'|\bappendix\b'                    # "Appendix"
    r'|\bglossary\b'                    # "Glossary"
    r'|\bindex\b'                       # "Index"
    r'|\bsupplementary\b'               # "Supplementary"
    r'|\bchecklist\b'                   # "Checklist"
    r'|\bworksheet\b'                   # "Worksheet"
    r'|\bfaq\b'                         # "FAQ"
    r'|\bvideo\b'                       # "Video"
    r'|\bcontact\b'                     # "Contact"
    r'|\blinks?\b'                      # "Links"
    r'|\bresource\b'                    # "Resources"
    r'|\bwebsite\b'                     # "Website"
    r'|\bportal\b'                      # "Portal"
    r'|\bdocument\b'                    # "Document"
    r'|\btemplate\b'                    # "Template"
    r'|\bguide\b'                       # "Guide"
    r'|\bhandbook\b'                    # "Handbook"
    r'|\bpolicy\b'                      # "Policy"
    r'|\bprocedure\b'                   # "Procedure"
    r'|\bregulation\b'                  # "Regulation"
    r'|\bstandard\b'                    # "Standard"
    r'|\bguideline\b'                   # "Guideline"
    r'|\brule\b'                        # "Rules"
    r'|\brequirement\s+for\s+all\b'     # "Requirements for All Concentrations"
    r'|\bcore\s+requirement\b'          # "Core Requirements"
    r'|\bgateway\s+course\b'            # "Gateway Course"
    r'|\badditional\s+requirement\b'    # "Additional Requirements"
    r'|\bglobal\s+language\b'           # "Global Language"
    r'|\bwriting\s+requirement\b'       # "Writing Requirement"
    r'|\bgeneral\s+education\b'         # "General Education"
    r'|\bphysical\s+education\b'        # "Physical Education"
    r'|\bservice\s+learning\b'          # "Service Learning"
    r'|\bcommunity\s+service\b'         # "Community Service"
    r'|\bvolunteer\b'                   # "Volunteer"
    r'|\bmentorship\b'                  # "Mentorship"
    r'|\bnetwork\b'                     # "Networking"
    r'|\bsocial\s+media\b'              # "Social Media"
    r'|\bpublication\b'                 # "Publication"
    r'|\bjournal\b'                     # "Journal"
    r'|\bmagazine\b'                    # "Magazine"
    r'|\bnewsletter\b'                  # "Newsletter"
    r'|\bnewspaper\b'                   # "Newspaper"
    r'|\breport\b'                      # "Report"
    r'|\bpresentation\b'                # "Presentation"
    r'|\bposter\b'                      # "Poster"
    r'|\bexhibit\b'                     # "Exhibition"
    r'|\bdissertation\b'                # "Dissertation"
    r'|\bthesis\b'                      # "Thesis" (standalone sections, not "thesis track")
    r'|\bcredential\b'                  # "Credential in..."
    r'|\bcertification\b'               # "Certification"
    r'|\blicensure\b'                   # "Licensure"
    r'|\baccreditation\b'               # "Accreditation"
    r'|\bnurse\b|\bnursing\b'           # nursing-specific sections
    r'|\bprelaw\b|\bpre-law\b'          # "Pre-Law"
    r'|\bpremed\b|\bpre-med\b'          # "Pre-Med"
    r'|\bpredental\b|\bpre-dental\b'    # "Pre-Dental"
    r'|\bpre-professional\b'            # "Pre-Professional"
    r'|\bfield\s+placement\b'           # "Field Placement"
    r'|\bclinical\s+placement\b'        # "Clinical Placement"
    r'|\bpracticum\b'                   # "Practicum"
    r'|\bapprentice\b'                  # "Apprentice"
    r'|\bproject\s+lab\b'               # "Project Lab"
    r'|\bcapstone\s+seminar\b'          # "Capstone Seminar"
    r'|\bsenior\s+thesis\b'             # "Senior Thesis"
    r'|\bsenior\s+seminar\b'            # "Senior Seminar"
    r'|\bsenior\s+project\b'            # "Senior Project"
    r'|\bsenior\s+capstone\b'           # "Senior Capstone"
    r'|\bdirected\s+study\b'            # "Directed Study"
    r'|\bindependent\s+study\b'         # "Independent Study"
    r'|\bcooperative\s+education\b'     # "Cooperative Education"
    r'|\bco-?op\b'                      # "Co-op"
    r'|\bfield\s+school\b'              # "Field School"
    r'|\blab\s+rotation\b'              # "Lab Rotation"
    r'|\bclass\s+of\b'                  # "Class of 2024"
    r'|\bcohort\b'                      # "Cohort"
    r'|\bstudy\s+groups?\b'             # "Study Groups"
    r'|\btutor\b'                       # "Tutoring"
    r'|\bmentors?\b'                    # "Mentors"
    r'|\bcoach\b'                       # "Coaching"
    r'|\badvised\b'                     # "Advised"
    r'|\binformation\s+session\b'       # "Information Sessions"
    r'|\borientation\b'                 # "Orientation"
    r'|\bwelcome\b'                     # "Welcome"
    r'|\bintro\b'                       # "Introduction"
    r'|\bwhat\s+is\b'                   # "What is..."
    r'|\bwhy\s+study\b'                 # "Why Study..."
    r'|\babout\s+the\b'                 # "About the Program"
    r'|\bprogram\s+description\b'       # "Program Description"
    r'|\bprogram\s+objective\b'         # "Program Objectives"
    r'|\bprogram\s+overview\b'          # "Program Overview"
    r'|\bcourse\s+sequence\b'           # "Course Sequence" (informational)
    r'|\belective\s+course\b'           # "Elective Courses" (pool)
    r'|\bapproved\s+elective\b'         # "Approved Electives"
    r'|\bupper.?division\s+elective\b'  # "Upper-Division Electives"
    r'|\bfree\s+elective\b'             # "Free Electives"
    r'|\bopen\s+elective\b'             # "Open Electives"
    r'|\bgeneral\s+elective\b'          # "General Electives"
    r'|\bcontrol\s+of\s+infection\b'    # specific clinical tables
    r'|\bplan\s+a\b|\bplan\s+b\b'       # "Plan A", "Plan B" sub-parts
    r'|\bsection\s+[a-z]\b'             # "Section A", "Section B"
    r'|\bpart\s+[a-z\d]\b'              # "Part A", "Part 1"
    r'|\bgroup\s+[a-z\d]\b'             # "Group A", "Group 1"
    r'|\blist\s+[a-z\d]\b'              # "List A", "List 1"
    r'|\bcollaboration\b'               # "Collaboration"
    r'|\bpartnership\b'                 # "Partnership"
    r'|\bexchange\s+program\b'          # "Exchange Program"
    r'|\bvisiting\b'                    # "Visiting"
    r'|\bguest\b'                       # "Guest"
    r'|\bspeaker\b'                     # "Speaker"
    r'|\bpanel\b'                       # "Panel"
    r'|\bworkshop\b'                    # "Workshop"
    r'|\bsymposium\b'                   # "Symposium"
    r'|\bfestival\b'                    # "Festival"
    r'|\bevent\b'                       # "Events"
    r'|\bnetworking\b'                  # "Networking"
    r'|\bcommunity\s+engage\b'          # "Community Engagement"
    r'|\boutreach\b'                    # "Outreach"
    r'|\bservice\s+trip\b'              # "Service Trip"
    r'|\bimmersion\b'                   # "Immersion"
    r'|\bfield\s+trip\b'                # "Field Trip"
    r'|\bcultural\s+exchange\b'         # "Cultural Exchange"
    r'|\blanguage\s+immersion\b'        # "Language Immersion"
    r'|\bglobal\s+engagement\b'         # "Global Engagement"
    r'|\binternational\s+experience\b'  # "International Experience"
    r'|\bglobal\s+learning\b'           # "Global Learning"
    r'|\bprofessional\s+develop\b'      # "Professional Development"
    r'|\bcollege\s+of\b'                # "College of..."
    r'|\bdepartment\s+of\b'             # "Department of..."
    r'|\bdivision\s+of\b'               # "Division of..."
    r'|\bschool\s+of\b'                 # "School of..."
    r'|\boffice\s+of\b'                 # "Office of..."
    r'|\bcenter\s+for\b'                # "Center for..."
    r'|\binstitute\s+for\b'             # "Institute for..."
    r'|\bprogram\s+in\b'                # "Program in..."
    r'|\bjoint\s+program\b'             # "Joint Program"
    r'|\binterdisciplinary\s+program\b' # "Interdisciplinary Program"
    r'|\bcollaborative\s+program\b'     # "Collaborative Program"
    r'|\bcooperative\s+program\b'       # "Cooperative Program"
    r'|\bpartnership\s+program\b'       # "Partnership Program"
    r'|\bacceler\b'                     # "Accelerated"
    r'|\bfast.?track\b'                 # "Fast-Track"
    r'|\bexpedit\b'                     # "Expedited"
    r'|\bexpress\b'                     # "Express"
    r'|\bbridge\s+program\b'            # "Bridge Program"
    r'|\btransition\b'                  # "Transition"
    r'|\bpostbaccalaureate\b'           # "Post-Baccalaureate"
    r'|\bpostgraduate\b'                # "Post-Graduate"
    r'|\bgraduate\s+school\b'           # "Graduate School"
    r'|\bmaster\s+of\b'                 # "Master of..."
    r'|\bdoctor\s+of\b'                 # "Doctor of..."
    r'|\bphd\b'                         # "PhD"
    r'|\bjd\b'                          # "JD"
    r'|\bmd\b'                          # "MD"
    r'|\bmba\b'                         # "MBA"
    r'|\bllm\b'                         # "LLM"
    r'|\bmsw\b'                         # "MSW"
    r'|\bmph\b'                         # "MPH"
    r'|\bma\s+in\b'                     # "MA in..."
    r'|\bms\s+in\b'                     # "MS in..."
    r'|\bbs\s+to\s+ms\b'                # "BS to MS"
    r'|\bfive.year\b'                   # "Five-Year"
    r'|\b4\s*\+\s*1\b'                  # "4+1"
    r'|\b3\s*\+\s*2\b'                  # "3+2"
    r'|\bchange\s+of\s+major\b'         # "Change of Major"
    r'|\bdeclar\b'                      # "Declaring"
    r'|\benrolling\b'                   # "Enrolling"
    r'|\btransfer\s+credit\b'           # "Transfer Credit"
    r'|\bap\s+credit\b'                 # "AP Credit"
    r'|\bib\s+credit\b'                 # "IB Credit"
    r'|\bwaivers?\s+and\b'              # "Waivers and..."
    r'|\bsubstitution\b'                # "Substitutions"
    r'|\bpetition\b'                    # "Petition"
    r'|\bappeal\b'                      # "Appeal"
    r'|\bgrade\b'                       # "Grading"
    r'|\bgrading\s+policy\b'            # "Grading Policy"
    r'|\bincomplete\b'                  # "Incomplete"
    r'|\bwithdraw\b'                    # "Withdrawal"
    r'|\bgraduation\s+requirement\b'    # "Graduation Requirements"
    r'|\bcommencement\b'                # "Commencement"
    r'|\bdiploma\b'                     # "Diploma"
    r'|\btranscript\b'                  # "Transcript"
    r'|\bdegree\s+audit\b'              # "Degree Audit"
    r'|\bdegree\s+check\b'              # "Degree Check"
    r'|\bdegree\s+progress\b'           # "Degree Progress"
    r'|\bdegree\s+requirement\b'        # "Degree Requirements" (generic)
    r'|\bprogram\s+requirement\b'       # "Program Requirements" (generic)
    r'|\bmajor\s+requirement\b'         # "Major Requirements" (generic)
    r'|\bminor\s+requirement\b'         # "Minor Requirements"
    r'|\bcourse\s+requirement\b'        # "Course Requirements"
    r'|\bcredit\s+hour\s+requirement\b' # "Credit Hour Requirements"
    r'|\bcumulative\s+gpa\b'            # "Cumulative GPA"
    r'|\bgrade\s+point\b'               # "Grade Point"
    r'|\bcoursework\b'                  # "Coursework"
    r'|\bcurriculum\b'                  # "Curriculum"
    r'|\bplan\s+of\s+study\b'           # "Plan of Study"
    r'|\bsyllabi?\b'                    # "Syllabus"
    r'|\bofficial\b'                    # "Official"
    r'|\binstructor\b'                  # "Instructor"
    r'|\bprofessor\b'                   # "Professor"
    r'|\bstudent\s+affair\b'            # "Student Affairs"
    r'|\bregistrar\b'                   # "Registrar"
    r'|\bbursar\b'                      # "Bursar"
    r'|\bfinancial\b'                   # "Financial"
    r'|\bscholarship\b'                 # "Scholarship"
    r'|\bgrant\b'                       # "Grant"
    r'|\bloan\b'                        # "Loan"
    r'|\bfellowship\b'                  # "Fellowship"
    r'|\bstipend\b'                     # "Stipend"
    r'|\bwork.?study\b'                 # "Work-Study"
    r'|\bemployment\b'                  # "Employment"
    r'|\bvoluntary\b'                   # "Voluntary"
    r'|\bextra.?curricular\b'           # "Extra-Curricular"
    r'|\bactivities\b'                  # "Activities"
    r'|\borganization\b'                # "Organizations"
    r'|\bfraternity\b'                  # "Fraternity"
    r'|\bsorority\b'                    # "Sorority"
    r'|\bcampus\s+life\b'               # "Campus Life"
    r'|\bhousing\b'                     # "Housing"
    r'|\bdining\b'                      # "Dining"
    r'|\bhealth\s+service\b'            # "Health Services"
    r'|\bcounseling\b'                  # "Counseling"
    r'|\brecreation\b'                  # "Recreation"
    r'|\bathletic\b'                    # "Athletics"
    r'|\bsport\s+club\b'                # "Sport Clubs"
    r'|\bstudent\s+body\b'              # "Student Body"
    r'|\bstudent\s+government\b'        # "Student Government"
    r'|\bstudent\s+council\b'           # "Student Council"
    r'|\bstudent\s+representative\b'    # "Student Representative"
    r'|\bstudent\s+advocate\b'          # "Student Advocate"
    r'|\bstudent\s+fee\b'               # "Student Fees"
    r'|\btuition\b'                     # "Tuition"
    r'|\bcost\s+of\s+attendance\b'      # "Cost of Attendance"
    r'|\broom\s+and\s+board\b'          # "Room and Board"
    r'|\bbook\s+and\s+supplie\b'        # "Books and Supplies"
    r'|\bpersonal\s+expense\b'          # "Personal Expenses"
    r'|\btransportation\b'              # "Transportation"
    r'|\bliving\s+expense\b'            # "Living Expenses"
    r'|\bnet\s+price\b'                 # "Net Price"
    r'|\bcost\s+estimat\b'              # "Cost Estimate"
    r'|\btuition\s+calculator\b'        # "Tuition Calculator"
    r'|\bpayment\s+plan\b'              # "Payment Plan"
    r'|\bbilling\b'                     # "Billing"
    r'|\bfee\s+schedule\b'              # "Fee Schedule"
    r'|\bverification\b'                # "Verification"
    r'|\bdocumentation\b'               # "Documentation"
    r'|\bproof\b'                       # "Proof"
    r'|\bcertified\b'                   # "Certified"
    r'|\bofficial\s+transcript\b'       # "Official Transcript"
    r'|\bunofficial\s+transcript\b'     # "Unofficial Transcript"
    r'|\bacademic\s+record\b'           # "Academic Record"
    r'|\bstudent\s+record\b'            # "Student Records"
    r'|\benrollment\s+verification\b'   # "Enrollment Verification"
    r'|\bdegree\s+verification\b'       # "Degree Verification"
    r'|\bgraduation\s+application\b'    # "Graduation Application"
    r'|\bcommencement\s+ceremony\b'     # "Commencement Ceremony"
    r'|\baward\s+ceremony\b'            # "Award Ceremony"
    r'|\brecognition\s+ceremony\b'      # "Recognition Ceremony"
    r'|\binduction\s+ceremony\b'        # "Induction Ceremony"
    r'|\bcapping\s+ceremony\b'          # "Capping Ceremony"
    r'|\bconvocation\b'                 # "Convocation"
    r'|\bpinning\s+ceremony\b'          # "Pinning Ceremony"
    r'|\bwhite\s+coat\s+ceremony\b'     # "White Coat Ceremony"
    r'|\bmatching\b'                    # "Matching"
    r'|\bboard\s+exam\b'                # "Board Exam"
    r'|\blicensing\s+exam\b'            # "Licensing Exam"
    r'|\bcertifying\s+exam\b'           # "Certifying Exam"
    r'|\bnclex\b'                       # "NCLEX"
    r'|\bpcat\b'                        # "PCAT"
    r'|\bmcat\b'                        # "MCAT"
    r'|\blsat\b'                        # "LSAT"
    r'|\bgmat\b'                        # "GMAT"
    r'|\bgre\b'                         # "GRE"
    r'|\btoefl\b'                       # "TOEFL"
    r'|\bielts\b'                       # "IELTS"
    r'|\bdiscovery\b'                   # "Discovery"
    r'|\bcooperative\b'                 # "Cooperative"
    r'|\bservice\s+opportunit\b'        # "Service Opportunities"
    r'|\bvolunteer\s+opportunit\b'      # "Volunteer Opportunities"
    r'|\bopportunity\s+for\b'           # "Opportunities for..."
    ,
    re.IGNORECASE
)

# Tables whose title suggests they are definitely NOT concentrations (elective pools, etc.)
_POOL_TABLE_PATTERNS = re.compile(
    r'\belective\b|\bcourse\s+list\b|\ballied\s+science\b|\bally\s+science\b'
    r'|\bsuggested\b|\bsample\b|\bplan\s+of\s+study\b|\bprint\s+option\b',
    re.IGNORECASE
)


def _is_noise(title: str) -> bool:
    """Return True if the title is a known non-concentration page element."""
    return bool(_NOISE_PATTERNS.search(title))


def _title_contains_missing_alias(title: str) -> tuple[bool, str]:
    """Return (matched, keyword) for the MISSING aliases not yet handled by scraper."""
    t = title.lower()
    for kw in MISSING_ALIASES:
        if kw in t:
            return True, kw
    return False, ''


def _title_contains_any_alias(title: str) -> tuple[bool, str]:
    t = title.lower()
    for kw in ALL_ALIAS_KEYWORDS:
        if kw in t:
            return True, kw
    return False, ''


def _is_reference_pool_title(title: str) -> bool:
    """True for titles that clearly indicate a reference-list pool table."""
    return bool(_POOL_TABLE_PATTERNS.search(title))


def fetch_page_analysis(url: str) -> dict:
    """
    Fetch the catalog page and analyze its structure for concentration signals.
    Returns a dict with:
      - extra_tables: list of tables AFTER the core requirements table and BEFORE
        the sample plan / special opportunities section, with non-trivial course content.
        Each entry: {'title': str, 'course_count': int, 'has_alias': bool, 'alias_kw': str}
      - missing_alias_headers: headers containing unhandled alias keywords
      - total_tables: total sc_courselist table count
      - has_areaheader_concentrations: True if areaheader rows inside tables contain aliases
    """
    try:
        html = fetch_html(url)
    except Exception as e:
        logger.warning(f"  Fetch failed for {url}: {e}")
        return {}

    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table', class_='sc_courselist')
    total_tables = len(tables)

    if not tables:
        return {'extra_tables': [], 'missing_alias_headers': [],
                'total_tables': 0, 'has_areaheader_concentrations': False}

    # Build a document-order position map for all relevant elements
    all_elements = list(soup.find_all(['h2', 'h3', 'h4', 'table']))
    pos_map = {id(el): i for i, el in enumerate(all_elements)}

    first_table_pos = pos_map.get(id(tables[0]), 0)

    # Find the position of the "stop" marker (sample plan / special opportunities)
    stop_pos = 999999
    for el in soup.find_all(['h2', 'h3']):
        title = el.get_text(strip=True).lower()
        if any(kw in title for kw in (
            'sample plan', 'special opportunities', 'department programs',
            'notes on the suggested', 'honors in', 'study abroad',
            'dual bachelor', 'print options', 'program of study',
        )):
            el_pos = pos_map.get(id(el), 999999)
            if el_pos > first_table_pos:
                stop_pos = min(stop_pos, el_pos)

    # Analyze each table after the first one
    extra_tables = []
    for table in tables[1:]:
        table_pos = pos_map.get(id(table), 0)
        if table_pos >= stop_pos:
            continue  # past the stop marker

        prev_h = table.find_previous(['h2', 'h3', 'h4'])
        title = prev_h.get_text(strip=True) if prev_h else ''

        if not title or _is_noise(title) or _is_reference_pool_title(title):
            continue

        # Count course rows in this table
        course_count = 0
        for tr in table.find_all('tr'):
            if 'areaheader' in (tr.get('class') or []):
                continue
            for cell in tr.find_all(['td', 'th']):
                import re as _re
                text = cell.get_text(strip=True)
                if _re.match(r'^[A-Z]{2,5}\d{2,4}[A-Z]?$', text):
                    course_count += 1
                    break

        if course_count < 1:
            # Check if the table has at least anchored course links
            course_anchors = [
                a for a in table.find_all('a')
                if re.match(r'^[A-Z]{2,5}\d{2,4}[A-Z]?$',
                            a.get_text(strip=True).replace(' ', ''))
            ]
            course_count = len(course_anchors)

        if course_count < 1:
            continue  # Skip tables with no courses

        has_alias, alias_kw = _title_contains_any_alias(title)

        extra_tables.append({
            'title': title,
            'course_count': course_count,
            'has_alias': has_alias,
            'alias_kw': alias_kw,
        })

    # Check for missing alias keywords in ALL headers (including areaheaders in tables)
    missing_alias_headers = []
    # Page-level headers
    for el in soup.find_all(['h2', 'h3', 'h4']):
        title = el.get_text(strip=True)
        matched, kw = _title_contains_missing_alias(title)
        if matched and not _is_noise(title):
            el_pos = pos_map.get(id(el), 0)
            missing_alias_headers.append({
                'title': title,
                'keyword': kw,
                'after_first_table': el_pos > first_table_pos,
                'source': 'page_header',
            })

    # Areaheader rows inside tables
    for table in tables:
        table_pos = pos_map.get(id(table), 0)
        for row in table.find_all('tr', class_='areaheader'):
            header_text = row.get_text(strip=True)
            matched, kw = _title_contains_missing_alias(header_text)
            if matched and not _is_noise(header_text):
                missing_alias_headers.append({
                    'title': header_text,
                    'keyword': kw,
                    'after_first_table': table_pos >= first_table_pos,
                    'source': 'areaheader',
                })

    # Check if any areaheader rows (in non-first tables) have concentration aliases
    has_areaheader_concentrations = False
    for table in tables[1:]:
        for row in table.find_all('tr', class_='areaheader'):
            header_text = row.get_text(strip=True)
            has_any, _ = _title_contains_any_alias(header_text)
            if has_any and not _is_noise(header_text):
                has_areaheader_concentrations = True
                break

    return {
        'extra_tables': extra_tables,
        'missing_alias_headers': missing_alias_headers,
        'total_tables': total_tables,
        'has_areaheader_concentrations': has_areaheader_concentrations,
    }


def audit_track(track_id: str, url: str, req_entry: dict) -> dict:
    """Audit a single track. Returns a result dict with verdict and details."""
    logger.info("Auditing %s ...", track_id)
    time.sleep(0.3)  # polite crawl rate

    base = req_entry.get('base_requirements', {})
    concs = req_entry.get('concentrations', {})
    existing_conc_names = [k for k in concs if k != 'None']
    choice_group_count = len(base.get('choice_groups', []))
    required_count = len(base.get('required_courses', []))
    only_none = (existing_conc_names == [])

    analysis = fetch_page_analysis(url)
    if not analysis:
        return {
            'track_id': track_id, 'url': url, 'verdict': 'FETCH_FAILED',
            'priority': 5, 'reasons': ['Could not fetch catalog page'],
            'existing_concentrations': existing_conc_names,
            'base_choice_groups': choice_group_count,
            'base_required_courses': required_count,
            'extra_tables': [], 'missing_alias_headers': [],
        }

    extra_tables = analysis.get('extra_tables', [])
    missing_alias_headers = analysis.get('missing_alias_headers', [])
    total_tables = analysis.get('total_tables', 0)
    has_areaheader_concs = analysis.get('has_areaheader_concentrations', False)

    confirmed_missing = False
    possible_missing = False
    reasons = []

    # ── Heuristic A: Multiple extra content tables after core ─────────────────
    # 2+ distinct non-noise tables after the core = very likely concentration choices
    if only_none and len(extra_tables) >= 2:
        confirmed_missing = True
        reasons.append(
            f"Catalog has {len(extra_tables)} extra content table(s) after core requirements "
            f"(titles: {[t['title'] for t in extra_tables[:5]]})"
        )

    # Even 1 extra table with an alias keyword is a strong signal
    if only_none and len(extra_tables) == 1 and extra_tables[0]['has_alias']:
        confirmed_missing = True
        reasons.append(
            f"1 extra table with alias keyword '{extra_tables[0]['alias_kw']}': "
            f"'{extra_tables[0]['title']}'"
        )

    # ── Heuristic B: Unhandled alias keywords on page ─────────────────────────
    if only_none and missing_alias_headers:
        new_aliases = [h for h in missing_alias_headers if h.get('after_first_table', False)]
        if new_aliases:
            confirmed_missing = True
            kws = list(set(h['keyword'] for h in new_aliases))
            reasons.append(
                f"Page uses unhandled alias keywords after core: {kws} "
                f"in: {[h['title'] for h in new_aliases[:3]]}"
            )

    # ── Heuristic C: Thin data + catalog complexity ──────────────────────────
    if only_none and not confirmed_missing:
        is_thin = (choice_group_count < 3)
        has_catalog_content = (total_tables >= 2)
        if is_thin and has_catalog_content:
            possible_missing = True
            reasons.append(
                f"Thin data (choice_groups={choice_group_count}, required={required_count}) "
                f"but catalog has {total_tables} tables"
            )
        elif not is_thin and len(extra_tables) == 1 and not extra_tables[0]['has_alias']:
            # 1 extra table (no alias), data looks OK → flag as possible for human review
            possible_missing = True
            reasons.append(
                f"1 extra content table after core: '{extra_tables[0]['title']}' "
                f"({extra_tables[0]['course_count']} courses)"
            )

    # ── Heuristic D: Existing concentrations partial-capture check ────────────
    if existing_conc_names:
        # Collect all alias-matched or extra-table titles on page
        page_conc_signals = [t['title'] for t in extra_tables if t['has_alias']]
        if page_conc_signals:
            unmatched = []
            for page_title in page_conc_signals:
                page_lower = page_title.lower()
                matched_any = any(
                    name.lower().replace('_', ' ') in page_lower or
                    page_lower.replace(' ', '_') in name.lower()
                    for name in existing_conc_names
                )
                if not matched_any:
                    unmatched.append(page_title)
            if unmatched:
                possible_missing = True
                reasons.append(
                    f"Has {len(existing_conc_names)} concentration(s) but {len(unmatched)} "
                    f"page section(s) don't match: {unmatched[:3]}"
                )

    if confirmed_missing:
        # Priority 1 = new alias keywords; Priority 2 = extra tables / areaheader
        priority = 1 if missing_alias_headers else 2
        verdict = 'CONFIRMED_MISSING'
    elif possible_missing:
        priority = 3
        verdict = 'POSSIBLE_MISSING'
    else:
        priority = 4
        verdict = 'LOOKS_CORRECT'

    return {
        'track_id': track_id,
        'url': url,
        'verdict': verdict,
        'priority': priority,
        'reasons': reasons,
        'existing_concentrations': existing_conc_names,
        'base_choice_groups': choice_group_count,
        'base_required_courses': required_count,
        'extra_tables': extra_tables,
        'missing_alias_headers': missing_alias_headers,
        'total_tables': total_tables,
    }


def run_audit(only_tracks: set | None = None):
    # Import TARGET_TRACKS from the pipeline script
    from scripts.pipeline.run_requirements_pipeline import TARGET_TRACKS

    with open(REQUIREMENTS_PATH) as f:
        requirements = json.load(f)

    results = []
    tracks_to_audit = {
        k: v for k, v in TARGET_TRACKS.items()
        if only_tracks is None or k in only_tracks
    }

    logger.info("Auditing %d tracks ...", len(tracks_to_audit))

    for track_id, url in tracks_to_audit.items():
        req_entry = requirements.get(track_id, {
            'base_requirements': {'required_courses': [], 'choice_groups': []},
            'concentrations': {}
        })
        result = audit_track(track_id, url, req_entry)
        results.append(result)

    # Sort by priority then track_id
    results.sort(key=lambda r: (r['priority'], r['track_id']))

    # Save
    os.makedirs(os.path.dirname(AUDIT_OUTPUT_PATH), exist_ok=True)
    tmp = AUDIT_OUTPUT_PATH + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(results, f, indent=2)
    os.replace(tmp, AUDIT_OUTPUT_PATH)

    # Print summary
    by_verdict = {}
    for r in results:
        by_verdict.setdefault(r['verdict'], []).append(r['track_id'])

    print("\n" + "=" * 70)
    print("CONCENTRATION AUDIT REPORT")
    print("=" * 70)

    for verdict in ['CONFIRMED_MISSING', 'POSSIBLE_MISSING', 'LOOKS_CORRECT', 'FETCH_FAILED']:
        tracks = by_verdict.get(verdict, [])
        if not tracks:
            continue
        print(f"\n{verdict} ({len(tracks)} tracks):")
        for tid in tracks:
            r = next(x for x in results if x['track_id'] == tid)
            extra_info = ''
            if r.get('missing_alias_headers'):
                kws = list(set(h['keyword'] for h in r['missing_alias_headers']))
                extra_info = f" [NEW ALIASES: {kws}]"
            elif r.get('extra_tables'):
                extra_info = f" [{len(r['extra_tables'])} extra table(s)]"
            print(f"  {tid}{extra_info}")
            for reason in r['reasons']:
                print(f"    -> {reason}")

    print(f"\nFull report saved to {AUDIT_OUTPUT_PATH}")
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Audit tracks for missed concentrations')
    parser.add_argument('--tracks', nargs='+', metavar='TRACK_ID',
                        help='Only audit these specific track IDs')
    args = parser.parse_args()
    run_audit(only_tracks=set(args.tracks) if args.tracks else None)
