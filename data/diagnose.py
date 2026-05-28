# run this in your project directory as: python3 diagnose.py
import requests
from bs4 import BeautifulSoup

URLS = {
    "COMP_BS": "https://catalog.unc.edu/undergraduate/programs-study/computer-science-major-bs/",
    "COMP_BA": "https://catalog.unc.edu/undergraduate/programs-study/computer-science-major-ba/",
    "DATA_BS": "https://catalog.unc.edu/undergraduate/programs-study/data-science-major-bs/",
}

headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'}

for track, url in URLS.items():
    print(f"\n=== {track} ===")
    html = requests.get(url, headers=headers, timeout=15).text
    soup = BeautifulSoup(html, 'html.parser')
    tables = soup.find_all('table', class_='sc_courselist')
    print(f"Total tables: {len(tables)}")
    for i, table in enumerate(tables):
        prev_h = table.find_previous(['h2', 'h3', 'h4'])
        heading = prev_h.get_text(strip=True) if prev_h else "NONE"
        areaheaders = [
            r.get_text(strip=True) 
            for r in table.find_all('tr') 
            if 'areaheader' in (r.get('class') or [])
        ]
        print(f"  Table {i}: heading='{heading}' | areaheaders={areaheaders}")