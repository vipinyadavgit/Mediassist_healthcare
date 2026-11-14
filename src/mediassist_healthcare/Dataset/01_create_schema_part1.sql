-- Step 1 of 5: create the schema and first tables.
-- Paste this whole file into Aiven SQL editor and run once.

-- MediAssist fabricated demo dataset for PostgreSQL / Aiven.
-- 500 total table rows across 13 related tables. All records are synthetic.
-- Educational integration testing only. Not real patient data; not for clinical use.
-- Safe to re-run: tables are created if absent and seed rows use ON CONFLICT DO NOTHING.
-- Run the entire script in the Aiven SQL editor after selecting your service database.

CREATE SCHEMA IF NOT EXISTS mediassist_demo;

COMMENT ON SCHEMA mediassist_demo IS 'Synthetic MediAssist demo data only; never use for clinical decisions.';

CREATE TABLE IF NOT EXISTS mediassist_demo.departments (department_id INTEGER PRIMARY KEY, department_name TEXT NOT NULL UNIQUE);

CREATE TABLE IF NOT EXISTS mediassist_demo.providers (provider_id INTEGER PRIMARY KEY, department_id INTEGER NOT NULL REFERENCES mediassist_demo.departments(department_id), synthetic_provider_id TEXT NOT NULL UNIQUE, display_name TEXT NOT NULL, specialty TEXT NOT NULL, email TEXT NOT NULL UNIQUE);

CREATE TABLE IF NOT EXISTS mediassist_demo.patients (patient_id INTEGER PRIMARY KEY, synthetic_patient_id TEXT NOT NULL UNIQUE, first_name TEXT NOT NULL, last_name TEXT NOT NULL, date_of_birth DATE NOT NULL, gender TEXT NOT NULL, email TEXT NOT NULL UNIQUE, phone TEXT NOT NULL UNIQUE, city TEXT NOT NULL, created_at TIMESTAMP NOT NULL);

CREATE TABLE IF NOT EXISTS mediassist_demo.patient_insurance (insurance_id INTEGER PRIMARY KEY, patient_id INTEGER NOT NULL REFERENCES mediassist_demo.patients(patient_id), synthetic_member_id TEXT NOT NULL UNIQUE, payer_name TEXT NOT NULL, plan_name TEXT NOT NULL, effective_from DATE NOT NULL, effective_to DATE NOT NULL, status TEXT NOT NULL CHECK (status IN ('active','inactive')));

CREATE TABLE IF NOT EXISTS mediassist_demo.appointments (appointment_id INTEGER PRIMARY KEY, synthetic_appointment_id TEXT NOT NULL UNIQUE, patient_id INTEGER NOT NULL REFERENCES mediassist_demo.patients(patient_id), provider_id INTEGER NOT NULL REFERENCES mediassist_demo.providers(provider_id), department_id INTEGER NOT NULL REFERENCES mediassist_demo.departments(department_id), scheduled_at TIMESTAMP NOT NULL, status TEXT NOT NULL CHECK (status IN ('completed','scheduled','cancelled','no_show')), reason TEXT NOT NULL, location TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS mediassist_demo.encounters (encounter_id INTEGER PRIMARY KEY, synthetic_encounter_id TEXT NOT NULL UNIQUE, appointment_id INTEGER UNIQUE REFERENCES mediassist_demo.appointments(appointment_id), patient_id INTEGER NOT NULL REFERENCES mediassist_demo.patients(patient_id), provider_id INTEGER NOT NULL REFERENCES mediassist_demo.providers(provider_id), department_id INTEGER NOT NULL REFERENCES mediassist_demo.departments(department_id), encounter_at TIMESTAMP NOT NULL, encounter_type TEXT NOT NULL, chief_complaint TEXT NOT NULL, summary TEXT NOT NULL);
