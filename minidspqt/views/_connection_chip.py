"""Strings shared by the two connection chips (home view and detail view).

Both views render their own ``connectionLabel`` — the state names and the
short chip captions are deliberately inline at each call site, since they
are single words read next to the code that sets them. The busy tooltip is
the one exception: it is a full sentence of user-facing help text, so it
lives here to keep the two chips from drifting apart.
"""

from __future__ import annotations

DEVICE_BUSY_TOOLTIP = (
    "Another program (for example the minidsp command-line tool or the "
    "vendor editor) is holding the DSP. The connection is made "
    "automatically once it is released."
)
"""Tooltip shown on the connection chip while the DSP is held elsewhere.

Explains the one thing the user has to do — quit the other program — and
that no further action is needed after that, because
:meth:`minidspqt.device_thread.DeviceThread._try_connect` keeps retrying.
"""
