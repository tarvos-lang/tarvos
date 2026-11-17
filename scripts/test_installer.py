#!/usr/bin/env python3
"""Static checks for installer safeguards; never downloads or installs Tarvos."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class InstallerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.shell = (ROOT / "install.sh").read_text(encoding="utf-8")
        cls.powershell = (ROOT / "install.ps1").read_text(encoding="utf-8")

    def test_shell_installer_uses_valid_tls_and_checks_source_tree(self) -> None:
        self.assertRegex(self.shell, r"(?m)^\s*curl --proto '=https' --tlsv1\.2")
        self.assertNotRegex(self.shell, r"(?m)^\s*curl .*--tl1v1\.2")
        self.assertIn('if [ ! -d "crates/tarvos-cli" ]; then', self.shell)
        self.assertIn("cargo install --locked --path crates/tarvos-cli --force", self.shell)

    def test_windows_installer_verifies_checksum_before_replacing_binary(self) -> None:
        verify_at = self.powershell.index("if ($expected -ne $actual)")
        replace_at = self.powershell.index("Move-Item -LiteralPath $temporary")
        self.assertLess(verify_at, replace_at)
        self.assertIn("Get-FileHash -LiteralPath $temporary -Algorithm SHA256", self.powershell)
        self.assertIn("and -not $Force", self.powershell)
        self.assertIn('SetEnvironmentVariable("Path",', self.powershell)


if __name__ == "__main__":
    unittest.main()
