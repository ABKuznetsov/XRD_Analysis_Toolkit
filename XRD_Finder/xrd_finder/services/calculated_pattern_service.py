from __future__ import annotations

import cmath
from dataclasses import dataclass
import math
import re

import numpy as np

CU_KA1_WAVELENGTH = 1.54051
CU_KA2_WAVELENGTH = 1.54433
CU_KA2_INTENSITY_RATIO = 0.5
PROFILE_WINDOW_FACTOR = 5.0

CORUNDUM_CIF = """
data_corundum_reference
_chemical_name_mineral 'Corundum'
_chemical_formula_sum 'Al2 O3'
_symmetry_space_group_name_H-M 'R -3 c'
_cell_length_a 4.759
_cell_length_b 4.759
_cell_length_c 12.991
_cell_angle_alpha 90
_cell_angle_beta 90
_cell_angle_gamma 120
loop_
_symmetry_equiv_pos_as_xyz
'x,y,z'
'-y,x-y,z'
'-x+y,-x,z'
'y,x,-z+1/2'
'x-y,-y,-z+1/2'
'-x,-x+y,-z+1/2'
'x+2/3,y+1/3,z+1/3'
'-y+2/3,x-y+1/3,z+1/3'
'-x+y+2/3,-x+1/3,z+1/3'
'y+2/3,x+1/3,-z+5/6'
'x-y+2/3,-y+1/3,-z+5/6'
'-x+2/3,-x+y+1/3,-z+5/6'
'x+1/3,y+2/3,z+2/3'
'-y+1/3,x-y+2/3,z+2/3'
'-x+y+1/3,-x+2/3,z+2/3'
'y+1/3,x+2/3,-z+7/6'
'x-y+1/3,-y+2/3,-z+7/6'
'-x+1/3,-x+y+2/3,-z+7/6'
loop_
_atom_site_label
_atom_site_type_symbol
_atom_site_fract_x
_atom_site_fract_y
_atom_site_fract_z
_atom_site_occupancy
Al Al 0 0 0.3522 1
O O 0.306 0 0.25 1
"""

KALPHA_DOUBLET_LINES = {
    "CuKa": (1.54051, 1.54433),
    "TiKa": (2.74841, 2.75207),
    "CrKa": (2.28962, 2.29351),
    "FeKa": (1.93597, 1.93991),
    "CoKa": (1.78892, 1.79278),
    "GaKa": (1.34003, 1.34394),
    "MoKa": (0.70926, 0.713543),
    "AgKa": (0.559363, 0.563775),
    "InKa": (0.512094, 0.516525),
}


@dataclass(slots=True)
class HKLPeak:
    h: int
    k: int
    l: int
    d: float
    two_theta: float
    intensity: float
    multiplicity: int = 1
    f2: float = 0.0
    lp: float = 1.0
    raw_intensity: float = 0.0


@dataclass(slots=True)
class ExpandedAtom:
    element: str
    x: float
    y: float
    z: float
    occupancy: float
    biso: float | None = None
    uiso: float | None = None


ATOMIC_Z = {
    "H": 1, "B": 5, "C": 6, "N": 7, "O": 8, "F": 9,
    "Na": 11, "Mg": 12, "Al": 13, "Si": 14, "P": 15, "S": 16,
    "K": 19, "Ca": 20, "Ti": 22, "Fe": 26, "Cu": 29, "Zn": 30,
    "Sr": 38, "Y": 39, "Zr": 40, "Nb": 41, "Mo": 42, "Ba": 56,
    "La": 57, "Ce": 58, "Eu": 63, "Gd": 64, "Tb": 65, "W": 74, "Pb": 82,
}

