"""Isolation guards for the standalone pilot launcher."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest


def _run_guard(candidate: Path, repo: Path, work: Path) -> subprocess.CompletedProcess[str]:
    script = Path(__file__).resolve().parents[2] / "scripts" / "pilot_preview" / "isolated-roots.ps1"
    return subprocess.run(
        ["pwsh", "-NoProfile", "-File", str(script), "-Candidate", str(candidate), "-RepoRoot", str(repo), "-WorkRoot", str(work)],
        capture_output=True,
        text=True,
        check=False,
    )


def test_isolated_root_guard_accepts_only_fresh_workroot_child(tmp_path: Path) -> None:
    if shutil.which("pwsh") is None:
        pytest.skip("pwsh is required for launcher guard coverage")
    repo = tmp_path / "repo"
    work = tmp_path / "fresh-run"
    accepted = _run_guard(work / "runtime" / "output", repo, work)
    assert accepted.returncode == 0, accepted.stderr
    assert json.loads(accepted.stdout)["status"] == "PASS"


def test_isolated_root_guard_rejects_repo_and_outside_paths(tmp_path: Path) -> None:
    if shutil.which("pwsh") is None:
        pytest.skip("pwsh is required for launcher guard coverage")
    repo = tmp_path / "repo"
    work = tmp_path / "fresh-run"
    repo_child = _run_guard(repo / "runtime-runs", repo, work)
    outside = _run_guard(tmp_path / "other", repo, work)
    assert repo_child.returncode != 0
    assert outside.returncode != 0


def test_isolated_root_guard_rejects_named_s12_integration_root(tmp_path: Path) -> None:
    if shutil.which("pwsh") is None:
        pytest.skip("pwsh is required for launcher guard coverage")
    repo = tmp_path / "repo"
    work = tmp_path / "fresh-run"
    protected = Path.home() / "MotionForge2D-worktrees" / "s12-integration" / "runtime"
    result = _run_guard(protected, repo, work)
    assert result.returncode != 0
    assert "S12" in (result.stderr + result.stdout).upper()
