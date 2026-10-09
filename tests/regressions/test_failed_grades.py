from contextlib import nullcontext
from types import SimpleNamespace

from src.planner import transcript_parser as parser
from src.planner.requirements_checker import generate_slots_and_candidates


def parse_rows(monkeypatch, rows):
    monkeypatch.setattr(parser.pdfplumber, 'open', lambda _: nullcontext(SimpleNamespace(pages=[rows])))
    monkeypatch.setattr(parser, '_column_rows', lambda page: page)
    return parser.parse_tarheel_tracker('synthetic')


def test_failed_course_remains_a_requirement_and_retakes_win(monkeypatch):
    failed = ['COMP', '110', 'Intro', 'F']
    passed = ['COMP', '110', 'Intro', 'A']
    parsed = parse_rows(monkeypatch, [failed])
    assert parsed['completed'] == []
    cat = {'COMP110': {'credits': 3, 'prerequisites': [], 'cross_listed': []}}
    req = {'P': {'base_requirements': {'required_courses': ['COMP110']}}}
    slots, *_ = generate_slots_and_candidates(req, cat, ['P'], parsed['completed'])
    assert len(slots) == 1
    assert parse_rows(monkeypatch, [failed, passed])['completed'] == ['COMP110']
    assert parse_rows(monkeypatch, [passed, failed])['completed'] == ['COMP110']


def test_failed_attempt_does_not_hide_in_progress_retake(monkeypatch):
    parsed = parse_rows(monkeypatch, [['MATH', '231', 'Calc', 'F'], ['MATH', '231', 'Calc', 'Fall']])
    assert parsed['completed'] == []
    assert parsed['in_progress'] == ['MATH231']
    assert parsed['course_terms'] == {'MATH231': 'Fall'}