CM = {
    "O": ([3.0485, 2.2868, 1.5463, 0.8670], [13.2771, 5.7011, 0.3239, 32.9089], 0.2508),
    "Al": ([6.4202, 1.9002, 1.5936, 1.9646], [3.0387, 0.7426, 31.5472, 85.0886], 1.1151),
    "Si": ([6.2915, 3.0353, 1.9891, 1.5410], [2.4386, 32.3337, 0.6785, 81.6937], 1.1407),
    "Ca": ([8.6266, 7.3873, 1.5899, 1.0211], [10.4421, 0.6599, 85.7484, 178.437], 1.3751),
    "Mg": ([5.4204, 2.1735, 1.2269, 2.3073], [2.8275, 79.2611, 0.3808, 7.1937], 0.8584),
    "Na": ([4.7626, 3.1736, 1.2674, 1.1128], [3.2850, 8.8422, 0.3136, 129.424], 0.6760),
    "K": ([8.2186, 7.4398, 1.0519, 0.8659], [12.7949, 0.7748, 213.187, 41.6841], 1.4228),
    "Ti": ([9.7595, 7.3558, 1.6991, 1.9021], [7.8508, 0.5000, 35.6338, 116.105], 1.2807),
    "Fe": ([11.7695, 7.3573, 3.5222, 2.3045], [4.7611, 0.3072, 15.3535, 76.8805], 1.0369),
    "Zr": ([17.8765, 10.9480, 5.41732, 3.65721], [1.27618, 11.9160, 0.117622, 87.6627], 2.06929),
    "Mo": ([3.7025, 17.2356, 12.8876, 3.7429], [0.2772, 1.0958, 11.0040, 61.6584], 4.3875),
    "W": ([29.0818, 15.43, 14.4327, 5.11982], [1.72029, 9.2259, 0.321703, 57.056], 9.8875),
}

def _mod1(value: float) -> float:
    value = value % 1.0
    if abs(value - 1.0) < 1e-8 or abs(value) < 1e-8:
        return 0.0
    return value


def _safe_eval_expr(expr: str, x: float, y: float, z: float) -> float:
    prepared = expr.strip().lower().replace(" ", "")
    prepared = prepared.replace("x", "X").replace("y", "Y").replace("z", "Z")
    if re.search(r"[^XYZ0-9+\-*/().]", prepared):
        raise ValueError(f"Unsupported symop expression: {expr}")
    return float(eval(prepared, {"__builtins__": {}}, {"X": x, "Y": y, "Z": z}))


def _expr_coeffs(expr: str) -> tuple[int, int, int]:
    values = []
    for basis in [(1, 0, 0), (0, 1, 0), (0, 0, 1), (0, 0, 0)]:
        values.append(_safe_eval_expr(expr, *basis))
    constant = values[3]
    return tuple(int(round(values[index] - constant)) for index in range(3))


def _symop_rotation_matrix(op: str) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    parts = [part.strip() for part in op.replace("'", "").replace('"', "").split(",")]
    if len(parts) != 3:
        raise ValueError(f"Bad symop: {op}")
    return tuple(_expr_coeffs(part) for part in parts)


def _point_group_matrices(structure) -> list[tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]]:
    matrices = []
    seen = set()
    for op in getattr(structure, "symops", None) or ["x,y,z"]:
        try:
            matrix = _symop_rotation_matrix(op)
        except Exception:
            continue
        if matrix not in seen:
            seen.add(matrix)
            matrices.append(matrix)
    return matrices or [((1, 0, 0), (0, 1, 0), (0, 0, 1))]


def _apply_hkl_matrix(matrix, hkl: tuple[int, int, int]) -> tuple[int, int, int]:
    h, k, l = hkl
    # Symmetry operations transform fractional coordinates as r' = R r + t.
    # Reflection indices transform with the reciprocal-space transpose R^T.
    return (
        matrix[0][0] * h + matrix[1][0] * k + matrix[2][0] * l,
        matrix[0][1] * h + matrix[1][1] * k + matrix[2][1] * l,
        matrix[0][2] * h + matrix[1][2] * k + matrix[2][2] * l,
    )


def _equivalent_hkls(structure, hkl: tuple[int, int, int]) -> set[tuple[int, int, int]]:
    equivalents = set()
    for matrix in _point_group_matrices(structure):
        item = _apply_hkl_matrix(matrix, hkl)
        equivalents.add(item)
        equivalents.add((-item[0], -item[1], -item[2]))
    return equivalents


