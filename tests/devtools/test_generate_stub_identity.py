from grafix.devtools.generate_stub import generate_stubs_str


def test_generated_stub_exposes_parameter_identity_controls() -> None:
    stub = generate_stubs_str()

    line_signature = next(
        line for line in stub.splitlines() if line.lstrip().startswith("def line(")
    )
    assert "key: str | int | None" in line_signature
    assert "instance_key: str | int | None" in line_signature
    assert "shared: bool" in line_signature

    assert "        instance_key: str | int | None = ...,\n" in stub
    assert "        shared: bool = ...,\n" in stub
