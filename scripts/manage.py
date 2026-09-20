#!/usr/bin/env python3
"""Install, update, or remove only Omarchy Zones' owned integration files."""
import argparse
import hashlib
import errno
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config")
DATA = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local/share")
DEST = DATA / "omarchy-zones"
MAIN = CONFIG / "hypr/hyprland.lua"
LAUNCHER = HOME / ".local/bin/omarchy-zones"
DESKTOP = DATA / "applications/omarchy-zones.desktop"
BEGIN = "-- BEGIN omarchy-zones (managed)\n"
END = "-- END omarchy-zones (managed)\n"
BINARIES = ("omarchy-zones.so", "omarchy-zones-editor")
MAX_MANIFEST_BYTES = 64 * 1024


def run(*args):
    p = subprocess.run(args, text=True, capture_output=True, check=True, timeout=15)
    return p.stdout.strip()


def atomic(path, data, mode=0o644, *, replace=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".zones-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data if isinstance(data, bytes) else data.encode())
            f.flush()
            os.fsync(f.fileno())
        os.chmod(name, mode)
        if replace:
            os.replace(name, path)
        else:
            os.link(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def digest(path):
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(128 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def exists(path):
    return path.exists() or path.is_symlink()


def plugin_loaded():
    plugins = json.loads(run("hyprctl", "-j", "plugin", "list"))
    return any(p.get("name") == "omarchy-zones" for p in plugins)


def unload_if_loaded():
    # A manually unloaded plugin is a valid state for removal.
    if not plugin_loaded():
        return
    failure = None
    try:
        run("hyprctl", "plugin", "unload", str(DEST / "omarchy-zones.so"))
    except subprocess.CalledProcessError as error:
        failure = error
    if plugin_loaded():
        raise RuntimeError("Hyprland still has Omarchy Zones loaded; installation files were retained.") from failure


def remove_exact_block(block):
    current = MAIN.read_bytes()
    encoded = block.encode()
    if current.count(encoded) != 1:
        raise RuntimeError("The managed block was edited. Restore that block before removal; unrelated content will not be overwritten.")
    atomic(MAIN, current.replace(encoded, b"", 1), MAIN.stat().st_mode & 0o777)
    return current


def verify_owned(owned, *, require_present=False):
    for name, expected in owned.items():
        path = Path(name)
        if require_present and not path.exists():
            raise RuntimeError(f"Owned file is missing: {path}")
        if path.is_symlink() or (path.exists() and (not path.is_file() or digest(path) != expected)):
            raise RuntimeError(f"Owned file was edited; refusing to delete it: {path}")


def delete_owned(owned):
    verify_owned(owned)
    for name in owned:
        Path(name).unlink(missing_ok=True)
    (DEST / "manifest.json").unlink(missing_ok=True)
    try:
        DEST.rmdir()
    except OSError as error:
        if error.errno != errno.ENOTEMPTY:
            raise
        print("Unrecognized files retained in " + str(DEST))


def check_reload():
    run("hyprctl", "reload")
    errors = run("hyprctl", "configerrors")
    if errors:
        raise RuntimeError(errors)


def validate_paths():
    # Relative XDG paths and control characters cannot be represented safely in
    # every integration format (Lua, a shell launcher, and a desktop entry).
    for path in (HOME, CONFIG, DATA, DEST, MAIN, LAUNCHER, DESKTOP):
        if not path.is_absolute() or any(ord(c) < 32 or ord(c) == 127 for c in str(path)):
            raise RuntimeError(f"Installation paths must be absolute and contain no control characters: {path!s}")


def lua_string(value):
    # Lua accepts literal UTF-8, but not JSON's \uXXXX escape syntax.
    return json.dumps(str(value), ensure_ascii=False)


def integration_block():
    return BEGIN + "dofile(" + lua_string(DEST / "zones.lua") + ")\n" + END


def build_binaries(build_dir=None):
    # An explicit build directory is relative to the caller, not the checkout.
    # Keeping the default here also preserves callers that import this module.
    directory = Path(build_dir) if build_dir is not None else ROOT / "build"
    if any(ord(c) < 32 or ord(c) == 127 for c in str(directory)):
        raise RuntimeError("The build directory must contain no control characters.")
    directory = directory.expanduser().resolve()
    if not directory.is_dir():
        raise RuntimeError(f"Build directory does not exist or is not a directory: {directory}")
    hash_path = directory / "hyprland-hash.txt"
    if hash_path.is_symlink() or not hash_path.is_file():
        raise RuntimeError("Build the project before installation or update; the Hyprland build hash must be a regular file.")
    version = json.loads(run("hyprctl", "-j", "version"))
    compiled = hash_path.read_text().strip()
    if version.get("commit") != compiled:
        raise RuntimeError("The running compositor and build headers differ. Rebuild against the running Hyprland.")
    result = {}
    for name in BINARIES:
        source = directory / name
        if source.is_symlink() or not source.is_file():
            raise RuntimeError("Build the project before installation or update; build artifacts must be regular files.")
        result[name] = (source.read_bytes(), source.stat().st_mode & 0o777)
    return result


def read_manifest():
    validate_paths()
    manifest_path = DEST / "manifest.json"
    if DEST.is_symlink() or MAIN.is_symlink() or manifest_path.is_symlink():
        raise RuntimeError("An installation path became a symlink; refusing to alter its target.")
    if not MAIN.is_file() or not manifest_path.is_file() or manifest_path.stat().st_size > MAX_MANIFEST_BYTES:
        raise RuntimeError("Installation configuration or manifest is missing, invalid, or oversized.")
    manifest = json.loads(manifest_path.read_text())
    if not isinstance(manifest, dict) or set(manifest) != {"block", "owned"}:
        raise RuntimeError("The installation manifest has unexpected fields.")
    block, owned = manifest["block"], manifest["owned"]
    expected_paths = {str(LAUNCHER), str(DESKTOP)} | {
        str(DEST / name) for name in (*BINARIES, "zones.lua", "hyprland.lua.before-install")
    }
    if not isinstance(owned, dict) or set(owned) != expected_paths:
        raise RuntimeError("The installation manifest has unexpected paths; refusing to alter files.")
    if any(not isinstance(value, str) or len(value) != 64 or
           any(character not in "0123456789abcdef" for character in value) for value in owned.values()):
        raise RuntimeError("The installation manifest contains an invalid file hash.")
    expected_block = integration_block()
    if block not in (expected_block, "\n" + expected_block):
        raise RuntimeError("The installation manifest contains an unexpected managed block.")
    return manifest


def install(build_dir=None):
    validate_paths()
    if exists(DEST):
        raise RuntimeError("Installation already exists. Run update to replace binaries or remove to uninstall; zone definitions are retained.")
    if exists(LAUNCHER) or exists(DESKTOP):
        raise RuntimeError("An integration path already exists; refusing to overwrite it.")
    if MAIN.is_symlink() or not MAIN.is_file():
        raise RuntimeError("hyprland.lua must be a regular file; linked configurations need explicit integration.")
    old = MAIN.read_bytes()
    old_mode = MAIN.stat().st_mode & 0o777
    if BEGIN.encode() in old or END.encode() in old:
        raise RuntimeError("A managed block already exists in hyprland.lua.")
    if plugin_loaded():
        raise RuntimeError("Omarchy Zones is already loaded outside this installation. Unload it before installing.")
    if run("hyprctl", "configerrors"):
        raise RuntimeError("Resolve existing Hyprland configuration errors before installation.")
    binaries = build_binaries(build_dir)
    binds = json.loads(run("hyprctl", "-j", "binds"))
    if any(b["modmask"] == 65 and b["key"].upper() in ("MOUSE:272", "F8") for b in binds):
        raise RuntimeError("Super+Shift+left mouse or Super+Shift+F8 is already bound; resolve the conflict explicitly.")
    # Lua string literals and desktop Exec fields have different escaping rules.
    q = lua_string
    so = str(DEST / "omarchy-zones.so")
    lua = f'''-- Generated by Omarchy Zones; loaded only through its marked integration block.
o.window("^(omarchy-zones-editor)$", {{ float = true, center = true }})
-- This declares the desired plugin set on every config reload; it does not
-- immediately load a second copy. Skipping this when loaded causes reload loops.
hl.plugin.load({q(so)})
o.bind("SUPER + SHIFT + mouse:272", "Move window with zones", hl.dsp.window.drag(), {{ mouse = true }})
o.bind("SUPER + SHIFT + F8", "Edit window zones", {q(str(LAUNCHER))})
'''
    block = integration_block()
    prefix = b"" if old.endswith(b"\n") else b"\n"
    owned = {}
    integrated = False
    DEST.mkdir(parents=True)

    def remember(path):
        owned[str(path)] = digest(path)

    try:
        atomic(DEST / "hyprland.lua.before-install", old, 0o600, replace=False)
        remember(DEST / "hyprland.lua.before-install")
        for name, (contents, mode) in binaries.items():
            atomic(DEST / name, contents, mode, replace=False)
            remember(DEST / name)
        atomic(DEST / "zones.lua", lua, replace=False)
        remember(DEST / "zones.lua")
        # The shell single-quote escape is independent of JSON/Lua quoting.
        executable = str(DEST / "omarchy-zones-editor").replace("'", "'\"'\"'")
        atomic(LAUNCHER, "#!/bin/sh\nexec '" + executable + "' \"$@\"\n", 0o755, replace=False)
        remember(LAUNCHER)
        exec_field = str(LAUNCHER).replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
        atomic(DESKTOP, '[Desktop Entry]\nType=Application\nName=Omarchy Zones\nComment=Define window zones\nExec="' + exec_field + '"\nIcon=preferences-desktop-display\nCategories=Utility;\nTerminal=false\n', replace=False)
        remember(DESKTOP)
        managed_block = (prefix + block.encode()).decode()
        atomic(DEST / "manifest.json", json.dumps({
            "block": managed_block,
            "owned": owned,
        }, indent=2), replace=False)
        if MAIN.read_bytes() != old:
            raise RuntimeError("hyprland.lua changed during installation; retry after editing is complete.")
        atomic(MAIN, old + managed_block.encode(), old_mode)
        integrated = True
        check_reload()
        if not plugin_loaded():
            raise RuntimeError("Hyprland did not load the plugin.")
    except Exception as original:
        try:
            if integrated:
                # Remove only our exact block, retaining unrelated edits made meanwhile.
                remove_exact_block(managed_block)
                check_reload()
                unload_if_loaded()
            delete_owned(owned)
        except Exception as rollback:
            raise RuntimeError(f"Installation failed: {original}. Rollback could not finish: {rollback}") from original
        raise
    print("Installed. Run omarchy-zones or Super+Shift+F8. Hold Shift while dragging a window.")


def remove():
    manifest = read_manifest()
    block, owned = manifest["block"], manifest["owned"]
    verify_owned(owned)
    current = remove_exact_block(block)
    removed = current.replace(block.encode(), b"", 1)
    try:
        check_reload()
        unload_if_loaded()
    except Exception as original:
        # Restore the removed integration only if doing so cannot lose another edit.
        latest = MAIN.read_bytes()
        if latest == removed:
            atomic(MAIN, current, MAIN.stat().st_mode & 0o777)
        elif BEGIN.encode() not in latest and END.encode() not in latest:
            separator = b"" if latest.endswith(b"\n") else b"\n"
            atomic(MAIN, latest + separator + block.encode(), MAIN.stat().st_mode & 0o777)
        else:
            raise RuntimeError(f"Removal failed: {original}. Configuration changed; installation files retained.") from original
        try:
            check_reload()
        except Exception as rollback:
            raise RuntimeError(f"Removal failed: {original}. Reload after rollback failed: {rollback}") from original
        raise
    delete_owned(owned)
    print("Removed. Zone definitions retained in " + str(CONFIG / "omarchy-zones"))


def update(build_dir=None):
    """Replace binaries without rewriting desktop configuration or zone data."""
    manifest = read_manifest()
    verify_owned(manifest["owned"], require_present=True)
    if MAIN.read_bytes().count(manifest["block"].encode()) != 1:
        raise RuntimeError("The managed block was edited; refusing to update this installation.")
    if run("hyprctl", "configerrors"):
        raise RuntimeError("Resolve existing Hyprland configuration errors before updating.")
    binaries = build_binaries(build_dir)
    manifest_path = DEST / "manifest.json"
    paths = [*(DEST / name for name in BINARIES), manifest_path]
    previous = {path: (path.read_bytes(), path.stat().st_mode & 0o777) for path in paths}
    was_loaded = plugin_loaded()
    changed = {}
    try:
        unload_if_loaded()
        for name, (contents, mode) in binaries.items():
            path = DEST / name
            # Recheck after the compositor call in case the user edited a file
            # while the update was waiting. Never overwrite that edit.
            verify_owned({str(path): manifest["owned"][str(path)]}, require_present=True)
            atomic(path, contents, mode)
            changed[path] = digest(path)
            manifest["owned"][str(path)] = changed[path]
        atomic(manifest_path, json.dumps(manifest, indent=2), previous[manifest_path][1])
        changed[manifest_path] = digest(manifest_path)
        if was_loaded:
            run("hyprctl", "plugin", "load", str(DEST / "omarchy-zones.so"))
            if not plugin_loaded():
                raise RuntimeError("Hyprland did not load the updated plugin.")
    except Exception as original:
        try:
            if changed:
                unload_if_loaded()
                for path, expected in changed.items():
                    verify_owned({str(path): expected}, require_present=True)
                for path in changed:
                    contents, mode = previous[path]
                    atomic(path, contents, mode)
            if was_loaded and not plugin_loaded():
                run("hyprctl", "plugin", "load", str(DEST / "omarchy-zones.so"))
                if not plugin_loaded():
                    raise RuntimeError("Hyprland did not reload the original plugin.")
        except Exception as rollback:
            raise RuntimeError(f"Update failed: {original}. Rollback could not finish: {rollback}") from original
        raise
    print("Updated binaries. Desktop configuration and zone definitions were preserved.")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="action", required=True)
    for action in ("install", "update"):
        command = commands.add_parser(action)
        command.add_argument("--build-dir", type=Path, metavar="PATH",
                             help="Use artifacts from PATH (default: checkout/build). Relative paths use the current directory.")
    commands.add_parser("remove")
    args = parser.parse_args(argv)
    try:
        if args.action == "remove":
            remove()
        else:
            {"install": install, "update": update}[args.action](args.build_dir)
    except Exception as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
