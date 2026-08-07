# XRD Phase Finder 1.3.1

## Portable phase data

- Store CIF data for every phase used by Match, Gain or individual-pattern phase assignments inside the `.xpff` project.
- Store a shared phase only once even when it is used by many XRD patterns.
- Restore missing embedded phases to the user's local phase library when a project is opened on another computer.
- Keep an existing local phase with the same source and entry unchanged.
- Prefer the exact embedded CIF for project profiles, markers and derived phase data so the project remains reproducible.
- Keep legacy `.xpff` projects compatible and report any phase data that cannot be restored.

Download: [XRD_Phase_Finder_Setup_1.3.1.exe](https://github.com/ABKuznetsov/XRD_Analysis_Toolkit/releases/download/v1.3.1/XRD_Phase_Finder_Setup_1.3.1.exe)
