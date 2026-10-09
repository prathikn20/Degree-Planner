from src.planner.topological_sort import kahns_algorithm


def test_honors_prerequisite_is_scheduled_earlier():
    cat = {'CHEM102': {}, 'CHEM102H': {}, 'CHEM251': {'prerequisites': [['CHEM102']]}}
    assert kahns_algorithm(['CHEM102H', 'CHEM251'], cat) == {
        'Semester 1': ['CHEM102H'], 'Semester 2': ['CHEM251']}


def test_transitive_one_way_crosslists_get_real_code_edges():
    cat = {'TEST100': {'cross_listed': ['ALIS100']},
           'ALIS100': {'cross_listed': ['OTHR100']}, 'OTHR100': {},
           'TEST200': {'prerequisites': [['TEST100']]}}
    assert kahns_algorithm(['OTHR100', 'TEST200'], cat) == {
        'Semester 1': ['OTHR100'], 'Semester 2': ['TEST200']}
