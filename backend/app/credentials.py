"""Encrypted database credentials; key lives outside PostgreSQL/backups."""

import json
import os
from pathlib import Path

from cryptography.fernet import Fernet


def cipher():
    key = os.getenv("SOURCE_CREDENTIAL_KEY")
    if not key:
        path = Path(__file__).resolve().parents[2] / "data/private/source-credentials.key"
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with path.open("xb") as out:
                out.write(Fernet.generate_key())
        except FileExistsError:
            pass
        key = path.read_bytes()
    return Fernet(key)


def encrypt(value):
    return cipher().encrypt(json.dumps(value).encode()).decode()


def decrypt(value):
    return json.loads(cipher().decrypt(value.encode()))
