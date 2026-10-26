# Alpha test script (NFR-USE-02)

3–5 classmates each play one role for about 20 minutes, then fill in the SUS questionnaire
(`sus-form.md`). Target: mean SUS ≥ 70. The facilitator only reads out the tasks, does not
help, and notes where people hesitate.

## Before the session
1. Start the platform (`./scripts/dev.sh`, then `npm run dev` in `web/`), then run
   `scripts/seed_demo.py`.
2. Hand each participant one demo account from `scripts/seed_demo.py` (development
   passwords only).
3. Tell everyone: this is a teaching prototype with invented patients, not a medical
   device.

## Tasks per role

**Designer** (designer@adaptivecare.test)
1. Open the Triage pathway. Find the step that calculates the early warning score.
2. Make a new draft, add a task "Pain relief" for nurses after the confirmation, and verify.
3. Break it on purpose: add a parallel split without its join. Verify, then use the
   step-by-step replay to see why it is unsafe.
4. Simulate the published version with 2 and then 4 nurses. Compare the two runs: what
   changes?

**Nurse** (nurse@adaptivecare.test)
1. Register a new patient who arrived by ambulance with chest pain.
2. Find that patient's "Measure vital signs" task, take it and enter the vital signs.
3. Look at the model's suggestion and the NEWS2 score. Choose a different urgency level:
   what does the system ask for?
4. Find a free bed in ward W1.

**Doctor** (doctor@adaptivecare.test)
1. Complete the imaging task for the patient the nurse registered.
2. Decide to admit the patient. Then find the patient's whole journey (Monitoring → Cases).

**Manager** (manager@adaptivecare.test)
1. On the dashboard, find how many tasks missed their deadline today.
2. Find a case where a nurse changed the model's suggestion, and the reason given (Monitoring → Cases).

**Admin** (admin@adaptivecare.test)
1. Add yourself as an email contact for charge nurse alerts.
2. Deploy the designer's new version. Check that every service is healthy.

## After the session
Enter each questionnaire as one row of `sus-results.csv`, then run
`.venv/bin/python scripts/sus_score.py docs/alpha-test/sus-results.csv`, and copy the
output and the facilitator's notes into the report (Section 15).
