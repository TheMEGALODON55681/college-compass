"""Regenerates schema.sql from models.py so the two never drift apart.

Run after any change to models.py: python -m db.generate_schema_sql
"""

import os

from sqlalchemy.schema import CreateTable

from db.models import Base


def run():
    lines = [
        "-- Generated from db/models.py (python -m db.generate_schema_sql). Do not hand-edit.",
        "-- Targets PostgreSQL. Local dev runs the same models against SQLite instead;",
        "-- see data_pipeline/build_dataset.py.",
        "",
    ]
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=__import__("sqlalchemy.dialects.postgresql", fromlist=["dialect"]).dialect()))
        lines.append(ddl.strip() + ";")
        lines.append("")
    out_path = os.path.join(os.path.dirname(__file__), "schema.sql")
    with open(out_path, "w") as f:
        f.write("\n".join(lines))
    print(f"wrote {out_path}")


if __name__ == "__main__":
    run()
