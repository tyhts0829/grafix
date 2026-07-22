from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


def test_root_import_defers_builtin_catalog_bootstrap_until_attribute_access() -> None:
    script = r'''
import json
import sys

import grafix
from grafix.core.builtins import builtin_operation_manifest

prefixes = ("grafix.core.primitives.", "grafix.core.effects.")
expected = sorted(item.module for item in builtin_operation_manifest())
before = sorted(name for name in sys.modules if name.startswith(prefixes))
_ = grafix.G.polygon
after_polygon = sorted(name for name in sys.modules if name.startswith(prefixes))
_ = grafix.E.scale
after_scale = sorted(name for name in sys.modules if name.startswith(prefixes))
print(json.dumps({
    "expected": expected,
    "before": before,
    "after_polygon": after_polygon,
    "after_scale": after_scale,
}))
'''
    env = dict(os.environ)
    source_root = Path(__file__).resolve().parents[2] / "src"
    env["PYTHONPATH"] = str(source_root)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    result = json.loads(completed.stdout)

    assert result["before"] == []
    assert set(result["expected"]) <= set(result["after_polygon"])
    assert result["after_scale"] == result["after_polygon"]
