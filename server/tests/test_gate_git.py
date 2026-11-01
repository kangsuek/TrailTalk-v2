"""Claude Bash 훅 gate-git.py: push 게이트(.githooks/pre-push)가 켜져 있는지 지키고 우회 차단."""

import importlib.util
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOOK = ROOT / ".claude" / "hooks" / "gate-git.py"

spec = importlib.util.spec_from_file_location("gate_git", HOOK)
assert spec is not None and spec.loader is not None
gate_git = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate_git)


def kinds(command: str) -> set[str]:
    return {kind for kind, _ in gate_git.checks_for(command)}


@pytest.mark.parametrize(
    "command",
    [
        "git push",
        "git push origin main",
        "git -C /tmp/x push origin HEAD:refs/heads/x",
        "cd /tmp && git push --tags",
        "bash -c 'git push origin main'",
        "sudo git push",
        "FOO=1 git push origin v1",
        # commit과 push를 묶어도 push는 잡힌다(실제 검증은 push 때 pre-push 훅이 한다)
        "git commit -m x && git push origin main",
    ],
)
def test_push_is_detected(command):
    assert "push" in kinds(command)


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "git commit -m x",
        "git merge feature",
        "git pull",
        "git push --dry-run origin main",
        "git push -n",
        "git push --delete origin old-branch",
        "echo git push",
        "git log --oneline",
    ],
)
def test_other_commands_are_not_push(command):
    assert "push" not in kinds(command)


@pytest.mark.parametrize(
    "command",
    [
        "git push --no-verify",
        "git push origin main --no-verify",
        "git -c core.hooksPath=/dev/null push",
        "git -c core.hooksPath= push origin main",
        "bash -c 'git push --no-verify origin main'",
        "GIT_CONFIG_KEY_0=core.hooksPath git push",
    ],
)
def test_gate_bypass_is_detected(command):
    assert "bypass" in kinds(command)


def test_normal_push_is_not_a_bypass():
    assert "bypass" not in kinds("git push origin main")


def test_gh_pr_merge_is_detected():
    assert "ghmerge" in kinds("gh pr merge 3 --squash")
    assert "ghmerge" not in kinds("gh pr view 3")


def _repo(tmp_path: Path) -> Path:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / ".githooks").mkdir()
    return tmp_path


def _executable(path: Path) -> None:
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


def test_hooks_disabled_when_config_is_empty(tmp_path):
    repo = _repo(tmp_path)
    _executable(repo / ".githooks" / "pre-push")
    enabled, why = gate_git.hooks_enabled(str(repo))
    assert not enabled
    assert "비어 있음" in why


def test_hooks_enabled_with_relative_path(tmp_path):
    repo = _repo(tmp_path)
    _executable(repo / ".githooks" / "pre-push")
    subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", ".githooks"], check=True)
    assert gate_git.hooks_enabled(str(repo)) == (True, "")


def test_hooks_enabled_with_absolute_path(tmp_path):
    repo = _repo(tmp_path)
    _executable(repo / ".githooks" / "pre-push")
    subprocess.run(
        ["git", "-C", str(repo), "config", "core.hooksPath", str(repo / ".githooks")], check=True
    )
    assert gate_git.hooks_enabled(str(repo)) == (True, "")


def test_hooks_disabled_when_pointing_elsewhere(tmp_path):
    repo = _repo(tmp_path)
    _executable(repo / ".githooks" / "pre-push")
    subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", "/dev/null"], check=True)
    enabled, why = gate_git.hooks_enabled(str(repo))
    assert not enabled
    assert ".githooks" in why


def test_hooks_disabled_when_pre_push_is_missing_or_not_executable(tmp_path):
    repo = _repo(tmp_path)
    subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", ".githooks"], check=True)
    assert not gate_git.hooks_enabled(str(repo))[0]  # 없음
    (repo / ".githooks" / "pre-push").write_text("#!/bin/sh\n")  # 실행 권한 없음
    assert not gate_git.hooks_enabled(str(repo))[0]


def _run_hook(command: str, cwd: Path) -> str:
    payload = json.dumps({"tool_input": {"command": command}, "cwd": str(cwd)})
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
    result = subprocess.run(
        [sys.executable, str(HOOK)],
        input=payload,
        capture_output=True,
        text=True,
        env=env,
        check=True,
    )
    return result.stdout


def test_hook_denies_push_when_hooks_are_off(tmp_path):
    repo = _repo(tmp_path)
    out = json.loads(_run_hook("git push origin main", repo))
    decision = out["hookSpecificOutput"]
    assert decision["permissionDecision"] == "deny"
    assert "core.hooksPath" in decision["permissionDecisionReason"]


def test_hook_denies_no_verify_even_when_hooks_are_on(tmp_path):
    repo = _repo(tmp_path)
    _executable(repo / ".githooks" / "pre-push")
    subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", ".githooks"], check=True)
    out = json.loads(_run_hook("git push --no-verify origin main", repo))
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert "우회" in out["hookSpecificOutput"]["permissionDecisionReason"]


def test_hook_allows_push_when_hooks_are_on(tmp_path):
    repo = _repo(tmp_path)
    _executable(repo / ".githooks" / "pre-push")
    subprocess.run(["git", "-C", str(repo), "config", "core.hooksPath", ".githooks"], check=True)
    assert _run_hook("git push origin main", repo) == ""


def test_hook_ignores_unrelated_commands(tmp_path):
    repo = _repo(tmp_path)
    assert _run_hook("git commit -m x", repo) == ""
    assert _run_hook("ls", repo) == ""
