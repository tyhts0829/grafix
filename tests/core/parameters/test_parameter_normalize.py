import pytest

from grafix.core.parameters import ParamMeta, normalize_input


@pytest.mark.parametrize(
    "value",
    ["1", "false", 0, 1],
)
def test_normalize_bool_rejects_non_bool(value):
    out, err = normalize_input(value, ParamMeta(kind="bool"))
    assert out is None
    assert err is not None


def test_normalize_int_and_error():
    out, err = normalize_input(10, ParamMeta(kind="int"))
    assert out == 10 and err is None
    out2, err2 = normalize_input(10.5, ParamMeta(kind="int"))
    assert out2 is None and err2 is not None


def test_normalize_float_and_error():
    out, err = normalize_input(0.25, ParamMeta(kind="float"))
    assert out == 0.25 and err is None
    out2, err2 = normalize_input("0.25", ParamMeta(kind="float"))
    assert out2 is None and err2 is not None


def test_normalize_str():
    out, err = normalize_input(123, ParamMeta(kind="str"))
    assert out is None
    assert err is not None


def test_normalize_font():
    out, err = normalize_input("SFNS.ttf", ParamMeta(kind="font"))
    assert out == "SFNS.ttf"
    assert err is None


def test_normalize_choice_rejects_unavailable_value():
    meta = ParamMeta(kind="choice", choices=["red", "green"])
    out, err = normalize_input("blue", meta)
    assert out is None
    assert err is not None


def test_normalize_vec3():
    out, err = normalize_input((1, 2.5, 3), ParamMeta(kind="vec3"))
    assert out == (1.0, 2.5, 3.0)
    assert err is None
    out2, err2 = normalize_input([1.0, 2.0, 3.0], ParamMeta(kind="vec3"))
    assert out2 is None and err2 is not None


def test_normalize_rgb():
    out, err = normalize_input((255, 0, 10), ParamMeta(kind="rgb"))
    assert out == (255, 0, 10)
    assert err is None
    out2, err2 = normalize_input((300, -5, 10), ParamMeta(kind="rgb"))
    assert out2 is None and err2 is not None


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_normalize_float_rejects_nonfinite(value: float) -> None:
    out, err = normalize_input(value, ParamMeta(kind="float"))
    assert out is None
    assert err is not None
