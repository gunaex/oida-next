"""Hashed operator credentials; encrypted agent key; signed replay-resistant requests."""

import base64
import hashlib
import os
import re
import time
import uuid
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def password_hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1).hex()


def redact(text: str) -> str:
    text = re.sub(
        r"(?i)(password|token|secret|authorization|api[_-]?key)\s*[:=]\s*\S+",
        r"\1=[REDACTED]",
        text,
    )
    text = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", text)
    return "".join(c for c in text if c in "\n\t" or ord(c) >= 32)


def load_key(path: Path, passphrase: str) -> Ed25519PrivateKey:
    if len(passphrase) < 16:
        raise ValueError("Agent key passphrase must contain at least 16 characters")
    if path.exists():
        key = serialization.load_pem_private_key(path.read_bytes(), password=passphrase.encode())
        if not isinstance(key, Ed25519PrivateKey):
            raise ValueError("Invalid agent key type")
        return key
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    key = Ed25519PrivateKey.generate()
    pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(passphrase.encode()),
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(pem)
    return key


def public_key(key: Ed25519PrivateKey) -> str:
    return base64.b64encode(
        key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    ).decode()


def signature_message(method: str, path: str, timestamp: str, nonce: str, body: bytes) -> bytes:
    return f"{method}\n{path}\n{timestamp}\n{nonce}\n{hashlib.sha256(body).hexdigest()}".encode()


def signed_headers(key: Ed25519PrivateKey, agent: str, method: str, path: str, body: bytes) -> dict:
    timestamp, nonce = str(int(time.time())), uuid.uuid4().hex
    signature = key.sign(signature_message(method, path, timestamp, nonce, body))
    return {
        "X-Agent-ID": agent,
        "X-Timestamp": timestamp,
        "X-Nonce": nonce,
        "X-Signature": base64.b64encode(signature).decode(),
        "Content-Type": "application/json",
    }
