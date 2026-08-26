# Modular XRD Analysis Toolkit Installer Design

## Purpose

Add XRD CRAFT to the XRD Analysis Toolkit repository without merging application internals or copying development artefacts. Preserve independent installation, removal, and update lifecycles while allowing each application to discover and install other toolkit modules directly from a shared catalogue.

## Product boundaries

Each application remains a standalone product:

- XRD Phase Finder performs PXRD phase-search and interpretation workflows.
- XRD CRAFT performs crystal-structure visualisation and structural-mechanics analysis.
- Future applications are added as independent modules.
- A future paid application may coordinate installed modules, but no current module depends on that application.

There is no common bootstrapper in this release. Each application owns its installer and consumes the shared catalogue only for discovery.

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
    ├── finder_setup/
    └── craft_setup/
```

`XRD_Craft` is imported as a curated application source tree. It includes only runtime source, required assets and examples, launchers, packaging metadata, and files required to build and test the module. It excludes existing release binaries, generated `dist` and `build` trees, caches, bytecode, local environments, temporary files, internal development plans, and the old standalone installer output.

The existing XRD Finder source tree and unrelated working-tree changes are not reorganised as part of this work.

## Installation locations

The module installers do not create a shared application directory. Existing locations remain authoritative:

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

GitHub release assets include the two module installers. Per-application update manifests remain the source of truth for application updates. The toolkit catalogue is the source of truth for discovery of other modules.

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

## Direct module installation

Each application presents other catalogue entries through its update experience and a permanent `More XRD tools…` command. When the user chooses `Install`, the application:

1. downloads that module's standalone installer into a per-user toolkit download cache;
2. reuses a previously downloaded file only when its size and SHA-256 match;
3. asks for final confirmation before starting the installer;
4. runs the installer independently and reports its result.

No module is downloaded or installed without explicit user action. Installing another module does not change the current application's files or update settings.

## Shared Sci environment

Each module declares its own runtime requirements. A module installer validates imports and compatible versions required by that module, then installs or repairs only missing or invalid requirements in `%LocalAppData%\Sci\env`.

A working environment is never deleted or rebuilt merely because a new installer runs. Network interruption, package-index failure, incompatible Python, and invalid package metadata produce an actionable English-language error that identifies the failing requirement and offers Retry or Cancel. Valid downloaded packages and installers remain cached for retry.

## Independent updates

Finder keeps its current automatic-update workflow and its `toolkit/updates/xrd_finder.json` manifest. Finder `1.4.1` sees Finder `1.5.0`, downloads the standalone Finder installer, exits, and updates in its existing installation directory. CRAFT uses a separate `toolkit/updates/xrd_craft.json` manifest and does not depend on Finder.

CRAFT checks its own update manifest in the background after startup and provides a permanent `Check for updates…` command in Help. When a newer version is available, CRAFT shows the version and release notes, downloads its standalone installer only after user confirmation, validates its exact size and SHA-256, asks for final installation confirmation, and then launches that installer. A failed or unavailable update check never prevents CRAFT from starting.

Updating one module:

- does not launch or update other installed modules;
- does not change another module's update or discovery preferences;
- validates only the dependencies required by that module;
- may update backwards-compatible shared toolkit launcher files when required.

## Application discovery

Finder and CRAFT may show other catalogue applications without installing them. A newly announced application is offered once per announcement revision. Choosing `Not now` suppresses that announcement until its revision changes.

Every application also provides a permanent `More XRD tools…` command that opens the catalogue view. Choosing `Install` downloads the selected module's verified standalone installer. No download begins before confirmation.

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
- Catalogue or installer cancellation: leave installed applications working and do not remove cached valid downloads.

## Verification

Automated and manual verification covers:

1. curated XRD CRAFT payload contains required runtime files and excludes generated artefacts;
2. catalogue schema, versions, URLs, sizes, and SHA-256 values are valid;
3. an installed current module is not downloaded or reinstalled unnecessarily;
4. Finder `1.4.1` updates to `1.5.0` through its existing updater;
5. CRAFT installs and updates in its existing per-user path;
6. both applications launch against the shared Sci environment;
7. a working Sci environment is preserved and only missing dependencies are added;
8. failed downloads and checksum mismatches never execute invalid files;
9. uninstalling one module leaves the other module and shared environment intact;
10. one-time discovery prompts and `More XRD tools…` work without automatic installation;
11. choosing a catalogue module downloads and runs only its verified standalone installer;
12. the two Windows installer artefacts build reproducibly and their release metadata matches the generated files.

## Out of scope

- Building the future paid integration application.
- Building a common XRD Analysis Toolkit bootstrapper or combined installer.
- Combining Finder and CRAFT source code or user interfaces.
- Moving installed applications into a shared Program Files directory.
- Removing the shared Sci environment during uninstall.
- Redesigning scientific algorithms in either module.
- Publishing internal SCI Manager integration in user-facing release notes.
