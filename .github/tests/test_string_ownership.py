"""Compile real JSON helpers and the bundled SDK; replace only the 4D callback.

The host shim exercises both owned allocated and null empty-string
representations. It does not claim to emulate or measure a running 4D host.
No project build, signing, packaging, publication, or 4D launch is performed.
"""

from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


@unittest.skipUnless(sys.platform == "darwin" and shutil.which("clang"),
                     "requires macOS frameworks and clang")
class StringOwnershipTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="ocr-string-ownership-")
        cls.addClassCleanup(cls.temp.cleanup)
        directory = Path(cls.temp.name)
        sdk = directory / "sdk.o"
        cls.executable = directory / "ownership"
        include = ["-I", str(ROOT / "4D Plugin API"),
                   "-I", str(ROOT / "support")]
        subprocess.run(
            ["clang", "-c", str(ROOT / "4D Plugin API/4DPluginAPI.c"),
             # Legacy SDK initializes an unrelated integer result with NULL.
             "-Wno-error=int-conversion",
             *include, "-o", str(sdk)], check=True)
        subprocess.run(
            ["clang++", "-std=c++11", *include,
             str(ROOT / "support/4DPlugin-JSON.cpp"),
             str(ROOT / ".github/tests/string_ownership.cpp"), str(sdk),
             "-framework", "CoreFoundation", "-Wl,-dead_strip",
             "-o", str(cls.executable)], check=True)

    def test_string_setters_release_every_owned_descriptor(self):
        for overload in range(4):
            for allocated_empty in range(2):
                with self.subTest(overload=overload, allocated_empty=allocated_empty):
                    result = subprocess.run(
                        [str(self.executable), str(overload), str(allocated_empty)],
                        capture_output=True, text=True)
                    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