def _canonical_hkl(structure, hkl: tuple[int, int, int]) -> tuple[int, int, int]:
    return min(_equivalent_hkls(structure, hkl))


def _apply_symop(op: str, x: float, y: float, z: float) -> tuple[float, float, float]:
    parts = [part.strip() for part in op.replace("'", "").replace('"', "").split(",")]
    if len(parts) != 3:
        raise ValueError(f"Bad symop: {op}")
    return (
        _mod1(_safe_eval_expr(parts[0], x, y, z)),
        _mod1(_safe_eval_expr(parts[1], x, y, z)),
        _mod1(_safe_eval_expr(parts[2], x, y, z)),
    )


def expand_atoms_by_symmetry(structure, tol_digits: int = 5) -> list[ExpandedAtom]:
    expanded = []
    seen = set()
    for atom in getattr(structure, "atoms", None) or []:
        if atom.x is None or atom.y is None or atom.z is None:
            continue
        occupancy = atom.occupancy if atom.occupancy is not None else 1.0
        for op in getattr(structure, "symops", None) or ["x,y,z"]:
            try:
                x, y, z = _apply_symop(op, atom.x, atom.y, atom.z)
            except Exception:
                continue
            key = (atom.element, round(x, tol_digits), round(y, tol_digits), round(z, tol_digits))
            if key in seen:
                continue
            seen.add(key)
            expanded.append(ExpandedAtom(atom.element, x, y, z, occupancy, atom.biso, atom.uiso))
    return expanded


def _cell_volume(a, b, c, alpha, beta, gamma) -> float:
    ar, br, gr = map(math.radians, [alpha, beta, gamma])
    term = 1 + 2 * math.cos(ar) * math.cos(br) * math.cos(gr)
    term -= math.cos(ar) ** 2 + math.cos(br) ** 2 + math.cos(gr) ** 2
    return a * b * c * math.sqrt(max(term, 0.0))


def _d_spacing_general(h, k, l, cell) -> float | None:
    a, b, c, alpha, beta, gamma = cell.a, cell.b, cell.c, cell.alpha, cell.beta, cell.gamma
    volume = _cell_volume(a, b, c, alpha, beta, gamma)
    if volume <= 0:
        return None
    ar, br, gr = map(math.radians, [alpha, beta, gamma])
    astar = b * c * math.sin(ar) / volume
    bstar = a * c * math.sin(br) / volume
    cstar = a * b * math.sin(gr) / volume
    if abs(math.sin(ar) * math.sin(br) * math.sin(gr)) < 1e-12:
        return None
    cos_astar = (math.cos(br) * math.cos(gr) - math.cos(ar)) / (math.sin(br) * math.sin(gr))
    cos_bstar = (math.cos(ar) * math.cos(gr) - math.cos(br)) / (math.sin(ar) * math.sin(gr))
    cos_cstar = (math.cos(ar) * math.cos(br) - math.cos(gr)) / (math.sin(ar) * math.sin(br))
    inv_d2 = (
        h * h * astar * astar
        + k * k * bstar * bstar
        + l * l * cstar * cstar
        + 2 * h * k * astar * bstar * cos_cstar
        + 2 * h * l * astar * cstar * cos_bstar
        + 2 * k * l * bstar * cstar * cos_astar
    )
    return 1.0 / math.sqrt(inv_d2) if inv_d2 > 0 else None


def _d_limits(two_theta_min: float, two_theta_max: float, wavelength: float) -> tuple[float, float]:
    theta_min = math.radians(max(two_theta_min, 0.001) / 2.0)
    theta_max = math.radians(min(two_theta_max, 179.999) / 2.0)
    return wavelength / (2.0 * math.sin(theta_max)), wavelength / (2.0 * math.sin(theta_min))


