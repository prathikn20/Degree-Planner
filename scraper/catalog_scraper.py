import requests
import json
from bs4 import BeautifulSoup
import time

def fetch_html(url):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.text

def extract_course_info(block):
    # 1. Grab ID and strip the trailing period
    code_tag = block.find(class_='detail-code')
    if not code_tag:
        return None, None
    course_id = code_tag.get_text(strip=True).replace('\xa0', '').replace(' ', '').strip('.')
    
    # Grab Title and strip its trailing period too
    title_tag = block.find(class_='detail-title')
    title_text = title_tag.get_text(strip=True).strip('.') if title_tag else ""
    
    raw_prereq = ""
    attributes = []

    # 2. Iterate only over higher-level blocks (p and div) to get the full text sentences
    for tag in block.find_all(['p', 'div']):
        text = tag.get_text(separator=' ', strip=True)
        
        # Requisites: Must be longer than 15 chars so we don't just grab the bold label
        if text.startswith('Requisites:') and len(text) > 15:
            raw_prereq = text
            
        # 3. Gen Eds: Cleaner splitting to avoid empty strings
        elif 'Gen Ed:' in text:
            # Splits "IDEAs in Action Gen Ed: FC-VALUES. Grading..."
            parts = text.split('Gen Ed:')
            if len(parts) > 1:
                # Grabs the text right after the colon, stops at the first period
                tag_name = parts[-1].split('.')[0].strip(': ')
                if tag_name and tag_name not in attributes:
                    attributes.append(tag_name)

    course_data = {
        "name": title_text,
        "raw_requisite_text": raw_prereq,
        "attributes": attributes
    }
    
    return course_id, course_data

def scrape_department(url):
    """Scrapes a single department URL and returns a dictionary of courses."""
    html = fetch_html(url)
    soup = BeautifulSoup(html, 'html.parser')
    
    courses = {}
    course_blocks = soup.find_all('div', class_='courseblock')
    
    for block in course_blocks:
        course_id, course_data = extract_course_info(block)
        if course_id:
            courses[course_id] = course_data
            
    return courses

def build_master_catalog(department_urls, output_filepath="data/master_catalog.json"):
    master_catalog = {}
    
    for url in department_urls:
        print(f"Scraping {url}...")
        try:
            # Scrape the individual department
            dept_courses = scrape_department(url)
            
            # Update our master dictionary
            master_catalog.update(dept_courses)
            
            # Checkpoint: Save to disk immediately after success
            with open(output_filepath, 'w') as f:
                json.dump(master_catalog, f, indent=2)
                
            print(f"Success! Master catalog now has {len(master_catalog)} courses.")
            
            # Be nice to the university's servers so we don't get IP banned
            time.sleep(1) 
            
        except Exception as e:
            # Crash handling logic: Log the error and move to the next URL
            print(f"CRASH on {url}: {e}")
            print("Skipping to next department...")
            continue
            
    print(f"Scrape complete. Total courses saved: {len(master_catalog)}")
    return master_catalog