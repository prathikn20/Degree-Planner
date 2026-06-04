"""
One-shot post-processor: ensures all I-suffix / IDST courses have the
INTERDISCIPLINARY attribute and that every course listed on the official
IDST website exists in the catalog.

Run after run_catalog_pipeline.py completes:
    python scripts/fix_interdisciplinary_catalog.py
"""
import json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

CATALOG_PATH = "data/course_catalog.json"

_IDST_WEBSITE_COURSES = {
    'AMST101I', 'AMST217I', 'ANTH210I', 'ASIA125I', 'ASIA426I', 'ASIA447I',
    'DATA420I', 'ECON573I', 'EDUC321I', 'ENEC202I', 'ENGL217I', 'EXSS321I',
    'GEOG117I', 'GEOG117H', 'GEOG210I', 'GEOG447I', 'GERM416I', 'GLBL210I',
    'GSLL275I', 'HIST210I', 'HIST217I', 'ITAL325I', 'JWST100I', 'LING545I',
    'LTAM117I', 'LTAM117H', 'MHCH150I', 'MUSC51I', 'PHYS51I', 'PHYS150I',
    'POLI210I', 'PORT270I', 'RELI123I', 'STOR323I', 'WGST111I', 'WGST111H',
    'WGST117I', 'WGST117H', 'WGST262I', 'WGST447I',
}
_H_CROSS = {
    'GEOG117H': 'GEOG117I', 'LTAM117H': 'LTAM117I',
    'WGST111H': 'WGST111I', 'WGST117H': 'WGST117I',
}

def main():
    with open(CATALOG_PATH) as f:
        catalog = json.load(f)
    print(f"Loaded {len(catalog)} courses.")

    changed = 0

    # Tag all I-suffix and IDST courses
    for cid, data in catalog.items():
        is_i = (cid.endswith('I') and len(cid) > 1 and cid[-2].isdigit()) or cid.startswith('IDST')
        if is_i and 'INTERDISCIPLINARY' not in data.get('attributes', []):
            data.setdefault('attributes', []).append('INTERDISCIPLINARY')
            changed += 1

    # Ensure IDST website courses exist
    for cid in _IDST_WEBSITE_COURSES:
        if cid not in catalog:
            catalog[cid] = {
                'name': f'Interdisciplinary Perspectives ({cid})',
                'credits': 3.0,
                'prerequisites': [], 'corequisites': [],
                'cross_listed': [_H_CROSS[cid]] if cid in _H_CROSS else [],
                'attributes': ['INTERDISCIPLINARY'],
            }
            changed += 1
            print(f"  Added missing: {cid}")
        else:
            attrs = catalog[cid].setdefault('attributes', [])
            if 'INTERDISCIPLINARY' not in attrs:
                attrs.append('INTERDISCIPLINARY')
                changed += 1

    tmp = CATALOG_PATH + '.tmp'
    with open(tmp, 'w') as f:
        json.dump(catalog, f, indent=2)
    os.replace(tmp, CATALOG_PATH)
    print(f"Done. {changed} changes applied. Final catalog: {len(catalog)} courses.")

if __name__ == '__main__':
    main()
