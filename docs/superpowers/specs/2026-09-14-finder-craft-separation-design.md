# XRD Finder and CRAFT Repository Separation

## Goal

Turn `XRD_Analysis_Toolkit` into a Finder-only repository and release payload. XRD CRAFT will be developed and distributed as a separate application outside this repository.

## Scope

The separation applies only to the current `XRD_Analysis_Toolkit` working tree. No external CRAFT project or directory is modified.

Remove from this repository:

- the complete `XRD_Craft/` source tree;
- `installer/craft_setup/`;
- CRAFT-specific build output under `dist/`;
- the CRAFT update manifest;
- the CRAFT application entry in the toolkit catalogue;
- Finder installer tasks and scripts that offer or install CRAFT;
- Finder UI and tests whose only purpose is CRAFT discovery or installation;
- internal specifications and plans dedicated to the former combined Finder/CRAFT distribution.

Keep:

- `XRD_Finder/` and all Finder scientific, project, UI, and test code;
- the shared `Sci` runtime layout used by Finder;
- Finder launchers, automatic update manifests, `.xpff` registration, and platform installers;
- generic toolkit infrastructure only where Finder still uses it independently.

## Finder Behaviour After Separation

Finder starts, installs, updates, and works without any CRAFT files. Its menus and installers do not advertise CRAFT or attempt to download it. Removing CRAFT must not change Finder's scientific calculations, CrIStMa integration, instrument profiles, project files, or automatic updates.

The Windows installer contains no optional CRAFT task and no `CraftIsInstalled` detection. The macOS package contains only Finder and the runtime/setup files required by Finder.

## Repository Cleanup

Tracked and untracked CRAFT files inside this repository are deleted. Git history remains the recovery mechanism; no backup copy is created inside the repository.

Historical documents devoted to the combined modular CRAFT integration are removed so they do not describe a release architecture that no longer exists. Unrelated Finder documentation and manuscript material remain untouched.

## macOS Package

Build the package with `scripts/build_macos_pkg.command` using the current Finder version from project metadata. The output name remains the Finder-specific form:

```text
XRD_Phase_Finder_macOS_<version>.pkg
```

The package must install the Finder application into `/Applications`, preserve the existing Finder update mechanism, and contain no path or payload whose name or contents reference `XRD_Craft`, `XRD CRAFT`, or `crystal_viewer`.

## Validation

Validation is deliberately focused rather than a full repository test run:

1. Search maintained source, installer, manifest, and build files for CRAFT references.
2. Run Finder installer, updater, runtime, and application-startup contract tests affected by the cleanup.
3. Run the focused Finder UI/scientific tests touched during the current work.
4. Build the macOS package and inspect its expanded payload and metadata.
5. Confirm that the package contains Finder only and report its path, size, and SHA-256.

Generated caches, old release artefacts, and unrelated dirty Finder work are not reverted or reformatted.
