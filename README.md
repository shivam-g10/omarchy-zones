# Omarchy Zones

Dedicated window zones for large screens, inspired by Windows FancyZones.
Create precise layouts, switch profiles while dragging, and snap windows once.

**Plugin ID: `omarchy-zones` · Version: 0.5.0**

## Install

Ask your Omarchy agent:

> Install https://github.com/shivam-g10/omarchy-zones.

Uses Omarchy's existing shell and theme. No build, setup script or extra packages.
Update or remove through Omarchy's plugin manager.

## Use

- **Edit:** Super+Shift+F8. Draw zones or enter exact values; shared boundaries
  resize adjacent zones without overlaps.
- **Snap:** hold Super+Shift before left-dragging a window. Choose a profile
  or zone, then release the mouse.
- **Cancel:** release Shift before dropping.

Editing layouts leaves existing windows unchanged. Snapped windows float.
Profiles stay in `~/.config/omarchy-zones/zones.conf` (or under
`$XDG_CONFIG_HOME`), including after removal.

## Performance

Idle memory change in two warm enabled/disabled checks, 21 September 2026:

| Memory measurement | Change, MB |
| --- | ---: |
| Accounted memory (cgroup) | −0.004 to +0.225 |
| Proportional memory (PSS) | −0.094 to +0.340 |

Measured across the shared desktop fixture. The baseline retains UI caches;
these are differences, not total plugin memory. [Results and limits](docs/validation.md).

[Development](CONTRIBUTING.md) · [Maintenance](docs/maintenance.md)

No reuse license has been selected yet.
