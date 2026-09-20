# Git distribution validation

Checked on 20 September 2026 before the initial public push. This packaging
change retains version 0.3.1 and does not change the native snapping algorithm.

- A clean 90-file publication snapshot passed `omarchy plugin validate` and QML
  lint. Additional lifecycle test/documentation files were then added without
  changing the product entry point or manifest.
- The explicit setup wrapper built both release binaries from a separate build
  directory. An editor-only build without Hyprland discovery also completed;
  all seven CTest targets passed there.
- All 27 installer tests and six packaging tests passed. They cover alternate
  build paths, ABI rejection, ownership, rollback, removal, spaces in paths,
  launcher handoff, and the absence of implicit build/install on summon.
- A real native update in the isolated compositor used the new build-directory
  option. It preserved seven fixture files and checked six ownership hashes;
  the existing production binaries were unchanged.

## Official shell lifecycle

The actual installed Omarchy shell host and CLI ran on a private nested
Hyprland desktop with private HOME/XDG/D-Bus paths. Only an empty built-in bar
was exposed; first-party services were excluded before startup. The editor
dependency was pre-staged from the exact release build.

Git add installed the requested `omarchy-zones` ID disabled. Enabling did not
start an editor. Summoning opened the native Wayland editor; repeated summons
retained one process and window. Hiding or disabling the launcher preserved
the editor, disabled summons were rejected, and re-enabling reused that same
editor. Official removal deleted the shell checkout while preserving the
separately installed native dependency and saved definitions.

Two 20-second samples compared the same shell and its existing inotify helper:

| Metric | Before installation | Enabled after editor closed |
| --- | ---: | ---: |
| PSS | 199,017 KiB | 199,045 KiB |
| CPU, percent of one core | 0.05% | 0.00% |
| Added idle process | — | 0 |

The observed PSS increment was 28 KiB. This short endpoint comparison includes
existing shell activity and does not isolate every allocator/kernel allocation.
It is not a production-session or long-running benchmark. Native plugin/editor
resource measurements remain in [validation.md](validation.md).

The full private-runtime census covered reparented processes as well as shell
children. All test processes exited. All 165 pre-existing parent desktop
configuration hashes remained unchanged, and the installed native plugin still
reported 0.3.1 with four profiles and no error. Exposé was not modified or restarted.

This shell check does not replace the earlier native snapping, unsaved-edit,
theme, or physical-display coverage. Its editor dependency is pre-staged rather
than installed by Omarchy, matching the documented two-step installation model.
Raw logs, measurements and private fixtures are excluded from Git.
