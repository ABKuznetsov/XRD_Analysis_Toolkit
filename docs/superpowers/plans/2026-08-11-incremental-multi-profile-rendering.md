# Incremental Multi-Profile Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refresh only the active calculated profile in multi-pattern mode while preserving complete redraws for global plot changes.

**Architecture:** Plot items already carry `_xrd_pattern_id`. Add one focused removal helper that filters layer lists by this ownership tag, then expose an `active_only` refresh path in the existing profile method. Scientific profile calculation and its result cache remain unchanged.

**Tech Stack:** Python 3.11, PySide6, pyqtgraph, unittest.

## Global Constraints

- Do not change Match, Gain, fitted parameters, markers, legends, or export output.
- Preserve the current full-redraw path for global view and project changes.
- Fall back to full redraw when no active pattern identifier is available.
- Do not modify the shared runtime at `C:\Users\Artem\AppData\Local\Sci`.

---

### Task 1: Pattern-owned plot item removal

**Files:**
- Modify: `XRD_Finder/xrd_finder/ui/plot_actions.py:500-565`
- Create: `XRD_Finder/tests/test_incremental_profile_rendering.py`

**Interfaces:**
- Consumes: plot items tagged with `_xrd_pattern_id` by `match_profile_renderer.py`.
- Produces: `remove_pattern_layer_items(match_plot, plot_layers, layers, pattern_id) -> int`.

- [ ] **Step 1: Write the failing ownership test**

```python
def test_remove_pattern_layer_items_keeps_other_patterns_and_untagged_items():
    active = FakeItem("active")
    other = FakeItem("other")
    untagged = object()
    layers = {"total_profile": [active, other, untagged]}

    removed = remove_pattern_layer_items(
        FakePlot(), layers, ("total_profile",), "active"
    )

    assert removed == 1
    assert layers["total_profile"] == [other, untagged]
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m unittest XRD_Finder.tests.test_incremental_profile_rendering -v`

Expected: FAIL because `remove_pattern_layer_items` is not defined.

- [ ] **Step 3: Implement the minimal ownership filter**

```python
def remove_pattern_layer_items(match_plot, plot_layers, layers, pattern_id: str) -> int:
    removed = 0
    for layer in layers:
        kept = []
        for item in list(plot_layers.get(layer, [])):
            if getattr(item, "_xrd_pattern_id", None) != pattern_id:
                kept.append(item)
                continue
            try:
                match_plot.removeItem(item)
            except Exception:
                pass
            removed += 1
        plot_layers[layer] = kept
    return removed
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run: `python -m unittest XRD_Finder.tests.test_incremental_profile_rendering -v`

Expected: PASS.

- [ ] **Step 5: Commit the helper and test**

```powershell
git add XRD_Finder/xrd_finder/ui/plot_actions.py XRD_Finder/tests/test_incremental_profile_rendering.py
git commit -m "Add pattern-owned plot layer removal"
```

### Task 2: Active-only profile refresh

**Files:**
- Modify: `XRD_Finder/xrd_finder/ui/plot_actions.py:548-552`
- Modify: `XRD_Finder/xrd_finder/ui/analysis_windows.py:1623-1735`
- Modify: `XRD_Finder/xrd_finder/ui/preprocessing_actions.py:423-436`
- Modify: `XRD_Finder/xrd_finder/ui/selected_phases_actions.py:1-305`
- Modify: `XRD_Finder/tests/test_incremental_profile_rendering.py`

**Interfaces:**
- Consumes: `remove_pattern_layer_items(...)` from Task 1.
- Produces: `_clear_calculated_overlay(pattern_id: str | None = None)` and `_recalculate_match_profile(auto_zoom: bool = False, active_only: bool = False)`.

- [ ] **Step 1: Extend the test with selective and full-clear behavior**

```python
def test_selective_clear_removes_only_active_pattern():
    harness = PlotActionsHarness()
    harness.plot_layers["total_profile"] = [
        FakeItem("active"), FakeItem("other")
    ]
    harness._clear_calculated_overlay(pattern_id="active")
    assert [item.pattern_id for item in harness.plot_layers["total_profile"]] == ["other"]

