# Incremental Multi-Profile Rendering Design

## Goal

Reduce multi-pattern profile refreshes from roughly 2.6–2.7 seconds toward the
single-pattern 0.4–0.6 second range without changing Match, Gain, fitted profile
parameters, markers, legends, or export output.

## Evidence

Runtime logs show that ordinary profile updates take 0.43–0.56 seconds, while
two updates with 17 selected patterns take 2.63–2.75 seconds. The current
refresh path clears the complete calculated overlay and recreates every cached
pattern layer even when only the active pattern changed.

## Design

Calculated plot items are owned by a pattern identifier. A refresh receives an
update scope:

- `active`: remove and recreate calculated items for the active pattern only;
- `all`: preserve the current full rebuild for global view changes.

Scientific profile results remain in the existing result cache. Incremental
rendering changes only the lifecycle of plot items. A cache miss for an inactive
pattern never starts a scientific calculation; activating that pattern creates
its result and rendered items.

Full redraw remains mandatory when the displayed pattern set, stacking,
normalization, global plot style, layer visibility, or project contents change.
Phase acceptance, preprocessing, and parameter refinement update only the active
pattern unless their operation explicitly affects every pattern.

## Safety and fallback

If pattern ownership cannot be established for an existing plot item, the code
falls back to the current full overlay rebuild. Removing a pattern also removes
its owned items. Export continues to build the complete publication canvas and
does not depend on incremental on-screen state.

## Verification

- A focused ownership test proves that active refresh removes only active items.
- Existing full-clear behavior remains available and unchanged.
- User verification compares `match.profile` timings on the same 17-pattern
  project and visually checks markers, fitted profiles, legends, and export.

