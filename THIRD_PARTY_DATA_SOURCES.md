# Third-party Data Sources

XRD Finder can work with several external crystallographic and diffraction data sources. These databases are not owned by this project, and their data remains the property of the corresponding database projects, institutions, publishers or contributors.

XRD Finder does not redistribute large third-party databases. It only uses data through official access mechanisms, user-provided imports, local folders configured by the user or optional APIs enabled by the user.

## Crystallography Open Database (COD)

The Crystallography Open Database is an open collection of crystallographic structures and CIF files.

XRD Finder can search COD online, download individual CIF entries selected by the user, and index a local COD CIF collection when the user provides one. COD data and metadata belong to COD and its contributors. Users should follow the COD terms, citation guidance and attribution requirements when using COD-derived data in publications.

Project website: https://www.crystallography.net/cod/

## Materials Project

Materials Project provides computed materials data and structure information through its official API.

XRD Finder can use Materials Project only when the user enables this source and provides their own API key. Materials Project data belongs to Materials Project and its contributors. Users should follow Materials Project API terms and citation guidance.

Project website: https://materialsproject.org/

## RRUFF Project

The RRUFF Project provides mineralogical reference data, including measured powder diffraction patterns for many mineral samples.

XRD Finder can import or index RRUFF powder-pattern data when the user chooses to download or provide it. RRUFF data belongs to the RRUFF Project and its contributors. Users should follow RRUFF attribution and citation guidance when using RRUFF-derived data.

Project website: https://rruff.info/

## CCDC / CSD

The Cambridge Crystallographic Data Centre (CCDC) maintains the Cambridge Structural Database (CSD) and provides official access tools for licensed users.

XRD Finder can optionally interact with CCDC/CSD only when the user has the appropriate CCDC Python API installed and configured. XRD Finder does not include or redistribute CSD data. CCDC/CSD data belongs to CCDC and its data contributors, and users are responsible for following their license terms.

Project website: https://www.ccdc.cam.ac.uk/

## User-provided CIF and Reference Data

Users may import their own CIF files, local phase libraries and locally available reference data. In that case, the user is responsible for ensuring they have the right to use, store and publish results derived from those files.

## General Note

The presence of a database connector or import workflow in XRD Finder does not imply endorsement by the external database project. Users should cite the original data sources in scientific work whenever database-derived structures, reference patterns or metadata are used.
