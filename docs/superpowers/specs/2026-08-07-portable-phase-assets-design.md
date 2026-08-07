# Portable Phase Assets in XPFF — Design

## Goal

An `.xpff` project must reopen on another computer with the same selected phases, calculated profiles and automatic phase markers even when that computer has no matching USER CIF files, local database cache or network connection. Restored phases must remain editable and recalculable.

## Scope

The container stores the original CIF for every CIF-backed phase used by any saved pattern profile. This includes USER, COD, MP, CCDC, AFLOW and OQMD candidates. It does not embed every search result: only candidates present in a saved Match/Gain working set or linked project phase are included.

Embedded phase assets are authoritative for the opened project. When the same source/entry key is absent from the local phase library, loading an `.xpff` file also copies and indexes that CIF locally. Existing local entries are not overwritten.

## Data Model

`FinderProjectState` gains a mapping from stable candidate key (`SOURCE:ENTRY`) to the candidate CIF source path. Before saving, the GUI refreshes this mapping from the active Match/Gain set and every per-pattern profile state. Existing project `Phase` and `Structure` records continue to use their current `source_path` fields.

A phase is a project-wide asset and may be referenced by any number of observed patterns. Its CIF is embedded once, while every pattern keeps its own candidate membership, refined profile parameters, quantity and marker state. Removing the phase from one pattern must not remove it from other patterns or delete the shared asset while it is still referenced.

The portable writer embeds three asset collections:

- project patterns under `assets/xrd/`;
- project phases and structures under `assets/cif/`;
- working-set candidate CIF files under `assets/candidates/`.

Files sharing the same resolved source path are written only once. `project.json` contains archive-relative paths, never absolute paths from the source computer.

## Save Flow

1. Save the active pattern state so all Match/Gain candidates are present in `profile_states`.
2. Collect unique CIF-backed candidates from the active working set and all stored pattern states.
3. Resolve each candidate through the existing candidate-path logic and record its path by candidate key.
4. Write the project manifest and all resolved assets to a temporary ZIP.
5. Atomically replace the target `.xpff` only after the archive has been written successfully.

If a selected phase has no readable CIF, saving must report the phase name and source instead of silently producing a non-portable project. The existing file must remain untouched after a failed save.

## Load Flow

1. Validate archive member paths with the existing traversal protection.
2. Extract candidate CIF assets into the private temporary directory derived from the `.xpff` identity.
3. For every missing source/entry key, copy and index the extracted CIF in the local phase library without replacing an existing entry.
4. Rewrite the candidate-path mapping to the extracted files.
5. Restore Match/Gain candidates, colors, names, quantities and per-pattern links.
6. Resolve CIF paths from the project mapping before consulting the machine-wide cache.
7. Parse the extracted CIF files and recalculate phase profiles and markers through the existing Finder pipeline.

For older `.xpff` files without embedded candidate assets, loading remains backward compatible. Locally cached phases are restored as before. Database-backed missing phases may use the existing download path when the user activates or recalculates them; private USER CIF files that were never embedded must be reported as unavailable.

## Editing Behavior

Restored phases behave like phases selected on the original computer. The user can rename them, change colors, remove them, recalculate profiles and add other phases. These edits update project state and are saved into the next `.xpff` file. A missing local-library phase is installed automatically from the embedded CIF under its original source/entry key; this does not add a node to the current project tree.

## Error Handling

- Reject unsafe or missing referenced archive members with a clear project-load error.
- Abort Save without replacing the previous `.xpff` when a selected phase asset cannot be read.
- Identify unresolved legacy phases by display name, source and entry ID.
- Keep duplicate CIF data out of the archive through source-path deduplication.

## Tests

- Save a project with a working-set USER phase that is not present in `project.phases`; delete the original CIF; load the `.xpff`; verify that the extracted CIF exists and is mapped to the candidate.
- Restore the working set with an empty simulated local cache and verify that a structure can be parsed for recalculation.
- Verify one phase shared by several patterns is embedded once while every pattern restores its own fitted state and markers.
- Verify multiple patterns and multiple sources use their own saved candidates while duplicate CIF paths are embedded once.
- Verify that loading adds missing embedded assets to the local phase library once, preserves their source/entry identity, and does not overwrite existing entries.
- Verify backward compatibility with an older `.xpff` lacking the new mapping.
- Verify Save fails atomically and names the unresolved selected phase when its CIF is missing.

## Compatibility

No new file extension or separate sidecar is introduced. Older readers will ignore the new manifest field and extra ZIP members; the updated reader continues to load existing `.xpff` files. A format-version bump is unnecessary because the change is additive.
