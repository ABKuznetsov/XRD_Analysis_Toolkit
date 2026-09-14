from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys

from docx import Document


def replace_by_prefix(document: Document, prefix: str, replacement: str) -> None:
    for paragraph in document.paragraphs:
        if paragraph.text.strip().startswith(prefix):
            paragraph.text = replacement
            return
    raise KeyError(f"Paragraph not found: {prefix!r}")


def replace_validation_table(document: Document) -> None:
    table = document.tables[1]
    style_names = [
        cell.paragraphs[0].style.name if cell.paragraphs else "Normal"
        for cell in table.rows[1].cells
    ]
    template_row = deepcopy(table.rows[1]._tr)
    for row in list(table.rows[1:]):
        table._tbl.remove(row._tr)

    rows = [
        (
            "Closed-world corpus",
            "50 synthetic profiles (20 single, 20 binary, 10 ternary); "
            "51 COD entries in 23 families",
            "Shift, broadening, background, noise and overlap",
            "Closed-world ranking test; not a real-sample accuracy estimate.",
        ),
        (
            "Dominant-phase Match",
            "All 50 synthetic profiles",
            "Dominant family: top-1 = 48/50; top-5 = 50/50",
            "The dominant family was shortlisted in every case; two top-1 errors.",
        ),
        (
            "Mixture completeness",
            "All expected families in the 30 multiphase profiles",
            "All true families: Match top-5 = 39/50; top-10 = 45/50",
            "Global Match initializes the search but does not recover every component.",
        ),
        (
            "Conditional Gain",
            "40 expected phase-addition steps from the binary and ternary profiles",
            "Expected family: top-1 = 29/40; top-5 = 36/40; positive Gain = 37/40",
            "Residual ranking usually promoted the next true family after refitting.",
        ),
        (
            "False additions",
            "20 closed single-phase profiles",
            "False Gain >= 5% = 1/20; median maximum false Gain = 0%",
            "The evidence gate suppressed, but did not eliminate, false additions.",
        ),
        (
            "Noise-significance stress test",
            "40 binary profiles and 10 negative controls",
            "Gain top-5 by secondary-line SNR: 2/13 (<2), 2/11 (2-3), "
            "3/7 (3-5), 8/9 (>=5); false Gain >=5%: 2/10 controls",
            "Useful ranking emerged above the noise floor; weaker results are tentative.",
        ),
    ]

    for values in rows:
        table._tbl.append(deepcopy(template_row))
        row = table.rows[-1]
        for index, (cell, value) in enumerate(zip(row.cells, values, strict=True)):
            cell.text = value
            if cell.paragraphs and index < len(style_names):
                cell.paragraphs[0].style = style_names[index]


