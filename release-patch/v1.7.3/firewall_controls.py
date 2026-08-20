#!/usr/bin/env python3
"""HYZoraX V1.7.3 Firewall Controls release-patch launcher.

The release patch payload is gzip-compressed and base64-split so it can be
stored reliably through the repository publishing API. The decoded Python
payload is SHA-256 verified before execution.
"""
from pathlib import Path
import base64
import gzip
import hashlib

EXPECTED_SHA256 = "cb89392d59660f048b5ec2924eb963b0bff41e728472040740487dc93e6105ce"
base = Path(__file__).resolve().parent
parts = sorted(base.glob("firewall_controls.py.gz.b64.part*"))
if not parts:
    raise SystemExit("V1.7.3 firewall payload parts are missing")
encoded = "".join(part.read_text(encoding="ascii").strip() for part in parts)
try:
    payload = gzip.decompress(base64.b64decode(encoded, validate=True))
except Exception as exc:
    raise SystemExit(f"V1.7.3 firewall payload decode failed: {exc}") from exc
actual = hashlib.sha256(payload).hexdigest()
if actual != EXPECTED_SHA256:
    raise SystemExit(f"V1.7.3 firewall payload checksum mismatch: {actual}")
exec(compile(payload, "firewall_controls_v1.7.3_payload.py", "exec"), {"__name__": "__main__"})
