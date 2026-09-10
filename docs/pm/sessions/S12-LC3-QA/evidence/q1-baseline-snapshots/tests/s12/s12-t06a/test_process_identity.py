"""S12-T06A C2 tests — process identity, fail-closed lifecycle, data keep.

Unit/integration tests for the staged-package lifecycle (F09 closure):

  - identity_ok refuses reused/wrong PIDs (creation time / exe / cmd)
  - cmd_stop refuses wrong identity, retains evidence and exits nonzero
  - cmd_stop on already-gone pids succeeds and clears records
  - uninstall keeps user data by default; removal needs explicit confirm
  - install root guard rejects protected MAIN tree and package tree

All tests are isolated (tempfile dirs), spawn no long-lived servers and
kill every helper process in teardown.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent.parent
SCRIPTS = REPO / "scripts" / "s12"
sys.path.insert(0, str(SCRIPTS))

import s12_t06a_run as run  # noqa: E402


def _spawn_sleeper(timeout_s: int = 60) -> subprocess.Popen:
    """Spawn a harmless owned helper process (python sleep)."""
    return subprocess.Popen(
        [sys.executable, "-c",
         f"import time; time.sleep({timeout_s})"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class IdentityGuardTests(unittest.TestCase):
    def test_identity_ok_matches_own_spawn(self) -> None:
        proc = _spawn_sleeper()
        self.addCleanup(lambda: run.kill_tree(proc.pid, timeout=5))
        # Wait for WMI to see it.
        for _ in range(20):
            live = run.probe_process(proc.pid)
            if live and live.get("creation_time"):
                break
            time.sleep(0.25)
        live = run.probe_process(proc.pid)
        self.assertIsNotNone(live)
        self.assertIsNotNone(live.get("creation_time"))
        rec = {"pid": proc.pid,
               "creation_time": live["creation_time"],
               "expected_executable": "python",
               "command_marker": ""}
        ok, why = run.identity_ok(rec, live)
        self.assertTrue(ok, why)

    def test_identity_ok_refuses_wrong_creation_time(self) -> None:
        proc = _spawn_sleeper()
        self.addCleanup(lambda: run.kill_tree(proc.pid, timeout=5))
        for _ in range(20):
            live = run.probe_process(proc.pid)
            if live and live.get("creation_time"):
                break
            time.sleep(0.25)
        live = run.probe_process(proc.pid)
        rec = {"pid": proc.pid,
               "creation_time": "2020-01-01T00:00:00.000000+00:00",
               "expected_executable": "python",
               "command_marker": ""}
        ok, why = run.identity_ok(rec, live)
        self.assertFalse(ok)
        self.assertIn("creation-time mismatch", why)

    def test_identity_ok_refuses_wrong_executable(self) -> None:
        proc = _spawn_sleeper()
        self.addCleanup(lambda: run.kill_tree(proc.pid, timeout=5))
        for _ in range(20):
            live = run.probe_process(proc.pid)
            if live and live.get("creation_time"):
                break
            time.sleep(0.25)
        live = run.probe_process(proc.pid)
        rec = {"pid": proc.pid,
               "creation_time": live["creation_time"],
               "expected_executable": "this-is-not-python.exe",
               "command_marker": ""}
        ok, why = run.identity_ok(rec, live)
        self.assertFalse(ok)
        self.assertIn("executable mismatch", why)

    def test_identity_ok_refuses_command_marker_mismatch(self) -> None:
        proc = _spawn_sleeper()
        self.addCleanup(lambda: run.kill_tree(proc.pid, timeout=5))
        for _ in range(20):
            live = run.probe_process(proc.pid)
            if live and live.get("creation_time"):
                break
            time.sleep(0.25)
        live = run.probe_process(proc.pid)
        rec = {"pid": proc.pid,
               "creation_time": live["creation_time"],
               "expected_executable": "python",
               "command_marker": "uvicorn app.main:app"}
        ok, why = run.identity_ok(rec, live)
        self.assertFalse(ok)
        self.assertIn("command mismatch", why)


class StopEvidenceTests(unittest.TestCase):
    def _make_root(self) -> Path:
        root = Path(tempfile.mkdtemp(prefix="s12t06a_stop_"))
        return root

    def test_stop_refuses_foreign_pid_and_keeps_evidence(self) -> None:
        root = self._make_root()
        self.addCleanup(lambda: (run.kill_tree(proc.pid, timeout=5),
                                 __import__("shutil").rmtree(root,
                                                             ignore_errors=True)))
        proc = _spawn_sleeper(30)
        live = None
        for _ in range(20):
            live = run.probe_process(proc.pid)
            if live and live.get("creation_time"):
                break
            time.sleep(0.25)
        # Record a WRONG identity (foreign process, wrong creation time).
        rec = {"pid": proc.pid,
               "creation_time": "2020-01-01T00:00:00.000000+00:00",
               "expected_executable": "python",
               "command_marker": ""}
        run.write_runtime(root, {"schema": "s12-t06a-runtime/2",
                                 "backend_proc": None,
                                 "frontend_proc": rec,
                                 "backend_pid": None,
                                 "frontend_pid": rec["pid"]})
        # stop must refuse and exit nonzero without killing the process.
        rc = run.cmd_stop(type("A", (), {"install_root": str(root)})())
        self.assertNotEqual(rc, 0)
        self.assertTrue(run.pid_alive(proc.pid),
                        "foreign process must never be killed")
        ev = root / "evidence" / "stop_evidence.json"
        self.assertTrue(ev.is_file(), "failed stop must retain evidence")
        data = json.loads(ev.read_text(encoding="utf-8"))
        self.assertTrue(data)
        self.assertIn("REFUSE", data[0]["attempts"][0]["action"])

    def test_stop_clears_gone_pids_successfully(self) -> None:
        root = self._make_root()
        self.addCleanup(lambda: __import__("shutil").rmtree(root,
                                                             ignore_errors=True))
        run.write_runtime(root, {"schema": "s12-t06a-runtime/2",
                                 "backend_proc": None,
                                 "frontend_proc": None,
                                 "backend_pid": 999999,
                                 "frontend_pid": 999998})
        rc = run.cmd_stop(type("A", (), {"install_root": str(root)})())
        self.assertEqual(rc, 0)


class UninstallKeepsDataTests(unittest.TestCase):
    def test_uninstall_keeps_user_data_by_default(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="s12t06a_un_"))
        self.addCleanup(lambda: __import__("shutil").rmtree(root,
                                                             ignore_errors=True))
        data = root / "data"
        data.mkdir()
        (data / "sentinel.db").write_text("keep", encoding="utf-8")
        args = type("A", (), {"install_root": str(root),
                              "keep_data": True,
                              "confirm_remove_data": False})()
        rc = run.cmd_uninstall(args)
        self.assertEqual(rc, 0)
        self.assertTrue((data / "sentinel.db").is_file(),
                        "user data must survive uninstall by default")

    def test_uninstall_refuses_data_removal_without_confirm(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="s12t06a_un2_"))
        self.addCleanup(lambda: __import__("shutil").rmtree(root,
                                                             ignore_errors=True))
        data = root / "data"
        data.mkdir()
        (data / "sentinel.db").write_text("keep", encoding="utf-8")
        args = type("A", (), {"install_root": str(root),
                              "keep_data": False,
                              "confirm_remove_data": False})()
        rc = run.cmd_uninstall(args)
        self.assertEqual(rc, 3)
        self.assertTrue((data / "sentinel.db").is_file())

    def test_uninstall_removes_data_only_with_explicit_confirm(self) -> None:
        root = Path(tempfile.mkdtemp(prefix="s12t06a_un3_"))
        self.addCleanup(lambda: __import__("shutil").rmtree(root,
                                                             ignore_errors=True))
        data = root / "data"
        data.mkdir()
        (data / "sentinel.db").write_text("keep", encoding="utf-8")
        args = type("A", (), {"install_root": str(root),
                              "keep_data": False,
                              "confirm_remove_data": True})()
        rc = run.cmd_uninstall(args)
        self.assertEqual(rc, 0)
        self.assertFalse((data / "sentinel.db").is_file())


class InstallRootGuardTests(unittest.TestCase):
    def test_main_tree_rejected(self) -> None:
        main = Path.home() / "MotionForge2D"
        with self.assertRaises(SystemExit) as ctx:
            run.resolve_install_root(str(main))
        self.assertEqual(ctx.exception.code, 3)

    def test_relative_root_under_package_rejected(self) -> None:
        with self.assertRaises(SystemExit) as ctx:
            run.resolve_install_root(".")
        self.assertEqual(ctx.exception.code, 3)


import tempfile  # noqa: E402


if __name__ == "__main__":
    unittest.main()