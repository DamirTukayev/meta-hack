import numpy as np
from shapely.geometry import box

from orbitroute.perception.graph import build_road_graph
from orbitroute.understanding.scene import Scene, Zone


def grid_graph(size=400, step=100, thick=8, m_per_px=2.0):
    """A square street grid: bands every `step` px in both directions."""
    mask = np.zeros((size, size), bool)
    for c in range(step, size, step):
        mask[c - thick // 2 : c + thick // 2, 20 : size - 20] = True
        mask[20 : size - 20, c - thick // 2 : c + thick // 2] = True
    return build_road_graph(mask, m_per_px, densify_px=25)


def grid_scene(size=400):
    """Industrial block in the top-left quarter, residential elsewhere, one warehouse in the bottom-right."""
    zones = [
        Zone("industrial", box(0, 0, size / 2 - 10, size / 2 - 10)),
        Zone("residential", box(size / 2 - 10, 0, size, size)),
        Zone("residential", box(0, size / 2 - 10, size / 2 - 10, size)),
    ]
    return Scene(size, size, zones, warehouses=[(size * 0.75, size * 0.75)])
