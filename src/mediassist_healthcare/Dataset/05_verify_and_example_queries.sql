-- Step 5 of 5: verify row counts and try read-only demo queries.
-- Paste this whole file into Aiven SQL editor and run once.

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