def _hkl_limits(structure, dmin: float, cap: int) -> tuple[int, int, int]:
    cell = structure.cell
    volume = _cell_volume(cell.a, cell.b, cell.c, cell.alpha, cell.beta, cell.gamma)
    if volume <= 0:
        return cap, cap, cap
    ar, br, gr = map(math.radians, [cell.alpha, cell.beta, cell.gamma])
    reciprocal = (
        cell.b * cell.c * math.sin(ar) / volume,
        cell.a * cell.c * math.sin(br) / volume,
        cell.a * cell.b * math.sin(gr) / volume,
    )
    qmax = 1.0 / max(dmin, 1e-9)
    return tuple(min(cap, max(1, int(math.ceil(qmax / max(value, 1e-12))) + 1)) for value in reciprocal)


def _atomic_f0(element: str, sq: float) -> float:
    element = (element or "").strip().capitalize()
    if element in CM:
        fa, fb, fc = CM[element]
        return sum(a * math.exp(-b * sq) for a, b in zip(fa, fb)) + fc
    z = ATOMIC_Z.get(element, 10)
    return z * math.exp(-8.0 * sq / max(z**0.25, 1.0))


def _debye_waller(atom: ExpandedAtom, sq: float) -> float:
    if atom.biso is not None:
        b = atom.biso
    elif atom.uiso is not None:
        b = 8.0 * math.pi * math.pi * atom.uiso
    else:
        b = 0.4
    return math.exp(-max(b, 0.0) * sq)


def _lorentz_polarization(two_theta_deg: float) -> float:
    theta = math.radians(two_theta_deg / 2.0)
    two_theta = math.radians(two_theta_deg)
    sin_theta = max(math.sin(theta), 1e-6)
    cos_theta = max(math.cos(theta), 1e-6)
    return (1.0 + math.cos(two_theta) ** 2) / (sin_theta * sin_theta * cos_theta)


def _structure_factor_components(
    expanded_atoms: list[ExpandedAtom],
    h: int,
    k: int,
    l: int,
    d: float,
    two_theta: float,
    use_lp: bool = False,
) -> tuple[float, float, float]:
    sq = 1.0 / ((2.0 * d) ** 2)
    factor = 0j
    for atom in expanded_atoms:
        phase_arg = 2.0 * math.pi * (h * atom.x + k * atom.y + l * atom.z)
        factor += atom.occupancy * _atomic_f0(atom.element, sq) * _debye_waller(atom, sq) * cmath.exp(1j * phase_arg)
    f2 = float(factor.real * factor.real + factor.imag * factor.imag)
    lp = _lorentz_polarization(two_theta) if use_lp else 1.0
    return f2, lp, float(max(f2 * lp, 0.0))


def _merge_close_peaks(peaks: list[HKLPeak], tolerance_2theta: float = 0.035) -> list[HKLPeak]:
    if not peaks:
        return []
    peaks = sorted(peaks, key=lambda peak: peak.two_theta)
    merged = []
    group = [peaks[0]]

    def flush(items: list[HKLPeak]) -> HKLPeak:
        if len(items) == 1:
            return items[0]
        total = sum(item.raw_intensity for item in items)
        best = max(items, key=lambda item: item.raw_intensity)
        if total <= 0:
            return best
        return HKLPeak(
            h=best.h,
            k=best.k,
            l=best.l,
            d=sum(item.d * item.raw_intensity for item in items) / total,
            two_theta=sum(item.two_theta * item.raw_intensity for item in items) / total,
            intensity=total,
            multiplicity=sum(item.multiplicity for item in items),
            f2=sum(item.f2 for item in items),
            lp=sum(item.lp * item.raw_intensity for item in items) / total,
            raw_intensity=total,
        )

    for peak in peaks[1:]:
        if abs(peak.two_theta - group[-1].two_theta) <= tolerance_2theta:
            group.append(peak)
        else:
            merged.append(flush(group))
            group = [peak]
    merged.append(flush(group))
    return merged


