# Modular XRD Analysis Toolkit Installer Design

## Purpose

Add XRD CRAFT to the XRD Analysis Toolkit repository without merging application internals or copying development artefacts. Provide one user-facing installer that offers XRD Phase Finder, XRD CRAFT, and future applications while preserving independent installation, removal, and update lifecycles for every module.

## Product boundaries

Each application remains a standalone product:

- XRD Phase Finder performs PXRD phase-search and interpretation workflows.
- XRD CRAFT performs crystal-structure visualisation and structural-mechanics analysis.
- Future applications are added as independent modules.
- A future paid application may coordinate installed modules, but no current module depends on that application.

The shared installer is a catalogue and bootstrapper, not a combined application runtime.

## Repository layout

The repository root contains one directory per application:

```text
XRD_Analysis_Toolkit/
├── XRD_Finder/
├── XRD_Craft/
├── toolkit/
│   ├── catalog.json
│   └── updates/
└── installer/
    ├── toolkit_setup/
    ├── finder_setup/
    └── craft_setup/
```

`XRD_Craft` is imported as a curated application source tree. It includes only runtime source, required assets and examples, launchers, packaging metadata, and files required to build and test the module. It excludes existing release binaries, generated `dist` and `build` trees, caches, bytecode, local environments, temporary files, internal development plans, and the old standalone installer output.

The existing XRD Finder source tree and unrelated working-tree changes are not reorganised as part of this work.

## Installation locations

The common installer does not create a shared application directory. Existing locations remain authoritative:

```text
C:\Program Files\XRD Phase Finder\
C:\Users\<user>\AppData\Local\Sci\apps\craft\
C:\Users\<user>\AppData\Local\Sci\env\
```

Finder retains its machine-level installation and `.xpff` file association. CRAFT retains its per-user installation. Both reuse the shared scientific Python environment under `%LocalAppData%\Sci\env`.

Uninstalling or updating one application must not remove or modify another application's files. Shared Sci packages are not removed by an application uninstaller.

## Versions and release identity

Versions remain independent:

- XRD Phase Finder: `1.5.0` for the first modular-toolkit release.
- XRD CRAFT: `0.1.0`.
- XRD Analysis Toolkit bootstrapper: `1.0.0`.

GitHub release assets include the two module installers and the toolkit bootstrapper. Per-application update manifests remain the source of truth for application updates. The toolkit catalogue is the source of truth for discovery and initial installation.

## Application catalogue

`toolkit/catalog.json` is a versioned catalogue. Each entry contains at least:

- stable application ID;
- display name and concise description;
- current version;
- icon or card asset;
- installer URL, size, and SHA-256;
- update-manifest URL;
- supported platform and architecture;
- optional announcement revision used to control one-time discovery prompts.

Adding a future free application requires a catalogue entry and its standalone installer. Paid applications may use the same catalogue entry format with a product or sign-in URL, but licensing is outside this implementation.

## Common installer flow

`XRD_Analysis_Toolkit_Setup_1.0.0.exe` presents a component-selection page. XRD Phase Finder and XRD CRAFT are the initial entries; future entries are populated from the catalogue supported by that bootstrapper version.

For each selected application the bootstrapper:

1. detects whether the application is absent, installed, or outdated;
2. downloads the standalone installer into a per-user toolkit download cache;
3. reuses a previously downloaded file only when its size and SHA-256 match;
4. runs the module installer and waits for its result;
5. reports success or a precise failure for that module;
6. continues with other selected modules only when doing so is safe.

No module is installed without explicit user selection. A failed module does not roll back another module that completed successfully.

## Shared Sci environment

Each module declares its own runtime requirements. A module installer validates imports and compatible versions required by that module, then installs or repairs only missing or invalid requirements in `%LocalAppData%\Sci\env`.

A working environment is never deleted or rebuilt merely because a new installer runs. Network interruption, package-index failure, incompatible Python, and invalid package metadata produce an actionable English-language error that identifies the failing requirement and offers Retry or Cancel. Valid downloaded packages and installers remain cached for retry.

## Independent updates

Finder keeps its current automatic-update workflow and its `toolkit/updates/xrd_finder.json` manifest. Finder `1.4.1` sees Finder `1.5.0`, downloads the standalone Finder installer, exits, and updates in its existing installation directory. CRAFT uses a separate `toolkit/updates/xrd_craft.json` manifest and does not depend on Finder.

Updating one module:

- does not launch or update other installed modules;
- does not change component-selection preferences;
- validates only the dependencies required by that module;
- may update backwards-compatible shared toolkit launcher files when required.

The common bootstrapper can also detect and update selected installed modules, but it is not required for normal automatic updates.

## Application discovery

Finder and CRAFT may show other catalogue applications without installing them. A newly announced application is offered once per announcement revision. Choosing `Not now` suppresses that announcement until its revision changes.

Every application also provides a permanent `More XRD tools…` command that opens the catalogue view. Choosing `Install` launches the toolkit bootstrapper with the requested module preselected. Optional modules remain unchecked and no download begins before confirmation.

Release notes describe user-facing functionality and optimisation; compatibility with internal management software is not advertised.

## Migration and compatibility

No installation-path migration is required because both existing application locations are retained. The first modular Finder release updates the existing Finder installation in place. The first repository-backed CRAFT installer updates or replaces the existing CRAFT installation in `%LocalAppData%\Sci\apps\craft`.

Installers preserve user projects, databases, caches, settings, and the shared Sci environment. Obsolete shortcuts or uninstall records belonging to an earlier installer may be removed only after the replacement module has installed successfully.

## Failure handling

- Catalogue unavailable: show cached catalogue data when valid; otherwise explain that module discovery is unavailable while installed applications can still run.
- Interrupted installer download: retain the partial or completed cache safely and offer Retry.
- Checksum mismatch: discard the invalid file, report the mismatch, and never execute it.
- Module installer failure: show the module name, exit code, and log path.
- Sci environment failure: show the Python path, missing or incompatible requirements, log path, and Retry/Cancel actions.
- Existing application in use: ask the user to close it, then retry without terminating it forcibly.
- Bootstrapper cancellation: leave already installed applications working and do not remove cached valid downloads.

## Verification

Automated and manual verification covers:

1. curated XRD CRAFT payload contains required runtime files and excludes generated artefacts;
2. catalogue schema, versions, URLs, sizes, and SHA-256 values are valid;
3. selecting Finder only, CRAFT only, or both invokes only the requested module installers;
4. an installed current module is not downloaded or reinstalled unnecessarily;
5. Finder `1.4.1` updates to `1.5.0` through its existing updater;
6. CRAFT installs and updates in its existing per-user path;
7. both applications launch against the shared Sci environment;
8. a working Sci environment is preserved and only missing dependencies are added;
9. failed downloads and checksum mismatches never execute invalid files;
10. uninstalling one module leaves the other module and shared environment intact;
11. one-time discovery prompts and `More XRD tools…` work without automatic installation;
12. the three Windows installer artefacts build reproducibly and their release metadata matches the generated files.

## Out of scope

- Building the future paid integration application.
- Combining Finder and CRAFT source code or user interfaces.
- Moving installed applications into a shared Program Files directory.
- Removing the shared Sci environment during uninstall.
- Redesigning scientific algorithms in either module.
- Publishing internal SCI Manager integration in user-facing release notes.
