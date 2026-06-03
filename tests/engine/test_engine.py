import os
import json
import time

# Import the new architecture
from src.planner.requirements_checker import generate_slots_and_candidates
from src.planner.path_generator import solve_optimal_path

def load_local_data():
    """Attempt to load the real data, or fail gracefully."""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    catalog_path = os.path.join(base_dir, "data", "course_catalog.json")
    req_path = os.path.join(base_dir, "data", "degree_requirements.json")
    
    try:
        with open(catalog_path, "r") as f:
            catalog = json.load(f)
        with open(req_path, "r") as f:
            requirements = json.load(f)
        return catalog, requirements
    except FileNotFoundError as e:
        print(f"[!] Critical Error: Could not find data files at {base_dir}/data/")
        print(e)
        exit(1)

def run_diagnostics():
    print("="*60)
    print("🚀 INITIATING DEGREE PLANNER ENGINE STRESS TEST")
    print("="*60)
    
    catalog, requirements = load_local_data()
    print(f"[+] Loaded {len(catalog)} courses from catalog.")
    print(f"[+] Loaded {len(requirements)} program tracks.")

    # STRESS TEST SETUP: Massive Search Space + High Overlap
    majors_to_check = ["Computer_Science_BS", "Data_Science_Minor"] 
    assumed_courses = [] # Blank transcript forces the engine to solve everything
    
    print("\n" + "-"*60)
    print("STAGE 1: DATA LAYER & CANONICAL MASKING")
    print("-"*60)
    
    t0 = time.time()
    slots, canon_catalog, credit_ledger, macro_bindings, blacklist = generate_slots_and_candidates(
        requirements=requirements,
        catalog=catalog,
        majors_to_check=majors_to_check,
        completed_courses=assumed_courses
    )
    t1 = time.time()
    
    print(f"Data Layer Execution Time: {t1 - t0:.4f} seconds")
    print(f"Generated Demand Slots: {len(slots)}")
    print(f"Credit Ledger Entries: {len(credit_ledger)}")
    print(f"Atomic Macro-Nodes Bound: {len(macro_bindings)}")
    print(f"Anti-Requisite Blacklist Entries: {len(blacklist)}")
    
    if not slots:
        print("[!] No slots generated. Check if Track IDs match the JSON exactly.")
        return

    print("\n" + "-"*60)
    print("STAGE 2: THE 30-SECOND ILS ENGINE (MATH STRESS TEST)")
    print("-"*60)
    print("Engine is running. Please wait up to 30 seconds...")
    
    t_start_math = time.time()
    best_path, course_to_slots_map = solve_optimal_path(
        slots=slots, 
        canon_catalog=canon_catalog, 
        credit_ledger=credit_ledger,
        macro_bindings=macro_bindings,
        blacklist=blacklist,
        remaining_semesters=8
    )
    t_end_math = time.time()
    
    print(f"\n[SUCCESS] Engine completed in {t_end_math - t_start_math:.2f} seconds.")
    print(f"Total Unique Courses in Optimal Path: {len(best_path)}")
    
    print("\n--- Final Recommended Course List ---")
    print(sorted(best_path))
    
    print("\n--- Sample Slot Fulfillment Map (First 5) ---")
    sample_keys = list(course_to_slots_map.keys())[:5]
    for k in sample_keys:
        print(f"  {k} -> Fulfills: {course_to_slots_map[k]}")
        
    print("\n" + "="*60)
    print("END OF DIAGNOSTIC RUN")
    print("="*60)

if __name__ == "__main__":
    run_diagnostics()