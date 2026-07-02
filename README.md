# XRD Analysis Toolkit  
### Open-source X-ray Diffraction Phase Identification & Structure Simulation Framework

XRD Analysis Toolkit is a Python-based open-source framework for analysis of powder X-ray diffraction (XRD) data, phase identification, and crystallographic structure simulation using open databases and CIF-based calculations.

The system implements a modular search–match–simulation pipeline combining experimental diffraction data with theoretical diffraction patterns derived from crystal structures.

---

# 🧭 Overview

The toolkit allows users to:

- Load experimental XRD patterns
- Automatically detect diffraction peaks
- Search for candidate phases in open crystallographic databases (COD)
- Import and analyze CIF crystal structures
- Simulate theoretical diffraction patterns from structure models
- Compare experimental and calculated patterns
- Rank candidate phases by similarity score

---

# 🔬 Core workflow

The analysis pipeline is based on the following sequence:


Experimental XRD pattern
↓
Preprocessing (background removal, smoothing)
↓
Peak extraction
↓
Phase search (COD / local database / CIF libraries)
↓
Structure-based diffraction simulation
↓
Pattern comparison
↓
Similarity scoring
↓
Phase ranking and identification


---

# ⚙️ Features

## 🧪 Phase identification
- Search–match algorithm based on peak positions and intensity similarity
- Support for multiphase systems
- Ranking of candidate phases

## 🧬 Structure simulation
- CIF-based diffraction pattern generation
- Structure factor calculation
- Bragg law-based peak positioning

## 📂 Database support
- Crystallography Open Database (COD)
- Local user-defined phase libraries
- Cached structure storage (SQLite-based)

## 📊 Visualization
- XRD pattern plotting
- Experimental vs calculated pattern comparison
- Peak annotation and phase markers

---

# 📦 Supported formats

## Input:
- `.xy` — 2-column XRD data (2θ, intensity)
- `.txt` / `.dat` — generic diffraction patterns
- `.cif` — crystallographic structure files

## Output:
- Ranked phase list
- Simulated diffraction patterns
- Matching scores
- Structural metadata

---

# 🚀 Installation


1. Install Python 3.11 or newer.
2. Double-click:

```bat
setup_env.bat
```

This creates `.venv` and installs the required packages.

## Run

Double-click:

```bat
run_finder.bat
```

Optional startup files:

```bat
run_finder.bat --pattern "path\to\pattern.txt" --cif "path\to\phase.cif"
```

## CLI

```bat
run_finder_cli.bat "path\to\pattern.txt" "path\to\phase.cif"
```

## Optional Materials Project Support

Materials Project is not installed by default because it is a heavy optional dependency.

To enable it:

```bat
.venv\Scripts\python.exe -m pip install -r requirements-optional.txt
```

Then add your Materials Project API key in the app settings.

## Repository Contents

```text
xrd_manager/              application code
requirements.txt          required dependencies
requirements-optional.txt optional online database dependencies
setup_env.bat             create Windows virtual environment
run_finder.bat            launch GUI
run_finder_cli.bat        launch CLI
pyproject.toml            package metadata
```

Local downloaded databases and user caches are intentionally ignored by git.


🏗️ Architecture

The system is organized into modules:

Core → physical models (XRD, CIF, phases)
Finder Engine → phase identification logic
Services → CIF simulation, database access
IO Layer → file parsing (XRD, CIF)
UI Layer → visualization and interaction
Data Layer → caching and local database
🌍 External integrations
Crystallography Open Database (COD)
Optional Materials Project API
Local CIF repositories
🔬 Use cases
Phase identification in unknown materials
Solid solution analysis
Temperature-dependent structural evolution
Powder diffraction research
Educational crystallography
⚠️ Status

This project is in active development (beta version).

Some features are experimental and may change in future releases.

📜 License

MIT License

👤 Author

Developed as part of an open crystallography and materials informatics toolkit for X-ray diffraction analysis.

🚀 Citation (future use)

If you use this software in research, please cite the repository:

XRD Analysis Toolkit, ABKuznetsov, GitHub repository
