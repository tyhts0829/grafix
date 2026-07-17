from __future__ import annotations

from grafix.devtools.generate_stub import _ROOT_STUB, generate_stubs_str


def test_generated_stubs_export_render_session_types() -> None:
    api_stub = generate_stubs_str()

    for name in (
        "Color",
        "ExportFormat",
        "ExportResult",
        "Frame",
        "RenderOptions",
        "RenderSession",
        "RenderSessionMetadata",
    ):
        assert f"{name} as {name}" in api_stub
        assert f"{name} as {name}" in _ROOT_STUB

    for name in ("export", "render"):
        assert f"{name} as {name}" in api_stub
        assert f"{name} as {name}" in _ROOT_STUB

    assert "Export as Export" not in api_stub
    assert "Export as Export" not in _ROOT_STUB