def calculate_hkl_sticks(
    structure,
    two_theta_min: float = 5.0,
    two_theta_max: float = 120.0,
    wavelength: float = CU_KA1_WAVELENGTH,
    max_index: int = 12,
    use_lp: bool = True,
    intensity_min: float = 0.5,
) -> list[HKLPeak]:
    cell = structure.cell
    if None in (cell.a, cell.b, cell.c, cell.alpha, cell.beta, cell.gamma):
        raise ValueError("Structure has incomplete unit cell")
    expanded_atoms = expand_atoms_by_symmetry(structure)
    if not expanded_atoms:
        raise ValueError("No atoms available for structure factor")

    dmin, dmax = _d_limits(two_theta_min, two_theta_max, wavelength)
    hmax, kmax, lmax = _hkl_limits(structure, dmin, max_index)
    point_group_matrices = _point_group_matrices(structure)

    def equivalent_hkls(hkl: tuple[int, int, int]) -> set[tuple[int, int, int]]:
        equivalents = set()
        for matrix in point_group_matrices:
            item = _apply_hkl_matrix(matrix, hkl)
            equivalents.add(item)
            equivalents.add((-item[0], -item[1], -item[2]))
        return equivalents

    def canonical_hkl(hkl: tuple[int, int, int]) -> tuple[int, int, int]:
        return min(equivalent_hkls(hkl))

    peaks = []
    used_groups = set()
    for h in range(-hmax, hmax + 1):
        for k in range(-kmax, kmax + 1):
            for l in range(-lmax, lmax + 1):
                if h == 0 and k == 0 and l == 0:
                    continue
                d0 = _d_spacing_general(h, k, l, cell)
                if not d0 or d0 < dmin or d0 > dmax:
                    continue
                key = canonical_hkl((h, k, l))
                if key in used_groups:
                    continue
                used_groups.add(key)
                equivalents = equivalent_hkls((h, k, l))
                valid_equivalents = []
                for eh, ek, el in equivalents:
                    d = _d_spacing_general(eh, ek, el, cell)
                    if not d or d < dmin or d > dmax:
                        continue
                    argument = wavelength / (2.0 * d)
                    if argument <= 0 or argument >= 1:
                        continue
                    two_theta = 2.0 * math.degrees(math.asin(argument))
                    if two_theta_min <= two_theta <= two_theta_max:
                        valid_equivalents.append((eh, ek, el, d, two_theta))
                if not valid_equivalents:
                    continue
                bh, bk, bl, bd, btt = valid_equivalents[0]
                best_f2, best_lp, best_raw = _structure_factor_components(
                    expanded_atoms,
                    bh,
                    bk,
                    bl,
                    bd,
                    btt,
                    use_lp=use_lp,
                )
                multiplicity = len(valid_equivalents)
                raw = best_raw * multiplicity
                if raw > 1e-8:
                    peaks.append(
                        HKLPeak(
                            h=bh,
                            k=bk,
                            l=bl,
                            d=bd,
                            two_theta=btt,
                            intensity=raw,
                            multiplicity=multiplicity,
                            f2=best_f2 * multiplicity,
                            lp=best_lp,
                            raw_intensity=raw,
                        )
                    )

    peaks = _merge_close_peaks(peaks)
    if peaks:
        max_intensity = max(peak.raw_intensity for peak in peaks) or 1.0
        for peak in peaks:
            peak.intensity = 100.0 * peak.raw_intensity / max_intensity
        peaks = [peak for peak in peaks if peak.intensity >= intensity_min]
    return sorted(peaks, key=lambda peak: peak.two_theta)


def gaussian_values(x, center: float, fwhm: float):
    sigma = max(fwhm, 1e-8) / (2.0 * math.sqrt(2.0 * math.log(2.0)))
    return np.exp(-0.5 * ((x - center) / sigma) ** 2)


def lorentzian_values(x, center: float, fwhm: float):
    width = max(fwhm, 1e-8)
    return 1.0 / (1.0 + 4.0 * ((x - center) / width) ** 2)


