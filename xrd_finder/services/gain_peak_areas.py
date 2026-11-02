"""Conservative accepted-phase accounting on measured peak areas, not a grid fit."""
from __future__ import annotations

import math

import numpy as np
from scipy.optimize import nnls


def remaining_peak_areas(records, patterns):
    """Return residual areas and which peaks are dominated by unexplained signal.

    Each accepted pattern has one nonnegative scale shared by all its lines.
    A nearby weak/forbidden reflection therefore cannot claim an arbitrary
    experimental area. Duplicate accepted cards share the same fitted signal.
    Measured widths set positional support; native strengths stay unchanged.
    """
    if not records:
        return np.empty(0), np.empty(0,dtype=bool)
    observed=np.asarray([r.area for r in records],dtype=float)
    positions=np.asarray([r.two_theta for r in records],dtype=float)
    widths=np.asarray([max(r.fwhm,.05) for r in records],dtype=float)
    columns=[]
    strong_coincident=np.zeros(len(records),dtype=bool)
    for pattern in patterns:
        maximum=max((r.intensity for r in pattern),default=0.)
        lines=[r for r in pattern if r.intensity>maximum*1e-10]
        if not lines:
            continue
        angles=np.asarray([r.two_theta for r in lines],dtype=float)
        strengths=np.asarray([r.intensity/maximum for r in lines],dtype=float)
        distance=(positions[:,None]-angles[None,:])/widths[:,None]
        columns.append(np.exp(-4.*math.log(2.)*distance**2)@strengths)
        # Excess at an existing strong maximum may be texture/model error.
        # Keep it as shared corroboration; another phase still needs evidence
        # beyond well-coincident strong lines of the accepted phases.
        strong_coincident|=np.any((np.abs(distance)<=.5)&(strengths[None,:]>=.03),axis=1)
    if not columns:
        return observed.copy(),np.ones(len(records),dtype=bool)
    design=np.column_stack(columns)
    noise=[]
    for r in records:
        snrs=[float(v) for v in (r.area_snr,r.local_snr) if v is not None and math.isfinite(float(v)) and float(v)>0]
        noise.append(r.area/min(snrs) if snrs else 0.)
    noise=np.asarray(noise,dtype=float)
    floor=max(float(observed.max())*1e-8,1e-12)
    weights=1./np.sqrt(np.maximum(observed,floor))
    scales,_=nnls(design*weights[:,None],observed*weights)
    predicted=design@scales
    # Empirical disagreement at accepted-dominated peaks includes imperfect
    # area measurements and relative intensities. Do not promote that scatter
    # into a new phase; retain large local excess above this conservative bound.
    anchors=(predicted>=.5*observed)&(predicted>floor)
    relative=(observed[anchors]-predicted[anchors])/predicted[anchors]
    scatter=(1.4826*float(np.median(np.abs(relative-np.median(relative))))
             if len(relative)>=3 else 0.)
    allowance=3.*noise+3.*scatter*predicted
    residual=np.maximum(observed-predicted-allowance,0.)
    independent=((predicted+allowance)<.5*observed)&~strong_coincident
    return residual,independent
