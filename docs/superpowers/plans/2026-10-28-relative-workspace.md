# Relative workspace geometry repair

> Inline execution, no subagents, publication or installed/stable-folder changes.

**Goal:** Use the user's screenshot as the initial proportional layout and retain
user adjustments across HD/2K windows, scale changes and restarts.
**Baseline:** main 6e7495f / release source 978127f already contains a canonical
workspace_preferences module absent from local develop. Port only that layout
implementation (layout_state, interface_scaling, candidate-table persistence and
workspace_preferences) before repairing it. Do not replace unrelated develop code.
**Stack:** Existing PySide6/QSettings and JSON, no dependencies.

## Contract
- Initial geometry now uses the user's exact saved reference, not screenshot
  estimates: project/centre/right 12.4294% / 59.5480% / 28.0226%, vertical centre
  72.0805% / 27.9195%, right 37.1459% / 62.8541%.
- Column fractions and order match the same saved profile. The anonymous,
  layout-only reference is tests/fixtures/workspace_start_layout.json; the real
  profile was read without modifying it and is not a runtime dependency.
- Store positive normalized fractions and column order in one workspace record;
  derive pixels from current usable splitter/viewport extents only when rendering.
- Preserve explicit user ratios; minimum geometry constraints must never overwrite
  requested ratios. Remove the sidebar's fixed maximum-width cap.
- Migrate old JSON pixel weights and native Qt records once, without taking ratios
  from an already constrained HD rendering. Invalid records fall back safely.
- Give tables explicit initial column fractions, rather than capturing temporary
  construction-time pixel widths. Keep saved user column order/proportions.
- Edit layout retains its current meaning: pressed unlocks, released saves/locks.
- Preserve the existing adaptive font/control density and scientific calculations.

## Tasks
- [x] Reproduce current-release default ratios, sidebar width clamping and legacy
  migration. Add failing real-Qt tests for these contracts and column defaults.
- [x] Save a source backup, port the current main layout modules only, set the
  screenshot defaults and repair cap/migration/initial-column behavior.
- [x] Update obsolete binary-storage assertions to assert the relative workspace
  contract, preserving the tested user behavior. Run focused checks.
- [x] Verify actual user splitter dragging, save/reopen and repeated HD/2K cycles,
  then the full active suite and inspect HD/2K renders. Record a local patch/report.

## Evidence
Current release probe: main panels at 2K are approximately 8/70/22; at HD the
sidebar minimum changes their actual proportions to about 11/66/23. Canonical
fractions already exist in main, so storing a percentage alone is not the entire
fix. Local develop still has competing native-pixel and JSON-weight writers.

## Ledger
- Current main reproduction: legacy native-state migration changed a 20/50/30
  layout into approximately 33/33/33 after current minimum-size constraints.
  An unconstrained hidden Qt splitter now reads native weights before rendering.
- Actual splitter movement at 2K was capped at about 14% by the 360-pixel sidebar
  maximum. Removed that cap; the desired fractions remain authoritative.
- Explicit table defaults replace construction-time widths. Saved user fractions
  and column order remain authoritative after loading rows and toggling the lock.
- Fixed the 20-pixel column floor by scaling the minimum with UI density.
- Registered table height no longer imposes a 190-pixel/fixed native size hint on
  the vertical splitter. Vertical sizing follows the panel; rows retain scrolling.
- Expanded calibration-editor tests to UI 75–150%. Isolated their temporary
  settings so testing UI 150% does not contaminate later theme/peak-card checks.
- No subagents. No publication or changes to installed/stable app folders.
- Verification: 857 active tests passed, zero failures/errors/skips. Fourteen
  focused relative-workspace tests cover defaults, persistence, migration,
  constraints, user dragging, column order and loading table data.
- Eight real-Qt offscreen HD/QHD configurations at DPI 100%, 125%, 150% and
  200% preserve reference proportions; worst panel rounding difference 0.142
  percentage points, worst table-column difference 0.315 percentage points.
- HD and QHD renders inspected. Final review performed inline by the author,
  without subagents as requested. No scientific computation modules changed.
