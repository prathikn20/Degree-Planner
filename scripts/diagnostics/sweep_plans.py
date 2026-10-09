"""Phase 2: full-budget app pipeline sweep, synthetic PDFs, independent validation.

Run: python3 scripts/diagnostics/sweep_plans.py --output /tmp/degree-phase2 --workers 4
Self-checks: python3 scripts/diagnostics/sweep_plans.py --self-test
Re-run one saved input: --output NEW_DIRECTORY --manifest OLD/inputs.json --case CASE_ID
No source/data regeneration; no solver time patching in the live sweep.
"""
import argparse
import ast
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.diagnostics.plan_validator import (CatalogView, coverage, requirements_for,
    validate_plan, MAX_SEMESTER_CREDITS, MIN_NONFINAL_CREDITS, NEAR_EMPTY_COURSES)
from src.planner.graph import build_graph
from src.planner.path_generator import solve_optimal_path
from src.planner.plan_status import build_plan_report
from src.planner.requirements_checker import check_requirements, generate_slots_and_candidates
from src.planner.topological_sort import kahns_algorithm
from src.planner.transcript_parser import parse_tarheel_tracker

GEN_ED = 'UNC_General_Education'


def jsonable(obj):
    if isinstance(obj, set):
        return sorted(obj)
    raise TypeError(type(obj).__name__)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, default=jsonable) + '\n')


def load_pipeline(solver):
    """Compile the unchanged app functions, without executing Streamlit's UI body.

    Real parser, audit, generator, solver and scheduler are wired exactly as app imports.
    Only solver wrapper captures debug's extra return and passes original pair onward.
    """
    tree = ast.parse((ROOT / 'app.py').read_text(), filename='app.py')
    nodes = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in {'run_pipeline', '_req_short_desc', '_shorten_desc'}:
            nodes.append(node)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == '_GEN_ED_REQ_LABELS':
            nodes.append(node)
        elif isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == '_GEN_ED_REQ_LABELS' for t in node.targets):
            nodes.append(node)
    ns = {'_re': re, 'build_plan_report': build_plan_report, 'parse_tarheel_tracker': parse_tarheel_tracker,
          'check_requirements': check_requirements, 'generate_slots_and_candidates': generate_slots_and_candidates,
          'solve_optimal_path': solver, 'kahns_algorithm': kahns_algorithm}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(ROOT / 'app.py'), 'exec'), ns)
    return ns['run_pipeline']


def write_transcript(path, case):
    """Minimal deterministic text PDF: actual parser reads it, no parser mock.

    These are synthetic token-layout fixtures, not replicas of UNC's visual template.
    Four+ tokens per row; all text in the left half of each page.
    """
    rows = []
    for field, suffix in [('completed', 'A'), ('failed', 'F'), ('in_progress', 'Fall')]:
        for code in case.get(field, []):
            m = re.fullmatch(r'([A-Z]+)(\d.*)', code)
            if not m:
                raise ValueError(f'Cannot render course {code}')
            rows.append(f'{m[1]} {m[2]} Synthetic {suffix}')
    pages = [rows[i:i+48] for i in range(0, len(rows), 48)] or [[]]
    objects = [b'<< /Type /Catalog /Pages 2 0 R >>', b'',
               b'<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>']
    page_ids = []
    for lines in pages:
        pid = len(objects) + 1
        page_ids.append(pid)
        objects.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 3 0 R >> >> /Contents {pid+1} 0 R >>'.encode())
        commands = ['BT /F1 10 Tf 36 750 Td 14 TL']
        for line in lines:
            commands.append(f'({line}) Tj T*')
        commands.append('ET')
        content = '\n'.join(commands).encode()
        objects.append(f'<< /Length {len(content)} >>\nstream\n'.encode()+content+b'\nendstream')
    objects[1] = f'<< /Type /Pages /Kids [{" ".join(f"{n} 0 R" for n in page_ids)}] /Count {len(page_ids)} >>'.encode()
    data = bytearray(b'%PDF-1.4\n'); offsets = [0]
    for i, obj in enumerate(objects, 1):
        offsets.append(len(data)); data.extend(f'{i} 0 obj\n'.encode()+obj+b'\nendobj\n')
    xref = len(data)
    data.extend(f'xref\n0 {len(objects)+1}\n0000000000 65535 f \n'.encode())
    for offset in offsets[1:]:
        data.extend(f'{offset:010d} 00000 n \n'.encode())
    data.extend(f'trailer << /Size {len(objects)+1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n'.encode())
    Path(path).write_bytes(data)


