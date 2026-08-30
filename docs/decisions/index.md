# Architecture Decisions

This directory holds the project's architecture decision records, written in the
[MADR](https://adr.github.io/madr/) format — one file per decision, each stating
the problem, the options that were actually available, and why one was chosen.

The records were written retrospectively from the commit history and the existing
documentation. They describe real decisions and cite the commits that made them,
but the reasoning is reconstructed rather than captured at the time. See
[ADR-0000](0000-use-markdown-any-decision-records.md) for why the log exists.

To add a record, copy [adr-template.md](adr-template.md) to the next number and add
a line to the relevant table below.

## Foundation and dependencies

| ADR | Decision |
|-----|----------|
| [0001](0001-build-on-the-minidsp-linux-protocol-library.md) | Build on the miniDSP-Linux protocol library instead of speaking USB HID directly |
| [0002](0002-use-pyside6-essentials-as-the-gui-toolkit.md) | Use PySide6-Essentials as the GUI toolkit |
| [0003](0003-pin-the-protocol-library-to-a-release-wheel-via-pep-508.md) | Pin the protocol library to a published release wheel via a PEP 508 direct URL |
| [0004](0004-license-under-gplv3-with-lgpl-and-interop-notices.md) | License under GPLv3, with explicit Qt LGPL and protocol-interoperability notices |
| [0030](0030-support-windows-by-delegating-transport-selection-to-the-protocol-library.md) | Support Windows by delegating transport selection to the protocol library |

## Runtime architecture

| ADR | Decision |
|-----|----------|
| [0005](0005-isolate-device-io-in-a-dedicated-qthread-worker.md) | Isolate all device I/O in a dedicated QThread worker |
| [0006](0006-make-mainwindow-the-sole-mediator-between-views-and-device.md) | Make MainWindow the sole mediator between views and the device |
| [0007](0007-coalesce-parameter-writes-and-serialise-config-operations.md) | Coalesce parameter writes in a keyed dict; serialise config operations in a FIFO queue |
| [0008](0008-mirror-device-configuration-in-a-typed-devicestate-dataclass.md) | Mirror device configuration in a typed DeviceState dataclass |
| [0009](0009-replicate-master-to-slave-fan-out-in-the-client.md) | Replicate master-to-slave parameter fan-out in the client |
| [0010](0010-implement-offline-mode-as-an-in-ram-virtual-dsp.md) | Implement offline mode as an in-RAM VirtualDSP behind the DSPmini interface |
| [0011](0011-treat-the-device-as-authoritative-and-re-read-after-multi-step-edits.md) | Treat the device as authoritative and re-read configuration after multi-step edits |
| [0012](0012-catch-only-device-and-transport-errors.md) | Catch only device and transport errors; let programming errors propagate |

## Protocol and device semantics

| ADR | Decision |
|-----|----------|
| [0013](0013-emit-multi-parameter-dsp-commands-atomically.md) | Emit multi-parameter DSP commands atomically from the panel |
| [0014](0014-source-factory-defaults-from-the-protocol-library.md) | Source factory defaults from the protocol library rather than hardcoding them |
| [0015](0015-render-filter-curves-locally-from-biquad-math-at-48-khz.md) | Render filter response curves locally from biquad maths at 48 kHz |
| [0016](0016-preserve-unknown-unt-bytes-with-field-level-overwrites.md) | Preserve unknown `.unt` bytes by writing field-level overwrites onto a template |
| [0017](0017-device-lock-pin-flow-stops-the-worker-rather-than-retrying.md) | Stop the worker on lock cancellation rather than auto-reconnecting |

## UI composition and styling

| ADR | Decision |
|-----|----------|
| [0018](0018-build-the-ui-programmatically-instead-of-qt-designer-files.md) | Build the UI programmatically instead of using Qt Designer `.ui` files |
| [0019](0019-style-with-qss-and-drive-state-styling-through-dynamic-properties.md) | Style with QSS and drive state-dependent styling through Qt dynamic properties |
| [0020](0020-let-an-explicit-theme-preference-override-the-reported-system-scheme.md) | Centralise theming in a ThemeManager, and let an explicit preference override the reported system scheme |
| [0021](0021-give-each-dsp-feature-one-brand-hue-across-the-whole-ui.md) | Give each DSP feature one brand hue, reused across button, indicator, and graph |
| [0022](0022-compose-the-detail-view-from-pluggable-feature-panels.md) | Compose the detail view from pluggable feature panels with shared helpers |
| [0023](0023-make-linked-slave-channels-read-only-in-the-ui.md) | Make linked slave channels read-only in the UI |
| [0024](0024-use-non-modal-apply-and-stay-open-dialogs-for-iterative-tools.md) | Use non-modal, apply-and-stay-open dialogs for iterative device tools |

## Testing

| ADR | Decision |
|-----|----------|
| [0025](0025-test-headlessly-against-an-injected-fake-dsp.md) | Test headlessly against an injected fake DSP |

## Build, release, and documentation

| ADR | Decision |
|-----|----------|
| [0026](0026-manage-the-project-with-uv-hatchling-ruff-and-make.md) | Manage the project with uv, Hatchling, ruff, and a Makefile |
| [0027](0027-distribute-a-self-contained-appimage-with-bundled-cpython.md) | Distribute a self-contained AppImage with a bundled CPython |
| [0028](0028-drive-releases-from-conventional-commits.md) | Drive changelog and releases from Conventional Commits |
| [0029](0029-publish-docs-as-a-mkdocs-site-with-a-generated-api-reference.md) | Publish documentation as an MkDocs Material site with a generated API reference |

## Decisions that reversed an earlier position

Several records document a position the project actively abandoned. These are the
most useful entries to read before proposing a change in the same area, because the
alternative has already been tried here.

| ADR | Previous position | Why it was abandoned |
|-----|-------------------|----------------------|
| [0018](0018-build-the-ui-programmatically-instead-of-qt-designer-files.md) | A `.ui` skeleton compiled by `pyside6-uic` | Nothing in it was Designer-editable, while every layout tweak cost a regen-and-commit |
| [0015](0015-render-filter-curves-locally-from-biquad-math-at-48-khz.md) | Biquad coefficients evaluated at 96 kHz | Bilinear warping put high-frequency resonance peaks in the wrong place |
| [0020](0020-let-an-explicit-theme-preference-override-the-reported-system-scheme.md) | Always re-query `QStyleHints.colorScheme()` | KDE Plasma keeps reporting the system scheme after an override, so explicit choices bounced back |
| [0014](0014-source-factory-defaults-from-the-protocol-library.md) | Hardcoded default constants per widget | Values did not match the device's F00 preset, and knob reset jumped to the minimum |
| [0003](0003-pin-the-protocol-library-to-a-release-wheel-via-pep-508.md) | `[tool.uv.sources]` pointing at a git tag | Not propagated into wheel metadata, so plain `pip` tried to resolve from PyPI |
| [0002](0002-use-pyside6-essentials-as-the-gui-toolkit.md) | The full `PySide6` meta-package | Pulled ~100 MB of unused Addons and a `libnss3` dependency |
| [0012](0012-catch-only-device-and-transport-errors.md) | `except Exception` around the worker loop | Swallowed genuine bugs, presenting them as mysterious reconnects |
| [0019](0019-style-with-qss-and-drive-state-styling-through-dynamic-properties.md) | Inline `setStyleSheet()` per widget | Near-identical strings proliferated and state changes rebuilt stylesheets at runtime |
| [0016](0016-preserve-unknown-unt-bytes-with-field-level-overwrites.md) | `blank.unt` seeded with hand-rolled values | It re-seeded slot U01 with wrong values, masking in-RAM corrections |
