"""Editable planning policy; all PROVISIONAL rules live here.

Change settings here without editing planning algorithms. These values are
Prathik's interim decisions, not independently verified UNC policy. The shared completed-work allocator consumes the reuse settings. Load
scheduling consumes the reserved load settings in Wave 4.
"""
# PROVISIONAL: final semesters are exempt from this minimum.
MIN_NONFINAL_CREDITS = 12
MAX_SEMESTER_CREDITS = 18

# PROVISIONAL: failed attempts give no completion credit; passing retakes prevail.
FAILED_GRADES = frozenset({'F'})
PASSING_SUPERSEDES_FAILURE = True

# PROVISIONAL: same-program assignments remain exclusive except explicit conflicts.
PROHIBIT_SAME_PROGRAM_REUSE = True

# PROVISIONAL: shared allocator inputs, mirroring the current audit reuse pools.
# A consumed course can be reused once in one of the listed destination classes.
# RESEARCH, COMM and ordinary choice groups have no additional reuse pool.
COMPLETED_REUSE_POOLS = {
    'FY-SEMINAR': ('FC',),
    'FAD': ('FC',),
    'INTERDISCIPLINARY': ('FC',),
    'FC': ('FAD', 'INTERDISCIPLINARY'),
    'required': ('choice',),
}
REUSE_COMPLETED_ACROSS_PROGRAMS = True
