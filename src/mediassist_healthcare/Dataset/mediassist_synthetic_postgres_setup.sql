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
CREATE TABLE IF NOT EXISTS mediassist_demo.admissions (admission_id INTEGER PRIMARY KEY, synthetic_admission_id TEXT NOT NULL UNIQUE, patient_id INTEGER NOT NULL REFERENCES mediassist_demo.patients(patient_id), encounter_id INTEGER NOT NULL UNIQUE REFERENCES mediassist_demo.encounters(encounter_id), admitted_on DATE NOT NULL, discharged_on DATE, status TEXT NOT NULL CHECK (status IN ('discharged','in_progress')), admission_type TEXT NOT NULL, ward TEXT NOT NULL, room TEXT NOT NULL, CHECK ((status = 'discharged' AND discharged_on IS NOT NULL) OR (status = 'in_progress' AND discharged_on IS NULL)));
CREATE TABLE IF NOT EXISTS mediassist_demo.diagnoses (diagnosis_id INTEGER PRIMARY KEY, encounter_id INTEGER NOT NULL REFERENCES mediassist_demo.encounters(encounter_id), patient_id INTEGER NOT NULL REFERENCES mediassist_demo.patients(patient_id), diagnosis_code TEXT NOT NULL, diagnosis_name TEXT NOT NULL, category TEXT NOT NULL, is_primary BOOLEAN NOT NULL, recorded_on DATE NOT NULL);
CREATE TABLE IF NOT EXISTS mediassist_demo.lab_results (lab_result_id INTEGER PRIMARY KEY, synthetic_order_id TEXT NOT NULL UNIQUE, encounter_id INTEGER NOT NULL REFERENCES mediassist_demo.encounters(encounter_id), patient_id INTEGER NOT NULL REFERENCES mediassist_demo.patients(patient_id), ordered_by_provider_id INTEGER NOT NULL REFERENCES mediassist_demo.providers(provider_id), test_name TEXT NOT NULL, result_value NUMERIC(10,2) NOT NULL, unit TEXT NOT NULL, reference_low NUMERIC(10,2) NOT NULL, reference_high NUMERIC(10,2) NOT NULL, flag TEXT NOT NULL CHECK (flag IN ('normal','low','high')), collected_at TIMESTAMP NOT NULL, status TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mediassist_demo.medication_orders (medication_order_id INTEGER PRIMARY KEY, synthetic_order_id TEXT NOT NULL UNIQUE, encounter_id INTEGER NOT NULL REFERENCES mediassist_demo.encounters(encounter_id), patient_id INTEGER NOT NULL REFERENCES mediassist_demo.patients(patient_id), ordered_by_provider_id INTEGER NOT NULL REFERENCES mediassist_demo.providers(provider_id), medication_name TEXT NOT NULL, dose TEXT NOT NULL, route TEXT NOT NULL, frequency TEXT NOT NULL, start_date DATE NOT NULL, end_date DATE NOT NULL, status TEXT NOT NULL CHECK (status IN ('completed','active')), notes TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS mediassist_demo.insurance_claims (claim_id INTEGER PRIMARY KEY, synthetic_claim_id TEXT NOT NULL UNIQUE, insurance_id INTEGER NOT NULL REFERENCES mediassist_demo.patient_insurance(insurance_id), encounter_id INTEGER NOT NULL REFERENCES mediassist_demo.encounters(encounter_id), patient_id INTEGER NOT NULL REFERENCES mediassist_demo.patients(patient_id), submitted_on DATE NOT NULL, status TEXT NOT NULL CHECK (status IN ('submitted','approved','denied','pending','partially_approved')), billed_amount NUMERIC(10,2) NOT NULL CHECK (billed_amount >= 0), approved_amount NUMERIC(10,2) NOT NULL CHECK (approved_amount >= 0), denial_reason TEXT);
CREATE TABLE IF NOT EXISTS mediassist_demo.invoices (invoice_id INTEGER PRIMARY KEY, synthetic_invoice_id TEXT NOT NULL UNIQUE, encounter_id INTEGER NOT NULL REFERENCES mediassist_demo.encounters(encounter_id), claim_id INTEGER UNIQUE REFERENCES mediassist_demo.insurance_claims(claim_id), patient_id INTEGER NOT NULL REFERENCES mediassist_demo.patients(patient_id), issued_on DATE NOT NULL, due_on DATE NOT NULL, total_amount NUMERIC(10,2) NOT NULL CHECK (total_amount >= 0), status TEXT NOT NULL CHECK (status IN ('paid','open','under_review')));
CREATE TABLE IF NOT EXISTS mediassist_demo.payments (payment_id INTEGER PRIMARY KEY, synthetic_payment_id TEXT NOT NULL UNIQUE, invoice_id INTEGER NOT NULL REFERENCES mediassist_demo.invoices(invoice_id), amount NUMERIC(10,2) NOT NULL CHECK (amount > 0), paid_on DATE NOT NULL, payment_method TEXT NOT NULL, reference_code TEXT NOT NULL UNIQUE);

-- departments: 8 fabricated rows; Demo hospital departments.
INSERT INTO mediassist_demo.departments (department_id, department_name) VALUES
    (1, 'Admissions'),
    (2, 'Emergency'),
    (3, 'Internal Medicine'),
    (4, 'Cardiology'),
    (5, 'Laboratory'),
    (6, 'Radiology'),
    (7, 'Billing'),
    (8, 'Pharmacy')
ON CONFLICT DO NOTHING;

-- providers: 20 fabricated rows; Fabricated staff/provider directory linked to departments.
INSERT INTO mediassist_demo.providers (provider_id, department_id, synthetic_provider_id, display_name, specialty, email) VALUES
    (1, 1, 'SYN-PR-001', 'Dr. Casey Sample', 'Admissions Operations', 'provider01@example.test'),
    (2, 2, 'SYN-PR-002', 'Dr. Jordan Fiction', 'Emergency Medicine', 'provider02@example.test'),
    (3, 3, 'SYN-PR-003', 'Dr. Taylor Example', 'Internal Medicine', 'provider03@example.test'),
    (4, 4, 'SYN-PR-004', 'Dr. Morgan Sample', 'Cardiology', 'provider04@example.test'),
    (5, 5, 'SYN-PR-005', 'Dr. Alex Fiction', 'Clinical Pathology', 'provider05@example.test'),
    (6, 6, 'SYN-PR-006', 'Dr. Casey Example', 'Radiology', 'provider06@example.test'),
    (7, 7, 'SYN-PR-007', 'Dr. Jordan Sample', 'Revenue Cycle', 'provider07@example.test'),
    (8, 8, 'SYN-PR-008', 'Dr. Taylor Fiction', 'Pharmacy', 'provider08@example.test'),
    (9, 1, 'SYN-PR-009', 'Dr. Morgan Example', 'Family Medicine', 'provider09@example.test'),
    (10, 2, 'SYN-PR-010', 'Dr. Alex Sample', 'Pediatrics', 'provider10@example.test'),
    (11, 3, 'SYN-PR-011', 'Dr. Casey Fiction', 'Neurology', 'provider11@example.test'),
    (12, 4, 'SYN-PR-012', 'Dr. Jordan Example', 'Orthopedics', 'provider12@example.test'),
    (13, 5, 'SYN-PR-013', 'Dr. Taylor Sample', 'Dermatology', 'provider13@example.test'),
    (14, 6, 'SYN-PR-014', 'Dr. Morgan Fiction', 'General Surgery', 'provider14@example.test'),
    (15, 7, 'SYN-PR-015', 'Dr. Alex Example', 'Oncology', 'provider15@example.test'),
    (16, 8, 'SYN-PR-016', 'Dr. Casey Sample', 'Gastroenterology', 'provider16@example.test'),
    (17, 1, 'SYN-PR-017', 'Dr. Jordan Fiction', 'Pulmonology', 'provider17@example.test'),
    (18, 2, 'SYN-PR-018', 'Dr. Taylor Example', 'Urology', 'provider18@example.test'),
    (19, 3, 'SYN-PR-019', 'Dr. Morgan Sample', 'Endocrinology', 'provider19@example.test'),
    (20, 4, 'SYN-PR-020', 'Dr. Alex Fiction', 'Nursing Operations', 'provider20@example.test')
ON CONFLICT DO NOTHING;

-- patients: 80 fabricated rows; Fabricated patient demographics; all identifiers and contact details are synthetic.
INSERT INTO mediassist_demo.patients (patient_id, synthetic_patient_id, first_name, last_name, date_of_birth, gender, email, phone, city, created_at) VALUES
    (1, 'SYN-P-0001', 'Avery', 'Example', '1952-06-12', 'male', 'patient0001@example.test', '+1-202-555-1001', 'Demo City 2', '2025-01-02 00:00:00'),
    (2, 'SYN-P-0002', 'Jordan', 'Fiction', '1959-11-23', 'nonbinary', 'patient0002@example.test', '+1-202-555-1002', 'Demo City 3', '2025-01-03 00:00:00'),
    (3, 'SYN-P-0003', 'Riley', 'Demo', '1966-04-07', 'undisclosed', 'patient0003@example.test', '+1-202-555-1003', 'Demo City 4', '2025-01-04 00:00:00'),
    (4, 'SYN-P-0004', 'Casey', 'Testwell', '1973-09-18', 'female', 'patient0004@example.test', '+1-202-555-1004', 'Demo City 5', '2025-01-05 00:00:00'),
    (5, 'SYN-P-0005', 'Morgan', 'Mockingbird', '1980-02-02', 'male', 'patient0005@example.test', '+1-202-555-1005', 'Demo City 6', '2025-01-06 00:00:00'),
    (6, 'SYN-P-0006', 'Taylor', 'Placeholder', '1987-07-13', 'nonbinary', 'patient0006@example.test', '+1-202-555-1006', 'Demo City 7', '2025-01-07 00:00:00'),
    (7, 'SYN-P-0007', 'Cameron', 'Synthetic', '1994-12-24', 'undisclosed', 'patient0007@example.test', '+1-202-555-1007', 'Demo City 8', '2025-01-08 00:00:00'),
    (8, 'SYN-P-0008', 'Quinn', 'Imaginary', '1946-05-08', 'female', 'patient0008@example.test', '+1-202-555-1008', 'Demo City 1', '2025-01-09 00:00:00'),
    (9, 'SYN-P-0009', 'Rowan', 'Practice', '1953-10-19', 'male', 'patient0009@example.test', '+1-202-555-1009', 'Demo City 2', '2025-01-10 00:00:00'),
    (10, 'SYN-P-0010', 'Jamie', 'Sample', '1960-03-03', 'nonbinary', 'patient0010@example.test', '+1-202-555-1010', 'Demo City 3', '2025-01-11 00:00:00'),
    (11, 'SYN-P-0011', 'Skyler', 'Example', '1967-08-14', 'undisclosed', 'patient0011@example.test', '+1-202-555-1011', 'Demo City 4', '2025-01-12 00:00:00'),
    (12, 'SYN-P-0012', 'Reese', 'Fiction', '1974-01-25', 'female', 'patient0012@example.test', '+1-202-555-1012', 'Demo City 5', '2025-01-13 00:00:00'),
    (13, 'SYN-P-0013', 'Dakota', 'Demo', '1981-06-09', 'male', 'patient0013@example.test', '+1-202-555-1013', 'Demo City 6', '2025-01-14 00:00:00'),
    (14, 'SYN-P-0014', 'Parker', 'Testwell', '1988-11-20', 'nonbinary', 'patient0014@example.test', '+1-202-555-1014', 'Demo City 7', '2025-01-15 00:00:00'),
    (15, 'SYN-P-0015', 'Emerson', 'Mockingbird', '1995-04-04', 'undisclosed', 'patient0015@example.test', '+1-202-555-1015', 'Demo City 8', '2025-01-16 00:00:00'),
    (16, 'SYN-P-0016', 'Finley', 'Placeholder', '1947-09-15', 'female', 'patient0016@example.test', '+1-202-555-1016', 'Demo City 1', '2025-01-17 00:00:00'),
    (17, 'SYN-P-0017', 'Avery', 'Imaginary', '1954-02-26', 'male', 'patient0017@example.test', '+1-202-555-1017', 'Demo City 2', '2025-01-18 00:00:00'),
    (18, 'SYN-P-0018', 'Jordan', 'Practice', '1961-07-10', 'nonbinary', 'patient0018@example.test', '+1-202-555-1018', 'Demo City 3', '2025-01-19 00:00:00'),
    (19, 'SYN-P-0019', 'Riley', 'Sample', '1968-12-21', 'undisclosed', 'patient0019@example.test', '+1-202-555-1019', 'Demo City 4', '2025-01-20 00:00:00'),
    (20, 'SYN-P-0020', 'Casey', 'Example', '1975-05-05', 'female', 'patient0020@example.test', '+1-202-555-1020', 'Demo City 5', '2025-01-21 00:00:00'),
    (21, 'SYN-P-0021', 'Morgan', 'Fiction', '1982-10-16', 'male', 'patient0021@example.test', '+1-202-555-1021', 'Demo City 6', '2025-01-22 00:00:00'),
    (22, 'SYN-P-0022', 'Taylor', 'Demo', '1989-03-27', 'nonbinary', 'patient0022@example.test', '+1-202-555-1022', 'Demo City 7', '2025-01-23 00:00:00'),
    (23, 'SYN-P-0023', 'Cameron', 'Testwell', '1996-08-11', 'undisclosed', 'patient0023@example.test', '+1-202-555-1023', 'Demo City 8', '2025-01-24 00:00:00'),
    (24, 'SYN-P-0024', 'Quinn', 'Mockingbird', '1948-01-22', 'female', 'patient0024@example.test', '+1-202-555-1024', 'Demo City 1', '2025-01-25 00:00:00'),
    (25, 'SYN-P-0025', 'Rowan', 'Placeholder', '1955-06-06', 'male', 'patient0025@example.test', '+1-202-555-1025', 'Demo City 2', '2025-01-26 00:00:00'),
    (26, 'SYN-P-0026', 'Jamie', 'Synthetic', '1962-11-17', 'nonbinary', 'patient0026@example.test', '+1-202-555-1026', 'Demo City 3', '2025-01-27 00:00:00'),
    (27, 'SYN-P-0027', 'Skyler', 'Imaginary', '1969-04-01', 'undisclosed', 'patient0027@example.test', '+1-202-555-1027', 'Demo City 4', '2025-01-28 00:00:00'),
    (28, 'SYN-P-0028', 'Reese', 'Practice', '1976-09-12', 'female', 'patient0028@example.test', '+1-202-555-1028', 'Demo City 5', '2025-01-29 00:00:00'),
    (29, 'SYN-P-0029', 'Dakota', 'Sample', '1983-02-23', 'male', 'patient0029@example.test', '+1-202-555-1029', 'Demo City 6', '2025-01-30 00:00:00'),
    (30, 'SYN-P-0030', 'Parker', 'Example', '1990-07-07', 'nonbinary', 'patient0030@example.test', '+1-202-555-1030', 'Demo City 7', '2025-01-31 00:00:00'),
    (31, 'SYN-P-0031', 'Emerson', 'Fiction', '1997-12-18', 'undisclosed', 'patient0031@example.test', '+1-202-555-1031', 'Demo City 8', '2025-02-01 00:00:00'),
    (32, 'SYN-P-0032', 'Finley', 'Demo', '1949-05-02', 'female', 'patient0032@example.test', '+1-202-555-1032', 'Demo City 1', '2025-02-02 00:00:00'),
    (33, 'SYN-P-0033', 'Avery', 'Mockingbird', '1956-10-13', 'male', 'patient0033@example.test', '+1-202-555-1033', 'Demo City 2', '2025-02-03 00:00:00'),
    (34, 'SYN-P-0034', 'Jordan', 'Placeholder', '1963-03-24', 'nonbinary', 'patient0034@example.test', '+1-202-555-1034', 'Demo City 3', '2025-02-04 00:00:00'),
    (35, 'SYN-P-0035', 'Riley', 'Synthetic', '1970-08-08', 'undisclosed', 'patient0035@example.test', '+1-202-555-1035', 'Demo City 4', '2025-02-05 00:00:00'),
    (36, 'SYN-P-0036', 'Casey', 'Imaginary', '1977-01-19', 'female', 'patient0036@example.test', '+1-202-555-1036', 'Demo City 5', '2025-02-06 00:00:00'),
    (37, 'SYN-P-0037', 'Morgan', 'Practice', '1984-06-03', 'male', 'patient0037@example.test', '+1-202-555-1037', 'Demo City 6', '2025-02-07 00:00:00'),
    (38, 'SYN-P-0038', 'Taylor', 'Sample', '1991-11-14', 'nonbinary', 'patient0038@example.test', '+1-202-555-1038', 'Demo City 7', '2025-02-08 00:00:00'),
    (39, 'SYN-P-0039', 'Cameron', 'Example', '1998-04-25', 'undisclosed', 'patient0039@example.test', '+1-202-555-1039', 'Demo City 8', '2025-02-09 00:00:00'),
    (40, 'SYN-P-0040', 'Quinn', 'Fiction', '1950-09-09', 'female', 'patient0040@example.test', '+1-202-555-1040', 'Demo City 1', '2025-02-10 00:00:00'),
    (41, 'SYN-P-0041', 'Rowan', 'Demo', '1957-02-20', 'male', 'patient0041@example.test', '+1-202-555-1041', 'Demo City 2', '2025-02-11 00:00:00'),
    (42, 'SYN-P-0042', 'Jamie', 'Testwell', '1964-07-04', 'nonbinary', 'patient0042@example.test', '+1-202-555-1042', 'Demo City 3', '2025-02-12 00:00:00'),
    (43, 'SYN-P-0043', 'Skyler', 'Mockingbird', '1971-12-15', 'undisclosed', 'patient0043@example.test', '+1-202-555-1043', 'Demo City 4', '2025-02-13 00:00:00'),
    (44, 'SYN-P-0044', 'Reese', 'Placeholder', '1978-05-26', 'female', 'patient0044@example.test', '+1-202-555-1044', 'Demo City 5', '2025-02-14 00:00:00'),
    (45, 'SYN-P-0045', 'Dakota', 'Synthetic', '1985-10-10', 'male', 'patient0045@example.test', '+1-202-555-1045', 'Demo City 6', '2025-02-15 00:00:00'),
    (46, 'SYN-P-0046', 'Parker', 'Imaginary', '1992-03-21', 'nonbinary', 'patient0046@example.test', '+1-202-555-1046', 'Demo City 7', '2025-02-16 00:00:00'),
    (47, 'SYN-P-0047', 'Emerson', 'Practice', '1999-08-05', 'undisclosed', 'patient0047@example.test', '+1-202-555-1047', 'Demo City 8', '2025-02-17 00:00:00'),
    (48, 'SYN-P-0048', 'Finley', 'Sample', '1951-01-16', 'female', 'patient0048@example.test', '+1-202-555-1048', 'Demo City 1', '2025-02-18 00:00:00'),
    (49, 'SYN-P-0049', 'Avery', 'Fiction', '1958-06-27', 'male', 'patient0049@example.test', '+1-202-555-1049', 'Demo City 2', '2025-02-19 00:00:00'),
    (50, 'SYN-P-0050', 'Jordan', 'Demo', '1965-11-11', 'nonbinary', 'patient0050@example.test', '+1-202-555-1050', 'Demo City 3', '2025-02-20 00:00:00'),
    (51, 'SYN-P-0051', 'Riley', 'Testwell', '1972-04-22', 'undisclosed', 'patient0051@example.test', '+1-202-555-1051', 'Demo City 4', '2025-02-21 00:00:00'),
    (52, 'SYN-P-0052', 'Casey', 'Mockingbird', '1979-09-06', 'female', 'patient0052@example.test', '+1-202-555-1052', 'Demo City 5', '2025-02-22 00:00:00'),
    (53, 'SYN-P-0053', 'Morgan', 'Placeholder', '1986-02-17', 'male', 'patient0053@example.test', '+1-202-555-1053', 'Demo City 6', '2025-02-23 00:00:00'),
    (54, 'SYN-P-0054', 'Taylor', 'Synthetic', '1993-07-01', 'nonbinary', 'patient0054@example.test', '+1-202-555-1054', 'Demo City 7', '2025-02-24 00:00:00'),
    (55, 'SYN-P-0055', 'Cameron', 'Imaginary', '1945-12-12', 'undisclosed', 'patient0055@example.test', '+1-202-555-1055', 'Demo City 8', '2025-02-25 00:00:00'),
    (56, 'SYN-P-0056', 'Quinn', 'Practice', '1952-05-23', 'female', 'patient0056@example.test', '+1-202-555-1056', 'Demo City 1', '2025-02-26 00:00:00'),
    (57, 'SYN-P-0057', 'Rowan', 'Sample', '1959-10-07', 'male', 'patient0057@example.test', '+1-202-555-1057', 'Demo City 2', '2025-02-27 00:00:00'),
    (58, 'SYN-P-0058', 'Jamie', 'Example', '1966-03-18', 'nonbinary', 'patient0058@example.test', '+1-202-555-1058', 'Demo City 3', '2025-02-28 00:00:00'),
    (59, 'SYN-P-0059', 'Skyler', 'Fiction', '1973-08-02', 'undisclosed', 'patient0059@example.test', '+1-202-555-1059', 'Demo City 4', '2025-03-01 00:00:00'),
    (60, 'SYN-P-0060', 'Reese', 'Demo', '1980-01-13', 'female', 'patient0060@example.test', '+1-202-555-1060', 'Demo City 5', '2025-03-02 00:00:00'),
    (61, 'SYN-P-0061', 'Dakota', 'Testwell', '1987-06-24', 'male', 'patient0061@example.test', '+1-202-555-1061', 'Demo City 6', '2025-03-03 00:00:00'),
    (62, 'SYN-P-0062', 'Parker', 'Mockingbird', '1994-11-08', 'nonbinary', 'patient0062@example.test', '+1-202-555-1062', 'Demo City 7', '2025-03-04 00:00:00'),
    (63, 'SYN-P-0063', 'Emerson', 'Placeholder', '1946-04-19', 'undisclosed', 'patient0063@example.test', '+1-202-555-1063', 'Demo City 8', '2025-03-05 00:00:00'),
    (64, 'SYN-P-0064', 'Finley', 'Synthetic', '1953-09-03', 'female', 'patient0064@example.test', '+1-202-555-1064', 'Demo City 1', '2025-03-06 00:00:00'),
    (65, 'SYN-P-0065', 'Avery', 'Practice', '1960-02-14', 'male', 'patient0065@example.test', '+1-202-555-1065', 'Demo City 2', '2025-03-07 00:00:00'),
    (66, 'SYN-P-0066', 'Jordan', 'Sample', '1967-07-25', 'nonbinary', 'patient0066@example.test', '+1-202-555-1066', 'Demo City 3', '2025-03-08 00:00:00'),
    (67, 'SYN-P-0067', 'Riley', 'Example', '1974-12-09', 'undisclosed', 'patient0067@example.test', '+1-202-555-1067', 'Demo City 4', '2025-03-09 00:00:00'),
    (68, 'SYN-P-0068', 'Casey', 'Fiction', '1981-05-20', 'female', 'patient0068@example.test', '+1-202-555-1068', 'Demo City 5', '2025-03-10 00:00:00'),
    (69, 'SYN-P-0069', 'Morgan', 'Demo', '1988-10-04', 'male', 'patient0069@example.test', '+1-202-555-1069', 'Demo City 6', '2025-03-11 00:00:00'),
    (70, 'SYN-P-0070', 'Taylor', 'Testwell', '1995-03-15', 'nonbinary', 'patient0070@example.test', '+1-202-555-1070', 'Demo City 7', '2025-03-12 00:00:00'),
    (71, 'SYN-P-0071', 'Cameron', 'Mockingbird', '1947-08-26', 'undisclosed', 'patient0071@example.test', '+1-202-555-1071', 'Demo City 8', '2025-03-13 00:00:00'),
    (72, 'SYN-P-0072', 'Quinn', 'Placeholder', '1954-01-10', 'female', 'patient0072@example.test', '+1-202-555-1072', 'Demo City 1', '2025-03-14 00:00:00'),
    (73, 'SYN-P-0073', 'Rowan', 'Synthetic', '1961-06-21', 'male', 'patient0073@example.test', '+1-202-555-1073', 'Demo City 2', '2025-03-15 00:00:00'),
    (74, 'SYN-P-0074', 'Jamie', 'Imaginary', '1968-11-05', 'nonbinary', 'patient0074@example.test', '+1-202-555-1074', 'Demo City 3', '2025-03-16 00:00:00'),
    (75, 'SYN-P-0075', 'Skyler', 'Practice', '1975-04-16', 'undisclosed', 'patient0075@example.test', '+1-202-555-1075', 'Demo City 4', '2025-03-17 00:00:00'),
    (76, 'SYN-P-0076', 'Reese', 'Sample', '1982-09-27', 'female', 'patient0076@example.test', '+1-202-555-1076', 'Demo City 5', '2025-03-18 00:00:00'),
    (77, 'SYN-P-0077', 'Dakota', 'Example', '1989-02-11', 'male', 'patient0077@example.test', '+1-202-555-1077', 'Demo City 6', '2025-03-19 00:00:00'),
    (78, 'SYN-P-0078', 'Parker', 'Fiction', '1996-07-22', 'nonbinary', 'patient0078@example.test', '+1-202-555-1078', 'Demo City 7', '2025-03-20 00:00:00'),
    (79, 'SYN-P-0079', 'Emerson', 'Demo', '1948-12-06', 'undisclosed', 'patient0079@example.test', '+1-202-555-1079', 'Demo City 8', '2025-03-21 00:00:00'),
    (80, 'SYN-P-0080', 'Finley', 'Testwell', '1955-05-17', 'female', 'patient0080@example.test', '+1-202-555-1080', 'Demo City 1', '2025-03-22 00:00:00')
ON CONFLICT DO NOTHING;

-- patient_insurance: 60 fabricated rows; Synthetic payer/plan coverage linked to demo patients.
INSERT INTO mediassist_demo.patient_insurance (insurance_id, patient_id, synthetic_member_id, payer_name, plan_name, effective_from, effective_to, status) VALUES
    (1, 1, 'SYN-MEMBER-00001', 'Example Health Plan', 'Standard Demo', '2024-01-01', '2027-12-31', 'active'),
    (2, 2, 'SYN-MEMBER-00002', 'Synthetic Mutual', 'Plus Demo', '2024-01-01', '2027-12-31', 'active'),
    (3, 3, 'SYN-MEMBER-00003', 'Demo Coverage Group', 'Basic Demo', '2024-01-01', '2027-12-31', 'inactive'),
    (4, 4, 'SYN-MEMBER-00004', 'Example Health Plan', 'Standard Demo', '2024-01-01', '2027-12-31', 'active'),
    (5, 5, 'SYN-MEMBER-00005', 'Synthetic Mutual', 'Plus Demo', '2024-01-01', '2027-12-31', 'active'),
    (6, 6, 'SYN-MEMBER-00006', 'Demo Coverage Group', 'Basic Demo', '2024-01-01', '2027-12-31', 'active'),
    (7, 7, 'SYN-MEMBER-00007', 'Example Health Plan', 'Standard Demo', '2024-01-01', '2025-12-31', 'inactive'),
    (8, 8, 'SYN-MEMBER-00008', 'Synthetic Mutual', 'Plus Demo', '2024-01-01', '2027-12-31', 'active'),
    (9, 9, 'SYN-MEMBER-00009', 'Demo Coverage Group', 'Basic Demo', '2024-01-01', '2027-12-31', 'active'),
    (10, 10, 'SYN-MEMBER-00010', 'Example Health Plan', 'Standard Demo', '2024-01-01', '2027-12-31', 'active'),
    (11, 11, 'SYN-MEMBER-00011', 'Synthetic Mutual', 'Plus Demo', '2024-01-01', '2027-12-31', 'inactive'),
    (12, 12, 'SYN-MEMBER-00012', 'Demo Coverage Group', 'Basic Demo', '2024-01-01', '2027-12-31', 'active'),
    (13, 13, 'SYN-MEMBER-00013', 'Example Health Plan', 'Standard Demo', '2024-01-01', '2027-12-31', 'active'),
    (14, 14, 'SYN-MEMBER-00014', 'Synthetic Mutual', 'Plus Demo', '2024-01-01', '2025-12-31', 'active'),
    (15, 15, 'SYN-MEMBER-00015', 'Demo Coverage Group', 'Basic Demo', '2024-01-01', '2027-12-31', 'inactive'),
    (16, 16, 'SYN-MEMBER-00016', 'Example Health Plan', 'Standard Demo', '2024-01-01', '2027-12-31', 'active'),
    (17, 17, 'SYN-MEMBER-00017', 'Synthetic Mutual', 'Plus Demo', '2024-01-01', '2027-12-31', 'active'),
    (18, 18, 'SYN-MEMBER-00018', 'Demo Coverage Group', 'Basic Demo', '2024-01-01', '2027-12-31', 'active'),
    (19, 19, 'SYN-MEMBER-00019', 'Example Health Plan', 'Standard Demo', '2024-01-01', '2027-12-31', 'inactive'),
    (20, 20, 'SYN-MEMBER-00020', 'Synthetic Mutual', 'Plus Demo', '2024-01-01', '2027-12-31', 'active'),
    (21, 21, 'SYN-MEMBER-00021', 'Demo Coverage Group', 'Basic Demo', '2024-01-01', '2025-12-31', 'active'),
    (22, 22, 'SYN-MEMBER-00022', 'Example Health Plan', 'Standard Demo', '2024-01-01', '2027-12-31', 'active'),
    (23, 23, 'SYN-MEMBER-00023', 'Synthetic Mutual', 'Plus Demo', '2024-01-01', '2027-12-31', 'inactive'),
    (24, 24, 'SYN-MEMBER-00024', 'Demo Coverage Group', 'Basic Demo', '2024-01-01', '2027-12-31', 'active'),
    (25, 25, 'SYN-MEMBER-00025', 'Example Health Plan', 'Standard Demo', '2024-01-01', '2027-12-31', 'active'),
    (26, 26, 'SYN-MEMBER-00026', 'Synthetic Mutual', 'Plus Demo', '2024-01-01', '2027-12-31', 'active'),
    (27, 27, 'SYN-MEMBER-00027', 'Demo Coverage Group', 'Basic Demo', '2024-01-01', '2027-12-31', 'inactive'),
    (28, 28, 'SYN-MEMBER-00028', 'Example Health Plan', 'Standard Demo', '2024-01-01', '2025-12-31', 'active'),
    (29, 29, 'SYN-MEMBER-00029', 'Synthetic Mutual', 'Plus Demo', '2024-01-01', '2027-12-31', 'active'),
    (30, 30, 'SYN-MEMBER-00030', 'Demo Coverage Group', 'Basic Demo', '2024-01-01', '2027-12-31', 'active'),
    (31, 31, 'SYN-MEMBER-00031', 'Example Health Plan', 'Standard Demo', '2024-01-01', '2027-12-31', 'inactive'),
    (32, 32, 'SYN-MEMBER-00032', 'Synthetic Mutual', 'Plus Demo', '2024-01-01', '2027-12-31', 'active'),
    (33, 33, 'SYN-MEMBER-00033', 'Demo Coverage Group', 'Basic Demo', '2024-01-01', '2027-12-31', 'active'),
    (34, 34, 'SYN-MEMBER-00034', 'Example Health Plan', 'Standard Demo', '2024-01-01', '2027-12-31', 'active'),
    (35, 35, 'SYN-MEMBER-00035', 'Synthetic Mutual', 'Plus Demo', '2024-01-01', '2025-12-31', 'inactive'),
    (36, 36, 'SYN-MEMBER-00036', 'Demo Coverage Group', 'Basic Demo', '2024-01-01', '2027-12-31', 'active'),
    (37, 37, 'SYN-MEMBER-00037', 'Example Health Plan', 'Standard Demo', '2024-01-01', '2027-12-31', 'active'),
    (38, 38, 'SYN-MEMBER-00038', 'Synthetic Mutual', 'Plus Demo', '2024-01-01', '2027-12-31', 'active'),
    (39, 39, 'SYN-MEMBER-00039', 'Demo Coverage Group', 'Basic Demo', '2024-01-01', '2027-12-31', 'inactive'),
    (40, 40, 'SYN-MEMBER-00040', 'Example Health Plan', 'Standard Demo', '2024-01-01', '2027-12-31', 'active'),
    (41, 41, 'SYN-MEMBER-00041', 'Synthetic Mutual', 'Plus Demo', '2024-01-01', '2027-12-31', 'active'),
    (42, 42, 'SYN-MEMBER-00042', 'Demo Coverage Group', 'Basic Demo', '2024-01-01', '2025-12-31', 'active'),
    (43, 43, 'SYN-MEMBER-00043', 'Example Health Plan', 'Standard Demo', '2024-01-01', '2027-12-31', 'inactive'),
    (44, 44, 'SYN-MEMBER-00044', 'Synthetic Mutual', 'Plus Demo', '2024-01-01', '2027-12-31', 'active'),
    (45, 45, 'SYN-MEMBER-00045', 'Demo Coverage Group', 'Basic Demo', '2024-01-01', '2027-12-31', 'active'),
    (46, 46, 'SYN-MEMBER-00046', 'Example Health Plan', 'Standard Demo', '2024-01-01', '2027-12-31', 'active'),
    (47, 47, 'SYN-MEMBER-00047', 'Synthetic Mutual', 'Plus Demo', '2024-01-01', '2027-12-31', 'inactive'),
    (48, 48, 'SYN-MEMBER-00048', 'Demo Coverage Group', 'Basic Demo', '2024-01-01', '2027-12-31', 'active'),
    (49, 49, 'SYN-MEMBER-00049', 'Example Health Plan', 'Standard Demo', '2024-01-01', '2025-12-31', 'active'),
    (50, 50, 'SYN-MEMBER-00050', 'Synthetic Mutual', 'Plus Demo', '2024-01-01', '2027-12-31', 'active'),
    (51, 51, 'SYN-MEMBER-00051', 'Demo Coverage Group', 'Basic Demo', '2024-01-01', '2027-12-31', 'inactive'),
    (52, 52, 'SYN-MEMBER-00052', 'Example Health Plan', 'Standard Demo', '2024-01-01', '2027-12-31', 'active'),
    (53, 53, 'SYN-MEMBER-00053', 'Synthetic Mutual', 'Plus Demo', '2024-01-01', '2027-12-31', 'active'),
    (54, 54, 'SYN-MEMBER-00054', 'Demo Coverage Group', 'Basic Demo', '2024-01-01', '2027-12-31', 'active'),
    (55, 55, 'SYN-MEMBER-00055', 'Example Health Plan', 'Standard Demo', '2024-01-01', '2027-12-31', 'inactive'),
    (56, 56, 'SYN-MEMBER-00056', 'Synthetic Mutual', 'Plus Demo', '2024-01-01', '2025-12-31', 'active'),
    (57, 57, 'SYN-MEMBER-00057', 'Demo Coverage Group', 'Basic Demo', '2024-01-01', '2027-12-31', 'active'),
    (58, 58, 'SYN-MEMBER-00058', 'Example Health Plan', 'Standard Demo', '2024-01-01', '2027-12-31', 'active'),
    (59, 59, 'SYN-MEMBER-00059', 'Synthetic Mutual', 'Plus Demo', '2024-01-01', '2027-12-31', 'inactive'),
    (60, 60, 'SYN-MEMBER-00060', 'Demo Coverage Group', 'Basic Demo', '2024-01-01', '2027-12-31', 'active')
ON CONFLICT DO NOTHING;

-- appointments: 70 fabricated rows; Synthetic appointment schedule, statuses, and workflow reasons.
INSERT INTO mediassist_demo.appointments (appointment_id, synthetic_appointment_id, patient_id, provider_id, department_id, scheduled_at, status, reason, location) VALUES
    (1, 'SYN-APPT-0001', 1, 1, 1, '2025-01-07 09:00:00', 'completed', 'routine follow-up', 'Demo Clinic 1'),
    (2, 'SYN-APPT-0002', 2, 2, 2, '2025-01-11 10:00:00', 'completed', 'lab review', 'Demo Clinic 2'),
    (3, 'SYN-APPT-0003', 3, 3, 3, '2025-01-15 11:00:00', 'scheduled', 'billing consultation', 'Demo Clinic 3'),
    (4, 'SYN-APPT-0004', 4, 4, 4, '2025-01-19 12:00:00', 'cancelled', 'general inquiry', 'Demo Clinic 4'),
    (5, 'SYN-APPT-0005', 5, 5, 5, '2025-01-23 13:00:00', 'no_show', 'admission consultation', 'Demo Clinic 5'),
    (6, 'SYN-APPT-0006', 6, 6, 6, '2025-01-27 14:00:00', 'completed', 'routine follow-up', 'Demo Clinic 6'),
    (7, 'SYN-APPT-0007', 7, 7, 7, '2025-01-31 15:00:00', 'completed', 'lab review', 'Demo Clinic 7'),
    (8, 'SYN-APPT-0008', 8, 8, 8, '2025-02-04 08:00:00', 'scheduled', 'billing consultation', 'Demo Clinic 8'),
    (9, 'SYN-APPT-0009', 9, 9, 1, '2025-02-08 09:00:00', 'cancelled', 'general inquiry', 'Demo Clinic 1'),
    (10, 'SYN-APPT-0010', 10, 10, 2, '2025-02-12 10:00:00', 'no_show', 'admission consultation', 'Demo Clinic 2'),
    (11, 'SYN-APPT-0011', 11, 11, 3, '2025-02-16 11:00:00', 'completed', 'routine follow-up', 'Demo Clinic 3'),
    (12, 'SYN-APPT-0012', 12, 12, 4, '2025-02-20 12:00:00', 'completed', 'lab review', 'Demo Clinic 4'),
    (13, 'SYN-APPT-0013', 13, 13, 5, '2025-02-24 13:00:00', 'scheduled', 'billing consultation', 'Demo Clinic 5'),
    (14, 'SYN-APPT-0014', 14, 14, 6, '2025-02-28 14:00:00', 'cancelled', 'general inquiry', 'Demo Clinic 6'),
    (15, 'SYN-APPT-0015', 15, 15, 7, '2025-03-04 15:00:00', 'no_show', 'admission consultation', 'Demo Clinic 7'),
    (16, 'SYN-APPT-0016', 16, 16, 8, '2025-03-08 08:00:00', 'completed', 'routine follow-up', 'Demo Clinic 8'),
    (17, 'SYN-APPT-0017', 17, 17, 1, '2025-03-12 09:00:00', 'completed', 'lab review', 'Demo Clinic 1'),
    (18, 'SYN-APPT-0018', 18, 18, 2, '2025-03-16 10:00:00', 'scheduled', 'billing consultation', 'Demo Clinic 2'),
    (19, 'SYN-APPT-0019', 19, 19, 3, '2025-03-20 11:00:00', 'cancelled', 'general inquiry', 'Demo Clinic 3'),
    (20, 'SYN-APPT-0020', 20, 20, 4, '2025-03-24 12:00:00', 'no_show', 'admission consultation', 'Demo Clinic 4'),
    (21, 'SYN-APPT-0021', 21, 1, 1, '2025-03-28 13:00:00', 'completed', 'routine follow-up', 'Demo Clinic 1'),
    (22, 'SYN-APPT-0022', 22, 2, 2, '2025-04-01 14:00:00', 'completed', 'lab review', 'Demo Clinic 2'),
    (23, 'SYN-APPT-0023', 23, 3, 3, '2025-04-05 15:00:00', 'scheduled', 'billing consultation', 'Demo Clinic 3'),
    (24, 'SYN-APPT-0024', 24, 4, 4, '2025-04-09 08:00:00', 'cancelled', 'general inquiry', 'Demo Clinic 4'),
    (25, 'SYN-APPT-0025', 25, 5, 5, '2025-04-13 09:00:00', 'no_show', 'admission consultation', 'Demo Clinic 5'),
    (26, 'SYN-APPT-0026', 26, 6, 6, '2025-04-17 10:00:00', 'completed', 'routine follow-up', 'Demo Clinic 6'),
    (27, 'SYN-APPT-0027', 27, 7, 7, '2025-04-21 11:00:00', 'completed', 'lab review', 'Demo Clinic 7'),
    (28, 'SYN-APPT-0028', 28, 8, 8, '2025-04-25 12:00:00', 'scheduled', 'billing consultation', 'Demo Clinic 8'),
    (29, 'SYN-APPT-0029', 29, 9, 1, '2025-04-29 13:00:00', 'cancelled', 'general inquiry', 'Demo Clinic 1'),
    (30, 'SYN-APPT-0030', 30, 10, 2, '2025-05-03 14:00:00', 'no_show', 'admission consultation', 'Demo Clinic 2'),
    (31, 'SYN-APPT-0031', 31, 11, 3, '2025-05-07 15:00:00', 'completed', 'routine follow-up', 'Demo Clinic 3'),
    (32, 'SYN-APPT-0032', 32, 12, 4, '2025-05-11 08:00:00', 'completed', 'lab review', 'Demo Clinic 4'),
    (33, 'SYN-APPT-0033', 33, 13, 5, '2025-05-15 09:00:00', 'scheduled', 'billing consultation', 'Demo Clinic 5'),
    (34, 'SYN-APPT-0034', 34, 14, 6, '2025-05-19 10:00:00', 'cancelled', 'general inquiry', 'Demo Clinic 6'),
    (35, 'SYN-APPT-0035', 35, 15, 7, '2025-05-23 11:00:00', 'no_show', 'admission consultation', 'Demo Clinic 7'),
    (36, 'SYN-APPT-0036', 36, 16, 8, '2025-05-27 12:00:00', 'completed', 'routine follow-up', 'Demo Clinic 8'),
    (37, 'SYN-APPT-0037', 37, 17, 1, '2025-05-31 13:00:00', 'completed', 'lab review', 'Demo Clinic 1'),
    (38, 'SYN-APPT-0038', 38, 18, 2, '2025-06-04 14:00:00', 'scheduled', 'billing consultation', 'Demo Clinic 2'),
    (39, 'SYN-APPT-0039', 39, 19, 3, '2025-06-08 15:00:00', 'cancelled', 'general inquiry', 'Demo Clinic 3'),
    (40, 'SYN-APPT-0040', 40, 20, 4, '2025-06-12 08:00:00', 'no_show', 'admission consultation', 'Demo Clinic 4'),
    (41, 'SYN-APPT-0041', 41, 1, 1, '2025-06-16 09:00:00', 'completed', 'routine follow-up', 'Demo Clinic 1'),
    (42, 'SYN-APPT-0042', 42, 2, 2, '2025-06-20 10:00:00', 'completed', 'lab review', 'Demo Clinic 2'),
    (43, 'SYN-APPT-0043', 43, 3, 3, '2025-06-24 11:00:00', 'scheduled', 'billing consultation', 'Demo Clinic 3'),
    (44, 'SYN-APPT-0044', 44, 4, 4, '2025-06-28 12:00:00', 'cancelled', 'general inquiry', 'Demo Clinic 4'),
    (45, 'SYN-APPT-0045', 45, 5, 5, '2025-07-02 13:00:00', 'no_show', 'admission consultation', 'Demo Clinic 5'),
    (46, 'SYN-APPT-0046', 46, 6, 6, '2025-07-06 14:00:00', 'completed', 'routine follow-up', 'Demo Clinic 6'),
    (47, 'SYN-APPT-0047', 47, 7, 7, '2025-07-10 15:00:00', 'completed', 'lab review', 'Demo Clinic 7'),
    (48, 'SYN-APPT-0048', 48, 8, 8, '2025-07-14 08:00:00', 'scheduled', 'billing consultation', 'Demo Clinic 8'),
    (49, 'SYN-APPT-0049', 49, 9, 1, '2025-07-18 09:00:00', 'cancelled', 'general inquiry', 'Demo Clinic 1'),
    (50, 'SYN-APPT-0050', 50, 10, 2, '2025-07-22 10:00:00', 'no_show', 'admission consultation', 'Demo Clinic 2'),
    (51, 'SYN-APPT-0051', 51, 11, 3, '2025-07-26 11:00:00', 'completed', 'routine follow-up', 'Demo Clinic 3'),
    (52, 'SYN-APPT-0052', 52, 12, 4, '2025-07-30 12:00:00', 'completed', 'lab review', 'Demo Clinic 4'),
    (53, 'SYN-APPT-0053', 53, 13, 5, '2025-08-03 13:00:00', 'scheduled', 'billing consultation', 'Demo Clinic 5'),
    (54, 'SYN-APPT-0054', 54, 14, 6, '2025-08-07 14:00:00', 'cancelled', 'general inquiry', 'Demo Clinic 6'),
    (55, 'SYN-APPT-0055', 55, 15, 7, '2025-08-11 15:00:00', 'no_show', 'admission consultation', 'Demo Clinic 7'),
    (56, 'SYN-APPT-0056', 56, 16, 8, '2025-08-15 08:00:00', 'completed', 'routine follow-up', 'Demo Clinic 8'),
    (57, 'SYN-APPT-0057', 57, 17, 1, '2025-08-19 09:00:00', 'completed', 'lab review', 'Demo Clinic 1'),
    (58, 'SYN-APPT-0058', 58, 18, 2, '2025-08-23 10:00:00', 'scheduled', 'billing consultation', 'Demo Clinic 2'),
    (59, 'SYN-APPT-0059', 59, 19, 3, '2025-08-27 11:00:00', 'cancelled', 'general inquiry', 'Demo Clinic 3'),
    (60, 'SYN-APPT-0060', 60, 20, 4, '2025-08-31 12:00:00', 'no_show', 'admission consultation', 'Demo Clinic 4'),
    (61, 'SYN-APPT-0061', 61, 1, 1, '2025-09-04 13:00:00', 'completed', 'routine follow-up', 'Demo Clinic 1'),
    (62, 'SYN-APPT-0062', 62, 2, 2, '2025-09-08 14:00:00', 'completed', 'lab review', 'Demo Clinic 2'),
    (63, 'SYN-APPT-0063', 63, 3, 3, '2025-09-12 15:00:00', 'scheduled', 'billing consultation', 'Demo Clinic 3'),
    (64, 'SYN-APPT-0064', 64, 4, 4, '2025-09-16 08:00:00', 'cancelled', 'general inquiry', 'Demo Clinic 4'),
    (65, 'SYN-APPT-0065', 65, 5, 5, '2025-09-20 09:00:00', 'no_show', 'admission consultation', 'Demo Clinic 5'),
    (66, 'SYN-APPT-0066', 66, 6, 6, '2025-09-24 10:00:00', 'completed', 'routine follow-up', 'Demo Clinic 6'),
    (67, 'SYN-APPT-0067', 67, 7, 7, '2025-09-28 11:00:00', 'completed', 'lab review', 'Demo Clinic 7'),
    (68, 'SYN-APPT-0068', 68, 8, 8, '2025-10-02 12:00:00', 'scheduled', 'billing consultation', 'Demo Clinic 8'),
    (69, 'SYN-APPT-0069', 69, 9, 1, '2025-10-06 13:00:00', 'cancelled', 'general inquiry', 'Demo Clinic 1'),
    (70, 'SYN-APPT-0070', 70, 10, 2, '2025-10-10 14:00:00', 'no_show', 'admission consultation', 'Demo Clinic 2')
ON CONFLICT DO NOTHING;

-- encounters: 60 fabricated rows; Synthetic visit records linked to appointments, patients, providers, and departments.
INSERT INTO mediassist_demo.encounters (encounter_id, synthetic_encounter_id, appointment_id, patient_id, provider_id, department_id, encounter_at, encounter_type, chief_complaint, summary) VALUES
    (1, 'SYN-ENC-0001', 1, 1, 1, 1, '2025-01-07 09:00:00', 'emergency', 'Synthetic visit reason 001', 'Fabricated summary for software testing only; encounter 001.'),
    (2, 'SYN-ENC-0002', 2, 2, 2, 2, '2025-01-11 10:00:00', 'follow_up', 'Synthetic visit reason 002', 'Fabricated summary for software testing only; encounter 002.'),
    (3, 'SYN-ENC-0003', 3, 3, 3, 3, '2025-01-15 11:00:00', 'diagnostic', 'Synthetic visit reason 003', 'Fabricated summary for software testing only; encounter 003.'),
    (4, 'SYN-ENC-0004', 4, 4, 4, 4, '2025-01-19 12:00:00', 'outpatient', 'Synthetic visit reason 004', 'Fabricated summary for software testing only; encounter 004.'),
    (5, 'SYN-ENC-0005', 5, 5, 5, 5, '2025-01-23 13:00:00', 'emergency', 'Synthetic visit reason 005', 'Fabricated summary for software testing only; encounter 005.'),
    (6, 'SYN-ENC-0006', 6, 6, 6, 6, '2025-01-27 14:00:00', 'follow_up', 'Synthetic visit reason 006', 'Fabricated summary for software testing only; encounter 006.'),
    (7, 'SYN-ENC-0007', 7, 7, 7, 7, '2025-01-31 15:00:00', 'diagnostic', 'Synthetic visit reason 007', 'Fabricated summary for software testing only; encounter 007.'),
    (8, 'SYN-ENC-0008', 8, 8, 8, 8, '2025-02-04 08:00:00', 'outpatient', 'Synthetic visit reason 008', 'Fabricated summary for software testing only; encounter 008.'),
    (9, 'SYN-ENC-0009', 9, 9, 9, 1, '2025-02-08 09:00:00', 'emergency', 'Synthetic visit reason 009', 'Fabricated summary for software testing only; encounter 009.'),
    (10, 'SYN-ENC-0010', 10, 10, 10, 2, '2025-02-12 10:00:00', 'follow_up', 'Synthetic visit reason 010', 'Fabricated summary for software testing only; encounter 010.'),
    (11, 'SYN-ENC-0011', 11, 11, 11, 3, '2025-02-16 11:00:00', 'diagnostic', 'Synthetic visit reason 011', 'Fabricated summary for software testing only; encounter 011.'),
    (12, 'SYN-ENC-0012', 12, 12, 12, 4, '2025-02-20 12:00:00', 'outpatient', 'Synthetic visit reason 012', 'Fabricated summary for software testing only; encounter 012.'),
    (13, 'SYN-ENC-0013', 13, 13, 13, 5, '2025-02-24 13:00:00', 'emergency', 'Synthetic visit reason 013', 'Fabricated summary for software testing only; encounter 013.'),
    (14, 'SYN-ENC-0014', 14, 14, 14, 6, '2025-02-28 14:00:00', 'follow_up', 'Synthetic visit reason 014', 'Fabricated summary for software testing only; encounter 014.'),
    (15, 'SYN-ENC-0015', 15, 15, 15, 7, '2025-03-04 15:00:00', 'diagnostic', 'Synthetic visit reason 015', 'Fabricated summary for software testing only; encounter 015.'),
    (16, 'SYN-ENC-0016', 16, 16, 16, 8, '2025-03-08 08:00:00', 'outpatient', 'Synthetic visit reason 016', 'Fabricated summary for software testing only; encounter 016.'),
    (17, 'SYN-ENC-0017', 17, 17, 17, 1, '2025-03-12 09:00:00', 'emergency', 'Synthetic visit reason 017', 'Fabricated summary for software testing only; encounter 017.'),
    (18, 'SYN-ENC-0018', 18, 18, 18, 2, '2025-03-16 10:00:00', 'follow_up', 'Synthetic visit reason 018', 'Fabricated summary for software testing only; encounter 018.'),
    (19, 'SYN-ENC-0019', 19, 19, 19, 3, '2025-03-20 11:00:00', 'diagnostic', 'Synthetic visit reason 019', 'Fabricated summary for software testing only; encounter 019.'),
    (20, 'SYN-ENC-0020', 20, 20, 20, 4, '2025-03-24 12:00:00', 'outpatient', 'Synthetic visit reason 020', 'Fabricated summary for software testing only; encounter 020.'),
    (21, 'SYN-ENC-0021', 21, 21, 1, 1, '2025-03-28 13:00:00', 'emergency', 'Synthetic visit reason 021', 'Fabricated summary for software testing only; encounter 021.'),
    (22, 'SYN-ENC-0022', 22, 22, 2, 2, '2025-04-01 14:00:00', 'follow_up', 'Synthetic visit reason 022', 'Fabricated summary for software testing only; encounter 022.'),
    (23, 'SYN-ENC-0023', 23, 23, 3, 3, '2025-04-05 15:00:00', 'diagnostic', 'Synthetic visit reason 023', 'Fabricated summary for software testing only; encounter 023.'),
    (24, 'SYN-ENC-0024', 24, 24, 4, 4, '2025-04-09 08:00:00', 'outpatient', 'Synthetic visit reason 024', 'Fabricated summary for software testing only; encounter 024.'),
    (25, 'SYN-ENC-0025', 25, 25, 5, 5, '2025-04-13 09:00:00', 'emergency', 'Synthetic visit reason 025', 'Fabricated summary for software testing only; encounter 025.'),
    (26, 'SYN-ENC-0026', 26, 26, 6, 6, '2025-04-17 10:00:00', 'follow_up', 'Synthetic visit reason 026', 'Fabricated summary for software testing only; encounter 026.'),
    (27, 'SYN-ENC-0027', 27, 27, 7, 7, '2025-04-21 11:00:00', 'diagnostic', 'Synthetic visit reason 027', 'Fabricated summary for software testing only; encounter 027.'),
    (28, 'SYN-ENC-0028', 28, 28, 8, 8, '2025-04-25 12:00:00', 'outpatient', 'Synthetic visit reason 028', 'Fabricated summary for software testing only; encounter 028.'),
    (29, 'SYN-ENC-0029', 29, 29, 9, 1, '2025-04-29 13:00:00', 'emergency', 'Synthetic visit reason 029', 'Fabricated summary for software testing only; encounter 029.'),
    (30, 'SYN-ENC-0030', 30, 30, 10, 2, '2025-05-03 14:00:00', 'follow_up', 'Synthetic visit reason 030', 'Fabricated summary for software testing only; encounter 030.'),
    (31, 'SYN-ENC-0031', 31, 31, 11, 3, '2025-05-07 15:00:00', 'diagnostic', 'Synthetic visit reason 031', 'Fabricated summary for software testing only; encounter 031.'),
    (32, 'SYN-ENC-0032', 32, 32, 12, 4, '2025-05-11 08:00:00', 'outpatient', 'Synthetic visit reason 032', 'Fabricated summary for software testing only; encounter 032.'),
    (33, 'SYN-ENC-0033', 33, 33, 13, 5, '2025-05-15 09:00:00', 'emergency', 'Synthetic visit reason 033', 'Fabricated summary for software testing only; encounter 033.'),
    (34, 'SYN-ENC-0034', 34, 34, 14, 6, '2025-05-19 10:00:00', 'follow_up', 'Synthetic visit reason 034', 'Fabricated summary for software testing only; encounter 034.'),
    (35, 'SYN-ENC-0035', 35, 35, 15, 7, '2025-05-23 11:00:00', 'diagnostic', 'Synthetic visit reason 035', 'Fabricated summary for software testing only; encounter 035.'),
    (36, 'SYN-ENC-0036', 36, 36, 16, 8, '2025-05-27 12:00:00', 'outpatient', 'Synthetic visit reason 036', 'Fabricated summary for software testing only; encounter 036.'),
    (37, 'SYN-ENC-0037', 37, 37, 17, 1, '2025-05-31 13:00:00', 'emergency', 'Synthetic visit reason 037', 'Fabricated summary for software testing only; encounter 037.'),
    (38, 'SYN-ENC-0038', 38, 38, 18, 2, '2025-06-04 14:00:00', 'follow_up', 'Synthetic visit reason 038', 'Fabricated summary for software testing only; encounter 038.'),
    (39, 'SYN-ENC-0039', 39, 39, 19, 3, '2025-06-08 15:00:00', 'diagnostic', 'Synthetic visit reason 039', 'Fabricated summary for software testing only; encounter 039.'),
    (40, 'SYN-ENC-0040', 40, 40, 20, 4, '2025-06-12 08:00:00', 'outpatient', 'Synthetic visit reason 040', 'Fabricated summary for software testing only; encounter 040.'),
    (41, 'SYN-ENC-0041', 41, 41, 1, 1, '2025-06-16 09:00:00', 'emergency', 'Synthetic visit reason 041', 'Fabricated summary for software testing only; encounter 041.'),
    (42, 'SYN-ENC-0042', 42, 42, 2, 2, '2025-06-20 10:00:00', 'follow_up', 'Synthetic visit reason 042', 'Fabricated summary for software testing only; encounter 042.'),
    (43, 'SYN-ENC-0043', 43, 43, 3, 3, '2025-06-24 11:00:00', 'diagnostic', 'Synthetic visit reason 043', 'Fabricated summary for software testing only; encounter 043.'),
    (44, 'SYN-ENC-0044', 44, 44, 4, 4, '2025-06-28 12:00:00', 'outpatient', 'Synthetic visit reason 044', 'Fabricated summary for software testing only; encounter 044.'),
    (45, 'SYN-ENC-0045', 45, 45, 5, 5, '2025-07-02 13:00:00', 'emergency', 'Synthetic visit reason 045', 'Fabricated summary for software testing only; encounter 045.'),
    (46, 'SYN-ENC-0046', 46, 46, 6, 6, '2025-07-06 14:00:00', 'follow_up', 'Synthetic visit reason 046', 'Fabricated summary for software testing only; encounter 046.'),
    (47, 'SYN-ENC-0047', 47, 47, 7, 7, '2025-07-10 15:00:00', 'diagnostic', 'Synthetic visit reason 047', 'Fabricated summary for software testing only; encounter 047.'),
    (48, 'SYN-ENC-0048', 48, 48, 8, 8, '2025-07-14 08:00:00', 'outpatient', 'Synthetic visit reason 048', 'Fabricated summary for software testing only; encounter 048.'),
    (49, 'SYN-ENC-0049', 49, 49, 9, 1, '2025-07-18 09:00:00', 'emergency', 'Synthetic visit reason 049', 'Fabricated summary for software testing only; encounter 049.'),
    (50, 'SYN-ENC-0050', 50, 50, 10, 2, '2025-07-22 10:00:00', 'follow_up', 'Synthetic visit reason 050', 'Fabricated summary for software testing only; encounter 050.'),
    (51, 'SYN-ENC-0051', 51, 51, 11, 3, '2025-07-26 11:00:00', 'diagnostic', 'Synthetic visit reason 051', 'Fabricated summary for software testing only; encounter 051.'),
    (52, 'SYN-ENC-0052', 52, 52, 12, 4, '2025-07-30 12:00:00', 'outpatient', 'Synthetic visit reason 052', 'Fabricated summary for software testing only; encounter 052.'),
    (53, 'SYN-ENC-0053', 53, 53, 13, 5, '2025-08-03 13:00:00', 'emergency', 'Synthetic visit reason 053', 'Fabricated summary for software testing only; encounter 053.'),
    (54, 'SYN-ENC-0054', 54, 54, 14, 6, '2025-08-07 14:00:00', 'follow_up', 'Synthetic visit reason 054', 'Fabricated summary for software testing only; encounter 054.'),
    (55, 'SYN-ENC-0055', 55, 55, 15, 7, '2025-08-11 15:00:00', 'diagnostic', 'Synthetic visit reason 055', 'Fabricated summary for software testing only; encounter 055.'),
    (56, 'SYN-ENC-0056', 56, 56, 16, 8, '2025-08-15 08:00:00', 'outpatient', 'Synthetic visit reason 056', 'Fabricated summary for software testing only; encounter 056.'),
    (57, 'SYN-ENC-0057', 57, 57, 17, 1, '2025-08-19 09:00:00', 'emergency', 'Synthetic visit reason 057', 'Fabricated summary for software testing only; encounter 057.'),
    (58, 'SYN-ENC-0058', 58, 58, 18, 2, '2025-08-23 10:00:00', 'follow_up', 'Synthetic visit reason 058', 'Fabricated summary for software testing only; encounter 058.'),
    (59, 'SYN-ENC-0059', 59, 59, 19, 3, '2025-08-27 11:00:00', 'diagnostic', 'Synthetic visit reason 059', 'Fabricated summary for software testing only; encounter 059.'),
    (60, 'SYN-ENC-0060', 60, 60, 20, 4, '2025-08-31 12:00:00', 'outpatient', 'Synthetic visit reason 060', 'Fabricated summary for software testing only; encounter 060.')
ON CONFLICT DO NOTHING;

-- admissions: 35 fabricated rows; Synthetic admission/discharge workflow and bed-location data.
INSERT INTO mediassist_demo.admissions (admission_id, synthetic_admission_id, patient_id, encounter_id, admitted_on, discharged_on, status, admission_type, ward, room) VALUES
    (1, 'SYN-ADM-0001', 1, 1, '2025-01-07', '2025-01-09', 'discharged', 'emergency', 'Demo Ward 2', 'R101'),
    (2, 'SYN-ADM-0002', 2, 2, '2025-01-11', '2025-01-14', 'discharged', 'observation', 'Demo Ward 3', 'R102'),
    (3, 'SYN-ADM-0003', 3, 3, '2025-01-15', '2025-01-19', 'discharged', 'elective', 'Demo Ward 4', 'R103'),
    (4, 'SYN-ADM-0004', 4, 4, '2025-01-19', '2025-01-24', 'discharged', 'emergency', 'Demo Ward 1', 'R104'),
    (5, 'SYN-ADM-0005', 5, 5, '2025-01-23', '2025-01-24', 'discharged', 'observation', 'Demo Ward 2', 'R105'),
    (6, 'SYN-ADM-0006', 6, 6, '2025-01-27', '2025-01-29', 'discharged', 'elective', 'Demo Ward 3', 'R106'),
    (7, 'SYN-ADM-0007', 7, 7, '2025-01-31', '2025-02-03', 'discharged', 'emergency', 'Demo Ward 4', 'R107'),
    (8, 'SYN-ADM-0008', 8, 8, '2025-02-04', '2025-02-08', 'discharged', 'observation', 'Demo Ward 1', 'R108'),
    (9, 'SYN-ADM-0009', 9, 9, '2025-02-08', '2025-02-13', 'discharged', 'elective', 'Demo Ward 2', 'R109'),
    (10, 'SYN-ADM-0010', 10, 10, '2025-02-12', '2025-02-13', 'discharged', 'emergency', 'Demo Ward 3', 'R110'),
    (11, 'SYN-ADM-0011', 11, 11, '2025-02-16', '2025-02-18', 'discharged', 'observation', 'Demo Ward 4', 'R111'),
    (12, 'SYN-ADM-0012', 12, 12, '2025-02-20', '2025-02-23', 'discharged', 'elective', 'Demo Ward 1', 'R112'),
    (13, 'SYN-ADM-0013', 13, 13, '2025-02-24', '2025-02-28', 'discharged', 'emergency', 'Demo Ward 2', 'R113'),
    (14, 'SYN-ADM-0014', 14, 14, '2025-02-28', '2025-03-05', 'discharged', 'observation', 'Demo Ward 3', 'R114'),
    (15, 'SYN-ADM-0015', 15, 15, '2025-03-04', '2025-03-05', 'discharged', 'elective', 'Demo Ward 4', 'R115'),
    (16, 'SYN-ADM-0016', 16, 16, '2025-03-08', '2025-03-10', 'discharged', 'emergency', 'Demo Ward 1', 'R116'),
    (17, 'SYN-ADM-0017', 17, 17, '2025-03-12', '2025-03-15', 'discharged', 'observation', 'Demo Ward 2', 'R117'),
    (18, 'SYN-ADM-0018', 18, 18, '2025-03-16', '2025-03-20', 'discharged', 'elective', 'Demo Ward 3', 'R118'),
    (19, 'SYN-ADM-0019', 19, 19, '2025-03-20', '2025-03-25', 'discharged', 'emergency', 'Demo Ward 4', 'R119'),
    (20, 'SYN-ADM-0020', 20, 20, '2025-03-24', '2025-03-25', 'discharged', 'observation', 'Demo Ward 1', 'R120'),
    (21, 'SYN-ADM-0021', 21, 21, '2025-03-28', '2025-03-30', 'discharged', 'elective', 'Demo Ward 2', 'R121'),
    (22, 'SYN-ADM-0022', 22, 22, '2025-04-01', '2025-04-04', 'discharged', 'emergency', 'Demo Ward 3', 'R122'),
    (23, 'SYN-ADM-0023', 23, 23, '2025-04-05', '2025-04-09', 'discharged', 'observation', 'Demo Ward 4', 'R123'),
    (24, 'SYN-ADM-0024', 24, 24, '2025-04-09', '2025-04-14', 'discharged', 'elective', 'Demo Ward 1', 'R124'),
    (25, 'SYN-ADM-0025', 25, 25, '2025-04-13', '2025-04-14', 'discharged', 'emergency', 'Demo Ward 2', 'R125'),
    (26, 'SYN-ADM-0026', 26, 26, '2025-04-17', '2025-04-19', 'discharged', 'observation', 'Demo Ward 3', 'R126'),
    (27, 'SYN-ADM-0027', 27, 27, '2025-04-21', '2025-04-24', 'discharged', 'elective', 'Demo Ward 4', 'R127'),
    (28, 'SYN-ADM-0028', 28, 28, '2025-04-25', '2025-04-29', 'discharged', 'emergency', 'Demo Ward 1', 'R128'),
    (29, 'SYN-ADM-0029', 29, 29, '2025-04-29', '2025-05-04', 'discharged', 'observation', 'Demo Ward 2', 'R129'),
    (30, 'SYN-ADM-0030', 30, 30, '2025-05-03', '2025-05-04', 'discharged', 'elective', 'Demo Ward 3', 'R130'),
    (31, 'SYN-ADM-0031', 31, 31, '2025-05-07', NULL, 'in_progress', 'emergency', 'Demo Ward 4', 'R131'),
    (32, 'SYN-ADM-0032', 32, 32, '2025-05-11', NULL, 'in_progress', 'observation', 'Demo Ward 1', 'R132'),
    (33, 'SYN-ADM-0033', 33, 33, '2025-05-15', NULL, 'in_progress', 'elective', 'Demo Ward 2', 'R133'),
    (34, 'SYN-ADM-0034', 34, 34, '2025-05-19', NULL, 'in_progress', 'emergency', 'Demo Ward 3', 'R134'),
    (35, 'SYN-ADM-0035', 35, 35, '2025-05-23', NULL, 'in_progress', 'observation', 'Demo Ward 4', 'R135')
ON CONFLICT DO NOTHING;

-- diagnoses: 45 fabricated rows; Fabricated illustrative encounter labels; not clinical reference data.
INSERT INTO mediassist_demo.diagnoses (diagnosis_id, encounter_id, patient_id, diagnosis_code, diagnosis_name, category, is_primary, recorded_on) VALUES
    (1, 1, 1, 'SYN-DX-001', 'Synthetic elevated blood pressure observation', 'observation', TRUE, '2025-01-07'),
    (2, 2, 2, 'SYN-DX-002', 'Synthetic seasonal allergy note', 'allergy', FALSE, '2025-01-11'),
    (3, 3, 3, 'SYN-DX-003', 'Synthetic wellness review', 'wellness', FALSE, '2025-01-15'),
    (4, 4, 4, 'SYN-DX-004', 'Synthetic respiratory symptom note', 'symptom', TRUE, '2025-01-19'),
    (5, 5, 5, 'SYN-DX-005', 'Synthetic digestive symptom note', 'symptom', FALSE, '2025-01-23'),
    (6, 6, 6, 'SYN-DX-006', 'Synthetic follow-up assessment', 'follow_up', FALSE, '2025-01-27'),
    (7, 7, 7, 'SYN-DX-007', 'Synthetic musculoskeletal symptom note', 'symptom', TRUE, '2025-01-31'),
    (8, 8, 8, 'SYN-DX-008', 'Synthetic laboratory review', 'observation', FALSE, '2025-02-04'),
    (9, 9, 9, 'SYN-DX-001', 'Synthetic elevated blood pressure observation', 'observation', FALSE, '2025-02-08'),
    (10, 10, 10, 'SYN-DX-002', 'Synthetic seasonal allergy note', 'allergy', TRUE, '2025-02-12'),
    (11, 11, 11, 'SYN-DX-003', 'Synthetic wellness review', 'wellness', FALSE, '2025-02-16'),
    (12, 12, 12, 'SYN-DX-004', 'Synthetic respiratory symptom note', 'symptom', FALSE, '2025-02-20'),
    (13, 13, 13, 'SYN-DX-005', 'Synthetic digestive symptom note', 'symptom', TRUE, '2025-02-24'),
    (14, 14, 14, 'SYN-DX-006', 'Synthetic follow-up assessment', 'follow_up', FALSE, '2025-02-28'),
    (15, 15, 15, 'SYN-DX-007', 'Synthetic musculoskeletal symptom note', 'symptom', FALSE, '2025-03-04'),
    (16, 16, 16, 'SYN-DX-008', 'Synthetic laboratory review', 'observation', TRUE, '2025-03-08'),
    (17, 17, 17, 'SYN-DX-001', 'Synthetic elevated blood pressure observation', 'observation', FALSE, '2025-03-12'),
    (18, 18, 18, 'SYN-DX-002', 'Synthetic seasonal allergy note', 'allergy', FALSE, '2025-03-16'),
    (19, 19, 19, 'SYN-DX-003', 'Synthetic wellness review', 'wellness', TRUE, '2025-03-20'),
    (20, 20, 20, 'SYN-DX-004', 'Synthetic respiratory symptom note', 'symptom', FALSE, '2025-03-24'),
    (21, 21, 21, 'SYN-DX-005', 'Synthetic digestive symptom note', 'symptom', FALSE, '2025-03-28'),
    (22, 22, 22, 'SYN-DX-006', 'Synthetic follow-up assessment', 'follow_up', TRUE, '2025-04-01'),
    (23, 23, 23, 'SYN-DX-007', 'Synthetic musculoskeletal symptom note', 'symptom', FALSE, '2025-04-05'),
    (24, 24, 24, 'SYN-DX-008', 'Synthetic laboratory review', 'observation', FALSE, '2025-04-09'),
    (25, 25, 25, 'SYN-DX-001', 'Synthetic elevated blood pressure observation', 'observation', TRUE, '2025-04-13'),
    (26, 26, 26, 'SYN-DX-002', 'Synthetic seasonal allergy note', 'allergy', FALSE, '2025-04-17'),
    (27, 27, 27, 'SYN-DX-003', 'Synthetic wellness review', 'wellness', FALSE, '2025-04-21'),
    (28, 28, 28, 'SYN-DX-004', 'Synthetic respiratory symptom note', 'symptom', TRUE, '2025-04-25'),
    (29, 29, 29, 'SYN-DX-005', 'Synthetic digestive symptom note', 'symptom', FALSE, '2025-04-29'),
    (30, 30, 30, 'SYN-DX-006', 'Synthetic follow-up assessment', 'follow_up', FALSE, '2025-05-03'),
    (31, 31, 31, 'SYN-DX-007', 'Synthetic musculoskeletal symptom note', 'symptom', TRUE, '2025-05-07'),
    (32, 32, 32, 'SYN-DX-008', 'Synthetic laboratory review', 'observation', FALSE, '2025-05-11'),
    (33, 33, 33, 'SYN-DX-001', 'Synthetic elevated blood pressure observation', 'observation', FALSE, '2025-05-15'),
    (34, 34, 34, 'SYN-DX-002', 'Synthetic seasonal allergy note', 'allergy', TRUE, '2025-05-19'),
    (35, 35, 35, 'SYN-DX-003', 'Synthetic wellness review', 'wellness', FALSE, '2025-05-23'),
    (36, 36, 36, 'SYN-DX-004', 'Synthetic respiratory symptom note', 'symptom', FALSE, '2025-05-27'),
    (37, 37, 37, 'SYN-DX-005', 'Synthetic digestive symptom note', 'symptom', TRUE, '2025-05-31'),
    (38, 38, 38, 'SYN-DX-006', 'Synthetic follow-up assessment', 'follow_up', FALSE, '2025-06-04'),
    (39, 39, 39, 'SYN-DX-007', 'Synthetic musculoskeletal symptom note', 'symptom', FALSE, '2025-06-08'),
    (40, 40, 40, 'SYN-DX-008', 'Synthetic laboratory review', 'observation', TRUE, '2025-06-12'),
    (41, 41, 41, 'SYN-DX-001', 'Synthetic elevated blood pressure observation', 'observation', FALSE, '2025-06-16'),
    (42, 42, 42, 'SYN-DX-002', 'Synthetic seasonal allergy note', 'allergy', FALSE, '2025-06-20'),
    (43, 43, 43, 'SYN-DX-003', 'Synthetic wellness review', 'wellness', TRUE, '2025-06-24'),
    (44, 44, 44, 'SYN-DX-004', 'Synthetic respiratory symptom note', 'symptom', FALSE, '2025-06-28'),
    (45, 45, 45, 'SYN-DX-005', 'Synthetic digestive symptom note', 'symptom', FALSE, '2025-07-02')
ON CONFLICT DO NOTHING;

-- lab_results: 50 fabricated rows; Fabricated demo lab observations and reference bands; not for clinical interpretation.
INSERT INTO mediassist_demo.lab_results (lab_result_id, synthetic_order_id, encounter_id, patient_id, ordered_by_provider_id, test_name, result_value, unit, reference_low, reference_high, flag, collected_at, status) VALUES
    (1, 'SYN-LAB-0001', 1, 1, 1, 'Demo hemoglobin', 13.8, 'g/dL', 12.0, 17.5, 'normal', '2025-01-07 10:00:00', 'final'),
    (2, 'SYN-LAB-0002', 2, 2, 2, 'Demo glucose', 96.0, 'mg/dL', 70.0, 110.0, 'normal', '2025-01-11 11:00:00', 'final'),
    (3, 'SYN-LAB-0003', 3, 3, 3, 'Demo sodium', 139.0, 'mmol/L', 135.0, 145.0, 'normal', '2025-01-15 12:00:00', 'final'),
    (4, 'SYN-LAB-0004', 4, 4, 4, 'Demo potassium', 4.1, 'mmol/L', 3.5, 5.1, 'normal', '2025-01-19 13:00:00', 'final'),
    (5, 'SYN-LAB-0005', 5, 5, 5, 'Demo creatinine', 0.9, 'mg/dL', 0.6, 1.3, 'normal', '2025-01-23 14:00:00', 'final'),
    (6, 'SYN-LAB-0006', 6, 6, 6, 'Demo white cell count', 7.2, '10^9/L', 4.0, 11.0, 'normal', '2025-01-27 15:00:00', 'final'),
    (7, 'SYN-LAB-0007', 7, 7, 7, 'Demo platelet count', 250.0, '10^9/L', 150.0, 400.0, 'normal', '2025-01-31 16:00:00', 'final'),
    (8, 'SYN-LAB-0008', 8, 8, 8, 'Demo total cholesterol', 185.0, 'mg/dL', 0.0, 200.0, 'normal', '2025-02-04 09:00:00', 'final'),
    (9, 'SYN-LAB-0009', 9, 9, 9, 'Demo oxygen saturation', 98.0, '%', 95.0, 100.0, 'normal', '2025-02-08 10:00:00', 'final'),
    (10, 'SYN-LAB-0010', 10, 10, 10, 'Demo temperature', 36.8, 'C', 36.0, 37.5, 'normal', '2025-02-12 11:00:00', 'final'),
    (11, 'SYN-LAB-0011', 11, 11, 11, 'Demo hemoglobin', 19.5, 'g/dL', 12.0, 17.5, 'high', '2025-02-16 12:00:00', 'final'),
    (12, 'SYN-LAB-0012', 12, 12, 12, 'Demo glucose', 96.0, 'mg/dL', 70.0, 110.0, 'normal', '2025-02-20 13:00:00', 'final'),
    (13, 'SYN-LAB-0013', 13, 13, 13, 'Demo sodium', 134.0, 'mmol/L', 135.0, 145.0, 'low', '2025-02-24 14:00:00', 'final'),
    (14, 'SYN-LAB-0014', 14, 14, 14, 'Demo potassium', 4.1, 'mmol/L', 3.5, 5.1, 'normal', '2025-02-28 15:00:00', 'final'),
    (15, 'SYN-LAB-0015', 15, 15, 15, 'Demo creatinine', 0.9, 'mg/dL', 0.6, 1.3, 'normal', '2025-03-04 16:00:00', 'final'),
    (16, 'SYN-LAB-0016', 16, 16, 16, 'Demo white cell count', 7.2, '10^9/L', 4.0, 11.0, 'normal', '2025-03-08 09:00:00', 'final'),
    (17, 'SYN-LAB-0017', 17, 17, 17, 'Demo platelet count', 250.0, '10^9/L', 150.0, 400.0, 'normal', '2025-03-12 10:00:00', 'final'),
    (18, 'SYN-LAB-0018', 18, 18, 18, 'Demo total cholesterol', 185.0, 'mg/dL', 0.0, 200.0, 'normal', '2025-03-16 11:00:00', 'final'),
    (19, 'SYN-LAB-0019', 19, 19, 19, 'Demo oxygen saturation', 98.0, '%', 95.0, 100.0, 'normal', '2025-03-20 12:00:00', 'final'),
    (20, 'SYN-LAB-0020', 20, 20, 20, 'Demo temperature', 36.8, 'C', 36.0, 37.5, 'normal', '2025-03-24 13:00:00', 'final'),
    (21, 'SYN-LAB-0021', 21, 21, 1, 'Demo hemoglobin', 13.8, 'g/dL', 12.0, 17.5, 'normal', '2025-03-28 14:00:00', 'final'),
    (22, 'SYN-LAB-0022', 22, 22, 2, 'Demo glucose', 112.0, 'mg/dL', 70.0, 110.0, 'high', '2025-04-01 15:00:00', 'final'),
    (23, 'SYN-LAB-0023', 23, 23, 3, 'Demo sodium', 139.0, 'mmol/L', 135.0, 145.0, 'normal', '2025-04-05 16:00:00', 'final'),
    (24, 'SYN-LAB-0024', 24, 24, 4, 'Demo potassium', 4.1, 'mmol/L', 3.5, 5.1, 'normal', '2025-04-09 09:00:00', 'final'),
    (25, 'SYN-LAB-0025', 25, 25, 5, 'Demo creatinine', 0.9, 'mg/dL', 0.6, 1.3, 'normal', '2025-04-13 10:00:00', 'final'),
    (26, 'SYN-LAB-0026', 26, 26, 6, 'Demo white cell count', 3.0, '10^9/L', 4.0, 11.0, 'low', '2025-04-17 11:00:00', 'final'),
    (27, 'SYN-LAB-0027', 27, 27, 7, 'Demo platelet count', 250.0, '10^9/L', 150.0, 400.0, 'normal', '2025-04-21 12:00:00', 'final'),
    (28, 'SYN-LAB-0028', 28, 28, 8, 'Demo total cholesterol', 185.0, 'mg/dL', 0.0, 200.0, 'normal', '2025-04-25 13:00:00', 'final'),
    (29, 'SYN-LAB-0029', 29, 29, 9, 'Demo oxygen saturation', 98.0, '%', 95.0, 100.0, 'normal', '2025-04-29 14:00:00', 'final'),
    (30, 'SYN-LAB-0030', 30, 30, 10, 'Demo temperature', 36.8, 'C', 36.0, 37.5, 'normal', '2025-05-03 15:00:00', 'final'),
    (31, 'SYN-LAB-0031', 31, 31, 11, 'Demo hemoglobin', 13.8, 'g/dL', 12.0, 17.5, 'normal', '2025-05-07 16:00:00', 'final'),
    (32, 'SYN-LAB-0032', 32, 32, 12, 'Demo glucose', 96.0, 'mg/dL', 70.0, 110.0, 'normal', '2025-05-11 09:00:00', 'final'),
    (33, 'SYN-LAB-0033', 33, 33, 13, 'Demo sodium', 147.0, 'mmol/L', 135.0, 145.0, 'high', '2025-05-15 10:00:00', 'final'),
    (34, 'SYN-LAB-0034', 34, 34, 14, 'Demo potassium', 4.1, 'mmol/L', 3.5, 5.1, 'normal', '2025-05-19 11:00:00', 'final'),
    (35, 'SYN-LAB-0035', 35, 35, 15, 'Demo creatinine', 0.9, 'mg/dL', 0.6, 1.3, 'normal', '2025-05-23 12:00:00', 'final'),
    (36, 'SYN-LAB-0036', 36, 36, 16, 'Demo white cell count', 7.2, '10^9/L', 4.0, 11.0, 'normal', '2025-05-27 13:00:00', 'final'),
    (37, 'SYN-LAB-0037', 37, 37, 17, 'Demo platelet count', 250.0, '10^9/L', 150.0, 400.0, 'normal', '2025-05-31 14:00:00', 'final'),
    (38, 'SYN-LAB-0038', 38, 38, 18, 'Demo total cholesterol', 185.0, 'mg/dL', 0.0, 200.0, 'normal', '2025-06-04 15:00:00', 'final'),
    (39, 'SYN-LAB-0039', 39, 39, 19, 'Demo oxygen saturation', 94.0, '%', 95.0, 100.0, 'low', '2025-06-08 16:00:00', 'final'),
    (40, 'SYN-LAB-0040', 40, 40, 20, 'Demo temperature', 36.8, 'C', 36.0, 37.5, 'normal', '2025-06-12 09:00:00', 'final'),
    (41, 'SYN-LAB-0041', 41, 41, 1, 'Demo hemoglobin', 13.8, 'g/dL', 12.0, 17.5, 'normal', '2025-06-16 10:00:00', 'final'),
    (42, 'SYN-LAB-0042', 42, 42, 2, 'Demo glucose', 96.0, 'mg/dL', 70.0, 110.0, 'normal', '2025-06-20 11:00:00', 'final'),
    (43, 'SYN-LAB-0043', 43, 43, 3, 'Demo sodium', 139.0, 'mmol/L', 135.0, 145.0, 'normal', '2025-06-24 12:00:00', 'final'),
    (44, 'SYN-LAB-0044', 44, 44, 4, 'Demo potassium', 7.1, 'mmol/L', 3.5, 5.1, 'high', '2025-06-28 13:00:00', 'final'),
    (45, 'SYN-LAB-0045', 45, 45, 5, 'Demo creatinine', 0.9, 'mg/dL', 0.6, 1.3, 'normal', '2025-07-02 14:00:00', 'final'),
    (46, 'SYN-LAB-0046', 46, 46, 6, 'Demo white cell count', 7.2, '10^9/L', 4.0, 11.0, 'normal', '2025-07-06 15:00:00', 'final'),
    (47, 'SYN-LAB-0047', 47, 47, 7, 'Demo platelet count', 250.0, '10^9/L', 150.0, 400.0, 'normal', '2025-07-10 16:00:00', 'final'),
    (48, 'SYN-LAB-0048', 48, 48, 8, 'Demo total cholesterol', 185.0, 'mg/dL', 0.0, 200.0, 'normal', '2025-07-14 09:00:00', 'final'),
    (49, 'SYN-LAB-0049', 49, 49, 9, 'Demo oxygen saturation', 98.0, '%', 95.0, 100.0, 'normal', '2025-07-18 10:00:00', 'final'),
    (50, 'SYN-LAB-0050', 50, 50, 10, 'Demo temperature', 36.8, 'C', 36.0, 37.5, 'normal', '2025-07-22 11:00:00', 'final')
ON CONFLICT DO NOTHING;

-- medication_orders: 35 fabricated rows; Fictional placeholder medication orders for workflow testing only.
INSERT INTO mediassist_demo.medication_orders (medication_order_id, synthetic_order_id, encounter_id, patient_id, ordered_by_provider_id, medication_name, dose, route, frequency, start_date, end_date, status, notes) VALUES
    (1, 'SYN-MED-0001', 1, 1, 1, 'Demo medication A', '10 mg', 'oral', 'once daily', '2025-01-07', '2025-01-15', 'completed', 'Synthetic demo order; not for clinical use.'),
    (2, 'SYN-MED-0002', 2, 2, 2, 'Demo medication B', '5 mg', 'oral', 'twice daily', '2025-01-11', '2025-01-20', 'completed', 'Synthetic demo order; not for clinical use.'),
    (3, 'SYN-MED-0003', 3, 3, 3, 'Demo medication C', '250 mg', 'oral', 'as documented', '2025-01-15', '2025-01-25', 'completed', 'Synthetic demo order; not for clinical use.'),
    (4, 'SYN-MED-0004', 4, 4, 4, 'Demo topical preparation', 'apply as documented', 'topical', 'as documented', '2025-01-19', '2025-01-30', 'active', 'Synthetic demo order; not for clinical use.'),
    (5, 'SYN-MED-0005', 5, 5, 5, 'Demo supplement', '1 unit', 'oral', 'once daily', '2025-01-23', '2025-02-04', 'completed', 'Synthetic demo order; not for clinical use.'),
    (6, 'SYN-MED-0006', 6, 6, 6, 'Demo medication A', '10 mg', 'oral', 'once daily', '2025-01-27', '2025-02-09', 'completed', 'Synthetic demo order; not for clinical use.'),
    (7, 'SYN-MED-0007', 7, 7, 7, 'Demo medication B', '5 mg', 'oral', 'twice daily', '2025-01-31', '2025-02-14', 'completed', 'Synthetic demo order; not for clinical use.'),
    (8, 'SYN-MED-0008', 8, 8, 8, 'Demo medication C', '250 mg', 'oral', 'as documented', '2025-02-04', '2025-02-19', 'active', 'Synthetic demo order; not for clinical use.'),
    (9, 'SYN-MED-0009', 9, 9, 9, 'Demo topical preparation', 'apply as documented', 'topical', 'as documented', '2025-02-08', '2025-02-24', 'completed', 'Synthetic demo order; not for clinical use.'),
    (10, 'SYN-MED-0010', 10, 10, 10, 'Demo supplement', '1 unit', 'oral', 'once daily', '2025-02-12', '2025-03-01', 'completed', 'Synthetic demo order; not for clinical use.'),
    (11, 'SYN-MED-0011', 11, 11, 11, 'Demo medication A', '10 mg', 'oral', 'once daily', '2025-02-16', '2025-03-06', 'completed', 'Synthetic demo order; not for clinical use.'),
    (12, 'SYN-MED-0012', 12, 12, 12, 'Demo medication B', '5 mg', 'oral', 'twice daily', '2025-02-20', '2025-03-11', 'active', 'Synthetic demo order; not for clinical use.'),
    (13, 'SYN-MED-0013', 13, 13, 13, 'Demo medication C', '250 mg', 'oral', 'as documented', '2025-02-24', '2025-03-16', 'completed', 'Synthetic demo order; not for clinical use.'),
    (14, 'SYN-MED-0014', 14, 14, 14, 'Demo topical preparation', 'apply as documented', 'topical', 'as documented', '2025-02-28', '2025-03-21', 'completed', 'Synthetic demo order; not for clinical use.'),
    (15, 'SYN-MED-0015', 15, 15, 15, 'Demo supplement', '1 unit', 'oral', 'once daily', '2025-03-04', '2025-03-26', 'completed', 'Synthetic demo order; not for clinical use.'),
    (16, 'SYN-MED-0016', 16, 16, 16, 'Demo medication A', '10 mg', 'oral', 'once daily', '2025-03-08', '2025-03-31', 'active', 'Synthetic demo order; not for clinical use.'),
    (17, 'SYN-MED-0017', 17, 17, 17, 'Demo medication B', '5 mg', 'oral', 'twice daily', '2025-03-12', '2025-04-05', 'completed', 'Synthetic demo order; not for clinical use.'),
    (18, 'SYN-MED-0018', 18, 18, 18, 'Demo medication C', '250 mg', 'oral', 'as documented', '2025-03-16', '2025-04-10', 'completed', 'Synthetic demo order; not for clinical use.'),
    (19, 'SYN-MED-0019', 19, 19, 19, 'Demo topical preparation', 'apply as documented', 'topical', 'as documented', '2025-03-20', '2025-04-15', 'completed', 'Synthetic demo order; not for clinical use.'),
    (20, 'SYN-MED-0020', 20, 20, 20, 'Demo supplement', '1 unit', 'oral', 'once daily', '2025-03-24', '2025-04-20', 'active', 'Synthetic demo order; not for clinical use.'),
    (21, 'SYN-MED-0021', 21, 21, 1, 'Demo medication A', '10 mg', 'oral', 'once daily', '2025-03-28', '2025-04-04', 'completed', 'Synthetic demo order; not for clinical use.'),
    (22, 'SYN-MED-0022', 22, 22, 2, 'Demo medication B', '5 mg', 'oral', 'twice daily', '2025-04-01', '2025-04-09', 'completed', 'Synthetic demo order; not for clinical use.'),
    (23, 'SYN-MED-0023', 23, 23, 3, 'Demo medication C', '250 mg', 'oral', 'as documented', '2025-04-05', '2025-04-14', 'completed', 'Synthetic demo order; not for clinical use.'),
    (24, 'SYN-MED-0024', 24, 24, 4, 'Demo topical preparation', 'apply as documented', 'topical', 'as documented', '2025-04-09', '2025-04-19', 'active', 'Synthetic demo order; not for clinical use.'),
    (25, 'SYN-MED-0025', 25, 25, 5, 'Demo supplement', '1 unit', 'oral', 'once daily', '2025-04-13', '2025-04-24', 'completed', 'Synthetic demo order; not for clinical use.'),
    (26, 'SYN-MED-0026', 26, 26, 6, 'Demo medication A', '10 mg', 'oral', 'once daily', '2025-04-17', '2025-04-29', 'completed', 'Synthetic demo order; not for clinical use.'),
    (27, 'SYN-MED-0027', 27, 27, 7, 'Demo medication B', '5 mg', 'oral', 'twice daily', '2025-04-21', '2025-05-04', 'completed', 'Synthetic demo order; not for clinical use.'),
    (28, 'SYN-MED-0028', 28, 28, 8, 'Demo medication C', '250 mg', 'oral', 'as documented', '2025-04-25', '2025-05-09', 'active', 'Synthetic demo order; not for clinical use.'),
    (29, 'SYN-MED-0029', 29, 29, 9, 'Demo topical preparation', 'apply as documented', 'topical', 'as documented', '2025-04-29', '2025-05-14', 'completed', 'Synthetic demo order; not for clinical use.'),
    (30, 'SYN-MED-0030', 30, 30, 10, 'Demo supplement', '1 unit', 'oral', 'once daily', '2025-05-03', '2025-05-19', 'completed', 'Synthetic demo order; not for clinical use.'),
    (31, 'SYN-MED-0031', 31, 31, 11, 'Demo medication A', '10 mg', 'oral', 'once daily', '2025-05-07', '2025-05-24', 'completed', 'Synthetic demo order; not for clinical use.'),
    (32, 'SYN-MED-0032', 32, 32, 12, 'Demo medication B', '5 mg', 'oral', 'twice daily', '2025-05-11', '2025-05-29', 'active', 'Synthetic demo order; not for clinical use.'),
    (33, 'SYN-MED-0033', 33, 33, 13, 'Demo medication C', '250 mg', 'oral', 'as documented', '2025-05-15', '2025-06-03', 'completed', 'Synthetic demo order; not for clinical use.'),
    (34, 'SYN-MED-0034', 34, 34, 14, 'Demo topical preparation', 'apply as documented', 'topical', 'as documented', '2025-05-19', '2025-06-08', 'completed', 'Synthetic demo order; not for clinical use.'),
    (35, 'SYN-MED-0035', 35, 35, 15, 'Demo supplement', '1 unit', 'oral', 'once daily', '2025-05-23', '2025-06-13', 'completed', 'Synthetic demo order; not for clinical use.')
ON CONFLICT DO NOTHING;

-- insurance_claims: 20 fabricated rows; Synthetic insurance claim lifecycle and fabricated amounts.
INSERT INTO mediassist_demo.insurance_claims (claim_id, synthetic_claim_id, insurance_id, encounter_id, patient_id, submitted_on, status, billed_amount, approved_amount, denial_reason) VALUES
    (1, 'SYN-CLM-0001', 1, 1, 1, '2025-03-10', 'submitted', 162.00, 0.00, NULL),
    (2, 'SYN-CLM-0002', 2, 2, 2, '2025-03-19', 'approved', 199.00, 199.00, NULL),
    (3, 'SYN-CLM-0003', 3, 3, 3, '2025-03-28', 'denied', 236.00, 0.00, 'Synthetic missing attachment'),
    (4, 'SYN-CLM-0004', 4, 4, 4, '2025-04-06', 'pending', 273.00, 0.00, NULL),
    (5, 'SYN-CLM-0005', 5, 5, 5, '2025-04-15', 'partially_approved', 310.00, 186.00, NULL),
    (6, 'SYN-CLM-0006', 6, 6, 6, '2025-04-24', 'submitted', 347.00, 0.00, NULL),
    (7, 'SYN-CLM-0007', 7, 7, 7, '2025-05-03', 'approved', 384.00, 384.00, NULL),
    (8, 'SYN-CLM-0008', 8, 8, 8, '2025-05-12', 'denied', 421.00, 0.00, 'Synthetic missing attachment'),
    (9, 'SYN-CLM-0009', 9, 9, 9, '2025-05-21', 'pending', 458.00, 0.00, NULL),
    (10, 'SYN-CLM-0010', 10, 10, 10, '2025-05-30', 'partially_approved', 495.00, 297.00, NULL),
    (11, 'SYN-CLM-0011', 11, 11, 11, '2025-06-08', 'submitted', 532.00, 0.00, NULL),
    (12, 'SYN-CLM-0012', 12, 12, 12, '2025-06-17', 'approved', 569.00, 569.00, NULL),
    (13, 'SYN-CLM-0013', 13, 13, 13, '2025-06-26', 'denied', 606.00, 0.00, 'Synthetic missing attachment'),
    (14, 'SYN-CLM-0014', 14, 14, 14, '2025-07-05', 'pending', 643.00, 0.00, NULL),
    (15, 'SYN-CLM-0015', 15, 15, 15, '2025-07-14', 'partially_approved', 680.00, 408.00, NULL),
    (16, 'SYN-CLM-0016', 16, 16, 16, '2025-07-23', 'submitted', 717.00, 0.00, NULL),
    (17, 'SYN-CLM-0017', 17, 17, 17, '2025-08-01', 'approved', 754.00, 754.00, NULL),
    (18, 'SYN-CLM-0018', 18, 18, 18, '2025-08-10', 'denied', 791.00, 0.00, 'Synthetic missing attachment'),
    (19, 'SYN-CLM-0019', 19, 19, 19, '2025-08-19', 'pending', 828.00, 0.00, NULL),
    (20, 'SYN-CLM-0020', 20, 20, 20, '2025-08-28', 'partially_approved', 865.00, 519.00, NULL)
ON CONFLICT DO NOTHING;

-- invoices: 12 fabricated rows; Synthetic billing invoices linked to encounters and claims.
INSERT INTO mediassist_demo.invoices (invoice_id, synthetic_invoice_id, encounter_id, claim_id, patient_id, issued_on, due_on, total_amount, status) VALUES
    (1, 'SYN-INV-0001', 1, 1, 1, '2025-04-09', '2025-05-09', 162.00, 'paid'),
    (2, 'SYN-INV-0002', 2, 2, 2, '2025-04-17', '2025-05-17', 199.00, 'paid'),
    (3, 'SYN-INV-0003', 3, 3, 3, '2025-04-25', '2025-05-25', 236.00, 'paid'),
    (4, 'SYN-INV-0004', 4, 4, 4, '2025-05-03', '2025-06-02', 273.00, 'paid'),
    (5, 'SYN-INV-0005', 5, 5, 5, '2025-05-11', '2025-06-10', 310.00, 'paid'),
    (6, 'SYN-INV-0006', 6, 6, 6, '2025-05-19', '2025-06-18', 347.00, 'under_review'),
    (7, 'SYN-INV-0007', 7, 7, 7, '2025-05-27', '2025-06-26', 384.00, 'open'),
    (8, 'SYN-INV-0008', 8, 8, 8, '2025-06-04', '2025-07-04', 421.00, 'under_review'),
    (9, 'SYN-INV-0009', 9, 9, 9, '2025-06-12', '2025-07-12', 458.00, 'open'),
    (10, 'SYN-INV-0010', 10, 10, 10, '2025-06-20', '2025-07-20', 495.00, 'under_review'),
    (11, 'SYN-INV-0011', 11, 11, 11, '2025-06-28', '2025-07-28', 532.00, 'open'),
    (12, 'SYN-INV-0012', 12, 12, 12, '2025-07-06', '2025-08-05', 569.00, 'under_review')
ON CONFLICT DO NOTHING;

-- payments: 5 fabricated rows; Fabricated payment records linked to invoices.
INSERT INTO mediassist_demo.payments (payment_id, synthetic_payment_id, invoice_id, amount, paid_on, payment_method, reference_code) VALUES
    (1, 'SYN-PAY-0001', 1, 162.00, '2025-05-10', 'demo_transfer', 'SYN-REF-0001'),
    (2, 'SYN-PAY-0002', 2, 199.00, '2025-05-19', 'demo_cash', 'SYN-REF-0002'),
    (3, 'SYN-PAY-0003', 3, 236.00, '2025-05-28', 'demo_card', 'SYN-REF-0003'),
    (4, 'SYN-PAY-0004', 4, 273.00, '2025-06-06', 'demo_transfer', 'SYN-REF-0004'),
    (5, 'SYN-PAY-0005', 5, 310.00, '2025-06-15', 'demo_cash', 'SYN-REF-0005')
ON CONFLICT DO NOTHING;

-- Verification: each table count and the combined total should be 500.
SELECT 'departments' AS table_name, COUNT(*) AS row_count FROM mediassist_demo.departments UNION ALL
SELECT 'providers', COUNT(*) FROM mediassist_demo.providers UNION ALL
SELECT 'patients', COUNT(*) FROM mediassist_demo.patients UNION ALL
SELECT 'patient_insurance', COUNT(*) FROM mediassist_demo.patient_insurance UNION ALL
SELECT 'appointments', COUNT(*) FROM mediassist_demo.appointments UNION ALL
SELECT 'encounters', COUNT(*) FROM mediassist_demo.encounters UNION ALL
SELECT 'admissions', COUNT(*) FROM mediassist_demo.admissions UNION ALL
SELECT 'diagnoses', COUNT(*) FROM mediassist_demo.diagnoses UNION ALL
SELECT 'lab_results', COUNT(*) FROM mediassist_demo.lab_results UNION ALL
SELECT 'medication_orders', COUNT(*) FROM mediassist_demo.medication_orders UNION ALL
SELECT 'insurance_claims', COUNT(*) FROM mediassist_demo.insurance_claims UNION ALL
SELECT 'invoices', COUNT(*) FROM mediassist_demo.invoices UNION ALL
SELECT 'payments', COUNT(*) FROM mediassist_demo.payments;

-- Functional example 1: synthetic patient history (replace the demo patient ID).
SELECT p.synthetic_patient_id, e.synthetic_encounter_id, e.encounter_at, e.encounter_type, e.summary
FROM mediassist_demo.patients AS p JOIN mediassist_demo.encounters AS e USING (patient_id)
WHERE p.synthetic_patient_id = 'SYN-P-0001' ORDER BY e.encounter_at DESC;

-- Functional example 2: lab history for one synthetic patient.
SELECT p.synthetic_patient_id, l.test_name, l.result_value, l.unit, l.flag, l.collected_at
FROM mediassist_demo.patients AS p JOIN mediassist_demo.lab_results AS l USING (patient_id)
WHERE p.synthetic_patient_id = 'SYN-P-0001' ORDER BY l.collected_at DESC;

-- Functional example 3: admission and discharge status.
SELECT p.synthetic_patient_id, a.synthetic_admission_id, a.admitted_on, a.discharged_on, a.status, a.ward, a.room
FROM mediassist_demo.patients AS p JOIN mediassist_demo.admissions AS a USING (patient_id)
WHERE p.synthetic_patient_id = 'SYN-P-0001' ORDER BY a.admitted_on DESC;

-- Functional example 4: claim and invoice status/amounts.
SELECT p.synthetic_patient_id, c.synthetic_claim_id, c.status AS claim_status, c.billed_amount, c.approved_amount,
       i.synthetic_invoice_id, i.total_amount, i.status AS invoice_status,
       COALESCE(SUM(pay.amount), 0) AS total_paid
FROM mediassist_demo.patients AS p
JOIN mediassist_demo.insurance_claims AS c USING (patient_id)
LEFT JOIN mediassist_demo.invoices AS i ON i.claim_id = c.claim_id
LEFT JOIN mediassist_demo.payments AS pay ON pay.invoice_id = i.invoice_id
WHERE p.synthetic_patient_id = 'SYN-P-0001'
GROUP BY p.synthetic_patient_id, c.synthetic_claim_id, c.status, c.billed_amount, c.approved_amount, i.synthetic_invoice_id, i.total_amount, i.status;

-- Functional example 5: provider schedule by day (edit the date as needed).
SELECT a.scheduled_at, a.status, a.reason, p.display_name AS provider, d.department_name, patient.synthetic_patient_id
FROM mediassist_demo.appointments AS a
JOIN mediassist_demo.providers AS p USING (provider_id)
JOIN mediassist_demo.departments AS d USING (department_id)
JOIN mediassist_demo.patients AS patient USING (patient_id)
WHERE a.scheduled_at::date = DATE '2025-01-07' ORDER BY a.scheduled_at;

-- Functional example 6: search by synthetic patient ID or fabricated name.
SELECT synthetic_patient_id, first_name, last_name FROM mediassist_demo.patients
WHERE synthetic_patient_id ILIKE '%0001%' OR first_name ILIKE '%Avery%' ORDER BY synthetic_patient_id LIMIT 20;
