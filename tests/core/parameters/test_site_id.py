from pathlib import Path

import pytest

from grafix.core.parameters import key as key_module
from grafix.core.parameters.key import caller_site_id


def test_site_id_stable_same_expression():
    ids = [caller_site_id(skip=1) for _ in range(2)]
    assert ids[0] == ids[1]


def helper_other():
    return caller_site_id(skip=1)


def test_site_id_differs_on_other_function():
    a = caller_site_id(skip=1)
    c = helper_other()
    assert a != c


def test_site_id_does_not_persist_absolute_project_path() -> None:
    def get_site_id() -> str:
        return caller_site_id(skip=1)

    site_id = get_site_id()

    assert str(Path.cwd().resolve()) not in site_id
    assert "tests/core/parameters/test_site_id.py" in site_id


def test_explicit_key_discards_instruction_location() -> None:
    first = caller_site_id(skip=1, key="stable")
    second = caller_site_id(skip=1, key="stable")

    assert first == second
    assert first.endswith("|str:6:stable")


def test_explicit_key_rejects_unsupported_types() -> None:
    with pytest.raises(TypeError, match=r"str\|int\|None"):
        caller_site_id(skip=1, key=object())  # type: ignore[arg-type]


def test_instance_key_is_appended_to_semantic_key() -> None:
    site_id = caller_site_id(skip=1, key="petal", instance_key=7)

    assert site_id.endswith("|str:5:petal|instance:int:7")


def test_string_and_integer_semantic_keys_do_not_collide() -> None:
    integer = caller_site_id(skip=1, key=1)
    string = caller_site_id(skip=1, key="1")

    assert integer != string
    assert integer.endswith("|int:1")
    assert string.endswith("|str:1:1")


@pytest.mark.parametrize("value", [True, ""])
def test_semantic_keys_reject_bool_and_empty_string(value: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        caller_site_id(skip=1, key=value)  # type: ignore[arg-type]


def test_shared_semantic_site_rejects_instance_key() -> None:
    with pytest.raises(ValueError, match="instance_key"):
        caller_site_id(skip=1, key="petals", instance_key=0, shared=True)


def test_automatic_site_id_uses_location_cache() -> None:
    key_module._automatic_site_id.cache_clear()

    ids = [caller_site_id(skip=1) for _ in range(3)]
    info = key_module._automatic_site_id.cache_info()

    assert len(set(ids)) == 1
    assert info.misses == 1
    assert info.hits == 2
