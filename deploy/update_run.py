"""One-shot update worker, spawned by app.py as a throwaway container.

Steps: fetch -> ff-only merge -> docker compose build -> up -d.
Any local change to tracked files aborts the run (never stash/force).
``UPDATE_RESULT:`` lines are the machine-readable outcome parsed by the
watcher for /api/status.
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

PROJECT = Path(os.environ.get("PROJECT_DIR", "/project")).resolve()
BRANCH = (os.environ.get("UPDATER_BRANCH") or "master").strip()
if BRANCH.startswith("refs/heads/"):
    BRANCH = BRANCH[len("refs/heads/"):]
TRIGGER = os.environ.get("UPDATER_TRIGGER") or "manual"
FORCE = os.environ.get("UPDATER_FORCE", "0").lower() in {"1", "true", "yes", "on"}
DRY_RUN = os.environ.get("UPDATER_DRY_RUN", "0").lower() in {"1", "true", "yes", "on"}


def log(message: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def fail(step: str, message: str, code: int = 1) -> None:
    log(f"FAILED at {step}: {message}")
    print(f"UPDATE_RESULT: failed step={step} rc={code} reason={message}", flush=True)
    sys.exit(code)


def git_env() -> dict[str, str]:
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        n = int(env.get("GIT_CONFIG_COUNT") or "0")
    except ValueError:
        n = 0
    env[f"GIT_CONFIG_KEY_{n}"] = "safe.directory"
    env[f"GIT_CONFIG_VALUE_{n}"] = str(PROJECT)
    env["GIT_CONFIG_COUNT"] = str(n + 1)
    return env


def run(
    cmd: list[str],
    *,
    step: str,
    capture: bool = False,
    check: bool = True,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    log("$ " + " ".join(cmd))
    result = subprocess.run(
        cmd,
        cwd=str(cwd or PROJECT),
        env=git_env(),
        text=True,
        capture_output=capture,
    )
    if capture:
        if result.stdout:
            log(result.stdout.strip())
        if result.stderr:
            log(result.stderr.strip())
    if check and result.returncode != 0:
        tail = ""
        if capture:
            tail = (result.stderr or result.stdout or "").strip()[:500]
        fail(step, tail or f"exit {result.returncode}", result.returncode)
    return result


def repo_owner() -> str:
    stat = (PROJECT / ".git").stat()
    return f"{stat.st_uid}:{stat.st_gid}"


def ensure_env_link() -> None:
    """compose interpolates host ports from ``.env``; the repo ships only
    ``.env.prod`` (gitignored), so keep ``.env`` as a symlink to it.
    The link is gitignored as well — a pull can never clobber it, and a
    missing one (fresh clone) is recreated here before compose runs."""
    link = PROJECT / ".env"
    if link.exists():
        return  # regular file or valid symlink: respect what the user has
    if link.is_symlink():
        try:
            link.unlink()  # broken symlink
        except OSError:
            return
    try:
        os.symlink(".env.prod", link)
        log("linked .env -> .env.prod (compose reads .env for interpolation)")
    except OSError as exc:
        log(f"cannot create .env symlink: {exc}")


def _env_path() -> Path:
    return PROJECT / ".env.prod"


def _read_env_lines() -> list[str] | None:
    try:
        return _env_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return None


def _write_env_lines(lines: list[str]) -> None:
    _env_path().write_text("\n".join(lines) + "\n", encoding="utf-8")
    if os.geteuid() != 0:
        return
    try:
        stat = (PROJECT / ".git").stat()
        os.chown(_env_path(), stat.st_uid, stat.st_gid)
    except OSError:
        pass  # no .git (temp dir in tests) or chown unsupported: not fatal


def write_build_info(sha: str) -> list[str] | None:
    """Bake the commit being built into .env.prod (APP_VERSION/APP_BUILD_TIME);
    compose interpolates them as build args. Returns the previous content so a
    failed build can roll the values back and the displayed version stays true.
    """
    old = _read_env_lines()
    if old is None:
        log("no .env.prod found, skip writing build info")
        return None
    version = sha[:8]
    stamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    new: list[str] = []
    seen_version = seen_stamp = False
    for line in old:
        if line.startswith("APP_VERSION="):
            new.append(f"APP_VERSION={version}")
            seen_version = True
        elif line.startswith("APP_BUILD_TIME="):
            new.append(f"APP_BUILD_TIME={stamp}")
            seen_stamp = True
        else:
            new.append(line)
    if not seen_version:
        new.append(f"APP_VERSION={version}")
    if not seen_stamp:
        new.append(f"APP_BUILD_TIME={stamp}")
    _write_env_lines(new)
    log(f"build info: APP_VERSION={version} APP_BUILD_TIME={stamp}")
    return old


def restore_owner(owner: str, before: str, after: str) -> None:
    """The helper runs as root; hand changed paths back to the checkout owner so
    a human can still run git on the host afterwards."""
    if os.geteuid() != 0 or owner == "0:0":
        return
    subprocess.run(
        ["chown", "-R", owner, str(PROJECT / ".git")],
        cwd=str(PROJECT), check=False,
    )
    if before == after:
        return
    result = subprocess.run(
        ["git", "diff", "--name-only", "-z", before, after],
        cwd=str(PROJECT), env=git_env(), text=True, capture_output=True,
    )
    directories: set[str] = set()
    for path in filter(None, result.stdout.split("\0")):
        target = PROJECT / path
        subprocess.run(["chown", owner, str(target)], check=False)
        directories.add(str(target.parent))
    for directory in sorted(directories):
        subprocess.run(["chown", owner, directory], check=False)


def main() -> None:
    log(f"update start trigger={TRIGGER} branch={BRANCH} force={FORCE} dry_run={DRY_RUN}")
    if not (PROJECT / ".git").exists():
        fail("checkout", f"{PROJECT} is not a git checkout")

    run(
        [
            "git", "fetch", "--prune", "origin",
            f"+refs/heads/{BRANCH}:refs/remotes/origin/{BRANCH}",
        ],
        step="fetch", capture=True,
    )
    before = run(["git", "rev-parse", "HEAD"], step="rev-parse", capture=True).stdout.strip()
    after = run(
        ["git", "rev-parse", f"refs/remotes/origin/{BRANCH}"],
        step="rev-parse-remote", capture=True,
    ).stdout.strip()

    # Dry runs never touch the worktree, so they are allowed on a dirty tree
    # (useful while developing) and report before any safety abort.
    if DRY_RUN:
        if before == after:
            log("dry run: already up to date")
            print(f"UPDATE_RESULT: skipped reason=already-up-to-date sha={before}", flush=True)
        else:
            log(f"dry run: {before[:8]} -> {after[:8]} (no pull, no rebuild)")
            log("commits:\n" + run(
                ["git", "log", "--oneline", f"{before}..{after}"],
                step="log", capture=True,
            ).stdout)
            print(f"UPDATE_RESULT: dry-run sha={after} from={before}", flush=True)
        return

    # Refuse to touch a tree with local edits; untracked files are fine (git
    # only fails if a merge would overwrite them, which surfaces below).
    status = run(["git", "status", "--porcelain"], step="status", capture=True)
    modified = [
        line for line in status.stdout.splitlines()
        if line.strip() and not line.startswith("??")
    ]
    if modified:
        preview = "\n  ".join(modified[:20])
        fail("dirty-tree", f"tracked files modified locally, refusing:\n  {preview}", 2)

    owner = repo_owner()
    if before == after:
        if not FORCE:
            log("already up to date, nothing to pull")
            print(f"UPDATE_RESULT: skipped reason=already-up-to-date sha={before}", flush=True)
            return
        log("code unchanged, FORCE/stale-build -> rebuild anyway")
    else:
        run(["git", "merge", "--ff-only", f"refs/remotes/origin/{BRANCH}"], step="merge")
        restore_owner(owner, before, after)
        log(f"code updated {before[:8]} -> {after[:8]}")

    ensure_env_link()
    # Bake the commit being built into .env.prod so compose passes it as a
    # build arg and /api/health + the WebUI sidebar can show it. Rolled back
    # if the build fails so the displayed version never lies.
    old_env = write_build_info(after)
    try:
        run(["docker", "compose", "version"], step="compose-version", capture=True)
        run(["docker", "compose", "build"], step="compose-build")
        # No --force-recreate: services whose image/config did not change
        # (napcat with its QQ session) stay up; only rebuilt services restart.
        run(["docker", "compose", "up", "-d"], step="compose-up")
    except SystemExit:
        if old_env is not None:
            _write_env_lines(old_env)
            log("compose failed, restored previous APP_VERSION")
        raise
    print(f"UPDATE_RESULT: ok sha={after}", flush=True)


if __name__ == "__main__":
    main()
