"""Transitive, symmetric cross-list and honors/base course identities.

Real catalog codes are retained by callers for display. This production helper
is implemented separately from the diagnostic validator's equivalence oracle.
"""


class CourseEquivalence:
    def __init__(self, catalog):
        self._parent = {}
        for course, data in catalog.items():
            self.key(course)
            for alias in data.get('cross_listed') or []:
                self._join(course, alias)
            if course.endswith('H') and course[-2:-1].isdigit():
                self._join(course, course[:-1])

    def key(self, course):
        self._parent.setdefault(course, course)
        root = course
        while root != self._parent[root]:
            root = self._parent[root]
        while course != root:
            parent = self._parent[course]
            self._parent[course] = root
            course = parent
        return root

    def _join(self, a, b):
        a, b = self.key(a), self.key(b)
        if a != b:
            self._parent[max(a, b)] = min(a, b)

    def equivalent(self, a, b):
        return self.key(a) == self.key(b)
