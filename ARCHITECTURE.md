# System Architecture & Engineering Decisions for UNC Degree Planner

## System Overview

### Project Description
The UNC Degree Planner is a bounded-time Constraint Satisfaction Problem (CSP) solver wrapped in a reactive, Streamlit based and hosted UI. It's designed to optimize a UNC Chapel Hill student's courses that they need to graduate when they upload their Tar Heel Tracker, the native accessible unofficial transcript. 

### Core Tech Stack
* **Frontend & UI:** Streamlit, Graphviz (for dynamic prerequisite tree rendering)
* **AI & Data Structuring:** Ollama (Local LLM orchestration: Qwen2.5 14B), Pydantic (Strict JSON schema validation and AST enforcement)
* **Data Extraction & ETL:** pdfplumber (Spatial PDF parsing), BeautifulSoup4 / Requests (HTML DOM parsing and web scraping)
* **Backend & Optimization Engine:** Pure Python 3.11+ Standard Library (The constraint solver and graph algorithms rely entirely on native data structures like `defaultdict`, `deque`, and sets, rather than relying on heavy external math libraries).
* **Testing & QA:** Pytest, Unittest.mock (For UI state isolation and exhaustive matrix testing)

---

## Core Architectural Domains

### Optimization Engine (Constraint Satisfaction)
Finding the best courses to take is an NP-Hard problem because of the restrictions on what courses can fulfill a requirement and how to effectively double count within the constraints of the policies. A brute force algorithm that uses backtracking would essentially take hours for a problem like this. That's why a hybrid Greedy + Iterated Localized Search algorithm was the better architecture. 

* **Phase 1: The Greedy Draft**
  * This part of the logical engine uses the Minimum Remaining Values heuristic to fulfill whatever requirements have the fewest options. Most of the times it means the course is necessary or there aren't many other choices, essentially drafting a baseline schedule.
* **Phase 2: ILS**
  * The algorithm is designed to reduce the points of a schedule with different things contributing to the points. Suboptimal courses like internships, 1-credit courses, or honors thesis (courses that most of the time students don't take), or policy violations are marked as point penalties on the schedule. The points are assigned in a way to account for edge cases as well, causing the algorithm to mutate the schedule in a desired and optimal way.
  * **Handling Double-Counting:** The algorithm assigns a massive penalty for exceeding the maximum amount of double-count permitted by the policies (>50% of core courses are double-counted). This causes the algorithm to rather take more courses than try and double count. 

### Graph Theory & Course Sequencing
The logic uses Kahn's algorithm on a Directed Acyclic Graph (DAG) to mathematically guarantee that the path is sequenceable without missing prerequisites. 

* **Subgraph Extraction (Performance):**
  * Loading and working with all the courses in the catalog would take too long as opposed to just loading the subset and achieving sub-second validation. 
* **DNF Prerequisite Flattening:**
  * The graph naturally resolves nested "OR" prerequisites by flattening them strictly based on the courses the CSP has already deterministically selected. 
* **Defensive Cycle Detection:**
  * By tracking the in-degrees of courses, how many prerequisites are left, the function has built-in cycle tracking where it checks if courses are still accessible after the queue is empty. The algorithm then stores those courses and prints them so the developer can fix the problems with those courses. 

### The ETL & LLM Parsing Pipeline
The path generator and other logical functions require strictly formatted data that can be computed on mathematically. Simple web scraping would just result in messy data since no amount of regex could account for how unstructured the data was, especially for the degree requirements where each degree had basically a different structure.  

* **Abstract Syntax Trees (AST) vs. Flat Arrays:**
  * The LLM model would exhibit chatty behavior on the first few runs so I used pydantic to force the model to output strict JSON formatted data. It outputs ASTs instead of flat arrays since the second tended to cause combinatorial explosions. 
* **Requirements Data Pipeline:**
  * The degree requirements just couldn't be converted from html to data with any of the methods I tried. I didn't want to use an llm API and couldn't run heavier models locally on my laptop so I designed a prompt to leverage my Claude Pro subscription to have Claude Code manually parse the data and extract relevant information. 

### Frontend State & User Experience
Because the backend takes a while to run (15 - sec usually for the ILS) and Streamlit's UI is reactive, refreshing for each change I had to manage the state for the numerous functions part of the UI. They hold their state till the user hits a button which causes the refresh. 

* **The "Buffered State" Architecture:**
  * I used `st.session_state` to decouple the dropdown inputs from the backend engine via an explicit "Apply" button. This way the UX is much smoother and requiring a refresh only when the user wants to. 
* **Spatial PDF Parsing:**
  * `pdfplumber` avoids column-bleeding issues of standard text extractors by geometrically cropping the page and grouping text by Y-axis tolerance.

---

## Future Considerations
* **Parallelization for Better Global Optimum**
    * I plan to implement a Multi-Start Iterated Local Search using Python's multiprocessing library. By generating multiple, slightly different drafts through the Greedy Algorithm and optimizing them concurrently across different CPU cores, the search engine could explore a vastly larger search space. The current method will be kept as a backup if that method causes worse schedules due to the randomization. This would yield a closer approximation of the global optimum without extending the 15-second wall-clock wait time for the user and ensuring current functionality.
* **Decoupling the Architecture**
    * I plan to eventually migrate the app from Streamlit. I want to build a custom Next.js/React frontend communicating with a FastAPI Python backend. Heavy ILS compute tasks would be offloaded to a background task queue (like Celery/Redis), allowing the frontend to remain instantly responsive and display WebSockets-driven progress bars while the engine runs.
* **Manual Override + Community Data-Correction Loop**
    * I plan to implement a way for the User to edit the requirements because the HTML is incredibly volatile, making web scraping prone to errors. This would allow them to still make use of the optimization engine effectively. I would also log these overrides to a central database where I could manually review and implement them, eventually implementing functions checking the validity of the overrides and auto changing the data. 
* **Semester Planning**
    * This would be a way for the users to not just download the courses needed but to plan the rest of their college career out and download a CSV of that plan.