from __future__ import annotations

from pathlib import Path

import pytest

from grafix.core.parameters.autosave import ParamStoreAutosave
from grafix.core.parameters.frame_params import FrameParamRecord
from grafix.core.parameters.key import ParameterKey
from grafix.core.parameters.merge_ops import merge_frame_params
from grafix.core.parameters.meta import ParamMeta
from grafix.core.parameters.persistence import load_param_store
from grafix.core.parameters.store import ParamStore
from grafix.core.parameters.ui_ops import update_state_from_ui


def _touch_with_parameter(store: ParamStore, value: float = 0.5) -> ParameterKey:
    key = ParameterKey(op="line", site_id="site-1", arg="length")
    merge_frame_params(
        store,
        [
            FrameParamRecord(
                key=key,
                base=value,
                meta=ParamMeta(kind="float", ui_min=0.0, ui_max=1.0),
                effective=value,
                source="code",
                explicit=False,
            )
        ],
    )
    return key


def test_autosave_waits_until_changes_settle(tmp_path: Path) -> None:
    now = [0.0]
    calls: list[tuple[int, Path]] = []
    store = ParamStore()

    def save(current: ParamStore, path: Path) -> None:
        calls.append((current.revision, path))

    autosave = ParamStoreAutosave(
        store,
        tmp_path / "store.json",
        debounce_seconds=1.0,
        clock=lambda: now[0],
        save=save,
    )
    _touch_with_parameter(store)

    assert autosave.tick() is False
    now[0] = 0.9
    assert autosave.tick() is False
    store._collapsed_headers_ref().add("primitive:line:site-1")
    store._touch()
    assert autosave.tick() is False
    now[0] = 1.89
    assert autosave.tick() is False
    now[0] = 1.91
    assert autosave.tick() is True

    assert calls == [(store.revision, tmp_path / "store.json")]
    assert autosave.dirty is False
    assert autosave.last_saved_revision == store.revision
    assert autosave.tick() is False


def test_autosave_flushes_at_max_interval_during_continuous_revisions(
    tmp_path: Path,
) -> None:
    now = [0.0]
    calls: list[int] = []
    store = ParamStore()

    autosave = ParamStoreAutosave(
        store,
        tmp_path / "store.json",
        debounce_seconds=1.0,
        max_interval_seconds=2.0,
        clock=lambda: now[0],
        save=lambda current, _path: calls.append(current.revision),
    )
    _touch_with_parameter(store)
    assert autosave.tick() is False

    # debounce より短い間隔で変更が続いても、最初の dirty
    # 観測から max_interval で recovery を確定する。
    for index, current_time in enumerate((0.5, 1.0, 1.5), start=1):
        now[0] = current_time
        store._collapsed_headers_ref().add(f"continuous:{index}")
        store._touch()
        assert autosave.tick() is False

    now[0] = 2.0
    store._collapsed_headers_ref().add("continuous:final")
    store._touch()
    assert autosave.tick() is True
    assert calls == [store.revision]
    assert autosave.dirty is False


def test_autosave_waits_for_release_debounce_while_edit_is_active(
    tmp_path: Path,
) -> None:
    now = [0.0]
    store = ParamStore()
    key = _touch_with_parameter(store)
    meta = store.get_meta(key)
    assert meta is not None
    calls: list[int] = []
    autosave = ParamStoreAutosave(
        store,
        tmp_path / "store.json",
        debounce_seconds=0.5,
        max_interval_seconds=1.0,
        clock=lambda: now[0],
        save=lambda current, _path: calls.append(current.revision),
    )

    update_state_from_ui(store, key, 0.4, meta=meta)
    assert autosave.tick(suspended=True) is False
    now[0] = 5.0
    update_state_from_ui(store, key, 0.5, meta=meta)
    # max interval を越えても active edit 中は同期 save しない。
    assert autosave.tick(suspended=True) is False
    assert calls == []

    # release frame から debounce を開始し直す。
    assert autosave.tick(suspended=False) is False
    now[0] = 5.49
    assert autosave.tick() is False
    now[0] = 5.5
    assert autosave.tick() is True
    assert calls == [store.revision]


def test_autosave_flush_uses_existing_atomic_persistence(tmp_path: Path) -> None:
    store = ParamStore()
    key = _touch_with_parameter(store, 0.75)
    path = tmp_path / "nested" / "store.json"
    autosave = ParamStoreAutosave(store, path)

    # 生成時点の revision は clean。その後の変更だけを保存する。
    store._collapsed_headers_ref().add("primitive:line:site-1")
    store._touch()
    assert autosave.flush() is True
    assert path.exists()
    loaded = load_param_store(path)
    assert loaded.get_state(key) is not None
    assert loaded._collapsed_headers_ref() == {"primitive:line:site-1"}
    assert autosave.flush() is False


def test_autosave_failure_is_retried_after_debounce(tmp_path: Path) -> None:
    now = [0.0]
    store = ParamStore()
    attempts = [0]

    def flaky_save(_store: ParamStore, _path: Path) -> None:
        attempts[0] += 1
        if attempts[0] == 1:
            raise OSError("disk busy")

    autosave = ParamStoreAutosave(
        store,
        tmp_path / "store.json",
        debounce_seconds=1.0,
        clock=lambda: now[0],
        save=flaky_save,
    )
    _touch_with_parameter(store)
    autosave.tick()
    now[0] = 1.0
    with pytest.raises(OSError, match="disk busy"):
        autosave.tick()
    assert autosave.status == "failed"
    assert autosave.last_error == "OSError: disk busy"

    now[0] = 1.5
    assert autosave.tick() is False
    now[0] = 2.0
    assert autosave.tick() is True
    assert attempts[0] == 2
    assert autosave.dirty is False
    assert autosave.status == "clean"
    assert autosave.last_error is None


def test_mark_clean_acknowledges_an_external_save(tmp_path: Path) -> None:
    store = ParamStore()
    autosave = ParamStoreAutosave(store, tmp_path / "store.json")
    _touch_with_parameter(store)
    assert autosave.dirty is True

    autosave.mark_clean()

    assert autosave.dirty is False
    assert autosave.flush() is False
    assert autosave.status == "clean"


def test_autosave_exposes_dirty_and_saving_states(tmp_path: Path) -> None:
    store = ParamStore()
    observed_statuses: list[str] = []
    autosave: ParamStoreAutosave

    def save(_store: ParamStore, _path: Path) -> None:
        observed_statuses.append(autosave.status)

    autosave = ParamStoreAutosave(
        store,
        tmp_path / "store.json",
        debounce_seconds=1.0,
        save=save,
    )
    _touch_with_parameter(store)

    assert autosave.tick(now=-1.0) is False
    assert autosave.status == "dirty"
    assert autosave.tick(now=0.0) is True
    assert observed_statuses == ["saving"]
    assert autosave.status == "clean"


def test_autosave_validates_max_interval(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="max_interval_seconds"):
        ParamStoreAutosave(
            ParamStore(),
            tmp_path / "store.json",
            max_interval_seconds=0.0,
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_autosave_rejects_non_finite_debounce(
    tmp_path: Path,
    value: float,
) -> None:
    with pytest.raises(ValueError, match="debounce_seconds"):
        ParamStoreAutosave(
            ParamStore(),
            tmp_path / "store.json",
            debounce_seconds=value,
        )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_autosave_rejects_non_finite_max_interval(
    tmp_path: Path,
    value: float,
) -> None:
    with pytest.raises(ValueError, match="max_interval_seconds"):
        ParamStoreAutosave(
            ParamStore(),
            tmp_path / "store.json",
            max_interval_seconds=value,
        )
