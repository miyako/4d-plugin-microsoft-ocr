"""Run literal Build shell steps against closed-PATH native tool stubs.

Never build, sign, notarize, publish, dispatch Actions, or launch 4D here.
Fixtures live below the repository, not in the system temporary directory.
"""

import importlib.util
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (ROOT / ".github/workflows/release.yml").read_text()
SPEC = importlib.util.spec_from_file_location(
    "native_source_version", ROOT / ".github/scripts/source_version.py"
)
source = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(source)
PWSH = shutil.which("pwsh") or (
    "/usr/local/bin/pwsh" if Path("/usr/local/bin/pwsh").exists() else None
)


def step(name):
    """Test the workflow itself, not a second hand-maintained shell script."""
    matches = re.findall(
        rf"^      - name: {re.escape(name)}\n"
        r"(?:(?!      - ).*\n)*?        run: \|\n"
        r"((?:          .*(?:\n|$)|[ \t]*\n)+)",
        WORKFLOW, re.MULTILINE,
    )
    if len(matches) != 1:
        raise AssertionError(f"Expected one shell block for {name!r}")
    return textwrap.dedent(matches[0])


STUB = r'''
import base64
import json
import os
from pathlib import Path
import plistlib
import sys

tool = Path(sys.argv[0]).name
args = sys.argv[1:]
root = Path.cwd()
with open(os.environ["CALL_LOG"], "a") as log:
    log.write(json.dumps([tool, *args]) + "\n")
contents = root / os.environ["BUNDLE_PATH"] / "Contents"
mode = os.environ.get("BUILD_MODE", "complete")

if tool == "xcodebuild":
    # Stale committed executables must be absent at the build boundary. A
    # timestamp check alone can pass on checkout and conceal a misdirected build.
    assert not (contents / "MacOS/OCR").exists()
    assert not (contents / "_CodeSignature").exists()
    assert not (contents / "Info.plist").exists()
    assert not (contents / "Resources/English.lproj/InfoPlist.strings").exists()
    assert (contents / "Resources/manifest.json").read_bytes() == b"committed manifest"
    assert (contents / "Windows64/OCR.4DX").read_bytes() == b"committed windows64"
    if mode == "failed":
        sys.exit(70)
    if mode != "missing-binary":
        (contents / "MacOS/OCR").write_bytes(b"rebuilt-universal")
    data = plistlib.loads((root / "Info.plist").read_bytes())
    for key in ("CFBundleShortVersionString", "CFBundleVersion"):
        if key in data and data[key].startswith(("$(", "${")):
            data[key] = os.environ["SOURCE_VERSION"]
    (contents / "Info.plist").write_bytes(plistlib.dumps(data))
    (contents / "Resources/English.lproj/InfoPlist.strings").write_bytes(
        (root / "English.lproj/InfoPlist.strings").read_bytes())
    if mode == "misdirected":
        (contents / "MacOS/OCR").unlink()
        wrong = contents.parent.parent / "Default/OCR.bundle/Contents/MacOS/OCR"
        wrong.parent.mkdir(parents=True)
        wrong.write_bytes(b"wrong build directory")
    if mode in ("missing-plist", "missing-localized"):
        (contents / ("Info.plist" if mode == "missing-plist" else
                     "Resources/English.lproj/InfoPlist.strings")).unlink()
    if mode in ("stale-plist", "stale-build-version"):
        target = contents / "Info.plist"
        data = plistlib.loads(target.read_bytes())
        data["CFBundleShortVersionString" if mode == "stale-plist" else
             "CFBundleVersion"] = os.environ["STALE_VERSION"]
        target.write_bytes(plistlib.dumps(data))
    if mode == "stale-localized":
        target = contents / "Resources/English.lproj/InfoPlist.strings"
        target.write_bytes(target.read_bytes().replace(
            os.environ["SOURCE_VERSION"].encode(), os.environ["STALE_VERSION"].encode()))
elif tool == "lipo":
    assert args[-1] == os.environ["BUNDLE_PATH"] + "/Contents/MacOS/OCR"
    assert Path(args[-1]).is_file()
    assert args[0] in ("-info", "-archs")
    if os.environ.get("LIPO_FAIL"):
        sys.exit(75)
    architectures = os.environ.get("ARCHS", "arm64 x86_64")
    print(("Architectures in the fat file: " if args[0] == "-info" else "") + architectures)
elif tool == "python3":
    if args[0] == ".github/scripts/source_version.py":
        assert args == [args[0], "--verify-bundle", os.environ["BUNDLE_PATH"]]
        os.execv(os.environ["REAL_PYTHON"], [os.environ["REAL_PYTHON"], *args])
    else:
        assert args[0] == ".github/scripts/release.py"
        assert args[1] in ("preflight", "publish")
        assert args[2:4] == ["--sha", os.environ["SELECTED_SHA"]]
        assert os.environ["GH_TOKEN"] == "fixture-token"
        expected = [] if args[1] == "preflight" else [
            "OCR-" + os.environ["SOURCE_VERSION"] + ".zip",
            "OCR-" + os.environ["SOURCE_VERSION"] + ".dmg",
        ]
        assert args[4:] == expected
elif tool == "security":
    if args[0] == "find-identity":
        assert args == ["find-identity", "-v", "-p", "codesigning", os.environ["KEYCHAIN_PATH"]]
        if os.environ.get("SIGN_MODE") != "missing-identity":
            print('1) FAKE "Developer ID Application: Fixture (TEST)"')
    else:
        assert args[0] in (
            "create-keychain", "set-keychain-settings", "unlock-keychain", "import",
            "list-keychain", "set-key-partition-list",
        )
elif tool == "base64":
    assert args[:2] == ["--decode", "-o"]
    Path(args[2]).write_bytes(base64.b64decode(sys.stdin.read()))
elif tool == "codesign":
    verify = args[0] == "--verify"
    expected = (["--verify", "--deep", "--strict", "--verbose=2"] if verify else
                ["--verbose", "--deep", "--timestamp", "--force", "--options=runtime",
                 "--sign", "Developer ID Application: Fixture (TEST)"])
    assert args == expected + [os.environ["BUNDLE_PATH"]]
    if os.environ.get("SIGN_MODE") == ("verify" if verify else "sign"):
        sys.exit(76)
elif tool in ("ditto", "hdiutil"):
    assert Path(os.environ["BUNDLE_PATH"]).is_dir()
    expected = (["-c", "-k", "--keepParent", os.environ["BUNDLE_PATH"]] if tool == "ditto"
                else ["create", "-format", "UDBZ", "-volname", "OCR", "-srcfolder",
                      os.environ["BUNDLE_PATH"]])
    assert args[:-1] == expected
    if os.environ.get("PACKAGE_FAIL") == tool:
        sys.exit(77)
    Path(args[-1]).write_bytes(b"stub archive")
elif tool == "xcrun":
    scenario = os.environ.get("NOTARY_MODE", "accepted")
    if args[:2] == ["notarytool", "store-credentials"]:
        assert args[2:] == [
            "notarytool-profile", "--apple-id", "fixture-apple-id", "--team-id",
            "fixture-team", "--password", "fixture-password", "--keychain",
            os.environ["KEYCHAIN_PATH"],
        ]
    elif args[:2] == ["notarytool", "submit"]:
        assert args[3:] == [
            "--keychain-profile", "notarytool-profile", "--keychain",
            os.environ["KEYCHAIN_PATH"], "--wait", "--output-format", "json",
        ]
        assert Path(args[2]).is_file()
        second = args[2].endswith(".dmg")
        if scenario in ("transport", "accepted-nonzero") or (
                scenario == "second-transport" and second):
            if scenario == "accepted-nonzero":
                print(json.dumps({"id": "misleading", "status": "Accepted"}))
            sys.exit(71)
        if scenario == "malformed":
            print("this is not JSON")
        else:
            status = "Invalid" if (
                scenario == "invalid" or (scenario == "second-invalid" and second)
            ) else "Accepted"
            payload = {"id": "submission-dmg" if second else "submission-zip", "status": status}
            if scenario == "missing-status":
                del payload["status"]
            if scenario == "pending":
                payload["status"] = "In Progress"
            print(json.dumps(payload))
    elif args[:2] == ["notarytool", "log"]:
        assert args[3:] == ["--keychain-profile", "notarytool-profile", "--keychain",
                            os.environ["KEYCHAIN_PATH"]]
        # A diagnostic failure must not mask a rejected submission.
        sys.exit(72)
    elif args[:2] == ["stapler", "staple"]:
        assert args == ["stapler", "staple", "OCR-" + os.environ["SOURCE_VERSION"] + ".dmg"]
        if scenario == "staple":
            sys.exit(73)
    else:
        raise AssertionError(args)
elif tool == "plutil":
    assert args[0] == "-extract" and args[2:] == ["raw", "-o", "-", "-"]
    try:
        value = json.load(sys.stdin)[args[1]]
        assert isinstance(value, str)
        print(value)
    except (ValueError, KeyError, AssertionError):
        sys.exit(74)
else:
    raise AssertionError("Unexpected tool: " + tool)
'''


class NativeShellTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".native-tests-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for path in (*source.SOURCE_PATHS, Path(".github/scripts/source_version.py")):
            target = self.root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / path, target)
        self.version = source.read(self.root)
        major, minor, patch = map(int, self.version.split("."))
        self.stale = f"{major}.{minor}.{patch + 1}"
        self.relative_bundle = "test/Plugins/OCR.bundle"
        self.contents = self.root / self.relative_bundle / "Contents"
        self.log = self.root / "calls.jsonl"
        self.env_file = self.root / "github-env"
        self.env_file.touch()
        self.bin = self.root / "stub-bin"
        self.bin.mkdir()
        for name in ("xcodebuild", "lipo", "python3", "security", "base64", "codesign",
                     "ditto", "hdiutil", "xcrun", "plutil"):
            executable = self.bin / name
            executable.write_text(f"#!{sys.executable}\n" + textwrap.dedent(STUB))
            executable.chmod(0o755)
        # No fallback to installed Apple/native executables is possible.
        for name in ("rm", "ls", "grep", "head", "sed", "mkdir", "cp"):
            executable = shutil.which(name)
            self.assertIsNotNone(executable)
            (self.bin / name).symlink_to(executable)
        self.env = {
            "PATH": str(self.bin), "CALL_LOG": str(self.log), "REAL_PYTHON": sys.executable,
            "PYTHONDONTWRITEBYTECODE": "1", "SOURCE_VERSION": self.version,
            "STALE_VERSION": self.stale, "BUNDLE_PATH": self.relative_bundle,
            "KEYCHAIN_PATH": str(self.root / "build.keychain-db"),
            "RUNNER_TEMP": str(self.root), "GITHUB_ENV": str(self.env_file),
            "SELECTED_SHA": "a" * 40, "GH_TOKEN": "fixture-token",
        }
        self.preserved = {
            "Resources/manifest.json": b"committed manifest",
            "Resources/constants.xlf": b"committed constants",
            "QuickLook/Thumbnail.png": b"committed thumbnail",
            "Windows/OCR.4DX": b"committed windows32",
            "Windows64/OCR.4DX": b"committed windows64",
            "MacOS/Dependency.dylib": b"committed runtime dependency",
            "Frameworks/Dependency.framework/Versions/A/Dependency": b"framework binary",
        }
        for name, data in self.preserved.items():
            self.write(name, data)
        self.link = self.contents / "Frameworks/Dependency.framework/Versions/Current"
        self.link.symlink_to("A")
        self.write("MacOS/OCR", b"stale committed executable")
        self.write("_CodeSignature/CodeResources", b"stale signature")
        # Committed bundle metadata is deliberately excluded from source bumps.
        # It must be recopied even when checkout mtimes would make it look fresh.
        self.seed_stale_metadata()

    def seed_stale_metadata(self):
        data = plistlib.loads((self.root / source.PLIST).read_bytes())
        data["CFBundleShortVersionString"] = self.stale
        self.write("Info.plist", plistlib.dumps(data))
        self.write("Resources/English.lproj/InfoPlist.strings",
                   source.text(self.root / source.LOCALIZED)
                   .replace(self.version, self.stale).encode())

    def write(self, name, data):
        target = self.contents / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def run_step(self, name, **env):
        script = step(name)
        values = {
            "env.PRODUCT_NAME": "OCR", "env.BASE_DIR": "test",
            "env.MACOS_DEPLOYMENT_TARGET": "11.0",
            "needs.version.outputs.version": self.version,
        }
        for key, value in values.items():
            script = script.replace("${{ " + key + " }}", value)
        self.assertNotIn("${{", script)
        return subprocess.run(
            ["/bin/bash", "-c", script], cwd=self.root, env={**self.env, **env},
            text=True, capture_output=True, timeout=30,
        )

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def calls(self, tool):
        if not self.log.exists():
            return []
        return [call[1:] for line in self.log.read_text().splitlines()
                if (call := json.loads(line))[0] == tool]

    def build(self, **env):
        result = self.run_step("build macOS plugin (universal)", **env)
        self.assert_ok(result)

    def test_fresh_build_refreshes_metadata_preserves_resources_windows_and_frameworks(self):
        self.build()
        self.assertEqual((self.contents / "MacOS/OCR").read_bytes(), b"rebuilt-universal")
        for name, data in self.preserved.items():
            self.assertEqual((self.contents / name).read_bytes(), data, name)
        self.assertTrue(self.link.is_symlink())
        self.assertEqual(self.link.readlink(), Path("A"))
        self.assertFalse((self.contents / "_CodeSignature").exists())
        self.assert_ok(self.run_step("verify universal binary"))
        self.assertEqual(
            plistlib.loads((self.contents / "Info.plist").read_bytes())["CFBundleShortVersionString"],
            self.version,
        )
        self.assertEqual(self.calls("xcodebuild"), [[
            "-project", "OCR.xcodeproj", "-target", "OCR", "-configuration", "Default",
            "ARCHS=arm64 x86_64", "ONLY_ACTIVE_ARCH=NO", "MACOSX_DEPLOYMENT_TARGET=11.0",
            "CODE_SIGNING_ALLOWED=NO",
            f"CONFIGURATION_BUILD_DIR={self.root}/test/Plugins", "build",
        ]])

    def test_missing_or_misdirected_rebuild_cannot_ship_committed_executable(self):
        for mode in ("missing-binary", "misdirected"):
            with self.subTest(mode=mode):
                self.build(BUILD_MODE=mode)
                self.assertFalse((self.contents / "MacOS/OCR").exists())
                result = self.run_step("verify universal binary")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Expected binary not found", result.stdout)
        self.assertEqual(self.calls("lipo"), [])
        self.assertEqual(self.calls("python3"), [])

    def test_native_build_failure_is_fatal(self):
        self.assertNotEqual(
            self.run_step("build macOS plugin (universal)", BUILD_MODE="failed").returncode, 0)
        self.assertEqual(self.calls("codesign"), [])

    def test_exact_slices_reject_missing_lookalike_extra_and_i386(self):
        self.build()
        # Presence/substring checks accept arm64e or stale i386. Require exactly
        # two named slices, not merely both names somewhere in lipo's prose.
        for architectures in (
            "arm64", "x86_64", "arm64e x86_64", "arm64 x86_64h",
            "arm64 x86_64 i386", "arm64 x86_64 arm64e", "i386", "",
        ):
            with self.subTest(architectures=architectures):
                result = self.run_step("verify universal binary", ARCHS=architectures)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("Expected exactly arm64 and x86_64", result.stdout)
        self.assertEqual(self.calls("python3"), [])
        self.assert_ok(self.run_step("verify universal binary", ARCHS="x86_64 arm64"))
        self.assertNotEqual(self.run_step("verify universal binary", LIPO_FAIL="1").returncode, 0)

    def test_missing_or_stale_built_metadata_rejected_before_signing(self):
        for mode in ("missing-plist", "missing-localized", "stale-plist",
                     "stale-build-version", "stale-localized"):
            with self.subTest(mode=mode):
                self.seed_stale_metadata()
                self.build(BUILD_MODE=mode)
                result = self.run_step("verify universal binary")
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("FileNotFoundError" if mode.startswith("missing-") else
                              "differs from selected source", result.stderr)
        self.assertEqual(self.calls("codesign"), [])

    def test_compiled_localizations_verified_not_treated_as_utf8(self):
        self.build()
        original = source.text(self.root / source.LOCALIZED)
        values = dict(re.findall(r'(?m)^(\w+)\s*=\s*"([^"]*)";', original))
        for fmt in (plistlib.FMT_BINARY, plistlib.FMT_XML):
            with self.subTest(fmt=fmt):
                self.write("Resources/English.lproj/InfoPlist.strings",
                           plistlib.dumps(values, fmt=fmt))
                self.assert_ok(self.run_step("verify universal binary"))
                for key in ("CFBundleShortVersionString", "CFBundleGetInfoString"):
                    stale = {**values, key: values[key].replace(self.version, self.stale)}
                    self.write("Resources/English.lproj/InfoPlist.strings",
                               plistlib.dumps(stale, fmt=fmt))
                    self.assertNotEqual(self.run_step("verify universal binary").returncode, 0)
        for encoding in ("utf-16", "utf-8-sig"):
            self.write("Resources/English.lproj/InfoPlist.strings", original.encode(encoding))
            self.assert_ok(self.run_step("verify universal binary"))

    def test_merge_requires_exact_nonempty_download_not_recursive_match(self):
        artifact = self.root / "winbuild/OCR.4DX"
        nested = artifact.parent / "stale/OCR.4DX"
        nested.parent.mkdir(parents=True)
        nested.write_bytes(b"wrong recursive match")
        for data in (None, b""):
            if data is not None:
                artifact.write_bytes(data)
            result = self.run_step("merge Windows binaries into the bundle")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("exact artifact path", result.stdout)
            self.assertEqual(self.env_file.read_text(), "")
        artifact.write_bytes(b"fresh Windows x64")
        self.assert_ok(self.run_step("merge Windows binaries into the bundle"))
        self.assertEqual((self.contents / "Windows64/OCR.4DX").read_bytes(), artifact.read_bytes())
        self.assertEqual(self.env_file.read_text(), f"BUNDLE_PATH={self.relative_bundle}\n")

    def test_certificate_import_and_notary_profile_preserve_original_commands(self):
        self.assert_ok(self.run_step(
            "import Developer ID certificate", CERT_BASE64="Zml4dHVyZQ==",
            CERT_PASSWORD="fixture-cert", KEYCHAIN_PASSWORD="fixture-keychain"))
        self.assertEqual((self.root / "certificate.p12").read_bytes(), b"fixture")
        keychain = self.env["KEYCHAIN_PATH"]
        self.assertEqual(self.calls("security"), [
            ["create-keychain", "-p", "fixture-keychain", keychain],
            ["set-keychain-settings", "-lut", "21600", keychain],
            ["unlock-keychain", "-p", "fixture-keychain", keychain],
            ["import", str(self.root / "certificate.p12"), "-P", "fixture-cert", "-A",
             "-t", "cert", "-f", "pkcs12", "-k", keychain],
            ["list-keychain", "-d", "user", "-s", keychain, "login.keychain"],
            ["set-key-partition-list", "-S", "apple-tool:,apple:,codesign:", "-s", "-k",
             "fixture-keychain", keychain],
        ])
        self.assert_ok(self.run_step(
            "store notarytool credentials", APPLE_ID="fixture-apple-id",
            TEAM_ID="fixture-team", APP_PASSWORD="fixture-password"))

    def test_signing_requires_identity_sign_and_strict_verification(self):
        self.assert_ok(self.run_step("codesign"))
        self.assertEqual(len(self.calls("codesign")), 2)
        for scenario, count in (("missing-identity", 0), ("sign", 1), ("verify", 2)):
            with self.subTest(scenario=scenario):
                self.log.unlink()
                self.assertNotEqual(self.run_step("codesign", SIGN_MODE=scenario).returncode, 0)
                self.assertEqual(len(self.calls("codesign")), count)
                self.assertEqual(self.calls("ditto"), [])
                self.assertEqual(self.calls("xcrun"), [])

    def assert_package_calls(self, submissions, staple=False, diagnostic=None):
        zip_path, dmg_path = f"OCR-{self.version}.zip", f"OCR-{self.version}.dmg"
        calls = self.calls("xcrun")
        self.assertEqual(len(self.calls("ditto")), 1)
        self.assertEqual(len(self.calls("hdiutil")), 1)
        self.assertEqual([call[2] for call in calls if call[:2] == ["notarytool", "submit"]],
                         [zip_path, dmg_path][:submissions])
        self.assertEqual([call for call in calls if call[:2] == ["stapler", "staple"]],
                         [["stapler", "staple", dmg_path]] if staple else [])
        self.assertEqual([call[2] for call in calls if call[:2] == ["notarytool", "log"]],
                         [diagnostic] if diagnostic else [])
        if staple:
            self.assertEqual(calls[-1], ["stapler", "staple", dmg_path])

    def test_both_accepted_then_staple_then_publication_paths(self):
        self.assert_ok(self.run_step("package, notarize & staple"))
        self.assert_package_calls(2, staple=True)
        self.assertEqual(self.env_file.read_text().splitlines(), [
            f"ZIP_PATH=OCR-{self.version}.zip", f"DMG_PATH=OCR-{self.version}.dmg",
        ])
        self.assert_ok(self.run_step("create GitHub Release",
                                    ZIP_PATH=f"OCR-{self.version}.zip",
                                    DMG_PATH=f"OCR-{self.version}.dmg"))

    def test_all_notary_failure_modes_block_staple_and_publication_paths(self):
        for scenario, submissions, diagnostic in (
            ("invalid", 1, "submission-zip"), ("transport", 1, None),
            ("accepted-nonzero", 1, None), ("malformed", 1, None),
            ("missing-status", 1, None), ("pending", 1, "submission-zip"),
            ("second-transport", 2, None), ("second-invalid", 2, "submission-dmg"),
            ("staple", 2, None),
        ):
            with self.subTest(scenario=scenario):
                self.log.unlink(missing_ok=True)
                result = self.run_step("package, notarize & staple", NOTARY_MODE=scenario)
                self.assertNotEqual(result.returncode, 0)
                self.assert_package_calls(submissions, staple=scenario == "staple",
                                          diagnostic=diagnostic)
                self.assertEqual(self.env_file.read_text(), "")
                self.assertEqual(self.calls("python3"), [])

    def test_archive_failure_blocks_notarization(self):
        for tool in ("ditto", "hdiutil"):
            with self.subTest(tool=tool):
                self.log.unlink(missing_ok=True)
                result = self.run_step("package, notarize & staple", PACKAGE_FAIL=tool)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(self.calls("xcrun"), [])
                self.assertEqual(self.env_file.read_text(), "")

    def test_preflight_selected_sha_cli_without_network(self):
        self.assert_ok(self.run_step("validate source and publication availability"))
        self.assertEqual(self.calls("python3"), [[
            ".github/scripts/release.py", "preflight", "--sha", "a" * 40,
        ]])

    def test_native_step_chain_only_publishes_after_every_gate_succeeds(self):
        names = re.findall(r"^      - name: (.+)$",
                           WORKFLOW.split("  build-macos:\n", 1)[1], re.MULTILINE)
        names = names[names.index("build macOS plugin (universal)"):]
        artifact = self.root / "winbuild/OCR.4DX"
        artifact.parent.mkdir()
        for scenario in (
            {}, {"BUILD_MODE": "missing-binary"}, {"BUILD_MODE": "stale-plist"},
            {"ARCHS": "arm64 x86_64 i386"}, {"MISSING_ARTIFACT": "1"},
            {"SIGN_MODE": "verify"}, {"NOTARY_MODE": "second-invalid"},
            {"NOTARY_MODE": "staple"},
        ):
            with self.subTest(scenario=scenario):
                self.log.unlink(missing_ok=True)
                self.env_file.write_text("")
                for name, data in self.preserved.items():
                    self.write(name, data)
                self.write("MacOS/OCR", b"stale committed executable")
                self.write("_CodeSignature/CodeResources", b"stale signature")
                self.seed_stale_metadata()
                artifact.unlink(missing_ok=True)
                if not scenario.get("MISSING_ARTIFACT"):
                    artifact.write_bytes(b"fresh Windows x64")
                environment = dict(scenario)
                for name in names:
                    result = self.run_step(name, **environment)
                    if result.returncode:
                        break
                    environment.update(dict(
                        line.split("=", 1) for line in self.env_file.read_text().splitlines()
                    ))
                publications = [call for call in self.calls("python3")
                                if call[:2] == [".github/scripts/release.py", "publish"]]
                if scenario:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(publications, [])
                else:
                    self.assert_ok(result)
                    self.assertEqual(len(publications), 1)
                    all_calls = [json.loads(line) for line in self.log.read_text().splitlines()]
                    self.assertEqual(all_calls[-1][1:3],
                                     [".github/scripts/release.py", "publish"])