def pseudo_voigt_values(x, center: float, fwhm: float, eta: float):
    eta = float(np.clip(eta, 0.0, 1.0))
    if eta <= 1e-8:
        return gaussian_values(x, center, fwhm)
    if eta >= 1.0 - 1e-8:
        return lorentzian_values(x, center, fwhm)
    return (1.0 - eta) * gaussian_values(x, center, fwhm) + eta * lorentzian_values(x, center, fwhm)


def _two_theta_from_d(d_spacing: float, wavelength: float) -> float | None:
    argument = wavelength / (2.0 * d_spacing)
    if argument <= 0.0 or argument >= 1.0:
        return None
    return float(2.0 * math.degrees(math.asin(argument)))


def radiation_lines_from_wavelength(
    wavelength: float | None,
    include_kalpha2: bool = True,
) -> list[tuple[float, float]]:
    if wavelength is None or wavelength <= 0:
        wavelength = CU_KA1_WAVELENGTH
    wavelength = float(wavelength)
    if include_kalpha2:
        for lam1, lam2 in KALPHA_DOUBLET_LINES.values():
            mean = (2.0 * lam1 + lam2) / 3.0
            if min(abs(wavelength - lam1), abs(wavelength - lam2), abs(wavelength - mean)) <= 0.006:
                return [(lam1, 1.0), (lam2, CU_KA2_INTENSITY_RATIO)]
    return [(wavelength, 1.0)]


def calculated_profile_from_peaks(
    peaks: list[HKLPeak],
    x_grid,
    fwhm: float = 0.12,
    eta: float = 0.0,
    wavelength: float | None = CU_KA1_WAVELENGTH,
    include_kalpha2: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    x = np.asarray(x_grid, dtype=float)
    y = np.zeros_like(x, dtype=float)
    if not peaks or len(x) == 0:
        return x, y

    def add_peak(center: float, intensity: float) -> None:
        if not (x[0] <= center <= x[-1]):
            return
        half_width = PROFILE_WINDOW_FACTOR * max(fwhm, 1e-6)
        left = np.searchsorted(x, center - half_width, side="left")
        right = np.searchsorted(x, center + half_width, side="right")
        if right <= left:
            return
        y[left:right] += intensity * pseudo_voigt_values(x[left:right], center, fwhm, eta)

    lines = radiation_lines_from_wavelength(wavelength, include_kalpha2=include_kalpha2)
    for peak in peaks:
        primary = _two_theta_from_d(float(peak.d), lines[0][0])
        zero_shift = float(peak.two_theta) - primary if primary is not None else 0.0
        for line_wavelength, line_fraction in lines:
            center = _two_theta_from_d(float(peak.d), line_wavelength)
            if center is not None:
                add_peak(center + zero_shift, float(peak.intensity) * line_fraction)
    if np.nanmax(y) > 0:
        y = 100.0 * y / np.nanmax(y)
    return x, y


class CalculatedPatternService:
    def calculate_sticks(self, structure, **kwargs) -> list[HKLPeak]:
        return calculate_hkl_sticks(structure, **kwargs)

    def calculate_profile(self, structure, x_grid=None, **kwargs) -> tuple[np.ndarray, np.ndarray, list[HKLPeak]]:
        two_theta_min = float(kwargs.pop("two_theta_min", 5.0))
        two_theta_max = float(kwargs.pop("two_theta_max", 120.0))
        fwhm = float(kwargs.pop("fwhm", 0.12))
        eta = float(kwargs.pop("eta", 0.0))
        wavelength = float(kwargs.get("wavelength", CU_KA1_WAVELENGTH))
        primary_wavelength = radiation_lines_from_wavelength(wavelength, include_kalpha2=True)[0][0]
        kwargs["wavelength"] = primary_wavelength
        peaks = calculate_hkl_sticks(structure, two_theta_min=two_theta_min, two_theta_max=two_theta_max, **kwargs)
        if x_grid is None:
            x_grid = np.linspace(two_theta_min, two_theta_max, 5000)
        x, y = calculated_profile_from_peaks(peaks, x_grid, fwhm=fwhm, eta=eta, wavelength=wavelength)
        return x, y, peaks
