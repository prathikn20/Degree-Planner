import requests
import json
from bs4 import BeautifulSoup
import time
import re
from requests.adapters import HTTPAdapter
from urllib3.util import Retry

def fetch_html(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    session = requests.Session()
    # Retry 3 times with exponential backoff if the server is busy or drops the connection
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    session.mount('https://', HTTPAdapter(max_retries=retries))
    
    response = session.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return response.text

def extract_course_info(block):
    # 1. Grab ID and clean trailing tokens
    code_tag = block.find(class_='detail-code')
    if not code_tag:
        return None, None
    course_id = code_tag.get_text(strip=True).replace('\xa0', '').replace(' ', '').strip('.')
    
    title_tag = block.find(class_='detail-title')
    title_text = title_tag.get_text(strip=True).strip('.') if title_tag else ""
    
    block_text = block.get_text(separator=' ', strip=True)
    
    # Dynamic credit count isolation
    credit_match = re.search(r'(\d+)\s*Credit', block_text, re.IGNORECASE)
    credits = int(credit_match.group(1)) if credit_match else 3

    raw_prereq = ""
    attributes = []
    cross_listed = []

    # Upgraded cross-listing parser that remembers the last seen department prefix
    indicators = ["Previously offered as", "Same as", "Cross-listed with"]
    sentences = block_text.split('.')
    for sentence in sentences:
        if any(ind.lower() in sentence.lower() for ind in indicators):
            tokens = re.split(r'[\s,、and]+', sentence)
            last_dept = None
            for token in tokens:
                token = token.strip().upper()
                # Match standalone prefix (e.g., "STOR")
                if re.match(r'^[A-Z]{3,4}$', token):
                    last_dept = token
                # Match complete combined code (e.g., "STOR435")
                elif re.match(r'^[A-Z]{3,4}\d{3,4}$', token):
                    match = re.match(r'^([A-Z]{3,4})(\d{3,4})$', token)
                    last_dept = match.group(1)
                    normalized = f"{last_dept}{match.group(2)}"
                    if normalized != course_id and normalized not in cross_listed:
                        cross_listed.append(normalized)
                # Match standalone number *only if* we recently stored a prefix (e.g., "535")
                elif re.match(r'^\d{3,4}$', token) and last_dept:
                    normalized = f"{last_dept}{token}"
                    if normalized != course_id and normalized not in cross_listed:
                        cross_listed.append(normalized)

    # 2. Extract structural attributes and requisites block
    for tag in block.find_all(['p', 'div']):
        text = tag.get_text(separator=' ', strip=True)
        
        if text.startswith('Requisites:') and len(text) > 15:
            raw_prereq = text
            
        elif 'Gen Ed:' in text:
            parts = text.split('Gen Ed:')
            if len(parts) > 1:
                tag_name = parts[-1].split('.')[0].strip(': ')
                for token in re.split(r'[\s,]+', tag_name):
                    token = token.strip()
                    if token and token not in attributes and len(token) >= 2:
                        attributes.append(token)

    course_data = {
        "name": title_text,
        "credits": credits,
        "raw_requisite_text": raw_prereq,
        "cross_listed": cross_listed,
        "attributes": attributes
    }
    
    return course_id, course_data

def scrape_department(url):
    html = fetch_html(url)
    soup = BeautifulSoup(html, 'html.parser')
    
    courses = {}
    course_blocks = soup.find_all('div', class_='courseblock')
    
    for block in course_blocks:
        course_id, course_data = extract_course_info(block)
        if course_id:
            courses[course_id] = course_data
            
    return courses

def build_master_catalog(department_urls, output_filepath="data/course_catalog.json"):
    import os
    
    # 1. Load existing data first if the file already exists to preserve other majors
    if os.path.exists(output_filepath):
        try:
            with open(output_filepath, 'r') as f:
                master_catalog = json.load(f)
            print(f"Loaded existing master catalog. Pre-populated with {len(master_catalog)} courses.")
        except Exception as e:
            print(f"Warning: Failed to read existing catalog, starting fresh: {e}")
            master_catalog = {}
    else:
        master_catalog = {}
    
    for url in department_urls:
        print(f"Scraping {url}...")
        try:
            dept_courses = scrape_department(url)
            
            # 2. Update merges new courses into the master index without dropping existing ones
            master_catalog.update(dept_courses)
            
            with open(output_filepath, 'w') as f:
                json.dump(master_catalog, f, indent=2)
                
            print(f"Success! Master catalog now contains a total of {len(master_catalog)} courses.")
            time.sleep(1) 
            
        except Exception as e:
            print(f"CRASH on {url}: {e}")
            print("Skipping to next department...")
            continue
            
    print(f"Scrape execution complete. Total catalog library size: {len(master_catalog)}")
    return master_catalog