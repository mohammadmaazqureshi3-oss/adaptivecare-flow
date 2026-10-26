"""NFR-SEC-05: patient name and date of birth encrypted at rest; keys outside the repository.

One secret, ``PATIENT_DATA_SECRET`` (from the environment, never from code), gives two
keys through HKDF: a Fernet key (AES-128-CBC with an HMAC-SHA256 tag) that encrypts the
values, and an HMAC key for the *blind index*: keyed hashes that let the service find a
patient by name or spot a duplicate without storing anything readable.

The index holds a hash of every prefix of every name word ("lo", "lov", ... "lovelace"),
so search works by the start of any word of the name. What it reveals is only which
records share a prefix, never the letters (decision 0007).
"""

from __future__ import annotations

import hashlib
import hmac
import os
from base64 import urlsafe_b64encode
from datetime import date

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

MIN_SECRET = 32
MAX_PREFIX = 20


def _derive(secret: str, purpose: bytes) -> bytes:
    hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=b"adaptivecare-patient", info=purpose)
    return hkdf.derive(secret.encode())


class Vault:
    """Encrypts identifiers and computes the blind index for one secret."""

    def __init__(self, secret: str) -> None:
        if len(secret) < MIN_SECRET:
            raise ValueError(f"PATIENT_DATA_SECRET must have at least {MIN_SECRET} characters")
        self._fernet = Fernet(urlsafe_b64encode(_derive(secret, b"encrypt")))
        self._index_key = _derive(secret, b"index")

    @classmethod
    def from_env(cls) -> Vault:
        """The service refuses to start without a secret: it never falls back to a built-in key."""
        secret = os.environ.get("PATIENT_DATA_SECRET")
        if not secret:
            raise RuntimeError("PATIENT_DATA_SECRET is not set (see .env.example)")
        return cls(secret)

    def encrypt(self, value: str) -> str:
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, token: str) -> str:
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:  # wrong key or a changed value: never return garbage
            raise ValueError("patient data cannot be decrypted with this key") from exc

    def digest(self, text: str) -> str:
        return hmac.new(self._index_key, text.encode(), hashlib.sha256).hexdigest()[:32]

    def identity(self, name: str, dob: date) -> str:
        """Blind index of (name, date of birth) for the duplicate check (PAT-01)."""
        return self.digest(f"id|{name.lower()}|{dob.isoformat()}")

    def name_terms(self, name: str) -> set[str]:
        """Blind index of every prefix of every word of the name."""
        return {
            self.digest(f"t|{word[:n]}")
            for word in name.lower().split()
            for n in range(1, min(len(word), MAX_PREFIX) + 1)
        }

    def query_terms(self, query: str) -> list[str]:
        """One hash per word of a search; a patient matches when every word starts a name word."""
        return [self.digest(f"t|{word[:MAX_PREFIX]}") for word in query.lower().split()]
