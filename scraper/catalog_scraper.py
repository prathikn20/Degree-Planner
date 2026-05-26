import requests
import re
import json
from bs4 import BeautifulSoup


CATALOG_URL = "https://catalog.unc.edu/courses/comp/"


def fetch_html(url):
    response = requests.get(url)
    response.raise_for_status()
    return response.text


def parse_course_code(text):
    """
    Normalize 'COMP 421' or 'COMP421' to 'COMP421'.
    Returns (dept, number, full_code) or None if no match.
    """
    match = re.search(r'([A-Z]{2,4})\s*(\d{3}[A-Z]?)', text.strip())
    if match:
        dept = match.group(1)
        number = match.group(2)
        return dept, number, f"{dept}{number}"
    return None


def tokenize_course_list(text, last_dept):
    """
    Converts 'COMP 210, 211, and 301' into ['COMP210', 'COMP211', 'COMP301'].
    Handles department inheritance for bare numbers.
    """
    courses = []

    # Remove 'and' as standalone word, strip extra whitespace
    text = re.sub(r'\band\b', ',', text)
    tokens = [t.strip() for t in text.split(',') if t.strip()]

    for token in tokens:
        result = parse_course_code(token)
        if result:
            last_dept, _, full_code = result
            courses.append(full_code)
        else:
            # Bare number — inherit last department
            number_match = re.search(r'\d{3}[A-Z]?', token)
            if number_match and last_dept:
                courses.append(f"{last_dept}{number_match.group()}")

    return courses, last_dept


def parse_prerequisites(raw_text):
    """
    Converts raw prerequisite text into list-of-lists structure.
    Handles AND (semicolons) and OR (' or ') logic.
    Strips grade requirement clauses.
    """
    if not raw_text:
        return []

    # Isolate just the prerequisite portion
    match = re.search(
        r'[Pp]rerequisites?,\s*(.+?)(?:\.|$)',
        raw_text
    )
    if not match:
        return []

    prereq_text = match.group(1)

    # Strip grade requirement clauses
    prereq_text = re.sub(
        r';?\s*a grade of [^;.]+',
        '',
        prereq_text,
        flags=re.IGNORECASE
    )

    prereq_text = prereq_text.strip()

    if not prereq_text:
        return []

    result = []
    last_dept = None

    # Split on semicolons for AND groups
    and_groups = [g.strip() for g in prereq_text.split(';') if g.strip()]

    for group in and_groups:
        # Split on ' or ' for OR options within each group
        or_parts = re.split(r'\s+or\s+', group, flags=re.IGNORECASE)

        or_courses = []
        for part in or_parts:
            courses, last_dept = tokenize_course_list(part, last_dept)
            or_courses.extend(courses)

        if or_courses:
            result.append(or_courses)

    return result


def parse_credits(title_text):
    """Extract credit count from 'COMP 421. Files and Databases. 3 Credits.'"""
    match = re.search(r'(\d+)\s+[Cc]redit', title_text)
    if match:
        return int(match.group(1))
    return 3  # default to 3 if not found


def parse_course_name(title_text):
    """
    Extract name from 'COMP 421.  Files and Databases.  3 Credits.'
    Returns just the middle portion.
    """
    parts = title_text.split('.')
    # parts[0] = 'COMP 421', parts[1] = name, parts[2] = '3 Credits'
    if len(parts) >= 2:
        return parts[1].strip()
    return title_text.strip()


def scrape_catalog(url):
    html = fetch_html(url)
    soup = BeautifulSoup(html, 'html.parser')

    courses = {}
    course_blocks = soup.find_all('div', class_='courseblock')

    for block in course_blocks:
        # Extract title
        title_tag = block.find('p', class_='courseblocktitle')
        if not title_tag:
            continue

        title_text = title_tag.get_text(separator=' ', strip=True)

        # Parse course code
        code_result = parse_course_code(title_text)
        if not code_result:
            continue

        _, _, course_id = code_result
        name = parse_course_name(title_text)
        credits = parse_credits(title_text)

        # Extract prerequisite text from rules block
        prereq_text = ""
        rules_tags = block.find_all('p', class_='courseblockextra')
        for tag in rules_tags:
            text = tag.get_text(separator=' ', strip=True)
            if 'requisite' in text.lower():
                prereq_text = text
                break

        prerequisites = parse_prerequisites(prereq_text)

        courses[course_id] = {
            "name": name,
            "credits": credits,
            "prerequisites": prerequisites,
            "corequisites": [],
            "cross_listed": []
        }

    return courses


def save_raw(courses, filepath="data/raw_scraped.json"):
    with open(filepath, 'w') as f:
        json.dump(courses, f, indent=2)
    print(f"Saved {len(courses)} courses to {filepath}")


if __name__ == "__main__":
    courses = scrape_catalog(CATALOG_URL)
    save_raw(courses)