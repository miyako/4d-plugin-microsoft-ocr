"""Source-only fixtures, derived from both live metadata and a stable version."""

import importlib.util
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("source_version", ROOT / ".github/scripts/source_version.py")
source = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(source)


class SourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".source-tests-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.copy_source()
        self.current = source.read(self.root)

    def copy_source(self):
        for name in source.SOURCE_PATHS:
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, path)

    def snapshot(self):
        return {name: (self.root / name).read_bytes() for name in source.SOURCE_PATHS}

    def plist(self, **values):
        path = self.root / source.PLIST
        data = plistlib.loads(path.read_bytes())
        data.update(values)
        path.write_bytes(plistlib.dumps(data))

    def rejected(self):
        before = self.snapshot()
        with self.assertRaises(ValueError):
            source.bump("patch", self.root)
        self.assertEqual(self.snapshot(), before)

    def test_live_all_modes_and_absent_optional_key(self):
        parts = list(map(int, self.current.split(".")))
        self.assertEqual(source.SETTING_COUNT, 6)
        for mode, values in (
            ("patch", [parts[0], parts[1], parts[2] + 1]),
            ("minor", [parts[0], parts[1] + 1, 0]),
            ("major", [parts[0] + 1, 0, 0]),
        ):
            self.copy_source()
            before = self.snapshot()
            new = ".".join(map(str, values))
            self.assertEqual(source.bump(mode, self.root), new)
            self.assertEqual(source.read(self.root), new)
            for name, data in before.items():
                self.assertEqual((self.root / name).read_bytes(),
                                 data.replace(self.current.encode(), new.encode()))
            self.assertNotIn("CFBundleVersion",
                             plistlib.loads((self.root / source.PLIST).read_bytes()))

    def test_stable_coordinated_fixture(self):
        (self.root / source.PROJECT).write_text(
            ("MARKETING_VERSION = 3.2.1;\nCURRENT_PROJECT_VERSION = 3.2.1;\n") * 6)
        self.plist(CFBundleShortVersionString="3.2.1", CFBundleVersion="3.2.1")
        (self.root / source.LOCALIZED).write_text(
            'CFBundleName = "OCR";\nCFBundleShortVersionString = "3.2.1";\n'
            'CFBundleGetInfoString = "OCR version 3.2.1, Copyright 2021 miyako.";\n')
        self.assertEqual(source.read(self.root), "3.2.1")
        self.assertEqual(source.bump("minor", self.root), "3.3.0")
        self.assertEqual(source.read(self.root), "3.3.0")

    def test_invalid_missing_duplicate_and_drifted_project_settings(self):
        path = self.root / source.PROJECT
        original = source.text(path)
        for key in source.KEYS:
            for bad in ("1.2", "77", "v1.2.3", "01.2.3", "1.2.3-beta", "",
                        "$(UNKNOWN)", "0.0.0", "$(CURRENT_PROJECT_VERSION)"):
                for count in (1, 6):
                    with self.subTest(key=key, bad=bad, count=count):
                        path.write_text(original.replace(
                            f"{key} = {self.current};", f"{key} = {bad};", count))
                        self.rejected()
            for extra in (f"{key} = {self.current};", f'"{key}" = {self.current};'):
                path.write_text(original + "\n" + extra)
                self.rejected()
            path.write_text(original.replace(f"{key} = {self.current};", "", 1))
            self.rejected()
        for reference in source.REFERENCES:
            path.write_text(original.replace(
                f"MARKETING_VERSION = {self.current};", f'MARKETING_VERSION = "{reference}";'))
            self.rejected()

    def test_supported_references_preserved(self):
        for reference in source.REFERENCES:
            for build_ref in ("$(MARKETING_VERSION)", "${MARKETING_VERSION}"):
                self.copy_source()
                self.plist(CFBundleShortVersionString=reference, CFBundleVersion=reference)
                path = self.root / source.PROJECT
                path.write_text(source.SETTING.sub(
                    lambda m: f'{m[1]}"{build_ref}"{m[4]}'
                    if m[2] == "CURRENT_PROJECT_VERSION" else m[0], source.text(path)))
                before = self.snapshot()
                new = source.bump("patch", self.root)
                self.assertEqual(source.read(self.root), new)
                for name, data in before.items():
                    self.assertEqual((self.root / name).read_bytes(),
                                     data.replace(self.current.encode(), new.encode()))
        self.copy_source()
        self.plist(CFBundleVersion=self.current)
        new = source.bump("minor", self.root)
        self.assertEqual(plistlib.loads((self.root / source.PLIST).read_bytes())["CFBundleVersion"], new)

    def test_display_reference_does_not_repair_invalid_build(self):
        self.plist(CFBundleShortVersionString="$(CURRENT_PROJECT_VERSION)")
        path = self.root / source.PROJECT
        path.write_text(source.text(path).replace(
            f"CURRENT_PROJECT_VERSION = {self.current};", "CURRENT_PROJECT_VERSION = 77;"))
        self.rejected()

    def test_plist_invalid_duplicate_and_serialization(self):
        for key in ("CFBundleShortVersionString", "CFBundleVersion"):
            for bad in ("$(UNKNOWN)", "0.0.0", "01.2.3", 1, "", "1.2", "7", "v1.2.3"):
                self.copy_source()
                self.plist(**{key: bad})
                self.rejected()
            self.copy_source()
            self.plist(**{key: self.current})
            path = self.root / source.PLIST
            path.write_text(source.text(path).replace(
                "</dict>", f"<key>{key}</key><string>{self.current}</string></dict>"))
            self.rejected()
        self.copy_source()
        path = self.root / source.PLIST
        original = path.read_bytes()
        for bad in (b"not plist", plistlib.dumps([]), original.replace(b"</dict>", b""),
                    plistlib.dumps(plistlib.loads(original), fmt=plistlib.FMT_BINARY),
                    original.replace(self.current.encode(), b"&#49;" + self.current[1:].encode())):
            path.write_bytes(bad)
            self.rejected()
        data = plistlib.loads(original)
        del data["CFBundleShortVersionString"]
        path.write_bytes(plistlib.dumps(data))
        self.rejected()

    def test_localized_strict_tokenization_and_duplicates(self):
        path = self.root / source.LOCALIZED
        original = source.text(path)
        for pattern in (source.LOCALIZED_SHORT, source.LOCALIZED_INFO):
            for bad in ("0.0.0", "1.2", "", "$(UNKNOWN)", "01.2.3", "1.2.3-beta"):
                path.write_text(pattern.sub(lambda m: f"{m[1]}{bad}{m[3]}", original))
                self.rejected()
            path.write_text(pattern.sub("", original))
            self.rejected()
        for key in ("CFBundleShortVersionString", "CFBundleGetInfoString"):
            for quoted in (True, False):
                name = f'"{key}"' if quoted else key
                path.write_text(original + f'Other = "x"; {name} = "bad";\n')
                self.rejected()
        for bad in (original.replace("Copyright 2021", "Copyright 2023"),
                    original.replace("OCR version", "Other version"), original + "garbage"):
            path.write_text(bad)
            self.rejected()
        quoted = original
        for key in ("CFBundleShortVersionString", "CFBundleGetInfoString"):
            quoted = quoted.replace(key + " =", f'"{key}" =')
        quoted += '// CFBundleShortVersionString = "not assignment";\n'
        quoted += '/* CFBundleGetInfoString = "not assignment"; */\n'
        path.write_text(quoted)
        new = source.bump("patch", self.root)
        self.assertEqual(path.read_bytes(), quoted.replace(self.current, new).encode())

    def test_bom_all_endings_modes_whitespace_quotes(self):
        for ending in ("\n", "\r", "\r\n", "mixed"):
            for bom in (b"", b"\xef\xbb\xbf"):
                self.copy_source()
                before = {}
                for i, name in enumerate(source.SOURCE_PATHS):
                    path = self.root / name
                    value = source.text(path)
                    if name == source.PROJECT:
                        for key in source.KEYS:
                            value = value.replace(f"{key} = {self.current};",
                                                  f'{key} \t= \t"{self.current}" \t;')
                    value = "".join(line.replace("\n", ("\n", "\r", "\r\n")[j % 3]
                                                if ending == "mixed" else ending)
                                    for j, line in enumerate(value.splitlines(keepends=True)))
                    path.write_bytes(bom + value.encode())
                    path.chmod((0o755, 0o640, 0o644)[i])
                    before[name] = (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                new = source.bump("minor", self.root)
                for name, (data, mode) in before.items():
                    path = self.root / name
                    self.assertEqual(path.read_bytes(), data.replace(self.current.encode(), new.encode()))
                    self.assertEqual(stat.S_IMODE(path.stat().st_mode), mode)

    def test_all_unrelated_tracked_files_excluded(self):
        tracked = subprocess.run(["git", "-C", str(ROOT), "ls-files"], check=True,
                                 capture_output=True, text=True).stdout.splitlines()
        for name in tracked:
            if Path(name) in source.SOURCE_PATHS or name.startswith(".github/"):
                continue
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, path)
        before = {path.relative_to(self.root): (path.read_bytes(), stat.S_IMODE(path.stat().st_mode))
                  for path in self.root.rglob("*") if path.is_file()
                  and path.relative_to(self.root) not in source.SOURCE_PATHS}
        source.bump("major", self.root)
        self.assertEqual(before, {path: ((self.root / path).read_bytes(),
                                        stat.S_IMODE((self.root / path).stat().st_mode))
                                  for path in before})

    def test_built_plist_and_utf16_binary_localized(self):
        bundle = self.root / "built/OCR.bundle"
        contents = bundle / "Contents"
        localized = contents / "Resources/English.lproj/InfoPlist.strings"
        localized.parent.mkdir(parents=True)
        shutil.copy2(self.root / source.PLIST, contents / "Info.plist")
        value = source.text(self.root / source.LOCALIZED)
        fields = {"CFBundleShortVersionString": self.current,
                  "CFBundleGetInfoString": f"OCR version {self.current}, Copyright 2021 miyako."}
        serializations = [value.encode("utf-8-sig"), value.encode("utf-16"),
                          b"\xfe\xff" + value.encode("utf-16-be"),
                          plistlib.dumps(fields), plistlib.dumps(fields, fmt=plistlib.FMT_BINARY)]
        for serialized in serializations:
            localized.write_bytes(serialized)
            source.verify_bundle(bundle, self.root)
        for key in fields:
            localized.write_bytes(plistlib.dumps({**fields, key: "bad"}))
            with self.assertRaises(ValueError):
                source.verify_bundle(bundle, self.root)
        localized.write_bytes(serializations[0])
        (contents / "Info.plist").write_bytes(plistlib.dumps(
            {"CFBundleShortVersionString": self.current, "CFBundleVersion": "77"}))
        with self.assertRaises(ValueError):
            source.verify_bundle(bundle, self.root)

    def test_missing_files_fail_before_writes(self):
        for name in source.SOURCE_PATHS:
            self.copy_source()
            (self.root / name).unlink()
            before = {p: (self.root / p).read_bytes() for p in source.SOURCE_PATHS if p != name}
            with self.assertRaises(FileNotFoundError):
                source.bump("patch", self.root)
            self.assertEqual(before, {p: (self.root / p).read_bytes() for p in before})

    def test_unrelated_literals_remain_and_bad_encoding_never_writes(self):
        project = self.root / source.PROJECT
        project.write_bytes(project.read_bytes() + f"\n/* Historical {self.current} */\n".encode())
        self.plist(UnrelatedVersion=self.current)
        localized = self.root / source.LOCALIZED
        localized.write_bytes(localized.read_bytes() + f'\rUnrelatedVersion = "{self.current}";\r'.encode())
        source.bump("minor", self.root)
        self.assertIn(f"Historical {self.current}".encode(), project.read_bytes())
        self.assertEqual(plistlib.loads((self.root / source.PLIST).read_bytes())["UnrelatedVersion"],
                         self.current)
        self.assertIn(f'UnrelatedVersion = "{self.current}";'.encode(), localized.read_bytes())
        self.copy_source()
        localized.write_bytes(source.text(localized).encode("utf-16"))
        before = self.snapshot()
        with self.assertRaises(UnicodeError):
            source.bump("patch", self.root)
        self.assertEqual(before, self.snapshot())

    def test_invalid_mode_and_cli_read_never_write(self):
        before = self.snapshot()
        with self.assertRaises(ValueError):
            source.bump("other", self.root)
        result = subprocess.run(
            [sys.executable, str(ROOT / ".github/scripts/source_version.py")],
            cwd=self.root, check=True, capture_output=True, text=True)
        self.assertEqual(result.stdout.strip(), self.current)
        self.assertEqual(before, self.snapshot())


if __name__ == "__main__":
    unittest.main()
