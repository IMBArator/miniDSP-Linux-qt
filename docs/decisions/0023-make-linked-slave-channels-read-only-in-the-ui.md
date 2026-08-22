---
status: accepted
date: 2026-05-11
decision-makers: Maximilian Zettler
---

# Make linked slave channels read-only in the UI

## Context and Problem Statement

When channels are linked, the master governs the group and slaves mirror it
(ADR-0009). The detail view can display any channel, including a slave — so what
should happen when a user turns a knob on a slave channel's PEQ panel?

The device would accept the write. But the value would be silently overwritten the
next time the master changed anything, and possibly sooner. The user would have made
an edit that appears to work and then quietly disappears.

## Decision Drivers

* An edit that is silently reverted is worse than an edit that is refused.
* Users still need to *see* a slave's parameters — that is how you verify a link
  did what you expected.
* The reason a control is disabled must be visible, or it reads as a bug.
* Whatever is chosen has to apply uniformly to five panels (ADR-0022).

## Considered Options

* Show slave values but disable editing, with an explanatory banner
* Allow edits on slaves and let them be overwritten
* Redirect slave edits to the master
* Hide slave channels from the detail view entirely

## Decision Outcome

Chosen option: **show the values, disable editing, and explain why.**

The shared `_slave_lock` helper (ADR-0022) installs a centred banner at the top of
a panel's layout reading `🔗 Linked to <master> — read-only`, or `🔗 Linked —
read-only` when the master's name is unknown. `apply_link_state` shows or hides it
and calls `setEnabled(not is_slave)` across the list of interactive widgets the
panel passes in. All five feature panels compose it.

The state propagates through the detail view: `set_channel` calls
`strip.set_linked_slave(...)` so the chain indicator and tooltip appear whenever
the displayed channel is a slave — previously only the home view showed it — and
`_apply_slave_lock` fans the read-only state out to every feature panel
(`822046b`). The per-feature Reset button joins the disabled widget list, since
resetting a slave is the same silent-overwrite problem.

**One deliberate exception is worth recording: the overlay checkboxes stay
interactive on slave channels.** They are pure view toggles that change nothing on
the device, so disabling them would remove a useful comparison tool for no benefit.
`_overlay_controls` documents this invariant explicitly — the checkboxes are never
added to the slave-lock interactive list.

A second nuance: in the delay panel the knob is disabled but the overview graph
stays enabled, so the inherited value is still visible across all four outputs.

The link indicator itself was later broadened. The chain icon moved from the end of
the toggle row into the title row beside the channel name, and **masters show it
too**, with a "Master of …" tooltip — so the relationship is legible from either
end rather than only marking the constrained side (`9f272a9`).

### Consequences

* Good, because the failure mode is eliminated by construction. There is no path
  for a user to make an edit that silently disappears.
* Good, because slave values remain fully visible, so linking can be verified.
* Good, because the banner makes disabled controls self-explanatory rather than
  looking broken.
* Good, because it is uniform across five panels through one helper, so behaviour
  cannot differ per feature.
* Bad, because editing a linked channel takes an extra step: the user must navigate
  to the master. Mitigated by the master's own indicator and tooltip naming the
  relationship.
* Bad, because the protection is opt-in per panel. A future panel that forgets to
  install the lock is editable on slaves, and nothing detects that.
* Neutral, because it makes the linking dialog the sole route to changing topology,
  which is consistent with topology changes needing a re-read (ADR-0011).

### Confirmation

`tests/test_channel_linking_sync.py` asserts that feature panels are disabled and
the banner shown for slaves, that panels stay editable for masters, that the chain
indicator appears on slave entry and not on standalone channels, and that it updates
on nav-button navigation. `tests/test_overlay_controls.py` asserts the overlay
checkboxes remain enabled regardless, pinning the documented exception.

## Pros and Cons of the Options

### Show, disable, explain

* Good, because silent data loss becomes structurally impossible
* Good, because values stay visible for verification
* Bad, because editing requires navigating to the master
* Bad, because the guard is opt-in per panel

### Allow edits and let them be overwritten

* Good, because every control is always live, with no special states
* Bad, because it is exactly the silent-overwrite trap this decision exists to
  prevent — the worst outcome for user trust

### Redirect slave edits to the master

* Good, because edits work from anywhere, which is arguably the friendliest behaviour
* Bad, because the user edits one channel and a different one changes, which is
  surprising in the opposite direction
* Bad, because it obscures the link relationship rather than teaching it
* Neutral, because it would be feasible — `mutate_with_links` already accepts the
  master's index

### Hide slave channels from the detail view

* Good, because the question disappears entirely
* Bad, because there is then no way to confirm what a slave actually holds
* Bad, because the nav buttons show all eight channels; hiding some would be odd

## More Information

* `e855cf9` — the `_slave_lock` helper and initial panel wiring
* `822046b` — detail-view link indicator and fan-out of the read-only state
* `9f272a9` — moving the indicator to the title row and showing it on masters
* Related: ADR-0009 (why slave values are mirrored), ADR-0011 (topology changes
  re-read), ADR-0022 (composition of the shared helper)