class NativeConfigurationTests(unittest.TestCase):
    def test_manual_immutable_source_and_cross_branch_serial_publication(self):
        self.assertRegex(WORKFLOW, r"(?m)^name: Build$")
        trigger = WORKFLOW.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertEqual(trigger.strip(), "workflow_dispatch:")
        self.assertIn("group: release-publication\n  cancel-in-progress: false", WORKFLOW)
        self.assertEqual(WORKFLOW.count("uses: actions/checkout@v4"), 3)
        self.assertEqual(WORKFLOW.count("ref: ${{ github.sha }}"), 3)
        self.assertEqual(WORKFLOW.count("SELECTED_SHA: ${{ github.sha }}"), 2)
        self.assertEqual(WORKFLOW.count("GH_TOKEN: ${{ github.token }}"), 2)
        self.assertIn("tag: ${{ steps.set.outputs.tag }}", WORKFLOW)
        self.assertIn("version: ${{ steps.set.outputs.version }}", WORKFLOW)
        self.assertIn("needs: version", WORKFLOW)
        self.assertIn("needs: [version, build-windows]", WORKFLOW)
        self.assertNotIn("softprops/", WORKFLOW)
        self.assertNotIn("continue-on-error", WORKFLOW)
        ordered = ("build macOS plugin (universal)", "verify universal binary",
                   "merge Windows binaries into the bundle", "codesign",
                   "package, notarize & staple", "create GitHub Release")
        positions = [WORKFLOW.index("- name: " + name) for name in ordered]
        self.assertEqual(positions, sorted(positions))
        self.assertIn('--verify-bundle "${BASE}/Plugins/${PRODUCT}.bundle"',
                      step("verify universal binary"))

    def test_exact_windows_output_matches_vcxproj_and_original_flags(self):
        ns = {"m": "http://schemas.microsoft.com/developer/msbuild/2003"}
        project = ET.parse(ROOT / "OCR.vcxproj")
        condition = "'$(Configuration)|$(Platform)'=='Release|x64'"
        outdirs = [node.text for node in project.findall(".//m:OutDir", ns)
                   if node.get("Condition") == condition]
        extensions = [node.text for node in project.findall(".//m:TargetExt", ns)
                      if node.get("Condition") == condition]
        self.assertEqual(len(outdirs), 1)
        self.assertEqual(extensions, [".4DX"])
        actual = (outdirs[0].replace("$(ProjectDir)", "").replace("$(ProjectName)", "OCR")
                  .replace("\\", "/") + "OCR.4DX")
        normalize = step("normalize windows output to canonical case")
        declared = re.search(r'^\$source = "([^"]+)"$', normalize, re.MULTILINE)[1]
        self.assertEqual(actual, declared.replace("$base", "test").replace("$product", "OCR"))
        self.assertNotIn("-Recurse", normalize)
        self.assertIn("$sourceResolved -ieq $destResolved", normalize)
        self.assertIn("Copy-Item -LiteralPath $source $destination -Force", normalize)
        self.assertEqual(step("build x64").strip(),
                         'msbuild "%PRODUCT_NAME%.sln" /p:Configuration=Release '
                         '/p:Platform=x64 /p:PlatformToolset=v143 '
                         '/p:WindowsTargetPlatformVersion=10.0 /m')
        self.assertEqual({node.text for node in project.findall(".//m:PlatformToolset", ns)},
                         {"v141"})
        self.assertTrue(all("windowsapp.lib;" in node.text
                            for node in project.findall(".//m:AdditionalDependencies", ns)))

    def test_original_macos_resources_frameworks_and_secrets_preserved(self):
        project = (ROOT / source.PROJECT).read_text()
        for setting, value, count in (
            ("SDKROOT", "macosx", 6), ("MACOSX_DEPLOYMENT_TARGET", "11.5", 3),
            ("MACOSX_DEPLOYMENT_TARGET", "10.8", 3), ("CLANG_CXX_LIBRARY", '"libc++"', 6),
            ("INFOPLIST_FILE", "Info.plist", 3), ("WRAPPER_EXTENSION", "bundle", 3),
            ("HEADER_SEARCH_PATHS", '"include/**"', 3),
        ):
            self.assertEqual(len(re.findall(
                rf"(?m)^\s*{setting} = {re.escape(value)};", project)), count)
        for name in ("Default", "Development", "Deployment"):
            self.assertEqual(len(re.findall(rf"(?m)^\s*name = {name};", project)), 2)
        for resource in ("manifest.json in CopyFiles", "constants.xlf in CopyFiles",
                         "Cocoa.framework in Frameworks", "InfoPlist.strings in Resources",
                         '"$(PROJECT_DIR)/lib"', '"$(PROJECT_DIR)/a"'):
            self.assertIn(resource, project)
        self.assertEqual(set(re.findall(r"\$\{\{ secrets\.([A-Z_]+) \}\}", WORKFLOW)), {
            "APPLE_DEVELOPER_ID_CERTIFICATE", "APPLE_DEVELOPER_ID_CERTIFICATE_PASSWORD",
            "KEYCHAIN_PASSWORD", "NOTARYTOOL_APPLE_ID", "NOTARYTOOL_TEAM_ID",
            "NOTARYTOOL_PASSWORD",
        })
        self.assertIn("runs-on: windows-latest", WORKFLOW)
        self.assertIn("runs-on: macos-latest", WORKFLOW)
        self.assertEqual(WORKFLOW.count("name: windows-binaries"), 2)
        self.assertIn("path: winbuild", WORKFLOW)
        self.assertIn("if-no-files-found: error", WORKFLOW)
        self.assertIn("path: ${{ env.BASE_DIR }}/Plugins/${{ env.PRODUCT_NAME }}.bundle/"
                      "Contents/Windows64/${{ env.PRODUCT_NAME }}.4DX", WORKFLOW)

    def test_cleanup_is_exact_and_never_deletes_committed_bundle_resources(self):
        # Broad bundle/plugins cleanup destroys committed Windows32/Windows64,
        # QuickLook and runtime dependencies on case-insensitive runners. Only
        # exact native/source-derived outputs and the stale signature are disposable.
        clean = step("clean stale outputs")
        self.assertNotIn("-Recurse", clean)
        self.assertIn('Remove-Item -LiteralPath $output -Force -ErrorAction Stop', clean)
        build = step("build macOS plugin (universal)")
        deletes = [line.strip() for line in build.splitlines() if line.strip().startswith("rm ")]
        self.assertEqual(deletes, [
            'rm -f "${BUNDLE:?}/Contents/MacOS/${PRODUCT:?}"',
            'rm -f "${BUNDLE:?}/Contents/Info.plist"',
            'rm -f "${BUNDLE:?}/Contents/Resources/English.lproj/InfoPlist.strings"',
            'rm -rf "${BUNDLE:?}/Contents/_CodeSignature"',
        ])


