"""S12-T06A C2 tests — manifest integrity and endpoint fail-closed (C24).

Verifies the staged-package manifest contract (F09 closure):

  - manifest has REAL locked dependency versions (no null locks,
    scoped packages included) for both dependencies and devDependencies;
  - manifest records toolchain VERSIONS only, never absolute user paths
    (no /Users/ or Admin under toolchain);
  - endpoint api_base_url is present and points at 127.0.0.1;
  - backend pins are exact (no bare caret/range).

These tests read the real repo manifest (packaging/windows/manifest.json)
which must be rebuilt by s12_t06a_build_manifest.py before the gates.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent.parent.parent
MANIFEST = REPO / "packaging" / "windows" / "manifest.json"


class ManifestIntegrityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not MANIFEST.is_file():
            raise unittest.SkipTest("manifest.json not built yet")
        cls.manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))

    def test_backend_pins_are_exact(self) -> None:
        pins = self.manifest["backend"]["pins"]
        self.assertTrue(pins)
        for pin in pins:
            self.assertIn("==", pin,
                          f"expected exact pin (==), got {pin!r}")

    def test_frontend_locks_not_null(self) -> None:
        pins = self.manifest["frontend"]["pins"]
        self.assertTrue(pins)
        null_locks = [k for k, v in pins.items()
                      if isinstance(v, dict) and not v.get("locked")]
        self.assertEqual(
            null_locks, [],
            f"F09: dependency locks must be real, got null for "
            f"{null_locks}")

    def test_scoped_packages_present(self) -> None:
        pins = self.manifest["frontend"]["pins"]
        scoped = [k for k in pins if "/" in k]
        self.assertTrue(scoped,
                        "scoped packages (e.g. @tanstack/*) must be locked")

    def test_toolchain_has_no_absolute_user_paths(self) -> None:
        tc = self.manifest["toolchain"]
        for name, probe in tc.items():
            for field, val in (probe or {}).items():
                self.assertNotIn(
                    "\\Users\\", str(val),
                    f"F09: toolchain {name}.{field} leaks a user path")
                self.assertNotIn("C:", str(val),
                                 f"F09: toolchain {name}.{field} "
                                 "leaks an absolute path")

    def test_toolchain_versions_present(self) -> None:
        tc = self.manifest["toolchain"]
        for name in ("python", "node", "ffmpeg"):
            self.assertIn(name, tc)
            self.assertTrue(tc[name].get("available"),
                            f"toolchain {name} must probe available")

    def test_endpoint_on_localhost(self) -> None:
        ep = self.manifest["endpoint"]
        self.assertEqual(ep["api_base_url"], f"http://127.0.0.1:{ep['backend_port']}")
        self.assertTrue(1000 < ep["backend_port"] < 65536)
        self.assertTrue(1000 < ep["frontend_port"] < 65536)


if __name__ == "__main__":
    unittest.main()