"""Fit visible peak annotations inside the frame without extending the x scan."""
from __future__ import annotations

import math
import pyqtgraph as pg


ANNOTATION_LAYERS = ('hkl', 'preview_hkl', 'peak_labels', 'coverage_markers',
                     'candidate_markers', 'unknown_peaks')


def annotation_upper_bound(plot, layers, baseline, header_pixels=0.):
    view = plot.getViewBox()
    view.updateMatrix()
    low, high = map(float, baseline)
    height = max(float(view.height()), 1.)
    header = max(float(header_pixels), 0.)
    required = low + (high-low)/(1.-min(header/height, .8))
    xmin, xmax = view.viewRange()[0]

    def include(x, y, above_pixels):
        nonlocal required
        if not all(math.isfinite(v) for v in (x,y,above_pixels)) or not xmin <= x <= xmax or y < low:
            return
        fraction = min(max(header+above_pixels+4., 0.)/height, .8)
        required = max(required, low+(y-low)/(1.-fraction))

    for layer in ANNOTATION_LAYERS:
        for item in layers.get(layer, ()):
            if not item.isVisible():
                continue
            if isinstance(item, pg.TextItem):
                # Text is measured in screen coordinates, including rotation.
                # HklLabelItem keeps its physical anchor separate from drag.
                above = item.scenePos().y()-item.sceneBoundingRect().top()
                y = item.pos().y()
                if getattr(item, '_base_y', None) is not None:
                    y = item._base_y
                    above -= item._offset_px
                include(float(item.pos().x()), float(y), float(above))
            elif isinstance(item, pg.ScatterPlotItem):
                for spot in item.points():
                    point = item.mapToView(spot.pos())
                    size = max(float(spot.size()), 0.)
                    if item.opts.get('pxMode', True):
                        above = size*.5+1.
                    else:
                        above = size*.5*height/max(high-low, 1.e-12)
                    include(float(point.x()), float(point.y()), above)
    return required
