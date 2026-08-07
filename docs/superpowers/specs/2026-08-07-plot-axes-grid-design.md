# Plot axes, ticks, grid, and units design

## Goal

Make the XRD plot axes publication-ready on screen, in the export preview, and in saved figures:

- draw major and minor tick marks outward from every visible axis;
- make minor ticks approximately 60% of the major tick length;
- use the axis line color and width for tick marks;
- make grid color, width, and alpha controls effective;
- keep grid styling independent from axis styling;
- allow an axis unit to be intentionally empty without restoring `deg` or `A` or leaving brackets.

## Current causes

1. `PhaseFinderPlotViewActionsMixin` passes a negative tick length to PyQtGraph. PyQtGraph defines negative tick lengths as pointing into the plot.
2. PyQtGraph already shortens lower-level ticks, but the current inward direction makes the hierarchy hard to see at the plot boundary.
3. The settings model and dialog expose `grid_color` and `grid_width`, but `_apply_grid_settings()` calls only `PlotWidget.showGrid()`. That API consumes visibility and alpha while the configured color and width remain unused.
4. `_x_unit_for_scale()` treats an empty unit as a request for the scale default. Clearing the unit therefore recreates `deg` or `A`, and `_axis_label()` formats it in brackets.

## Selected approach

Keep PyQtGraph axes and add a dedicated repository-owned `StyledGridItem` inside the plot view.

### Axis ticks

- Pass a positive major tick length to every visible axis so ticks point outward.
- Keep PyQtGraph's level hierarchy for minor ticks; lower levels are shorter than major ticks, targeting approximately 60% for the first minor level.
- Set the axis pen and tick pen explicitly from the same `axis_color` and `axis_width` settings.
- Hidden axes have zero tick length and no values, as before.
- Existing automatic and manual major/minor spacing remains supported for X and Y.

### Grid

- Disable the native `showGrid()` lines to avoid double drawing.
- Create one lightweight `StyledGridItem`, attach it to the plot view, and keep it behind observed and calculated profiles. A repository-owned item is required because the stock `pyqtgraph.GridItem` overwrites the configured pen alpha according to line density.
- Build its pen directly from `grid_color`, `grid_width`, and `grid_alpha`; all rendered grid levels use these user settings.
- Obtain major and minor positions from the bottom and left PyQtGraph axes so automatic and explicit spacing remain synchronized. Zero spacing values retain automatic spacing.
- Invalidate the grid picture when the view range or relevant axis spacing changes.
- Remove or hide the custom grid item when the grid setting is disabled.
- Reuse the same plot item for repeated setting changes when practical, avoiding accumulated graphics objects.

### Axis labels and units

- `_axis_label(label, unit)` adds brackets only when the trimmed unit is non-empty.
- `_x_unit_for_scale(scale, unit)` preserves an explicitly empty unit.
- Changing between `2theta` and `d` may replace a recognized previous default (`deg` or `A`), but must not fill an empty unit field.
- Custom units are preserved unchanged.

## State and export

No project-format change is required: the relevant axis and grid fields already live in `PlotViewSettings` and are serialized in the Finder project state.

The export preview renders the same plot widget and graphics items, so outward ticks and the custom grid must appear without a separate export-only implementation.

## Error handling

- Invalid grid colors fall back to the current default grid color rather than breaking plot refresh.
- Grid width and alpha remain constrained by the existing dialog controls and are clamped at application time.
- Failure to attach the custom grid must leave the plot usable with the grid disabled; it must not interrupt data display.

## Tests

1. Unit formatting tests:
   - empty unit produces no brackets;
   - empty X unit stays empty for both scales;
   - recognized non-empty defaults convert when the scale changes;
   - custom units remain unchanged.
2. Qt/PyQtGraph behavior tests:
   - visible axes receive a positive tick length;
   - tick pen color and width match the axis pen;
   - grid pen reflects configured color, width, and alpha;
   - explicit major/minor spacing reaches the grid item;
   - disabling the grid removes or hides its graphics item.
3. Regression checks:
   - settings survive project-state round-trip;
   - plot refresh does not accumulate grid items;
   - compile and existing focused tests remain green.

## Out of scope

- Separate user controls for major and minor tick lengths.
- Different colors or widths for major and minor grid lines.
- Replacing PyQtGraph's axis renderer entirely.
