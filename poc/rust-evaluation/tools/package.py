#!/usr/bin/env python3
"""Stage the three experiments into an explicit safe prefix, with reversible ownership."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = Path("share/omarchy-zones-rust-poc/manifest.json")
INFO = Path("share/omarchy-zones-rust-poc/build-info.json")
ARTIFACTS = {
    "lib/omarchy-zones-rust-poc/zones-rust-poc.so": ROOT / "native/target/release/zones-rust-poc.so",
    "bin/zones-qtbridge-poc": ROOT / "qtbridge/target/release/zones-qtbridge-poc",
    "bin/zones-cxxqt-evaluation": ROOT / "cxxqt/target/release/zones-cxxqt-evaluation",
}
OWNED = set(ARTIFACTS) | {str(INFO)}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def no_symlink(path):
    for part in [path, *path.parents]:
        if part.is_symlink():
            raise RuntimeError(f"Symlink paths are not supported: {part}")


def checked_prefix(value):
    raw = Path(value).expanduser()
    if not raw.is_absolute():
        raise RuntimeError("--prefix must be an explicit absolute path.")
    path = Path(os.path.abspath(raw))
    no_symlink(path)
    home = Path.home()
    if path in (Path("/"), home, ROOT) or len(path.parts) < 3:
        raise RuntimeError("Use a dedicated experiment prefix, not a top-level or home directory.")
    forbidden = [Path(x) for x in ("/usr", "/bin", "/sbin", "/lib", "/lib64", "/etc",
                                     "/boot", "/dev", "/proc", "/sys", "/run", "/opt")]
    forbidden += [home / name for name in (".local", ".config", ".cache")]
    if any(path == base or path.is_relative_to(base) for base in forbidden):
        raise RuntimeError("The experiment cannot be installed into desktop or system directories.")
    if path.is_relative_to("/var") and not path.is_relative_to("/var/tmp"):
        raise RuntimeError("Only /var/tmp is allowed below /var for this experiment.")
    return path


def existing(path):
    return path.exists() or path.is_symlink()


def atomic(path, data, mode):
    no_symlink(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".zones-rust-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as output:
            output.write(data)
        os.chmod(name, mode)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


def read_manifest(prefix):
    path = prefix / MANIFEST
    no_symlink(path)
    if not path.exists():
        return None
    manifest = json.loads(path.read_text())
    if (manifest.get("schema") != 1 or manifest.get("prefix") != str(prefix)
            or not isinstance(manifest.get("owned"), dict) or set(manifest["owned"]) != OWNED):
        raise RuntimeError("The ownership manifest does not match this experiment and prefix.")
    return manifest


def verify_owned(prefix, manifest):
    for relative, expected in manifest["owned"].items():
        path = prefix / relative
        no_symlink(path)
        if existing(path) and (not path.is_file() or digest(path.read_bytes()) != expected):
            raise RuntimeError(f"Owned file was modified; refusing changes: {path}")


def collect_artifacts():
    payload = {}
    metadata = {"created_at_unix": time.time(), "artifacts": {},
                "activation": "none; no bindings, autoload, desktop entries, or configuration"}
    for relative, source in ARTIFACTS.items():
        if not source.is_file():
            raise RuntimeError(f"Build first with sh build-all.sh. Missing: {source}")
        data = source.read_bytes()
        payload[relative] = (data, 0o755)
        dependencies = subprocess.run(["ldd", str(source)], text=True, capture_output=True)
        if dependencies.returncode or "not found" in dependencies.stdout:
            raise RuntimeError(f"Unresolved shared-library dependencies: {source}\n{dependencies.stdout}{dependencies.stderr}")
        metadata["artifacts"][relative] = {"source": str(source), "sha256": digest(data),
            "bytes": len(data), "ldd": dependencies.stdout.splitlines()}
    header = Path("/usr/include/hyprland/src/version.h").read_text()
    match = re.search(r'^#define\s+GIT_COMMIT_HASH\s+"([0-9a-f]+)"', header, re.M)
    if not match:
        raise RuntimeError("Could not read the native plugin's matching Hyprland header commit.")
    commit = match[1]
    if commit.encode() not in payload["lib/omarchy-zones-rust-poc/zones-rust-poc.so"][0]:
        raise RuntimeError("Native plugin does not contain the current header commit; rebuild before staging.")
    metadata["hyprland_header_commit"] = commit
    metadata["hyprland_commit_present_in_plugin"] = True
    payload[str(INFO)] = ((json.dumps(metadata, indent=2) + "\n").encode(), 0o644)
    return payload


def install(prefix, payload):
    manifest = read_manifest(prefix)
    if manifest:
        verify_owned(prefix, manifest)
    for relative in payload:
        path = prefix / relative
        no_symlink(path)
        if existing(path) and (not manifest or relative not in manifest["owned"]):
            raise RuntimeError(f"Foreign file occupies an install path: {path}")
    prior = {}
    for relative in [*payload, str(MANIFEST)]:
        path = prefix / relative
        if existing(path):
            if not path.is_file():
                raise RuntimeError(f"Install path is not a regular file: {path}")
            prior[relative] = (path.read_bytes(), path.stat().st_mode & 0o777)
    touched = []
    try:
        for relative, (data, mode) in payload.items():
            atomic(prefix / relative, data, mode)
            touched.append(relative)
        next_manifest = {"schema": 1, "prefix": str(prefix),
                         "owned": {name: digest(data) for name, (data, _) in payload.items()}}
        atomic(prefix / MANIFEST, (json.dumps(next_manifest, indent=2) + "\n").encode(), 0o644)
    except BaseException:
        for relative in touched:
            if relative in prior:
                atomic(prefix / relative, *prior[relative])
            else:
                (prefix / relative).unlink(missing_ok=True)
        raise


def remove(prefix):
    manifest = read_manifest(prefix)
    if manifest is None:
        raise RuntimeError("No ownership manifest exists; nothing will be removed.")
    verify_owned(prefix, manifest)
    for relative in manifest["owned"]:
        (prefix / relative).unlink(missing_ok=True)
    (prefix / MANIFEST).unlink()
    # Remove only empty directories under this prefix; unrelated files survive.
    directories = {prefix / Path(name).parent for name in [*manifest["owned"], str(MANIFEST)]}
    for directory in sorted(directories, key=lambda p: len(p.parts), reverse=True):
        while directory != prefix:
            try:
                directory.rmdir()
            except OSError:
                break
            directory = directory.parent


def self_test(output):
    payload = collect_artifacts()
    results = []
    with tempfile.TemporaryDirectory(prefix="zones-rust-package-") as temporary:
        prefix = checked_prefix(str(Path(temporary) / "prefix"))
        prefix.mkdir()
        sentinel = prefix / "unrelated.txt"
        sentinel.write_text("preserve unrelated state\n")
        before = sentinel.read_bytes()
        install(prefix, payload)
        verify_owned(prefix, read_manifest(prefix))
        results.append("staged all real built artifacts and verified hashes")
        install(prefix, payload)
        results.append("repeat install accepted matching owned files")
        path = prefix / "bin/zones-qtbridge-poc"
        original = path.read_bytes()
        path.write_bytes(original + b"modified")
        try:
            remove(prefix)
        except RuntimeError as error:
            if "modified" not in str(error):
                raise
        else:
            raise AssertionError("Removal accepted a modified owned file")
        if not all((prefix / name).exists() for name in OWNED):
            raise AssertionError("Rejected removal deleted an owned file")
        path.write_bytes(original)
        results.append("modified owned file blocks all removal")
        remove(prefix)
        if sentinel.read_bytes() != before or list(prefix.iterdir()) != [sentinel]:
            raise AssertionError("Removal changed unrelated contents or retained owned files")
        results.append("remove preserved unrelated sentinel exactly")
        path.parent.mkdir()
        path.write_text("foreign file")
        try:
            install(prefix, payload)
        except RuntimeError as error:
            if "Foreign file" not in str(error):
                raise
        else:
            raise AssertionError("Installation overwrote a foreign file")
        if path.read_text() != "foreign file" or (prefix / MANIFEST).exists():
            raise AssertionError("Foreign collision changed the prefix")
        results.append("foreign install collision refused without overwriting")
        symlink = Path(temporary) / "linked-prefix"
        symlink.symlink_to(prefix, target_is_directory=True)
        try:
            checked_prefix(str(symlink))
        except RuntimeError:
            pass
        else:
            raise AssertionError("Symlink prefix accepted")
        results.append("symlink prefix refused")
    for forbidden in [Path.home() / ".local/zones-test", Path("/usr/local/zones-test")]:
        try:
            checked_prefix(str(forbidden))
        except RuntimeError:
            pass
        else:
            raise AssertionError(f"Forbidden prefix accepted: {forbidden}")
    results.append("desktop and system prefixes refused")
    report = {"passed": True, "checks": results, "completed_at_unix": time.time(),
              "real_artifact_paths": [str(p) for p in ARTIFACTS.values()],
              "artifact_sha256": {name: digest(payload[name][0]) for name in ARTIFACTS}}
    if output:
        Path(output).parent.mkdir(parents=True, exist_ok=True)
        Path(output).write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    for action in ("install", "remove"):
        command = actions.add_parser(action)
        command.add_argument("--prefix", required=True)
    test = actions.add_parser("self-test")
    test.add_argument("--report")
    args = parser.parse_args()
    if args.action == "self-test":
        self_test(args.report)
    else:
        prefix = checked_prefix(args.prefix)
        if args.action == "install":
            install(prefix, collect_artifacts())
            print(f"Staged three experiments under {prefix}. Nothing activated or configured.")
        else:
            remove(prefix)
            print(f"Removed owned experiment files from {prefix}. Unrelated contents retained.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, RuntimeError, ValueError) as error:
        raise SystemExit(str(error)) from error
