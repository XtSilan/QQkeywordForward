"""Tests for the CI/CD updater (``deploy/updater/``): webhook auth + ref filter.

Runs under pytest or directly: ``python tests/test_updater.py``. The updater
image ships its own deps (fastapi/httpx/uvicorn), so these run both in CI
(after ``pip install -r requirements.txt``) and inside ``qq-bot-updater``.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "deploy"))

os.environ["UPDATER_WEBHOOK_SECRET"] = "test-webhook-secret"
os.environ["UPDATER_TOKEN"] = "test-token"
os.environ["UPDATER_BRANCH"] = "master"

from fastapi.testclient import TestClient  # noqa: E402

from updater import config, docker_api, signatures, versioning  # noqa: E402
from updater.api import app  # noqa: E402

client = TestClient(app)


def make_signature(secret: str, body: bytes) -> str:
    digest = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def post_webhook(body: bytes, *, signature: str | None = None, event: str = "push"):
    headers = {"X-GitHub-Event": event, "Content-Type": "application/json"}
    if signature is not None:
        headers["X-Hub-Signature-256"] = signature
    return client.post("/api/webhook", content=body, headers=headers)


def test_signature_roundtrip():
    body = b'{"ref":"refs/heads/master"}'
    sig = make_signature("s3cret", body)
    assert signatures.verify_signature("s3cret", body, sig) is True


def test_signature_rejects_wrong_secret_and_tampering():
    body = b'{"ref":"refs/heads/master"}'
    sig = make_signature("s3cret", body)
    assert signatures.verify_signature("other", body, sig) is False
    assert signatures.verify_signature("s3cret", body + b" ", sig) is False
    assert signatures.verify_signature("s3cret", body, "sha256=deadbeef") is False
    assert signatures.verify_signature("s3cret", body, "") is False
    assert signatures.verify_signature("", body, sig) is False


def test_target_ref_only_tracked_branch():
    assert signatures.is_target_ref("refs/heads/master", "master") is True
    assert signatures.is_target_ref("refs/heads/dev", "master") is False
    assert signatures.is_target_ref("refs/tags/v1.0", "master") is False
    assert signatures.is_target_ref("", "master") is False
    assert signatures.is_target_ref(None, "master") is False


def test_parse_app_version_from_env_text():
    text = "APP_ENV=prod\nAPP_VERSION=abc12345\nAPP_BUILD_TIME=now\n"
    assert versioning.parse_app_version(text) == "abc12345"
    assert versioning.parse_app_version("APP_VERSION=deadbeef99\n") == "deadbeef99"
    assert versioning.parse_app_version("APP_ENV=prod\n") == ""
    assert versioning.parse_app_version("") == ""


def test_compute_build_state_fresh_when_last_run_matches_head():
    head = "abcdef1234567890"
    version, stale = versioning.compute_build_state(
        {"ok": True, "sha_after": head}, "", head
    )
    assert version == "abcdef12" and stale is False


def test_compute_build_state_stale_when_head_moved_on():
    version, stale = versioning.compute_build_state(
        {"ok": True, "sha_after": "11111111aaaaaaaa"}, "", "22222222bbbbbbbb"
    )
    assert version == "11111111" and stale is True


def test_compute_build_state_falls_back_to_env_version():
    # no successful run recorded (e.g. before the updater existed)
    version, stale = versioning.compute_build_state(None, "abc12345", "abc12345ffff")
    assert version == "abc12345" and stale is False
    version, stale = versioning.compute_build_state({"ok": False}, "abc12345", "99999999ffff")
    assert version == "abc12345" and stale is True


def test_compute_build_state_dev_versions_are_always_stale():
    assert versioning.compute_build_state(None, "dev", "abcdef12") == ("dev", True)
    assert versioning.compute_build_state(None, "dev-local", "abcdef12") == ("dev-local", True)
    assert versioning.compute_build_state(None, "", "abcdef12") == ("dev", True)


def test_compute_build_state_short_sha_prefix_match_not_stale():
    # git short SHA is often 7 chars; APP_VERSION may be 7 while local is full.
    local = "de068728ec35ad7ae1c063cf4f830f625deda8b2"
    assert versioning.compute_build_state(None, "de06872", local) == ("de06872", False)
    assert versioning.compute_build_state(None, "de068728", local) == ("de068728", False)
    # different commit must stay stale
    version, stale = versioning.compute_build_state(None, "ffffffff", local)
    assert version == "ffffffff" and stale is True
    # last successful run uses full sha_after
    assert versioning.compute_build_state(
        {"ok": True, "sha_after": local}, "", local
    ) == (local[:8], False)


def test_write_build_info_updates_env_and_restores():
    import tempfile

    project = Path(tempfile.mkdtemp(prefix="updater-buildinfo-"))
    env_file = project / ".env.prod"
    env_file.write_text(
        "APP_ENV=prod\nAPP_VERSION=old00001\nADMIN_TOKEN=x\n", encoding="utf-8"
    )
    module = load_update_run(project)

    old = module.write_build_info("cafebabe12345678")
    text = env_file.read_text(encoding="utf-8")
    assert "APP_VERSION=cafebabe" in text
    assert "APP_BUILD_TIME=" in text
    assert "ADMIN_TOKEN=x" in text  # unrelated lines preserved
    assert "APP_VERSION=old00001" in (old or [""])[0] or any(
        line == "APP_VERSION=old00001" for line in (old or [])
    )

    # failed build -> restore previous content
    assert old is not None
    module._write_env_lines(old)
    assert "APP_VERSION=old00001" in env_file.read_text(encoding="utf-8")


def test_webhook_rejects_bad_signature():
    body = b'{"ref":"refs/heads/master"}'
    assert post_webhook(body).status_code == 401
    assert post_webhook(body, signature="sha256=00" * 32).status_code == 401


def test_webhook_accepts_ping():
    body = b'{}'
    sig = make_signature(os.environ["UPDATER_WEBHOOK_SECRET"], body)
    response = post_webhook(body, signature=sig, event="ping")
    assert response.status_code == 200, response.text
    assert response.json()["msg"] == "pong"


def test_webhook_ignores_other_refs_without_touching_git():
    body = b'{"ref":"refs/heads/feature-x"}'
    sig = make_signature(os.environ["UPDATER_WEBHOOK_SECRET"], body)
    response = post_webhook(body, signature=sig)
    assert response.status_code == 200, response.text
    assert response.json().get("ignored") is True


def test_webhook_disabled_without_secrets():
    body = b'{"ref":"refs/heads/master"}'
    secret, token = config.WEBHOOK_SECRET, config.UPDATER_TOKEN
    config.WEBHOOK_SECRET = ""
    config.UPDATER_TOKEN = ""
    try:
        response = post_webhook(body)
    finally:
        config.WEBHOOK_SECRET, config.UPDATER_TOKEN = secret, token
    assert response.status_code == 503, response.text


def test_webhook_token_header_fallback():
    # UPDATER_WEBHOOK_SECRET empty -> X-Updater-Token header is accepted instead.
    # Non-target ref so the request stops at ref filtering (no git needed).
    body = b'{"ref":"refs/heads/other"}'
    secret, token = config.WEBHOOK_SECRET, config.UPDATER_TOKEN
    config.WEBHOOK_SECRET = ""
    try:
        denied = post_webhook(body, signature=None, event="push")
        assert denied.status_code == 403, denied.text
        response = client.post(
            "/api/webhook",
            content=body,
            headers={"X-GitHub-Event": "push", "X-Updater-Token": token},
        )
    finally:
        config.WEBHOOK_SECRET, config.UPDATER_TOKEN = secret, token
    assert response.status_code == 200, response.text
    assert response.json().get("ignored") is True


def test_manual_trigger_requires_token():
    assert client.post("/api/check").status_code == 401
    assert client.post(
        "/api/update", headers={"Authorization": "Bearer wrong"}
    ).status_code == 401


def test_decode_log_stream_multiplexed():
    text = b"hello\nworld"
    framed = (
        b"\x01\x00\x00\x00" + len(text).to_bytes(4, "big") + text
    )
    assert docker_api.decode_log_stream(framed) == "hello\nworld"
    assert docker_api.decode_log_stream(text) == "hello\nworld"


def load_update_run(project_dir: Path):
    """Import deploy/update_run.py with PROJECT_DIR pointing at a temp dir."""
    spec = importlib.util.spec_from_file_location(
        f"qq_update_run_{id(object())}", ROOT / "deploy" / "update_run.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    previous = os.environ.get("PROJECT_DIR")
    os.environ["PROJECT_DIR"] = str(project_dir)
    try:
        spec.loader.exec_module(module)
    finally:
        if previous is None:
            os.environ.pop("PROJECT_DIR", None)
        else:
            os.environ["PROJECT_DIR"] = previous
    return module


def test_ensure_env_link_creates_symlink_for_compose_interpolation():
    import tempfile

    project = Path(tempfile.mkdtemp(prefix="updater-env-test-"))
    (project / ".env.prod").write_text("WEBUI_HOST_PORT=18080\n", encoding="utf-8")
    module = load_update_run(project)

    assert not (project / ".env").exists()
    module.ensure_env_link()
    link = project / ".env"
    assert link.is_symlink(), ".env must be a symlink so compose interpolation sees .env.prod"
    assert os.readlink(link) == ".env.prod"
    assert link.read_text(encoding="utf-8").startswith("WEBUI_HOST_PORT=")


def test_ensure_env_link_keeps_user_file_and_fixes_broken_symlink():
    import tempfile

    # a real file the user created must not be touched
    project = Path(tempfile.mkdtemp(prefix="updater-env-test-"))
    (project / ".env").write_text("WEBUI_HOST_PORT=9999\n", encoding="utf-8")
    module = load_update_run(project)
    module.ensure_env_link()
    assert not (project / ".env").is_symlink()
    assert "9999" in (project / ".env").read_text(encoding="utf-8")

    # a dangling symlink is replaced
    project2 = Path(tempfile.mkdtemp(prefix="updater-env-test-"))
    os.symlink("missing.env", project2 / ".env")
    module2 = load_update_run(project2)
    module2.ensure_env_link()
    assert (project2 / ".env").is_symlink()
    assert os.readlink(project2 / ".env") == ".env.prod"


def test_failure_backoff_ignores_future_finished_epoch():
    """Clock skew must not lock auto-poll out forever.

    ``age = now - finished`` goes negative when the recorded epoch is slightly
    ahead of the local clock; the old ``age < BACKOFF`` check then stayed true
    permanently and poll_once never ran again.
    """
    import asyncio
    import time

    from updater import config, service
    from updater.state import state

    previous = state.get("last_run")
    started = []
    original = service.check_and_maybe_start

    async def fake_check(trigger: str, force: bool, dry_run: bool):
        started.append(trigger)
        return {"ok": True}

    service.check_and_maybe_start = fake_check  # type: ignore[assignment]
    state["last_run"] = {
        "ok": False,
        "exit_code": 2,
        # ~1 hour in the future: age is largely negative
        "finished_epoch": time.time() + 3600,
    }
    try:
        assert config.ENABLED and config.AUTO_UPDATE
        asyncio.get_event_loop_policy()
        asyncio.run(service.poll_once())
    finally:
        service.check_and_maybe_start = original  # type: ignore[assignment]
        if previous is None:
            state.pop("last_run", None)
        else:
            state["last_run"] = previous
    assert started == ["poll"], "future finished_epoch must not block poll"


def test_failure_backoff_still_holds_for_recent_failure():
    import asyncio
    import time

    from updater import service
    from updater.state import state

    previous = state.get("last_run")
    started = []
    original = service.check_and_maybe_start

    async def fake_check(trigger: str, force: bool, dry_run: bool):
        started.append(trigger)
        return {"ok": True}

    service.check_and_maybe_start = fake_check  # type: ignore[assignment]
    state["last_run"] = {
        "ok": False,
        "exit_code": 2,
        "finished_epoch": time.time() - 10,  # just failed: still in backoff
    }
    try:
        asyncio.run(service.poll_once())
    finally:
        service.check_and_maybe_start = original  # type: ignore[assignment]
        if previous is None:
            state.pop("last_run", None)
        else:
            state["last_run"] = previous
    assert started == [], "recent failure must still back off"


def main() -> int:
    tests = [
        (name, fn)
        for name, fn in sorted(globals().items())
        if name.startswith("test_") and callable(fn)
    ]
    failed = 0
    for name, fn in tests:
        try:
            fn()
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
        except Exception as exc:  # noqa: BLE001 - surface everything in the runner
            failed += 1
            print(f"ERROR {name}: {type(exc).__name__}: {exc}")
        else:
            print(f"PASS {name}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
