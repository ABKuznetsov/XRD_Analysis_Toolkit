"""Optional bounded Le Bail for accepted phases; never a Quant calculation.

The GUI calls ``refine_accepted_le_bail`` from its background queue. Native
refinement runs in an owned process so even an uninterruptible native call
cannot exceed the search budget or hold Qt's GIL.
"""
from __future__ import annotations

from copy import deepcopy
import math
import os
from pathlib import Path
import pickle
import subprocess
import sys
import time

from xrd_finder.services.worker_directory import WorkerTemporaryDirectory

LE_BAIL_POLICY = 'accepted-le-bail-2:3cycles:2seconds'
QUANT_REASON = 'Le Bail adjusts reflection intensities independently; structural mass fractions are unavailable. Turn Le Bail off to restore Quant.'


def le_bail_available() -> bool:
    if getattr(sys, 'frozen', False):
        return False  # Packaged executables need a separate worker entry point.
    try:
        from cristma.diffraction import LeBailExtractor, LeBailRefiner, LeBailPhase
        return all(callable(api) for api in (LeBailExtractor, LeBailRefiner, LeBailPhase))
    except ImportError:
        return False


def _note(baseline, status, message, **details):
    result = deepcopy(baseline)
    result.position_refinement['le_bail'] = dict(
        status=status, message=message, policy=LE_BAIL_POLICY, **details)
    return result


def refresh_le_bail_peak_evidence(result):
    """Repair relative line strengths without changing the fitted count profile."""
    note = result.position_refinement.get('le_bail', {})
    if note.get('status') != 'applied' or note.get('peak_evidence') == 'visible-range-v1':
        return result
    from xrd_finder.finder.assignment_builder import AssignmentBuilder
    from xrd_finder.finder.matching import search_match_result
    from xrd_finder.services.calculated_pattern_service import HKLPeak

    low, high = result.pattern_x[0], result.pattern_x[-1]
    peak_sets = []
    for candidate in result.candidates:
        rows = list(zip(candidate.peak_two_theta, candidate.peak_intensity,
                        candidate.peak_h, candidate.peak_k, candidate.peak_l, strict=True))
        visible = [row for row in rows if low <= row[0] <= high]
        if not visible or any(not math.isfinite(row[1]) or row[1] < 0. for row in visible):
            raise ValueError('Le Bail has invalid visible reflection intensities.')
        maximum = max(row[1] for row in visible)
        if maximum <= 0.:
            raise ValueError('An accepted phase has no observable Le Bail intensity.')
        candidate.peak_intensity = [value/maximum*100. for _,value,*_ in rows]
        peaks = [HKLPeak(h,k,l,0.,angle,value/maximum*100.)
                 for angle,value,h,k,l in visible]
        matched = search_match_result(peaks, [p.two_theta for p in result.observed_peaks])
        for name in ('score','status','matched_peaks','total_peaks','mean_delta_two_theta'):
            setattr(candidate,name,getattr(matched,name))
        candidate.matched_reference_two_theta = [p.reference_two_theta for p in matched.matches]
        candidate.matched_observed_two_theta = [p.observed_two_theta for p in matched.matches]
        candidate.matched_delta_two_theta = [p.delta_two_theta for p in matched.matches]
        peak_sets.append((candidate,peaks))
    result.observed_peaks = AssignmentBuilder().assign_observed_peaks(
        result.observed_peaks,peak_sets,tolerance=.25)
    # Stored profiles remain reusable: only their derived line evidence changed.
    result.position_refinement = {**result.position_refinement,
        'le_bail': {**note, 'peak_evidence': 'visible-range-v1'}}
    return result


def _cif_paths(inputs, baseline):
    paths = [Path(item.cif_path or item.quantification_cif_path)
             if item.cif_path or item.quantification_cif_path else None for item in inputs.candidates]
    if (not paths or len(paths) != len(baseline.candidates) or baseline.candidate_failures
            or not inputs.quantification_complete
            or any(path is None or not path.is_file() for path in paths)):
        raise ValueError('Every accepted phase needs a readable CIF; reference-only or failed cards cannot be omitted.')
    return paths


