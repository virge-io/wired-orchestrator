"""Generate the ES256 keypair CNaaS-NMS verifies JWTs with, plus a long-lived token for WFO and dhcpd.

Idempotent: keeps existing keys/token in the shared volume.
"""

import os
import time
from pathlib import Path

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

out = Path(os.environ.get("JWT_DIR", "/jwt"))
out.mkdir(parents=True, exist_ok=True)
private, public, token = out / "private.pem", out / "public.pem", out / "token"

if not private.exists():
    key = ec.generate_private_key(ec.SECP256R1())
    private.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    public.write_bytes(
        key.public_key().public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    )
    token.unlink(missing_ok=True)

if not token.exists():
    now = int(time.time())
    claims = {"sub": "wired-orchestrator", "iat": now, "nbf": now, "jti": str(now), "type": "access", "fresh": False}
    token.write_text(jwt.encode(claims, private.read_bytes(), algorithm="ES256"))

for f in (public, token):
    f.chmod(0o644)
print(f"JWT material ready in {out}")
