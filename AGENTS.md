# Notes for coding agents

Read [CONTRIBUTING.md](CONTRIBUTING.md) before you change anything. It covers
branches, commits, the checks, the code conventions, the protocol library and
releases. The [README](README.md) and the [user guide](docs/user-guide.md)
explain how to install and use miniDSP-Linux-qt, and the
[developer guide](docs/development.md) how to set it up, run, test and build it
from a checkout. [docs/architecture.md](docs/architecture.md) explains the
design, with the module map and the invariants. Read the invariants before you
change the code they protect.

Architecture decisions are recorded as MADR files in
[docs/decisions/](docs/decisions/index.md). Read the records of an area before
you propose a change there. When a change would contradict a record, or makes a
decision worth recording, stop and ask the maintainer before you go on.

## How to work here

* Don't start the application in connected mode against a real DSP, and don't
  run anything that writes to one (storing presets, setting a PIN, linking
  channels, the test tone), unless the maintainer asks for it. A PIN can't be
  removed again: there is no known factory reset. Use `--offline`; the tests
  need no device.
* The device protocol is specified in the protocol library's
  [protocol documentation](https://imbarator.github.io/miniDSP-Linux/protocol/).
  Read it before you work on code that sends commands or interprets what the
  device reports.
* When the protocol library is wrong or lacks something, suggest a fix in the
  library instead of working around it here.
* Don't add AI attribution (co-author trailers, "generated with" footers) to
  commits, pull requests or files.
