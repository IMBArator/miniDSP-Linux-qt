---
status: accepted
date: 2026-04-24
decision-makers: Maximilian Zettler
---

# License under GPLv3, with explicit Qt LGPL and protocol-interoperability notices

## Context and Problem Statement

This application controls hardware sold by a third party, using a protocol that
was reverse-engineered rather than published, and links a GUI toolkit distributed
under LGPLv3. Three distinct licensing questions follow: what licence the
application carries, what obligations the Qt dependency imposes, and what the
project's stated position is on the reverse-engineered protocol.

Leaving any of them implicit is a problem for a project distributed publicly as a
prebuilt binary (ADR-0027).

## Decision Drivers

* The upstream protocol library and the sibling ecosystem are copyleft; matching
  them avoids a licence-compatibility seam within one toolchain.
* PySide6 is LGPLv3, which imposes real obligations on a distributed binary —
  particularly one that bundles Qt (ADR-0027).
* An AppImage bundles Qt, so "the user can swap the library" must be true in
  practice, not just in principle.
* The protocol was reverse-engineered, and the project's legal basis for that
  should be stated rather than left for a reader to guess.

## Considered Options

* GPLv3 for the application
* LGPLv3 for the application
* A permissive licence (MIT or Apache-2.0)

## Decision Outcome

Chosen option: **GPLv3**, recorded in [LICENSE](https://github.com/IMBArator/miniDSP-Linux-qt/blob/main/LICENSE),
alongside two explicit notices in the README and the About dialog (`ec35379`).

The Qt notice states that PySide6 is licensed under LGPLv3, that users have the
right to obtain, modify, and redistribute the Qt/PySide6 source, and — the
operative part for a bundled binary — that the library is **dynamically linked**
so users can replace the PySide6 version at runtime without modifying this
application. The AppImage design keeps that claim true: Qt ships as ordinary
shared objects inside the AppDir with `AppRun` wiring `LD_LIBRARY_PATH` and
`QT_PLUGIN_PATH`, rather than being statically linked or frozen into a single
binary.

The interoperability notice states that the project is not affiliated with
Musicrown, t.racks, or Thomann, and that the protocol was reverse-engineered for
interoperability purposes under applicable law.

The same attribution appears in the About dialog, so it reaches users who never
read the README (`ec35379`, and see ADR-0022 for where that dialog now lives).

### Consequences

* Good, because it is licence-compatible with the upstream protocol library and
  the wider sibling ecosystem, with no internal compatibility seam.
* Good, because GPLv3 and LGPLv3 dynamic linking are a well-understood pairing,
  so bundling Qt in the AppImage is a solved problem rather than a novel question.
* Good, because the interoperability position is stated publicly rather than left
  to inference.
* Neutral, because the notices must be maintained in two places — README and
  About dialog — which is accepted deliberately so the attribution is visible
  in the running application.
* Bad, because GPLv3 prevents reuse of this code in a closed-source product.
  That is the intended effect, but it also rules out permissively-licensed reuse
  of otherwise generic parts, such as the custom widgets.
* Bad, because packaging must preserve dynamic linking to keep the Qt notice
  accurate. A future switch to a freezing tool that statically links or embeds Qt
  would invalidate the stated claim and require re-examination.

### Confirmation

`LICENSE` contains the GPLv3 text; the README carries both notices; the About
dialog renders the PySide6 attribution, covered by `tests/test_about_dialog.py`.
The AppImage keeps Qt as replaceable shared objects — inspectable in the AppDir
layout produced by `packaging/appimage/build.sh`.

## Pros and Cons of the Options

### GPLv3

* Good, because it matches the upstream library and sibling projects
* Good, because it pairs cleanly and conventionally with LGPLv3 Qt
* Bad, because it forecloses closed-source reuse, including of generic components

### LGPLv3

* Good, because it would permit linking from non-copyleft applications
* Neutral, because this is a complete end-user application, not a library, so the
  distinction buys little
* Bad, because it is a weaker match for the surrounding ecosystem

### Permissive (MIT / Apache-2.0)

* Good, because it maximises reuse
* Bad, because it is a poor fit for a project built on copyleft foundations
* Bad, because it permits a proprietary redistribution of a community
  reverse-engineering effort, which runs against the project's intent

## More Information

* `ec35379` — the Acknowledgments section and About dialog attribution
* [README licensing section](https://github.com/IMBArator/miniDSP-Linux-qt#license)
* Related: ADR-0002 (PySide6 choice), ADR-0027 (AppImage bundling)