def update_document(source: Path, target: Path) -> None:
    document = Document(source)

    replacements = {
        "XRD Phase Finder is an open-source desktop application": (
            "XRD Phase Finder is an open-source desktop application for automatic "
            "and semi-automatic interpretation of the crystalline phases present "
            "in powder mixtures. Automatic search generates and ranks a candidate "
            "list, whereas the semi-automatic workflow allows the user to set "
            "elemental constraints, inspect the diffraction evidence and accept "
            "phases between search iterations. The program searches user-accessible "
            "records from the Crystallography Open Database, Materials Project, "
            "AFLOW, OQMD and RRUFF, and it can evaluate an individual CIF file "
            "without adding it to a database. Candidate patterns are calculated "
            "locally and displayed with the experimental profile, reflection "
            "markers, background components and unexplained lines. Match ranks "
            "initial candidates by two-way agreement between their strongest "
            "reflections and the strongest experimental line records. After one "
            "or more phases have been accepted and jointly fitted, Gain ranks "
            "remaining candidates by statistically supported diffraction evidence "
            "that is not adequately explained by the accepted model. Smoothing, "
            "physical-background estimation and an optional broad amorphous "
            "contribution remain inspectable and reversible. For accepted phases, "
            "normalized non-negative fitted profile contributions provide a "
            "semi-quantitative estimate. Projects retain imported patterns, "
            "processing settings, accepted phases and view state. Standalone "
            "Windows and macOS packages are distributed under the MIT licence. "
            "Match and Gain are ranking scores rather than phase probabilities, "
            "and the semi-quantitative values are not validated mass fractions."
        ),
        "Chemical-element filters restrict": (
            "Chemical-element filters restrict the initial candidate pool but are "
            "not treated as proof of phase presence. Source and entry identifiers "
            "are retained together to prevent collisions between databases, and "
            "each displayed candidate remains linked to a source record or local "
            "CIF. Large third-party collections are not embedded in the platform "
            "installers. The program can query supported online resources, reuse "
            "persistent local SQLite/CIF indexes and evaluate user-supplied CIF "
            "files directly. Search coverage therefore depends on the connected "
            "services and the local database snapshot available for a run. Absence "
            "from a compact local subset is a coverage limitation, not evidence "
            "that a phase is absent from the specimen."
        ),
        "Gain is a conditional score": (
            "Gain is a conditional score for the additional diffraction evidence "
            "supplied by a candidate. The profiles of all accepted phases are first "
            "refitted jointly to the active background-corrected signal by weighted "
            "non-negative least squares. This allows the coefficient of an earlier "
            "phase to decrease when a later phase shares a strong reflection, "
            "instead of assigning all shared intensity permanently to the first "
            "phase. The difference between the experiment and the refitted "
            "selected-phase total defines the residual evidence examined at the "
            "next step. Gain is displayed only after at least one phase has been "
            "accepted and is not a repeated Match calculation."
        ),
        "The search proceeds through three evidence stages": (
            "The search proceeds through three evidence stages. The direct stage "
            "tests lines outside the tolerance windows of accepted-phase "
            "reflections. When direct evidence is sparse, the overlap stage examines "
            "shared regions that remain measurably under-fitted after joint profile "
            "scaling. A hidden-evidence stage is used only when extensive overlap "
            "prevents the first two stages from producing enough independent lines. "
            "This staged design allows an incompletely fitted shared peak to "
            "contribute evidence without treating every residual at a selected-phase "
            "line as proof of another phase."
        ),
        "Candidate sticks provide the primary Gain evidence": (
            "Candidate sticks define the locations at which Gain evidence is tested. "
            "A calculated line must be strong enough to be testable relative to a "
            "robust local noise estimate and must be supported within an "
            "FWHM-dependent angular tolerance. In the direct stage, at least two "
            "supported lines independent of accepted-phase reflections are required; "
            "a single coincidence is not considered specific enough for an "
            "automated search across a large database. Unsupported testable lines "
            "are counted explicitly. The candidate profile must also reduce the "
            "weighted residual sufficiently to pass a Bayesian-information-criterion "
            "gate (Schwarz, 1978). The default line threshold is three times the "
            "estimated noise standard deviation, but this operational threshold is "
            "not presented as an analytical detection limit."
        ),
        "The resulting Gain is bounded": (
            "The reported Gain combines the residual fraction that a candidate can "
            "explain with its supported-line fraction, missing-line penalty and "
            "profile-model evidence. It is bounded by the part of the weighted fit "
            "that remains unexplained by the accepted phase model. A duplicate "
            "candidate can therefore retain a high global Match while receiving "
            "little or no Gain, whereas a weaker phase can move upward when it "
            "provides coherent additional evidence. Gain is neither a concentration "
            "estimate nor a formal probability and must be interpreted together "
            "with the difference curve, unexplained-line markers, source identifiers, "
            "I/Ic values and candidate card."
        ),
        "Current Match and Gain logic": (
            "Current Match and Gain logic. (a) The observed profile is converted "
            "into line records with position, integrated area and FWHM. (b) Match "
            "combines coverage of the strongest observed anchors with support of "
            "the candidate's strong reflections after bounded alignment. "
            "(c) Accepted phase profiles are fitted jointly, exposing uncovered "
            "lines and measurable deficits at shared reflections. (d) Gain requires "
            "multiple supported lines, rejects unsupported testable reflections and "
            "checks whether the candidate profile improves the residual model."
        ),
        "Prototype validation matrix": (
            "Validation matrix for the version 1.2.0 Match and Gain implementation. "
            "The tests use a closed-world synthetic candidate pool and therefore "
            "measure controlled ranking behaviour, not universal identification "
            "accuracy or mass-fraction detection limits."
        ),
        "Before any phase is accepted": (
            "Before any phase is accepted, the list is ordered by Match and the Gain "
            "column is intentionally left empty. The first pass is intended to "
            "recover a plausible dominant family without requiring every "
            "experimental line to belong to it. In the Ca2Al2SiO7 example, several "
            "COD entries have closely related chemistry and diffraction evidence. "
            "The ranking alone does not establish which entry best represents the "
            "sample. The user can compare source provenance, leading-reflection "
            "coverage and strong calculated lines that are absent from the "
            "experiment; one coincident maximum is not sufficient."
        ),
        "Dominant-phase identification example": (
            "Dominant-phase identification example. Closely related calcium "
            "aluminosilicate entries are ordered by Match before any phase is "
            "accepted. The plot and candidate table expose both supporting lines "
            "and strong calculated reflections absent from the experiment. Gain "
            "is intentionally left empty at this stage."
        ),
        "Once the dominant phase is accepted": (
            "Once a dominant phase is accepted, the ordering changes from overall "
            "resemblance to additional explanatory value. This is useful when "
            "several database entries describe the same structure family or when a "
            "minor phase shares its strongest reflection with an accepted phase. "
            "In the natural gehlenite example, accepting the principal candidate "
            "removes much of the common diffraction evidence from the next search. "
            "A related candidate is promoted only when it also supports residual "
            "lines or a reproducible under-fit at shared reflections. The example "
            "illustrates the intended workflow; the benchmark below tests the "
            "ranking behaviour independently of that specimen."
        ),
        "Effect of conditional residual ranking": (
            "Effect of conditional residual ranking. After the dominant candidate "
            "is accepted and the selected-phase model is refitted, Gain reorders "
            "the remaining entries according to additional residual evidence. "
            "Structurally related candidates that mainly repeat explained lines "
            "are demoted, while candidates supporting coherent unexplained lines "
            "remain visible for inspection."
        ),
        "Version 1.1.4 prototype validation baseline": (
            "Version 1.2.0 closed-world validation"
        ),
        "We evaluated the current implementation on 50 cases": (
            "The version 1.2.0 implementation was evaluated on 50 synthetic "
            "profiles generated from 23 representative COD formula families. The "
            "candidate pool contained 51 COD entries belonging to the same 23 "
            "families and therefore included the expected answer for every case. "
            "The set comprised 20 single-phase, 20 binary and 10 ternary profiles "
            "with controlled angular shifts, line broadening, background, noise "
            "and peak overlap. This closed-world design separates ranking behaviour "
            "from database-coverage failure, but it does not reproduce all "
            "instrumental and specimen effects found in laboratory data."
        ),
        "For all 30 single-phase RRUFF patterns": (
            "For the dominant phase, exact COD entry retrieval reached top-1 in "
            "47/50 cases and top-5 in 50/50. When crystallographically related "
            "entries were grouped by formula family, the dominant family ranked "
            "first in 48/50 cases and appeared in the top five in all 50. Across "
            "the complete mixtures, all expected families were present in the "
            "Match top five in 39/50 cases and in the top ten in 45/50. Match is "
            "therefore most reliable as an initial dominant-phase shortlist, not "
            "as a complete one-pass decomposition of a mixture."
        ),
        "Residual Gain was evaluated": (
            "Conditional Gain was evaluated over 40 expected phase-addition steps "
            "from the binary and ternary profiles. After the already accepted "
            "families were fitted, the next expected family ranked first by Gain "
            "in 29/40 steps and appeared in the top five in 36/40; it received "
            "positive Gain in 37/40. These results support the use of Gain as a "
            "residual shortlist, while the remaining failures show that extensive "
            "overlap and weak components still require manual inspection."
        ),
        "The version 1.1.4 Gain baseline": (
            "The same benchmark included 20 closed single-phase profiles for which "
            "any additional family was false. One profile produced a false Gain of "
            "at least 5%, while the median maximum false Gain was 0%. Thus, the "
            "multiple-line, missing-line and profile-improvement gates substantially "
            "reduced unsupported additions but did not make them impossible."
        ),
        "A preliminary impurity-detectability series": (
            "A separate noise-significance stress test contained 40 binary profiles "
            "and ten single-phase negative controls. The signal-to-noise ratio was "
            "defined as the height of the second-strongest true minor-phase line "
            "divided by the known pointwise Gaussian-plus-counting noise standard "
            "deviation. The expected family appeared in the Gain top five in 2/13 "
            "cases below SNR 2, 2/11 cases at SNR 2-3, 3/7 cases at SNR 3-5 and "
            "8/9 cases at SNR >= 5. Six of the nine SNR >= 5 cases ranked first. "
            "Two of the ten negative controls nevertheless produced false Gain "
            "above 5% (maximum 8.35%)."
        ),
        "Table 2 summarizes": (
            "Table 2 summarizes both tests. The sharp dependence on SNR is "
            "scientifically important: a three-sigma line threshold controls which "
            "reflections are testable, but it does not guarantee correct phase "
            "identification. Signals near the noise floor are retained as tentative "
            "candidates rather than converted into automatic positive calls. The "
            "reported percentages describe ranking positions and fitted profile "
            "contributions, not mass detection limits. Validation on independently "
            "interpreted laboratory mixtures remains necessary."
        ),
        "The version 1.1.4 baseline recovered": (
            "In the version 1.2.0 closed-world benchmark, Match placed the dominant "
            "formula family first in 48 of 50 profiles and within the top five in "
            "all 50. Conditional Gain placed the next expected family in the top "
            "five in 36 of 40 phase-addition steps. The noise-significance test "
            "showed that useful minor-phase ranking emerged mainly when more than "
            "one characteristic line rose clearly above the noise. These results "
            "support the intended use of the program as an inspectable automatic "
            "or semi-automatic phase-hypothesis tool. They do not establish "
            "universal accuracy, analytical detection limits or quantitative mass "
            "fractions. Independent laboratory evaluation and an archived database "
            "snapshot remain the next validation steps."
        ),
        "The source code and release packages": (
            "The source code and release packages are available at "
            "https://github.com/ABKuznetsov/XRD_Analysis_Toolkit. The exact version "
            "used for the reported evaluation, the synthetic benchmark patterns, "
            "expected family labels, generation settings and tabulated Match/Gain "
            "results will be archived in a persistent repository before submission. "
            "Complete third-party structure collections are not bundled with the "
            "platform installers. Reproduction must therefore report the database "
            "snapshot or archived candidate list used for the run. Individual CIF "
            "files can be evaluated directly without inclusion in a shared database."
        ),
    }

    for prefix, replacement in replacements.items():
        replace_by_prefix(document, prefix, replacement)

    replace_validation_table(document)
    document.save(target)


def main() -> None:
    if len(sys.argv) != 3:
        raise SystemExit("usage: update_phase_finder_v120_article.py SOURCE TARGET")
    source = Path(sys.argv[1]).expanduser().resolve()
    target = Path(sys.argv[2]).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    update_document(source, target)


if __name__ == "__main__":
    main()
