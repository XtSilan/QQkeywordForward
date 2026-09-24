"""Git subprocess helpers: local/remote HEAD, dirty-tree check."""
from __future__ import annotations

import asyncio
import os
import time
from typing import Any

from . import config


def git_env() -> dict[str, str]:
    """Env for every git call: no prompts, and safe.directory without touching
    a global gitconfig (the repo is owned by another uid than the container)."""
    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    try:
        n = int(env.get("GIT_CONFIG_COUNT") or "0")
    except ValueError:
        n = 0
    env[f"GIT_CONFIG_KEY_{n}"] = "safe.directory"
    env[f"GIT_CONFIG_VALUE_{n}"] = str(config.PROJECT_DIR)
    env["GIT_CONFIG_COUNT"] = str(n + 1)
    return env


async def git(*args: str, timeout: float = config.GIT_TIMEOUT) -> tuple[int, str, str]:
    proc = await asyncio.create_subprocess_exec(
        "git", *args,
        cwd=str(config.PROJECT_DIR),
        env=git_env(),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124, "", "git command timed out"
    return (
        proc.returncode or 0,
        out.decode("utf-8", errors="replace").strip(),
        err.decode("utf-8", errors="replace").strip(),
    )


async def local_sha() -> str:
    rc, out, err = await git("rev-parse", "HEAD")
    if rc != 0 or not out:
        raise RuntimeError(err or out or "cannot read local HEAD (not a git checkout?)")
    return out


_remote_cache: dict[str, Any] = {"sha": "", "at": 0.0, "error": ""}


async def remote_sha(force: bool = False) -> str:
    now = time.monotonic()
    cached = _remote_cache
    if (
        not force
        and cached["sha"]
        and not cached["error"]
        and now - float(cached["at"]) < config.REMOTE_CACHE_TTL
    ):
        return str(cached["sha"])
    rc, out, err = await git("ls-remote", "origin", f"refs/heads/{config.BRANCH}")
    parts = out.split()
    sha = parts[0] if rc == 0 and parts else ""
    if not sha:
        message = err or out or f"branch {config.BRANCH} not found on origin"
        _remote_cache.update({"sha": "", "at": now, "error": message})
        raise RuntimeError(message)
    _remote_cache.update({"sha": sha, "at": now, "error": ""})
    return sha


async def working_tree_dirty() -> bool | None:
    """True when tracked files have local modifications (None if git failed)."""
    rc, out, _ = await git("status", "--porcelain")
    if rc != 0:
        return None
    return any(
        line.strip() and not line.startswith("??") for line in out.splitlines()
    )