def _deadline_result(root, baseline, started):
    """Only atomically published, completed improvements survive a deadline."""
    try:
        result = pickle.loads((root/'checkpoint.pickle').read_bytes())
        note = result.position_refinement['le_bail']
        if note['status'] == 'applied':
            note.update(stopped='time_limit', elapsed_seconds=round(time.monotonic()-started,3),
                message='Le Bail reached the 2 s limit; best completed fit retained. Quant unavailable.')
            return result
    except (OSError, ValueError, KeyError, EOFError, pickle.UnpicklingError):
        pass
    return _note(baseline, 'timeout', 'Le Bail reached the 2 s limit; structural fit retained.')


def refine_accepted_le_bail(inputs, baseline, *, enabled=True, timeout_seconds=2., cancelled=lambda: False):
    """Keep the validated structural result on cancellation, limits or failure."""
    if not enabled:
        return baseline
    started = time.monotonic()
    deadline = started + min(max(float(timeout_seconds), 0.), 2.)
    if cancelled():
        return _note(baseline, 'cancelled', 'Le Bail cancelled; structural fit retained.')
    if time.monotonic() >= deadline:
        return _note(baseline, 'timeout', 'Le Bail reached the 2 s limit; structural fit retained.')
    try:
        _cif_paths(inputs, baseline)
        if not le_bail_available():
            raise ValueError('Native Le Bail requires CrIStMa 0.1.0b14 and a Python worker runtime.')
        package_root = str(Path(__file__).resolve().parents[2])
        environment = os.environ.copy()
        environment['PYTHONPATH'] = package_root + os.pathsep + environment.get('PYTHONPATH', '')
        # Avoid competing BLAS pools and long startup on small search problems.
        environment.update(OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1',
                           PYTHONDONTWRITEBYTECODE='1')
        with WorkerTemporaryDirectory(prefix='xrd-le-bail-') as folder:
            root = Path(folder)
            (root/'input.pickle').write_bytes(pickle.dumps((inputs, baseline, deadline)))
            process = None
            try:
                with (root/'stdout').open('wb') as output, (root/'stderr').open('wb') as errors:
                    process = subprocess.Popen([sys.executable, '-m',
                        'xrd_finder.services.le_bail', str(root)], stdout=output, stderr=errors,
                        cwd=package_root, env=environment)
                while process.poll() is None:
                    if cancelled():
                        return _note(baseline, 'cancelled', 'Le Bail cancelled; structural fit retained.')
                    # Leave time to terminate and reap our worker inside the total budget.
                    if time.monotonic() >= deadline - .10:
                        return _deadline_result(root, baseline, started)
                    time.sleep(.01)
                if process.returncode:
                    raise RuntimeError('Le Bail worker failed: '+(root/'stderr').read_text()[-1500:])
                result = pickle.loads((root/'result.pickle').read_bytes())
                if cancelled():
                    return _note(baseline, 'cancelled', 'Le Bail cancelled; structural fit retained.')
                if time.monotonic() >= deadline:
                    return _deadline_result(root, baseline, started)
                result.position_refinement['le_bail']['elapsed_seconds'] = round(time.monotonic()-started, 3)
                return result
            finally:
                if process is not None and process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3.)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()
    except (OSError, ValueError, RuntimeError, pickle.UnpicklingError, subprocess.TimeoutExpired) as exc:
        return _note(baseline, 'unavailable', str(exc))


def run_native_le_bail(inputs, baseline, *, checkpoint=None, deadline=None):
    """Worker-only native calculation. No user data or instrument is modified."""
    try:
        return _native_result(inputs, baseline, checkpoint=checkpoint, deadline=deadline)
    except Exception as exc:
        return _note(baseline, 'unavailable', f'Le Bail: {type(exc).__name__}: {exc}; structural fit retained.')


