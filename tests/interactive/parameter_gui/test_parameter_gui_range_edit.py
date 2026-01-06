from grafix.interactive.parameter_gui.range_edit import apply_range_shift


def test_apply_range_shift_float_shift():
    ui_min, ui_max = apply_range_shift(
        kind="float",
        ui_min=0.0,
        ui_max=2.0,
        delta=0.25,
        mode="shift",
        sensitivity=1.0,
    )
    assert ui_min == 0.5
    assert ui_max == 2.5


def test_apply_range_shift_float_max_only():
    ui_min, ui_max = apply_range_shift(
        kind="float",
        ui_min=0.0,
        ui_max=2.0,
        delta=0.25,
        mode="max",
        sensitivity=1.0,
    )
    assert ui_min == 0.0
    assert ui_max == 2.5


def test_apply_range_shift_float_min_only():
    ui_min, ui_max = apply_range_shift(
        kind="float",
        ui_min=0.0,
        ui_max=2.0,
        delta=0.25,
        mode="min",
        sensitivity=1.0,
    )
    assert ui_min == 0.5
    assert ui_max == 2.0


def test_apply_range_shift_float_swaps_when_crossing():
    ui_min, ui_max = apply_range_shift(
        kind="float",
        ui_min=0.0,
        ui_max=1.0,
        delta=-2.0,
        mode="max",
        sensitivity=1.0,
    )
    assert ui_min == -1.0
    assert ui_max == 0.0


def test_apply_range_shift_int_uses_at_least_one_step():
    ui_min, ui_max = apply_range_shift(
        kind="int",
        ui_min=0,
        ui_max=10,
        delta=1.0 / 127.0,
        mode="shift",
        sensitivity=1.0,
    )
    assert ui_min == 1
    assert ui_max == 11


def test_apply_range_shift_int_swaps_when_crossing():
    ui_min, ui_max = apply_range_shift(
        kind="int",
        ui_min=0,
        ui_max=10,
        delta=-2.0,
        mode="max",
        sensitivity=1.0,
    )
    assert ui_min == -10
    assert ui_max == 0

