"""Webhook auth + ref filtering (pure, unit-tested)."""
from __future__ import annotations

import hashlib
import hmac


def verify_signature(secret: str, raw: bytes, header: str) -> bool:
    """GitHub-style ``X-Hub-Signature-256: sha256=<hex>`` over the raw body."""
    if not secret or not header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret.encode("utf-8"), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header.strip())


def is_target_ref(ref: str | None, branch: str) -> bool:
    """Only branch pushes for the tracked branch count; tags/other branches do not."""
    ref = (ref or "").strip()
    if not ref.startswith("refs/heads/"):
        return False
    return ref == f"refs/heads/{branch}"