def build_cases(catalog, requirements):
    view = CatalogView(catalog)
    majors = sorted(t for t in requirements if 'Minor' not in t and t != GEN_ED)
    cases = []
    def program(track, concentration=None):
        concs = requirements[track].get('concentrations', {})
        conc = concentration if concentration is not None else ('None' if 'None' in concs else next(iter(concs), 'None'))
        return {'track': track, 'concentration': conc}

    def course_order(c):
        m = re.search(r'\d+', c)
        return (int(m[0]) if m else 9999, c.endswith('H'), c)

    def witness(programs):
        selected = set()
        for _, _, g in requirements_for(requirements, programs):
            options = sorted(view.group_courses(g), key=course_order)
            taken, credits = [], 0
            for c in options:
                if any(view.equivalent(c, x) for x in taken):
                    continue
                taken.append(c); credits += catalog[c]['credits']
                if ((g.get('credits_required') and credits >= g['credits_required']) or
                    (not g.get('credits_required') and len(taken) >= g.get('courses_required', 1))):
                    break
            selected.update(taken)
            for c in taken:
                selected.update(lab for lecture, lab in (g.get('companion_labs') or {}).items()
                                if view.equivalent(c, lecture) and lab in catalog)
        # Supply supporting courses from the shortest catalog alternative, independently.
        def add_prereqs(c, stack):
            if c in stack:
                return
            branches = catalog.get(c, {}).get('prerequisites') or []
            if branches:
                for pre in min(branches, key=lambda p: (len(p), p)):
                    if pre in catalog and pre not in selected:
                        selected.add(pre); add_prereqs(pre, stack | {c})
        for c in list(selected):
            add_prereqs(c, set())
        return sorted(selected, key=course_order)

    def add(tracks, stage, category='single_major', concentration=None):
        programs = [program(t, concentration if i == 0 else None) for i, t in enumerate(tracks)] + [program(GEN_ED)]
        pool = witness(programs) if stage != 'incoming' else []
        completed, progress, failed = [], [], []
        if stage == 'mid_degree':
            n = max(1, len(pool)//2); completed, progress = pool[:n], pool[n:n+3]
        elif stage == 'late_degree':
            n = max(0, len(pool)-4); completed, progress = pool[:n], pool[n:n+2]
        elif stage == 'overlapping':
            completed = sorted(c for c, d in catalog.items()
                               if sum(a.startswith('FC-') for a in d.get('attributes', [])) >= 2
                               and (re.search(r'\d+', c) and int(re.search(r'\d+', c)[0]) < 300))[:14]
            completed = list(dict.fromkeys(['ENGL105', 'IDST101', 'IDST111L'] + completed))
        elif stage == 'failed_courses':
            completed = pool[:max(1,len(pool)//2)]
            preferred = [c for c in ['COMP110','MATH231','CHEM101','ENGL105'] if c in completed]
            failed = preferred[:2] or completed[:2]
            completed = [c for c in completed if c not in failed]
        elif stage == 'catalog_saturated_adversarial':
            # Deliberately unrealistic empty-plan boundary, separated in profile counts.
            completed = sorted(c for c in catalog if re.fullmatch(r'[A-Z]{2,4}\d{2,4}[A-Z0-9]{0,2}L?', c))
        case_id = f'{len(cases):03d}_{tracks[0]}_{stage}'
        cases.append({'id': case_id, 'profile': stage, 'category': category,
                      'programs': programs, 'completed': completed, 'in_progress': progress,
                      'failed': failed, 'planned_courses': [], 'avoid_courses': [],
                      'remaining_semesters': 8, 'gen_ed_included': True})
    for major in majors:
        add([major], 'incoming')
    focus = ['Computer_Science_BS','Data_Science_BS','Biomedical_Engineering_BS',
             'Latin_American_Studies_BA','Biology_BS','Mathematics_BS','Economics_BS','Physics_BS']
    for track in focus:
        if track not in requirements:
            raise ValueError(track)
        for stage in ['mid_degree','late_degree','overlapping','failed_courses']:
            add([track], stage)
    combinations = [(['Computer_Science_BS','Data_Science_BS'],'double_major'),
                    (['Biology_BS','Biomedical_Engineering_BS'],'double_major'),
                    (['Latin_American_Studies_BA','Economics_BS'],'double_major'),
                    (['Computer_Science_BS','Mathematics_Minor'],'major_minor'),
                    (['Physics_BS','Computer_Science_Minor'],'major_minor'),
                    (['Latin_American_Studies_BA','Spanish_for_the_Professions_Minor'],'major_minor')]
    for tracks, category in combinations:
        for stage in ['incoming','mid_degree','late_degree']:
            add(tracks, stage, category)
    for conc in requirements['Biomedical_Engineering_BS']['concentrations']:
        if conc != 'None':
            add(['Biomedical_Engineering_BS'],'late_degree','concentration',conc)
    add(['Computer_Science_BS'],'catalog_saturated_adversarial')
    return cases


def run_case(case, output_dir):
    started = time.monotonic()
    catalog = json.loads((ROOT/'data/course_catalog.json').read_text())
    requirements = json.loads((ROOT/'data/degree_requirements.json').read_text())
    diagnostics = {}
    def capture_solver(**kwargs):
        path, mapping, info = solve_optimal_path(**kwargs, debug=True)
        diagnostics.update(info)
        return path, mapping
    log = io.StringIO()
    pdf = Path(output_dir)/'transcripts'/f"{case['id']}.pdf"
    record = {'input': case, 'transcript': str(pdf), 'semester_path_hidden_in_UI': True}
    stage = 'fixture'
    try:
        write_transcript(pdf, case)
        stage = 'pipeline'
        with contextlib.redirect_stdout(log):
            result = load_pipeline(capture_solver)(str(pdf), case['programs'], catalog, requirements,
                build_graph(catalog), planned_courses=case['planned_courses'], avoid_courses=case['avoid_courses'])
            stage = 'validation'
            validation = validate_plan(case, result, catalog, requirements, diagnostics)
            opinions = []
            # Show both the app's F-inclusive interpretation and known passing transcript facts.
            for label, prior in [('parsed_assumed_plus_path', result['completed']+result['in_progress']),
                                 ('passing_input_plus_path', case['completed']+case['in_progress'])]:
                for p in case['programs']:
                    audit = check_requirements(requirements, catalog, prior+result['path'],
                        track_id=p['track'], concentration_id=p['concentration'])
                    opinions.append({'label': 'NOT INDEPENDENT', 'input_basis': label,
                                     'program': p, 'results': audit})
        record.update({'output': result, 'validation': validation, 'solver_debug_NOT_INDEPENDENT': diagnostics,
                       'post_plan_audits_NOT_INDEPENDENT': opinions})
    except Exception:
        record.update({'exception': traceback.format_exc(), 'validation': {'events': [
            {'severity':'HARD','type':{'fixture':'INPUT_FIXTURE_ERROR','pipeline':'PIPELINE_EXCEPTION','validation':'VALIDATOR_EXCEPTION'}[stage],'traceback':traceback.format_exc()}]}})
    record['elapsed_seconds'] = round(time.monotonic()-started,3)
    record['solver_stdout'] = log.getvalue()
    write_json(Path(output_dir)/'cases'/f"{case['id']}.json",record)
    return record


def summarize(records):
    summary = {'cases': len(records), 'hard_events': 0, 'cases_with_hard_events': 0,
               'by_type': {}, 'by_profile': {}, 'by_category': {},
               'reuse_eligible_courses': 0, 'reuse_assigned_canons_NOT_INDEPENDENT': 0}
    types = defaultdict(lambda: {'events':0,'cases':0,'severity':None})
    for r in records:
        events = r['validation']['events']; hard = [e for e in events if e['severity']=='HARD']
        summary['hard_events'] += len(hard); summary['cases_with_hard_events'] += bool(hard)
        summary['reuse_eligible_courses'] += len(r['validation'].get('reuse_eligible',[]))
        summary['reuse_assigned_canons_NOT_INDEPENDENT'] += len(r['validation'].get('reuse_assigned_NOT_INDEPENDENT',[]))
        for e in events:
            types[e['type']]['events'] += 1; types[e['type']]['severity'] = e['severity']
        for t in {e['type'] for e in events}:
            types[t]['cases'] += 1
        for field, key in [('by_profile','profile'),('by_category','category')]:
            bucket = summary[field].setdefault(r['input'][key], {'cases':0,'hard_events':0,'cases_with_hard_events':0,'by_type':{}})
            bucket['cases'] += 1; bucket['hard_events'] += len(hard); bucket['cases_with_hard_events'] += bool(hard)
            for e in events:
                bucket['by_type'][e['type']] = bucket['by_type'].get(e['type'],0)+1
    summary['by_type'] = dict(types)
    return summary


def self_test():
    """Diagnostic fixtures only; does not fix or regenerate planner data."""
    from unittest.mock import patch
    def course(prereqs=None, **kw):
        return {'credits':3,'prerequisites':prereqs or [],'cross_listed':[], 'attributes':[], 'corequisites':[], **kw}
    cat = {'TEST100':course(), 'TEST100H':course(), 'ALIS100':course(cross_listed=['TEST100']),
           'TEST200':course([['TEST100'],['TEST150']]), 'TEST150':course(),
           'TEST300':course([['permission of instructor']]), 'TEST400':course([['TEST200']])}
    req = {'P':{'base_requirements':{'required_courses':['TEST200'],'choice_groups':[]}}}
    case = {'programs':[{'track':'P','concentration':'None'}], 'completed':['TEST100H'], 'in_progress':[], 'failed':[]}
    def output(path, semesters):
        return {'path':path,'semester_path':semesters,'completed':case['completed'], 'in_progress':[], 'audit':{}}
    good = validate_plan(case,output(['TEST200'],{'Semester 1':['TEST200']}),cat,req,{})
    assert not [e for e in good['events'] if e['severity']=='HARD']
    case['completed'] = ['ALIS100']
    assert not [e for e in validate_plan(case,output(['TEST200'],{'Semester 1':['TEST200']}),cat,req,{})['events'] if e['severity']=='HARD']
    case['completed'] = []
    bad = validate_plan(case,output(['TEST100','TEST200','TEST300','TEST400'],
        {'Semester 1':['TEST100','TEST200','TEST300'],'Semester 2':['TEST400']}),cat,req,{})
    assert sum(e['type']=='PREREQUISITE_NOT_EARLIER' for e in bad['events']) == 1
    assert any(e['type']=='PREREQUISITE_NONCOURSE' and e['severity']=='SOFT' for e in bad['events'])
    assert any(e['type']=='SEMESTER_UNDER_FULL_TIME' for e in bad['events'])
    overload = validate_plan(case,output(list(cat),{'Semester 1':list(cat)}),cat,req,{})
    assert any(e['type']=='SEMESTER_OVERLOAD' for e in overload['events'])
    # Unknown real codes cannot supply degree coverage.
    unknown = validate_plan(case,output(['FAKE100'],{'Semester 1':['FAKE100']}),cat,req,{})
    assert {'UNKNOWN_PLANNED_COURSE','REQUIREMENT_UNCOVERED'} <= {e['type'] for e in unknown['events']}
    # Debug must remain observational under the same deterministic clock.
    def fast_clock():
        calls = iter([0]+[100]*10000)
        return lambda: next(calls)
    slots = [{'slot_id':'P__a','program_id':'P','type':'single','candidates':['CANON_TEST100'],'is_core':True},
             {'slot_id':'P__missing','program_id':'P','type':'single','candidates':[]},
             {'slot_id':'P__optional','program_id':'P','type':'single','candidates':[],'is_optional':True}]
    cc = {'CANON_TEST100':{'credits':3,'depth':1,'original_courses':['TEST100']}}
    args = dict(slots=slots,canon_catalog=cc,credit_ledger={},macro_bindings={},blacklist={})
    with patch('time.time',side_effect=fast_clock()):
        new = solve_optimal_path(**args)
    with patch('time.time',side_effect=fast_clock()):
        dbg = solve_optimal_path(**args,debug=True)
    assert new == dbg[:2]
    assert [u['optional'] for u in dbg[2]['unfilled_slots']] == [False,True]
    assert dbg[2]['penalties']['by_constraint']['slot_sufficiency'] > 10000
    # Macro/filter branch absent in live data: exercise it without modifying catalog JSON.
    macro_slots = [{'slot_id':'P__macro','program_id':'P','type':'single','candidates':['MACRO_TEST100_AND_TEST100L']}]
    with patch('time.time',side_effect=fast_clock()):
        macro = solve_optimal_path(macro_slots,{'MACRO_TEST100_AND_TEST100L':{'original_courses':['TEST100'],'credits':3,'depth':1}},
                                  {},{'MACRO_TEST100_AND_TEST100L':['TEST100','TEST100L']},{},debug=True)
    assert macro[2]['dropped_courses'] == ['TEST100L']
    # Parsed F regression uses a real generated PDF.
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        pdf = Path(tmp)/'failed.pdf'
        write_transcript(pdf,{'completed':['TEST100'],'failed':['TEST200'],'in_progress':['TEST300']})
        parsed = parse_tarheel_tracker(pdf)
        assert parsed['completed']==['TEST100'] and parsed['in_progress']==['TEST300']
    print('SELF-TEST PASS: prerequisites/aliases/SOFT/loads/coverage/debug parity/macro drop/F parsing')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    parser.add_argument('--workers',type=int,default=4)
    parser.add_argument('--manifest',type=Path)
    parser.add_argument('--case')
    parser.add_argument('--limit',type=int)
    parser.add_argument('--self-test',action='store_true')
    args = parser.parse_args()
    if args.self_test:
        self_test(); return
    if not args.output:
        parser.error('--output required')
    os.chdir(ROOT)
    args.output = args.output.resolve()
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'transcripts').mkdir(); (args.output/'cases').mkdir()
    catalog = json.loads((ROOT/'data/course_catalog.json').read_text())
    requirements = json.loads((ROOT/'data/degree_requirements.json').read_text())
    cases = json.loads(args.manifest.read_text()) if args.manifest else build_cases(catalog,requirements)
    if args.case:
        cases = [c for c in cases if c['id']==args.case]
        if not cases:
            raise ValueError('Unknown case ID')
    if args.limit:
        cases = cases[:args.limit]
    write_json(args.output/'inputs.json',cases)
    files = ['app.py','src/planner/path_generator.py','src/planner/requirements_checker.py',
             'src/planner/topological_sort.py','src/planner/transcript_parser.py',
             'src/planner/policy.py','src/planner/equivalence.py','src/planner/plan_status.py',
             'data/course_catalog.json','data/degree_requirements.json',
             'scripts/diagnostics/plan_validator.py','scripts/diagnostics/sweep_plans.py']
    write_json(args.output/'manifest.json',{'source_sha256':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files},
        'python':sys.version,'workers':args.workers,'solver_budget_seconds':15,'remaining_semesters':8,
        'min_nonfinal_credits':MIN_NONFINAL_CREDITS,'max_credits':MAX_SEMESTER_CREDITS,
        'near_empty_courses':NEAR_EMPTY_COURSES,'semester_path_hidden_in_UI':True,
        'pipeline':'unchanged AST-compiled app.run_pipeline; real synthetic PDF parser; debug wrapper only',
        'noncourse_prerequisite_tokens_in_live_catalog':sorted({p for d in catalog.values() for branch in d.get('prerequisites',[]) for p in branch if not re.fullmatch(r'[A-Z]{2,5}\d{2,4}[A-Z0-9]*',p)}),
        'live_corequisite_courses':sum(bool(d.get('corequisites')) for d in catalog.values())})
    records = []
    with ProcessPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(run_case,case,str(args.output)):case for case in cases}
        for future in as_completed(futures):
            r = future.result(); records.append(r)
            hard = sum(e['severity']=='HARD' for e in r['validation']['events'])
            print(f"{len(records)}/{len(cases)} {r['input']['id']}: {hard} hard events, {r['elapsed_seconds']}s",flush=True)
            write_json(args.output/'summary.json',summarize(records))
    print(json.dumps(summarize(records),indent=2),flush=True)


if __name__ == '__main__':
    main()
