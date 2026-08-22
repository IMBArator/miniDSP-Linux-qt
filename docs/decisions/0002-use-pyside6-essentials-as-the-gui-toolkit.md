---
status: accepted
date: 2026-05-21
decision-makers: Maximilian Zettler
---

# Use PySide6-Essentials as the GUI toolkit

## Context and Problem Statement

The project goal is a Python GUI for the t.racks DSP 4x4 Mini on Linux. The UI is
dense: eight channel strips with live level meters polled every 150 ms, several
custom-painted graphs, and a routing matrix with drag interaction. It also needs
to ship to users who do not have a Python toolchain (ADR-0027).

Two questions had to be answered: which toolkit, and — once Qt was chosen — which
Qt distribution package.

## Decision Drivers

* Custom painting is central. Level meters, all five graphs, the knobs, the LED
  indicator, and the routing matrix are painted by hand, so a mature 2D painting
  API matters more than a rich stock-widget set.
* A worker-thread-to-UI communication primitive is needed, since all device I/O
  is off the GUI thread (ADR-0005).
* The application must be bundled into a single-file AppImage, so install size
  and transitive native dependencies are a direct cost.
* Licensing has to be compatible with distributing a GPLv3 application (ADR-0004).

## Considered Options

* PySide6 (the official Qt for Python binding), full meta-package
* PySide6-Essentials
* PyQt6
* GTK via PyGObject
* A web-technology shell (Electron-style, or a local server plus browser)

## Decision Outcome

Chosen option: **PySide6-Essentials**, the Qt-for-Python binding restricted to
the essential modules.

Qt was chosen for the toolkit: `QPainter` handles every custom widget here,
signals and slots are exactly the thread-to-UI primitive the worker design needs,
`QSS` provides stylesheet-based theming (ADR-0019), and PySide6 is the binding
maintained by the Qt Company under LGPLv3, which sits comfortably inside a GPLv3
application.

The package was later narrowed from `PySide6` to `PySide6-Essentials`
(`d26414c`). This codebase imports only `QtCore`, `QtGui`, and `QtWidgets`, all
of which live in Essentials. The full `PySide6` meta-package additionally pulls
`PySide6-Addons` — roughly 100 MB of QtWebEngine, QtMultimedia, and QML — and
`QtWebEngineCore` drags in `libsmime3` from `libnss3`. None of it is used.

The minimum is Qt 6.8, raised from an earlier floor when theming needed
`setColorScheme`/`unsetColorScheme` as the clean way to express an explicit
override plus a return-to-system path (`9e4c844`, ADR-0020).

### Consequences

* Good, because install size and the transitive native-dependency surface both
  shrink substantially, which matters most in the AppImage.
* Good, because the AppImage build can strip the entire `PySide6/Qt/qml` tree and
  several Qt plugin directories outright — this is a Qt Widgets application with
  no QML (`3179db6`).
* Neutral, because the floor is Qt 6.8 and Python 3.11, ruling out older
  distributions. The AppImage makes that irrelevant for end users.
* Bad, because the split package leaves `PySide6` a namespace package with no
  `__init__.py`, so `PySide6.__version__` does not exist. `pytest-qt`'s
  `qt_compat` reads it unconditionally in its `report_header` hook, so
  `tests/conftest.py` carries a shim synthesizing it from `QtCore.__version__`.
  This is a real, if small, permanent maintenance cost traceable directly to this
  decision.
* Bad, because adding a feature from Addons later means reverting to the full
  package, not adding a narrow dependency.

### Confirmation

The test suite passed unchanged across the narrowing, and imports stay confined to
the three Essentials modules. The AppImage smoke test
boots the GUI under the offscreen QPA platform, which would fail loudly if a
required Qt module were missing from the bundle (`c34205d`).

## Pros and Cons of the Options

### PySide6-Essentials

* Good, because it is the official binding, LGPLv3, and tracks Qt releases closely
* Good, because it carries only the modules this application actually imports
* Bad, because it requires the `pytest-qt` version shim described above

### PySide6 (full meta-package)

* Good, because everything is present and no shim is needed
* Bad, because roughly 100 MB and a `libnss3` dependency are carried for nothing

### PyQt6

* Good, because it is mature with equivalent capability
* Bad, because Riverbank's licensing is GPL-or-commercial, a needlessly tighter
  constraint than LGPLv3 for a project that also wants to be embeddable

### GTK via PyGObject

* Good, because it integrates natively on GNOME
* Bad, because custom painting and a stylesheet theming story are both weaker
* Bad, because there is no equally clean cross-thread signal primitive

### A web-technology shell

* Good, because layout and styling would be familiar
* Bad, because it adds a browser engine to ship a USB HID control panel
* Bad, because 150 ms level-meter polling across a process boundary is
  gratuitous complexity for no gain

## More Information

* `d26414c` — the narrowing, with measurements
* `ec35379` — the LGPLv3 acknowledgment and About dialog attribution
* Related: ADR-0004 (licensing), ADR-0019 (QSS styling), ADR-0027 (AppImage)
