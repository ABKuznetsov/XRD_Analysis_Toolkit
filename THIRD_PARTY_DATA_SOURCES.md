# Third-party Data Sources

XRD Phase Finder can work with several external crystallographic and diffraction data sources. These databases are not owned by this project, and their data remains the property of the corresponding database projects, institutions, publishers or contributors.

XRD Phase Finder does not redistribute large third-party databases. It only uses data through official access mechanisms, user-provided imports, local folders configured by the user or optional APIs enabled by the user.

## Crystallography Open Database (COD)

The Crystallography Open Database is an open collection of crystallographic structures and CIF files.

XRD Phase Finder can search COD online, download individual CIF entries selected by the user, and index a local COD CIF collection when the user provides one. COD data and metadata belong to COD and its contributors. Users should follow the COD terms, citation guidance and attribution requirements when using COD-derived data in publications.

Finder also includes an identifier-only inorganic selection (77,812 COD identifiers, selection date 2026-06-02) based on the COD inorganic collection listed on the [Match! downloads page](https://www.crystalimpact.com/match/download.htm). The bundled list contains no structures or calculated patterns. Original CIF files are downloaded from COD only when the user starts preparation.

Project website: https://www.crystallography.net/cod/

## Materials Project

Materials Project provides computed materials data and structure information through its official API.

XRD Phase Finder can use Materials Project only when the user enables this source and provides their own API key. Materials Project data belongs to Materials Project and its contributors. Users should follow Materials Project API terms and citation guidance.

Project website: https://materialsproject.org/

## AFLOW

AFLOW provides computational materials data and predicted crystal structures through AFLOW online services.

XRD Phase Finder can search AFLOW only when the user enables this source. AFLOW-derived metadata and structures belong to AFLOW and its contributors. Users should follow AFLOW terms, citation guidance and attribution requirements when using AFLOW-derived data.

Project website: https://aflow.org/

## Open Quantum Materials Database (OQMD)

OQMD provides computational materials data and predicted crystal structures through OQMD online services.

XRD Phase Finder can search OQMD only when the user enables this source. OQMD-derived metadata and structures belong to OQMD and its contributors. Users should follow OQMD terms, citation guidance and attribution requirements when using OQMD-derived data.

Project website: https://oqmd.org/

## RRUFF Project

The RRUFF Project provides mineralogical reference data, including measured powder diffraction patterns for many mineral samples.

XRD Phase Finder can import or index RRUFF powder-pattern data when the user chooses to download or provide it. RRUFF data belongs to the RRUFF Project and its contributors. Users should follow RRUFF attribution and citation guidance when using RRUFF-derived data.

Project website: https://rruff.info/

## CCDC / CSD

The Cambridge Crystallographic Data Centre (CCDC) maintains the Cambridge Structural Database (CSD) and provides official access tools for licensed users.

XRD Phase Finder can optionally interact with CCDC/CSD only when the user has the appropriate CCDC Python API installed and configured. XRD Phase Finder does not include or redistribute CSD data. CCDC/CSD data belongs to CCDC and its data contributors, and users are responsible for following their license terms.

Project website: https://www.ccdc.cam.ac.uk/

## User-provided CIF and Reference Data

Users may import their own CIF files, local phase libraries and locally available reference data. In that case, the user is responsible for ensuring they have the right to use, store and publish results derived from those files.

## General Note

The presence of a database connector or import workflow in XRD Phase Finder does not imply endorsement by the external database project. Users should cite the original data sources in scientific work whenever database-derived structures, reference patterns or metadata are used.
## Optional organic/framework libraries

Finder provides explicit download/import controls; these datasets are not bundled in the installer.

- **CoRE MOF SI 2024**, Zenodo record [15055758](https://zenodo.org/records/15055758), archive `CoREMOF2024DB_SI_20250204.zip`. Only the authors' computation-ready `SI/CR` ASR/FSR/Ion subset is imported. Source and processing provenance remain visible; the result is a CIF-calculated pattern, not measured powder data.
- **CURATED COFs v1.0.0**, Daniele Ongari and collaborators, [Zenodo 3352138](https://zenodo.org/records/3352138), [repository](https://github.com/danieleongari/CURATED-COFs/tree/v1.0.0). Original deposited archive, MD5 `210e2c708625eab49b91ac68814288b5`, contains 324 literature-derived COF CIFs. Retain attribution and consult the original papers and authors' geometry caveats. Finder does not execute repository scripts or redistribute the archive in the installer.
- **QMOF v18**, Andrew S. Rosen and collaborators, [Figshare](https://doi.org/10.6084/m9.figshare.13147324.v18). CC BY 4.0. Cite Rosen et al., *Matter* 4, 1578–1597 (2021), DOI [10.1016/j.matt.2021.02.015](https://doi.org/10.1016/j.matt.2021.02.015), and Rosen et al., *npj Computational Materials* 8 (2022), DOI [10.1038/s41524-022-00796-6](https://doi.org/10.1038/s41524-022-00796-6). Finder uses only relaxed CIFs and labels their DFT origin; no measured powder provenance is implied. The original archive is downloaded on request or imported locally. No bundled conversion scripts are executed.
- **Organic COD search** uses the existing COD connector and original COD identities, not a separate copy of COD. [COD](https://www.crystallography.net/cod/) dedicates its data to CC0; retain original structure-author attribution.
- **OMDB-GAP1 v1.1**, [official dataset page](https://omdb.mathub.io/dataset), DOI [10.1002/qute.201900023](https://doi.org/10.1002/qute.201900023). The official download currently requires personal website login. Finder opens the original page and can import a user-provided CIF collection through local connections; it does not bypass authentication or claim an unauthenticated OMDB API.

