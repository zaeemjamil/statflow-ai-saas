"""
Analytics package — structure only in Phase 3.

Every module here defines the *function signatures* Phase 7 will
implement (Phase 1 audit §7/§9: generalized versions of StatFlow's
cleaning/stats/correlation/regression logic, driven by profiler-detected
columns rather than hardcoded names). None of them compute anything yet.

Parameters are typed `Any` rather than `pandas.DataFrame` deliberately:
pandas isn't a dependency of the project until Phase 7 actually needs it,
so Phase 3 doesn't add a library it can't yet exercise. Phase 7 tightens
these signatures to real pandas/numpy/scipy/statsmodels types as it fills
each function in.
"""
