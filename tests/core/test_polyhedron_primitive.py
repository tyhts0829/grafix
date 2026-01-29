from __future__ import annotations

from importlib import resources

import numpy as np

from grafix.api import G
from grafix.core.realize import realize
from grafix.core.primitives import polyhedron as polyhedron_mod


def test_polyhedron_data_files_exist() -> None:
    data_dir = resources.files("grafix").joinpath("resource", "regular_polyhedron")
    assert data_dir.is_dir()

    for kind in polyhedron_mod._TYPE_ORDER:
        name = f"{kind}_vertices_list.npz"
        assert data_dir.joinpath(name).is_file()


def test_polyhedron_realize_returns_nonempty_geometry() -> None:
    for type_index in range(len(polyhedron_mod._TYPE_ORDER)):
        realized = realize(G.polyhedron(type_index=type_index))
        assert realized.coords.dtype == np.float32
        assert realized.offsets.dtype == np.int32
        assert realized.coords.shape[0] > 0
        assert realized.offsets.shape[0] > 1
        assert int(realized.offsets[-1]) == int(realized.coords.shape[0])
