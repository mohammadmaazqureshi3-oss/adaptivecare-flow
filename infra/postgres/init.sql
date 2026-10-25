-- One PostgreSQL server, one schema per service (plan Section 9 and 11).
-- Engine schemas (engine_<pathway>_v<version>) are created by the deployer at deploy time.
CREATE SCHEMA IF NOT EXISTS auth;
CREATE SCHEMA IF NOT EXISTS designer;
CREATE SCHEMA IF NOT EXISTS simulator;
CREATE SCHEMA IF NOT EXISTS deployer;
CREATE SCHEMA IF NOT EXISTS worklist;
CREATE SCHEMA IF NOT EXISTS patient;
-- Until the deployer exists, the manually started engine uses this schema.
CREATE SCHEMA IF NOT EXISTS engine_triage_v1;
