"""
Phase 9 (AI Analyst) - Stage 1: the evidence layer only.

Everything in this package is pure and local: no AI provider call, no API
key, no network, no database write. It answers three questions that must be
settled *before* any AI is ever called:

* ``eligibility`` - is this analysis complete enough to be explained at all?
* ``evidence``    - exactly which facts would the AI be allowed to see
                    (built from the persisted analysis, size-bounded, and
                    free of raw rows)?
* ``fingerprint`` - a stable hash of that evidence, so a later stage can tell
                    whether a stored explanation is still current.

Column names and text inside the evidence come from the user's file and must
always be treated as data, never as instructions.
"""
