-- Generated from db/models.py (python -m db.generate_schema_sql). Do not hand-edit.
-- Targets PostgreSQL. Local dev runs the same models against SQLite instead;
-- see data_pipeline/build_dataset.py.

CREATE TABLE colleges (
	college_id VARCHAR NOT NULL, 
	canonical_name VARCHAR NOT NULL, 
	institute_type VARCHAR NOT NULL, 
	state VARCHAR, 
	nirf_rank_latest INTEGER, 
	PRIMARY KEY (college_id)
);

CREATE TABLE programs (
	program_id VARCHAR NOT NULL, 
	branch_name VARCHAR NOT NULL, 
	degree_type VARCHAR NOT NULL, 
	duration_years INTEGER NOT NULL, 
	source_tag VARCHAR NOT NULL, 
	PRIMARY KEY (program_id)
);

CREATE TABLE cutoffs (
	cutoff_id SERIAL NOT NULL, 
	college_id VARCHAR NOT NULL, 
	program_id VARCHAR NOT NULL, 
	quota VARCHAR NOT NULL, 
	category VARCHAR NOT NULL, 
	gender_seat_type VARCHAR NOT NULL, 
	opening_rank INTEGER, 
	closing_rank INTEGER NOT NULL, 
	year INTEGER NOT NULL, 
	round INTEGER, 
	source_tag VARCHAR NOT NULL, 
	PRIMARY KEY (cutoff_id), 
	FOREIGN KEY(college_id) REFERENCES colleges (college_id), 
	FOREIGN KEY(program_id) REFERENCES programs (program_id)
);

CREATE TABLE nirf_rankings (
	nirf_id SERIAL NOT NULL, 
	college_id VARCHAR NOT NULL, 
	year INTEGER NOT NULL, 
	rank INTEGER, 
	score FLOAT, 
	PRIMARY KEY (nirf_id), 
	FOREIGN KEY(college_id) REFERENCES colleges (college_id)
);

CREATE TABLE reference_metadata (
	college_id VARCHAR NOT NULL, 
	fees_annual_lakhs FLOAT, 
	hostel_available INTEGER, 
	location_city VARCHAR, 
	location_state VARCHAR, 
	source_note VARCHAR, 
	PRIMARY KEY (college_id), 
	FOREIGN KEY(college_id) REFERENCES colleges (college_id)
);

CREATE TABLE seat_counts (
	seat_count_id SERIAL NOT NULL, 
	college_id VARCHAR NOT NULL, 
	program_id VARCHAR NOT NULL, 
	year INTEGER NOT NULL, 
	seat_count INTEGER NOT NULL, 
	PRIMARY KEY (seat_count_id), 
	FOREIGN KEY(college_id) REFERENCES colleges (college_id), 
	FOREIGN KEY(program_id) REFERENCES programs (program_id)
);
