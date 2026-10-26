"""Test-wide settings. The patient service refuses to start without a data secret
(NFR-SEC-05); tests use this throwaway one, never a real key."""

import os

os.environ.setdefault("PATIENT_DATA_SECRET", "test-only-patient-secret-0123456789abcdef")
