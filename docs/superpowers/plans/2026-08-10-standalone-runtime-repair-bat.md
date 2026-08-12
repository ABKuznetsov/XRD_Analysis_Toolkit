# Standalone Sci Runtime Repair BAT Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create one portable Windows BAT file that installs, validates, and, when needed, repairs every XRD Phase Finder dependency in `%LocalAppData%\Sci\env`.

**Architecture:** The BAT is self-contained and embeds its Python validation program into a temporary file at runtime. It serializes access with a lock directory, installs the complete dependency set in one resolver transaction constrained to `pandas>=2,<3`, runs metadata/import/numerical/Qt checks plus `pip check`, and performs one forced repair transaction before returning a detailed failure.

**Tech Stack:** Windows batch, PowerShell 5.1, Python 3.11/3.12, `venv`, `pip`.

## Global Constraints

- The shared environment path remains exactly `%LocalAppData%\Sci\env`.
- All XRD Phase Finder packages, including `mp-api` and `pymatgen`, are mandatory.
- `pandas` must remain on the compatible 2.x series.
- The file must run independently of the installed application directory.
- All diagnostics must be preserved in `%LocalAppData%\Sci\logs\runtime_repair.log`.
- A failed first validation triggers one automatic force-reinstall and one final validation.

---

### Task 1: Portable runtime repair script

**Files:**
- Create: `repair_xrd_finder_windows_runtime.bat`
- Create: `XRD_Finder/tests/test_standalone_runtime_repair_bat.py`

**Interfaces:**
- Consumes: Windows `%LocalAppData%`, a discoverable Python 3.11/3.12 interpreter, and internet access to PyPI.
- Produces: a validated `%LocalAppData%\Sci\env`, `%LocalAppData%\Sci\logs\runtime_repair.log`, and `%LocalAppData%\Sci\runtime_complete.flag`; process exit code `0` only after every validation passes.

- [ ] **Step 1: Write failing artifact tests**

  Add tests that copy the BAT into a temporary directory, run its `--describe` and `--self-test-validator` modes without network access, and assert literal observable output: shared environment path, complete mandatory package list, `pandas>=2,<3`, two repair attempts, lock/completion marker paths, and successful execution of the embedded validator against the current Python environment with a generated minimal requirement fixture.

- [ ] **Step 2: Run the tests and verify RED**

  Run: `python -m pytest XRD_Finder/tests/test_standalone_runtime_repair_bat.py -q`

  Expected: FAIL because `repair_xrd_finder_windows_runtime.bat` does not exist.

- [ ] **Step 3: Implement the BAT**

  Implement these execution phases: parse diagnostic modes; create folders; acquire the atomic setup lock; locate or install Python 3.11; create or replace an invalid venv; upgrade pip tooling; install the complete constrained requirement set in one call; write and execute the embedded validator; run `pip check`; on failure force-reinstall the same complete set once; write the completion marker only after success; always release the lock; display the log path and return a nonzero exit code on final failure.

- [ ] **Step 4: Run focused tests and verify GREEN**

  Run: `python -m pytest XRD_Finder/tests/test_standalone_runtime_repair_bat.py -q`

  Expected: all tests PASS without downloading or modifying the local Sci environment.

- [ ] **Step 5: Run repository regression tests**

  Run: `python -m pytest XRD_Finder/tests -q`

  Expected: all tests PASS.

- [ ] **Step 6: Deliver the BAT for the remote-computer test**

  Verify the file hash and provide the absolute path. Do not publish or build a new installer until the user reports the result from the other computer.
