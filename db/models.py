"""SQLAlchemy table definitions - the single source of truth for the schema.

db/schema.sql is generated from these same definitions (see generate_schema_sql.py)
so the two never drift apart. Local dev runs against SQLite; swapping to
Postgres is a DATABASE_URL change plus Base.metadata.create_all(engine)
against a real Postgres instance, since nothing here uses SQLite-only types.
"""

from sqlalchemy import Column, Float, ForeignKey, Integer, String
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class College(Base):
    __tablename__ = "colleges"

    college_id = Column(String, primary_key=True)
    canonical_name = Column(String, nullable=False)
    institute_type = Column(String, nullable=False)
    state = Column(String, nullable=True)
    nirf_rank_latest = Column(Integer, nullable=True)


class Program(Base):
    __tablename__ = "programs"

    program_id = Column(String, primary_key=True)
    branch_name = Column(String, nullable=False)
    degree_type = Column(String, nullable=False)
    duration_years = Column(Integer, nullable=False)
    source_tag = Column(String, nullable=False)


class Cutoff(Base):
    __tablename__ = "cutoffs"

    cutoff_id = Column(Integer, primary_key=True)
    college_id = Column(String, ForeignKey("colleges.college_id"), nullable=False)
    program_id = Column(String, ForeignKey("programs.program_id"), nullable=False)
    quota = Column(String, nullable=False)
    category = Column(String, nullable=False)
    gender_seat_type = Column(String, nullable=False)
    opening_rank = Column(Integer, nullable=True)
    closing_rank = Column(Integer, nullable=False)
    year = Column(Integer, nullable=False)
    round = Column(Integer, nullable=True)
    source_tag = Column(String, nullable=False)


class SeatCount(Base):
    __tablename__ = "seat_counts"

    seat_count_id = Column(Integer, primary_key=True)
    college_id = Column(String, ForeignKey("colleges.college_id"), nullable=False)
    program_id = Column(String, ForeignKey("programs.program_id"), nullable=False)
    year = Column(Integer, nullable=False)
    seat_count = Column(Integer, nullable=False)


class NirfRanking(Base):
    __tablename__ = "nirf_rankings"

    nirf_id = Column(Integer, primary_key=True)
    college_id = Column(String, ForeignKey("colleges.college_id"), nullable=False)
    year = Column(Integer, nullable=False)
    rank = Column(Integer, nullable=True)
    score = Column(Float, nullable=True)


class ReferenceMetadata(Base):
    __tablename__ = "reference_metadata"

    college_id = Column(String, ForeignKey("colleges.college_id"), primary_key=True)
    fees_annual_lakhs = Column(Float, nullable=True)
    hostel_available = Column(Integer, nullable=True)
    location_city = Column(String, nullable=True)
    location_state = Column(String, nullable=True)
    source_note = Column(String, nullable=True)
