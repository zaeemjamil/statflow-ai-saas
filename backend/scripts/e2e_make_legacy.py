"""Turn a project's stored file profile into what a PRE-Stage-3 upload stored (test helper).

    DATABASE_URL=... python scripts/e2e_make_legacy.py <project_id> <path-to-the-uploaded-csv>

Pre-Stage-3 code parsed with pandas' stock missing-value tokens (so the text "NA" was a missing
value) and stored a profile with no `import_notes`. This rewrites `files.profile` of that project to
exactly that shape, from the same CSV, so the UI/API can be exercised against a legacy-shaped
project on a real database. It is a simulation: no pre-Stage-3 build was available to create a
real one.
"""

from __future__ import annotations

import io
import json
import os
import sys
import uuid

import pandas as pd
from sqlalchemy import create_engine, text

from app.analytics.profiling import profile_dataset


def main() -> None:
    project_id, csv_path = uuid.UUID(sys.argv[1]), sys.argv[2]
    with open(csv_path, "rb") as fh:
        legacy = profile_dataset(pd.read_csv(io.BytesIO(fh.read()), index_col=False))
    assert "import_notes" not in legacy
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.begin() as conn:
        result = conn.execute(
            text("UPDATE files SET profile = CAST(:p AS jsonb) WHERE project_id = :pid"),
            {"p": json.dumps(legacy), "pid": str(project_id)},
        )
    missing = legacy["total_missing_values"]
    print(f"legacy profile written to {result.rowcount} file row(s); total_missing={missing}")


if __name__ == "__main__":
    main()