def _native_result(inputs, baseline, *, checkpoint=None, deadline=None):
    import numpy as np
    from dataclasses import asdict
    from cristma.diffraction import (LeBailExtractor, LeBailPhase, LeBailRefiner,
        PseudoVoigtProfile, ReflectionGenerator, TchProfile, UniformTwoThetaGrid)
    from xrd_finder.core.structure import CellParameters
    from xrd_finder.finder.profile_backend import instrument_profile_with_width_floor
    from xrd_finder.instrument.resolution import cristma_tch_profile
    from xrd_finder.services.calculated_pattern_service import HKLPeak
    from xrd_finder.services.cristma_powder_adapter import CristmaPowderAdapter

    paths = _cif_paths(inputs, baseline)
    x, y, bg, previous = (np.asarray(values, dtype=float) for values in
        (baseline.pattern_x, baseline.pattern_y, baseline.background, baseline.calculated_total))
    if not (4 <= x.size <= 30000 and all(a.shape == x.shape for a in (y,bg,previous))
            and all(np.all(np.isfinite(a)) for a in (x,y,bg,previous))
            and np.all(y >= 0.) and np.all(bg >= 0.) and np.max(y-bg) > 0.):
        raise ValueError('Le Bail needs finite non-negative counts on a grid of 4–30000 points.')
    shifted = x-float(baseline.global_zero_shift)
    step = float((shifted[-1]-shifted[0])/(len(shifted)-1))
    if step <= 0. or np.any(np.diff(shifted) <= 0.):
        raise ValueError('Le Bail needs strictly increasing scan angles.')
    grid = UniformTwoThetaGrid(float(shifted[0]), float(shifted[-1])+.01*step, step)
    native_x = np.asarray(grid.values)
    rounding_error = float(np.max(np.abs(native_x-shifted))) if native_x.shape == x.shape else math.inf
    # Printed scan angles can have a tiny rounding jitter. Do not resample counts
    # or smooth the input; return calculated profiles on the exact original x.
    # Genuinely nonuniform acquisitions need a nonuniform native backend.
    if rounding_error > max(1e-7, min(1e-4, step*.01)):
        raise ValueError('Le Bail needs a uniform scan (only small angle-rounding errors are allowed).')
    instrument = inputs.instrument_profile
    if instrument is None:
        raise ValueError('Le Bail needs an explicit instrument profile with the measurement radiation.')
    adapter = CristmaPowderAdapter()
    spectrum = adapter.radiation_from_profile(instrument)
    # Cover full native profile support for the largest allowed effective width.
    upper_width = 1.
    support_stop = min(179., grid.stop_deg+5.*upper_width)
    d_min = min(c.wavelength_angstrom for c in spectrum.components)/(2.*math.sin(math.radians(support_stop/2.)))
    phases, cells = [], {}
    generator = ReflectionGenerator(max_candidates=500000)
    for index, (item, candidate, path) in enumerate(zip(inputs.candidates, baseline.candidates, paths)):
        if candidate.entry_id != item.entry_id:
            raise ValueError('Accepted phase order differs from the structural fit.')
        override = candidate.estimated_cell
        cell = (CellParameters(**{key:override[key] for key in ('a','b','c','alpha','beta','gamma')})
                if all(key in override for key in ('a','b','c','alpha','beta','gamma')) else item.initial_cell)
        structure, setting = adapter._structure_and_setting(path, cell_override=cell)
        pid = str(index)
        cells[pid] = structure.cell
        representative = float(np.median(shifted))
        effective = instrument_profile_with_width_floor(instrument, candidate.fwhm, representative)
        profile = (PseudoVoigtProfile(float(effective.resolution.constant_fwhm_deg),
                    max(0., min(1., float(candidate.profile_eta or 0.))))
                   if effective.resolution.model == 'constant_fwhm' else cristma_tch_profile(effective.resolution))
        phases.append(LeBailPhase(pid, generator.generate(structure.cell, setting, d_min), profile))
    def convert(native):
        extraction = native.extraction
        if (native.initial_extraction.shared_intensities or extraction.shared_intensities
                or any(p.shared_group_ids for p in extraction.phases)):
            return _note(baseline, 'ambiguous', 'Le Bail cannot separate shared cross-phase intensities; structural fit retained.')
        profiles = np.array([p.calculated for p in extraction.phases])
        total = np.asarray(extraction.calculated)
        if (profiles.shape != (len(phases),len(x)) or not np.all(np.isfinite(profiles))
                or np.any(profiles < 0.) or not np.all(np.isfinite(total))
                or not np.allclose(profiles.sum(axis=0)+bg, total, atol=1e-7, rtol=1e-8)):
            raise ValueError('Le Bail returned inconsistent phase profiles.')
        profiles = np.array([np.interp(shifted,native_x,values) for values in profiles])
        total = profiles.sum(axis=0)+bg
        initial_norm = float(np.linalg.norm(y-previous))
        final_norm = float(np.linalg.norm(y-total))
        if final_norm >= initial_norm*(1.-1e-8):
            return _note(baseline, 'no_improvement', 'Le Bail did not improve profile agreement; structural fit retained.')
        result = deepcopy(baseline)
        final_cells = dict(native.cells)
        wavelength = float(spectrum.components[0].wavelength_angstrom)
        by_id = {p.phase.phase_id:p for p in extraction.phases}
        calculated_by_id = {p.phase.phase_id:values for p,values in zip(extraction.phases,profiles)}
        for index, candidate in enumerate(result.candidates):
            phase = by_id[str(index)]
            cell = final_cells[phase.phase.phase_id]
            candidate.estimated_cell = {key:float(getattr(cell,key).value) for key in ('a','b','c','alpha','beta','gamma')}
            candidate.profile = calculated_by_id[phase.phase.phase_id].tolist()
            candidate.two_theta = x.tolist()
            candidate.mass_profile = []
            candidate.quantity_percent = None
            candidate.scale = 1.  # Counts already include extracted areas; never reapply structural scale.
            profile = phase.phase.profile
            candidate.sample_broadening = {'status':'le_bail_effective_profile',
                'model':'tch' if isinstance(profile,TchProfile) else 'pseudo_voigt',
                'parameters':asdict(profile),
                'coefficient_units':'gsas_cw' if isinstance(profile,TchProfile) else 'degrees', 'scope':'phase_local_effective_not_instrument_calibration'}
            candidate.fwhm = float(profile.fwhm_deg_at(float(np.median(shifted)))
                if isinstance(profile,TchProfile) else profile.fwhm_deg)
            candidate.profile_eta = None if isinstance(profile,TchProfile) else float(profile.eta)
            peaks = []
            for group in phase.intensity_groups:
                ratio = wavelength/(2.*group.d_spacing)
                if not 0. < ratio < 1.:
                    continue
                angle = math.degrees(2.*math.asin(ratio))+result.global_zero_shift
                if not x[0] <= angle <= x[-1]:
                    continue
                hkl = group.representative_hkls[0]
                peaks.append(HKLPeak(hkl.h,hkl.k,hkl.l,group.d_spacing,angle,
                    group.integrated_intensity,raw_intensity=group.integrated_intensity,
                    intensity_origin='le_bail_integrated_counts'))
            peaks.sort(key=lambda p:p.two_theta)
            if not peaks:
                raise ValueError('An accepted phase has no visible primary reflections.')
            candidate.peak_two_theta = [p.two_theta for p in peaks]
            candidate.peak_reference_two_theta = [p.two_theta-result.global_zero_shift for p in peaks]
            candidate.peak_intensity = [p.intensity for p in peaks]
            candidate.peak_h = [p.h for p in peaks]
            candidate.peak_k = [p.k for p in peaks]
            candidate.peak_l = [p.l for p in peaks]
        result.calculated_total = total.tolist()
        result.fwhm = float(np.median([p.fwhm for p in result.candidates]))
        result.profile_eta = (None if any(p.profile_eta is None for p in result.candidates)
                              else float(np.median([p.profile_eta for p in result.candidates])))
        result.sample_broadening_requested = True
        result.quantification_error = QUANT_REASON
        result.position_refinement['le_bail'] = dict(status='applied',policy=LE_BAIL_POLICY,
            message='Le Bail applied; limited refinement, Quant unavailable.',cycles=native.cycles,
            native_status=native.status.value, intensity_iterations=native.total_intensity_iterations,
            grid_rounding_max_deg=round(rounding_error, 9),
            initial_residual_norm=initial_norm, residual_norm=final_norm,
            diagnostics=[str(d.message) for d in native.diagnostics])
        return refresh_le_bail_peak_evidence(result)


    # Start with all phases, then individually improve accepted phases while
    # the shared budget permits. A phase-only pass still redistributes intensities
    # jointly: it never fits one phase independently to overlapping raw counts.
    # Three completed native cycles/evaluation and intensity budgets are shared.
    scopes = [None] + [(p.phase_id,) for p in phases]
    if len(phases) == 1:
        scopes = [None, None, None]
    best = _note(baseline, 'no_improvement', 'Le Bail did not improve profile agreement; structural fit retained.')
    best_norm = float(np.linalg.norm(y-previous))
    cycles = iterations = evaluations = 0
    steps = []
    stopped = ''
    for selected in scopes:
        if deadline is not None and time.monotonic() >= deadline-.10:
            stopped = 'time_limit'
            break
        if evaluations >= 32 or iterations >= 30 or cycles >= 3:
            stopped = 'iteration_limit'
            break
        try:
            native = LeBailRefiner(max_cycles=1, max_backtracks=2, metric_strain_bound=.015,
                max_evaluations=32-evaluations, max_total_iterations=30-iterations,
                initial_intensity_iterations=min(6 if not steps else 3, 30-iterations),
                intensity_iterations_per_cycle=2, max_jacobian_values=2000000,
                tch_refine_parameters=('w','x'),
                extractor=LeBailExtractor(max_iterations=8, max_points=30000, max_profile_values=2000000),
                fwhm_bounds=(.005, upper_width)).refine(tuple(phases), cells, spectrum, grid, y, bg,
                                                      refine_phase_ids=selected)
            candidate = convert(native)
        except Exception as exc:
            if best.position_refinement['le_bail']['status'] != 'applied':
                raise
            best.position_refinement['le_bail'].update(stopped='calculation_error',
                message=f'Le Bail stopped ({type(exc).__name__}); best completed fit retained. Quant unavailable.')
            return best
        cycles += native.cycles
        iterations += native.total_intensity_iterations
        evaluations += len(native.trials)
        note = candidate.position_refinement['le_bail']
        steps.append(dict(scope='joint' if selected is None else 'phase',
            phases=[inputs.candidates[int(pid)].entry_id for pid in selected] if selected else [],
            status=note['status'], cycles=native.cycles))
        if note['status'] == 'ambiguous':
            if best.position_refinement['le_bail']['status'] != 'applied':
                return candidate
            stopped = 'ambiguous_trial'
            break
        norm = float(np.linalg.norm(y-np.asarray(candidate.calculated_total)))
        if note['status'] == 'applied' and norm < best_norm:
            note.update(cycles=cycles,intensity_iterations=iterations,evaluations=evaluations,
                        steps=deepcopy(steps),completed_passes=len(steps))
            best, best_norm = candidate, norm
            phases = [p.phase for p in native.extraction.phases]
            cells = dict(native.cells)
            if checkpoint is not None:
                checkpoint(deepcopy(best))
    note = best.position_refinement['le_bail']
    if stopped == 'time_limit':
        if note['status'] != 'applied':
            best = _note(baseline,'timeout','Le Bail reached the 2 s limit; structural fit retained.')
            note = best.position_refinement['le_bail']
        else:
            note['message'] = 'Le Bail reached the 2 s limit; best completed fit retained. Quant unavailable.'
    note.update(cycles=cycles,intensity_iterations=iterations,evaluations=evaluations,
                steps=steps,completed_passes=len(steps))
    if stopped:
        note['stopped'] = stopped
    return best

def _publish_checkpoint(root, result):
    temporary = root/'checkpoint.pending'
    # A checkpoint is optional; the final result has its own output file.
    # Preserve the last complete checkpoint while Windows readers release it.
    for attempt in range(4):
        try:
            temporary.write_bytes(pickle.dumps(result))
            temporary.replace(root/'checkpoint.pickle')
            return
        except PermissionError:
            if attempt < 3:
                time.sleep(.005*(attempt+1))


if __name__ == '__main__':
    root = Path(sys.argv[1])
    inputs, baseline, deadline = pickle.loads((root/'input.pickle').read_bytes())
    def checkpoint(result):
        _publish_checkpoint(root, result)
    result = run_native_le_bail(inputs, baseline, checkpoint=checkpoint, deadline=deadline)
    (root/'result.pickle').write_bytes(pickle.dumps(result))