@unittest.skipUnless(PWSH, "PowerShell required for Windows shell harness")
class WindowsShellTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix=".windows-tests-", dir=ROOT)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.binary = self.root / "test/plugins/OCR.bundle/contents/windows64/OCR.4DX"
        self.binary.parent.mkdir(parents=True)
        self.empty_path = self.root / "closed-path"
        self.empty_path.mkdir()

    def run_step(self, name, prefix=""):
        script = step(name)
        for key, value in (("PRODUCT_NAME", "OCR"), ("BASE_DIR", "test")):
            script = script.replace("${{ env." + key + " }}", value)
        self.assertNotIn("${{", script)
        return subprocess.run(
            [PWSH, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", prefix + "\n" + script],
            cwd=self.root, env={**os.environ, "PATH": str(self.empty_path)},
            text=True, capture_output=True, timeout=30,
        )

    def assert_ok(self, result):
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_exact_cleanup_preserves_all_other_contents_and_is_idempotent(self):
        self.binary.write_bytes(b"stale Windows x64")
        preserved = {}
        for name in ("windows/OCR.4DX", "MacOS/OCR", "QuickLook/Thumbnail.png",
                     "Resources/manifest.json", "Resources/English.lproj/InfoPlist.strings",
                     "Info.plist", "_CodeSignature/CodeResources"):
            target = self.binary.parent.parent / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"preserve " + name.encode())
            preserved[target] = target.read_bytes()
        self.assert_ok(self.run_step("clean stale outputs"))
        self.assertFalse(self.binary.exists())
        for target, data in preserved.items():
            self.assertEqual(target.read_bytes(), data)
        self.assert_ok(self.run_step("clean stale outputs"))

    def test_exact_output_required_then_normalized_without_self_copy(self):
        stale = self.root / "stale/Plugins/OCR.4DX"
        stale.parent.mkdir(parents=True)
        stale.write_bytes(b"wrong recursive match")
        result = self.run_step("normalize windows output to canonical case")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exact MSBuild output", result.stderr)
        self.binary.write_bytes(b"")
        result = self.run_step("normalize windows output to canonical case")
        self.assertNotEqual(result.returncode, 0)
        self.binary.write_bytes(b"fresh Windows x64")
        self.assert_ok(self.run_step("normalize windows output to canonical case"))
        canonical = self.root / "test/Plugins/OCR.bundle/Contents/Windows64/OCR.4DX"
        self.assertEqual(canonical.read_bytes(), b"fresh Windows x64")
        # On Windows/macOS case-insensitive filesystems source and destination
        # resolve identically. Prove the skip branch never attempts self-copy.
        prefix = (
            "function Resolve-Path { [pscustomobject]@{ Path = 'same/OCR.4DX' } }\n"
            "function Copy-Item { throw 'self-copy must not occur' }"
        )
        self.assert_ok(self.run_step("normalize windows output to canonical case", prefix))

    def test_cleanup_error_is_fatal_and_preserves_binary(self):
        self.binary.write_bytes(b"stale Windows x64")
        result = self.run_step("clean stale outputs",
                               "function Remove-Item { Write-Error 'fixture cleanup failure' }")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fixture cleanup failure", result.stderr)
        self.assertEqual(self.binary.read_bytes(), b"stale Windows x64")

    def test_canonical_directory_failure_is_fatal(self):
        self.binary.write_bytes(b"fresh Windows x64")
        result = self.run_step("normalize windows output to canonical case",
                               "function New-Item { Write-Error 'fixture directory failure' }")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("fixture directory failure", result.stderr)


if __name__ == "__main__":
    unittest.main()
