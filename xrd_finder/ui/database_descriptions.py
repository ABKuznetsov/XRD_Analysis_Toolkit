"""User-facing source descriptions shared by hover tips and context Help."""
from dataclasses import dataclass
from html import escape


@dataclass(frozen=True)
class DatabaseDescription:
    name: str
    summary: str
    details: str
    usage: str
    url: str = ''

    def tooltip(self):
        # Rich text lets Qt wrap explanations instead of making a screen-wide tip.
        return '<qt><b>' + escape(self.name) + '</b>' + ''.join(
            '<p>' + escape(part) + '</p>' for part in (self.details, self.usage, self.url) if part) + '</qt>'


DESCRIPTIONS = {
    'User phase library': DatabaseDescription('User phase library',
        'Your imported and downloaded CIF structures.',
        'Local crystal structures saved by Finder. Reference diffraction patterns are calculated from CIFs and cached.',
        'Use Manage to add your CIFs. Downloaded online cards also become available to local automatic search.'),
    'COD': DatabaseDescription('COD — Crystallography Open Database',
        'Open crystal structures: inorganic, organic and metal-organic.',
        'CIF structures of inorganic, organic and metal-organic compounds and minerals. Finder calculates diffraction from these structures; these are not measured powder profiles.',
        'Search online by formula or elements without an API key, or import a CIF folder/ZIP. Prepared cards are then available offline.',
        'https://www.crystallography.net/cod/'),
    'RRUFF powder': DatabaseDescription('RRUFF — mineral reference database',
        'Measured powder diffraction references for minerals.',
        'Mineral reference data. This connection uses powder diffraction profiles rather than CIF-derived structures.',
        'Use Update to prepare the local references, then enable RRUFF and Profile only in the search controls.',
        'https://rruff.info/'),
    'CoRE MOF SI': DatabaseDescription('CoRE MOF — Computation-Ready, Experimental Metal–Organic Frameworks',
        'Processed CIFs of metal-organic frameworks.',
        'MOFs are porous crystals with metal nodes and organic linkers. CoRE processes reported experimental structures for computation. SI is the supplementary-information collection used here; Finder prepares its computation-ready subset. Powder patterns are calculated from CIF.',
        'Download and prepare the collection, enable CoRE MOF SI and Organic for search. A CIF archive can also be imported.',
        'https://zenodo.org/records/15055758'),
    'CURATED COFs': DatabaseDescription('CURATED COFs — covalent organic frameworks',
        'Literature CIFs of covalent organic frameworks.',
        'COFs are crystalline organic networks connected by covalent bonds. This curated collection contains 324 literature structures in release 1.0.0. Finder calculates reference patterns from CIF.',
        'Download and prepare the collection or import its CIF ZIP. Enable the connection and Organic for search.',
        'https://zenodo.org/records/3352138'),
    'QMOF': DatabaseDescription('QMOF — Quantum MOF database',
        'DFT-relaxed metal-organic framework structures.',
        'Metal-organic frameworks and coordination polymers optimised with density functional theory (DFT). Atomic positions and lattice parameters may differ from experiment. Finder uses relaxed CIFs, not measured powder profiles.',
        'Download and prepare the collection or import the original archive if downloading is unavailable. Enable the connection and Organic for search.',
        'https://github.com/Andrew-S-Rosen/QMOF'),
    'OMDB': DatabaseDescription('OMDB — Organic Materials Database',
        'Organic molecular crystal structures; local CIF import.',
        'A database of three-dimensional organic crystals and calculated electronic properties. Finder needs crystal CIFs; a properties table alone cannot generate a powder pattern.',
        'Open the download page, sign in there if required, then import the downloaded CIF ZIP or connect a CIF folder. Finder does not sign in automatically.',
        'https://omdb.mathub.io/dataset'),
    'PDF-2': DatabaseDescription('PDF-2 — Powder Diffraction File, ICDD',
        'Licensed powder diffraction reference cards.',
        'A reference collection from the International Centre for Diffraction Data (ICDD), containing interplanar spacings, intensities and card quality/status marks. A card need not contain a full CIF structure.',
        'Choose your supported local PDF-2 folder, refresh the index and enable PDF-2 for search. The database and its licence are supplied by you.',
        'https://www.icdd.com/pdf-2/'),
    'CCDC / CSD': DatabaseDescription('CCDC — Cambridge Crystallographic Data Centre; CSD — Cambridge Structural Database',
        'Organic and metal-organic crystal structures.',
        'CSD contains organic and metal-organic crystal structures. Finder calculates reference diffraction from CIF, rather than using a measured powder trace.',
        'Use your configured local CCDC API when available. Web access in Finder is currently unavailable; download a CIF on the CCDC website and import it manually.',
        'https://www.ccdc.cam.ac.uk/structures/'),
    'Materials Project': DatabaseDescription('Materials Project — computed materials database',
        'DFT-relaxed crystal structures; personal API key.',
        'Computed crystal structures and properties, including structures associated with experimental reports. Finder calculates diffraction from the returned structure. An experimental-source star does not mean the powder trace was measured.',
        'Save your personal API key, enable Materials Project and search by formula or elements. Downloaded structures are prepared for local search.',
        'https://materialsproject.org/'),
    'AFLOW': DatabaseDescription('AFLOW — Automatic FLOW for Materials Discovery',
        'Computed crystal structures and materials properties.',
        'A materials discovery database with computational crystal structures. Finder calculates powder patterns from the retrieved structures.',
        'Enable AFLOW for manual online search. Retrieved structures are cached locally. This connector is experimental.',
        'https://aflow.org/'),
    'OQMD': DatabaseDescription('OQMD — Open Quantum Materials Database',
        'DFT-calculated crystal structures and properties.',
        'A collection of density-functional-theory calculations of crystal structures and thermodynamic properties. Finder calculates reference diffraction from the structures.',
        'Enable OQMD for manual online search. Retrieved structures are cached locally. This connector is experimental.',
        'https://oqmd.org/'),
    'Additional databases': DatabaseDescription('Additional database connections',
        'Your CIF folders, ZIP archives and online sources.',
        'Named connections to local CIF folders/ZIPs, downloadable archives or a compatible JSON API.',
        'Add a connection, enable it and prepare its CIFs. Connection settings also control whether custom collections participate in search.'),
    'Local diffraction index': DatabaseDescription('Local diffraction index',
        'Prepared reference data shared by local searches.',
        'The local SQLite library holds reference structures, calculated reflections and search indexes. Prepared-library transfer preserves these calculations.',
        'Export/import a prepared library to transfer it, recalculate after changing calculation requirements, or check CIF composition to audit chemical metadata.'),
}


def database_description(name):
    if name in ('COD online', 'COD local/bulk', 'COD local'):
        name = 'COD'
    elif name.startswith('CCDC'):
        name = 'CCDC / CSD'
    elif name == 'User library':
        name = 'User phase library'
    elif name == 'RRUFF':
        name = 'RRUFF powder'
    return DESCRIPTIONS.get(name)