def test_clear_without_pattern_keeps_existing_full_clear_behavior():
    harness = PlotActionsHarness()
    harness.plot_layers["total_profile"] = [FakeItem("active"), FakeItem("other")]
    harness._clear_calculated_overlay()
    assert harness.plot_layers["total_profile"] == []
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `python -m unittest XRD_Finder.tests.test_incremental_profile_rendering -v`

Expected: selective-clear test fails because `_clear_calculated_overlay` does not accept `pattern_id`.

- [ ] **Step 3: Add selective clear to the plot mixin**

```python
def _clear_calculated_overlay(self, pattern_id: str | None = None) -> None:
    if pattern_id:
        remove_pattern_layer_items(
            self.match_plot,
            self.plot_layers,
            self._PROFILE_OVERLAY_LAYERS,
            pattern_id,
        )
    else:
        self._clear_profile_plot_layers(rebuild_legend=False)
    self.active_overlay_entry_id = None
    self._rebuild_visible_legend()
```

- [ ] **Step 4: Restrict active-only recalculation to one pattern**

```python
def _recalculate_match_profile(
    self,
    auto_zoom: bool = False,
    active_only: bool = False,
) -> None:
    active_pattern = self._active_pattern()
    active_pattern_id = active_pattern.id if active_pattern is not None else ""
    incremental = bool(active_only and self.show_all_selected_patterns and active_pattern_id)
    patterns = [active_pattern] if incremental else (
        self._patterns_to_display() if self.show_all_selected_patterns else [active_pattern]
    )
    self._clear_calculated_overlay(pattern_id=active_pattern_id if incremental else None)
```

All existing result calculation and `draw_match_profile_result(...)` code remains unchanged.

- [ ] **Step 5: Route active-sample operations through the new path**

In `_rerun_active_calculation` and active phase add/remove/color actions, use:

```python
self._recalculate_match_profile(
    auto_zoom=self._should_autozoom_match_profile(),
    active_only=True,
)
```

Keep plot settings, project loading, normalization, stacking, and displayed-pattern selection on the default full-redraw path.

- [ ] **Step 6: Run the focused test and verify GREEN**

Run: `python -m unittest XRD_Finder.tests.test_incremental_profile_rendering -v`

Expected: PASS.

- [ ] **Step 7: Commit incremental refresh**

```powershell
git add XRD_Finder/xrd_finder/ui/plot_actions.py XRD_Finder/xrd_finder/ui/analysis_windows.py XRD_Finder/xrd_finder/ui/preprocessing_actions.py XRD_Finder/xrd_finder/ui/selected_phases_actions.py XRD_Finder/tests/test_incremental_profile_rendering.py
git commit -m "Refresh only active multi-pattern profile"
```

### Task 3: Build and user timing comparison

**Files:**
- Verify: `installer/XRD_Analysis_Toolkit.iss`
- Produce: `installer/output/XRD_Phase_Finder_Setup_1.3.2.exe`

**Interfaces:**
- Consumes: active-only refresh from Task 2.
- Produces: a local test installer; no GitHub release.

- [ ] **Step 1: Check the scoped diff**

Run: `git diff --check`

Expected: no output and exit code 0.

- [ ] **Step 2: Build the installer**

Run: `& 'C:\Program Files (x86)\Inno Setup 6\ISCC.exe' 'installer\XRD_Analysis_Toolkit.iss'`

Expected: successful compile and a fresh `XRD_Phase_Finder_Setup_1.3.2.exe`.

- [ ] **Step 3: User verification on the 17-pattern project**

Actions: open the same project, trigger the operations that previously produced
2.6–2.7 second `match.profile` entries, then close the application.

Expected: active-only updates approach the existing 0.4–0.6 second profile
timings; markers, calculated profiles, legends, and export remain visually
unchanged.

- [ ] **Step 4: Commit final build-ready state**

```powershell
git add XRD_Finder/xrd_finder XRD_Finder/tests/test_incremental_profile_rendering.py
git commit -m "Optimize multi-pattern profile refresh"
```

