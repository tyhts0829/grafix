"""ポリライン（線/面）を条件で間引き、選択されたものだけを残す effect。"""

from __future__ import annotations

import numpy as np

from grafix.core.operation_authoring import effect
from grafix.core.parameters.meta import ParamMeta
from grafix.core.realized_geometry import GeomTuple
from grafix.core.geometry_kernels.packed import empty_packed_geometry

# 高速 path の float64 中間配列・bool mask を 1 line あたり 192 bytes と
# 保守的に見積もっても、追加 peak が 8 MiB 未満に収まる上限にする。
_TWO_POINT_FAST_PATH_MIN_LINES = 64
_TWO_POINT_FAST_PATH_MAX_LINES = 32_768

drop_meta = {
    "interval": ParamMeta(
        kind="int",
        ui_min=0,
        ui_max=100,
        description="線または面をインデックス順に一定間隔で対象にする。1 以上で有効、0 で無効。",
    ),
    "index_offset": ParamMeta(
        kind="int",
        ui_min=0,
        ui_max=100,
        description="インデックスによる間引き判定の開始位置をずらす。",
    ),
    "min_length": ParamMeta(
        kind="float",
        ui_min=-1.0,
        ui_max=200.0,
        description="0 以上のとき、この長さ以下の線または面を対象にする。負値で無効。",
    ),
    "max_length": ParamMeta(
        kind="float",
        ui_min=-1.0,
        ui_max=200.0,
        description="0 以上のとき、この長さ以上の線または面を対象にする。負値で無効。",
    ),
    "probability_base": ParamMeta(
        kind="vec3",
        ui_min=0.0,
        ui_max=1.0,
        description="バウンディングボックス中心での選択確率を軸ごとに指定する。",
    ),
    "probability_slope": ParamMeta(
        kind="vec3",
        ui_min=-1.0,
        ui_max=1.0,
        description="正規化した各軸位置に対する選択確率の勾配。",
    ),
    "by": ParamMeta(
        kind="choice",
        choices=("line", "face"),
        description="選択と除去をポリライン単位または閉じた面単位で行う。",
    ),
    "keep_mode": ParamMeta(
        kind="choice",
        choices=("drop", "keep"),
        description="条件に一致した要素を除去するか、一致した要素だけ残すか選ぶ。",
    ),
    "seed": ParamMeta(
        kind="int",
        ui_min=0,
        ui_max=2**31 - 1,
        description="確率による選択結果を再現可能にする乱数シード。",
    ),
}


def _compute_polyline_lengths(
    coords: np.ndarray, offsets: np.ndarray, *, close: bool
) -> np.ndarray:
    """各ポリラインの長さを返す。"""
    n_lines = max(0, int(offsets.size) - 1)
    lengths = np.zeros((n_lines,), dtype=np.float64)
    for i in range(n_lines):
        start = int(offsets[i])
        end = int(offsets[i + 1])
        if end - start <= 1:
            lengths[i] = 0.0
            continue
        v = coords[start:end].astype(np.float64, copy=False)
        diff = v[1:] - v[:-1]
        seg_len = np.sqrt(np.sum(diff * diff, axis=1))
        L = float(seg_len.sum())
        if close and v.shape[0] >= 3:
            d = v[0] - v[-1]
            L += float(np.sqrt(np.dot(d, d)))
        lengths[i] = L
    return lengths


def _has_uniform_two_point_lines(
    coords: np.ndarray,
    offsets: np.ndarray,
    *,
    n_lines: int,
) -> bool:
    """標準 packed geometry が 2 点 line だけで構成されるかを返す。"""

    if (
        n_lines < _TWO_POINT_FAST_PATH_MIN_LINES
        or n_lines > _TWO_POINT_FAST_PATH_MAX_LINES
        or coords.shape != (2 * n_lines, 3)
    ):
        return False
    expected_offsets = np.arange(0, 2 * n_lines + 1, 2, dtype=np.int32)
    return bool(np.array_equal(offsets, expected_offsets))


def _pack_uniform_two_point_lines(
    coords: np.ndarray,
    keep_mask: np.ndarray,
) -> GeomTuple:
    """2 点 line の選択結果を入力順の exact-size 配列へ詰める。"""

    kept_count = int(np.count_nonzero(keep_mask))
    if kept_count <= 0:
        return empty_packed_geometry()

    point_mask = np.repeat(keep_mask, 2)
    out_coords = coords[point_mask]
    out_offsets = np.arange(0, 2 * kept_count + 1, 2, dtype=np.int32)
    return out_coords, out_offsets


@effect(meta=drop_meta)
def drop(
    g: GeomTuple,
    *,
    interval: int = 0,
    index_offset: int = 0,
    min_length: float = -1.0,
    max_length: float = -1.0,
    probability_base: tuple[float, float, float] = (0.0, 0.0, 0.0),
    probability_slope: tuple[float, float, float] = (0.0, 0.0, 0.0),
    by: str = "line",  # "line" | "face"
    seed: int = 0,
    keep_mode: str = "drop",  # "drop" | "keep"
) -> GeomTuple:
    """線や面を条件で間引く。

    Parameters
    ----------
    g : tuple[np.ndarray, np.ndarray]
        入力実体ジオメトリ（coords, offsets）。
    interval : int, default 0
        線インデックスに対する間引きステップ。1 以上で有効、0 で無効。
    index_offset : int, default 0
        interval 判定の開始オフセット。有効な interval に対して剰余へ正規化する。
    min_length : float, default -1.0
        この長さ以下の線を対象とする。0 以上で有効、0 未満で無効。
    max_length : float, default -1.0
        この長さ以上の線を対象とする。0 以上で有効、0 未満で無効。
    probability_base : tuple[float, float, float], default (0.0, 0.0, 0.0)
        ジオメトリ bbox の中心（正規化座標 t=0）における drop 確率（軸別）。
        各成分は 0.0〜1.0。有限な範囲外の値はクランプする。
    probability_slope : tuple[float, float, float], default (0.0, 0.0, 0.0)
        正規化座標 t∈[-1,+1] に対する確率勾配（軸別）。

        軸別確率を `p_axis = clamp(base_axis + slope_axis * t_axis, 0..1)` として作り、
        `p_eff = 1 - (1-p_x)(1-p_y)(1-p_z)`（OR のイメージ）で合成する。
    by : str, default "line"
        判定単位。

        "line":
            ポリラインごとに判定し、`offsets` 単位で drop/keep する。
            長さは開曲線としての線長（最後→最初は含めない）。
        "face":
            頂点数が 3 以上のポリラインを face ring とみなし、face 単位で drop/keep する。
            長さは閉曲線としての周長（最後→最初を含む）。
            頂点数が 2 以下のポリラインは常に残す（face 判定の対象外）。
    seed : int, default 0
        probability_* 使用時の乱数シード。同じ引数なら決定的に同じ線が選ばれる。
    keep_mode : str, default "drop"
        "drop": 条件に一致した線を捨てる。"keep": 条件に一致した線だけを残す。

    Returns
    -------
    tuple[np.ndarray, np.ndarray]
        条件適用後の実体ジオメトリ（coords, offsets）。

    Raises
    ------
    ValueError
        `interval` または `seed` が負の場合。
    """
    if interval < 0:
        raise ValueError("drop: interval は 0 以上である必要がある")

    eff_interval = interval if interval >= 1 else None
    effective_index_offset = index_offset
    if eff_interval is not None:
        effective_index_offset %= eff_interval
    if seed < 0:
        raise ValueError("drop: seed は 0 以上である必要がある")

    use_min = min_length >= 0.0
    use_max = max_length >= 0.0

    base_px, base_py, base_pz = probability_base

    if base_px < 0.0:
        base_px = 0.0
    elif base_px > 1.0:
        base_px = 1.0
    if base_py < 0.0:
        base_py = 0.0
    elif base_py > 1.0:
        base_py = 1.0
    if base_pz < 0.0:
        base_pz = 0.0
    elif base_pz > 1.0:
        base_pz = 1.0

    slope_x, slope_y, slope_z = probability_slope

    prob_enabled = (
        (base_px != 0.0)
        or (base_py != 0.0)
        or (base_pz != 0.0)
        or (slope_x != 0.0)
        or (slope_y != 0.0)
        or (slope_z != 0.0)
    )

    coords, offsets = g
    if coords.shape[0] == 0:
        return coords, offsets

    n_lines = int(offsets.size) - 1
    if n_lines <= 0:
        return coords, offsets

    if eff_interval is None and not use_min and not use_max and not prob_enabled:
        return coords, offsets

    rng = None
    if prob_enabled:
        rng = np.random.default_rng(seed)

    center = np.zeros((3,), dtype=np.float64)
    inv_extent = np.zeros((3,), dtype=np.float64)
    if prob_enabled:
        min_v = coords.min(axis=0).astype(np.float64, copy=False)
        max_v = coords.max(axis=0).astype(np.float64, copy=False)
        center = (min_v + max_v) * 0.5
        extent = (max_v - min_v) * 0.5
        for k in range(3):
            e = float(extent[k])
            inv_extent[k] = 0.0 if e < 1e-9 else 1.0 / e

    uniform_two_point_lines = by == "line" and _has_uniform_two_point_lines(
        coords,
        offsets,
        n_lines=n_lines,
    )
    if uniform_two_point_lines:
        selected = np.zeros((n_lines,), dtype=bool)

        if eff_interval is not None and effective_index_offset < n_lines:
            selected[effective_index_offset::eff_interval] = True

        points = coords.reshape(n_lines, 2, 3)
        if use_min or use_max:
            delta = np.subtract(
                points[:, 1, :],
                points[:, 0, :],
                dtype=np.float64,
            )
            two_point_lengths = np.sqrt(np.sum(delta * delta, axis=1))
            if use_min:
                selected |= two_point_lengths <= min_length
            if use_max:
                selected |= two_point_lengths >= max_length

        if rng is not None:
            centroids = np.add(
                points[:, 0, :],
                points[:, 1, :],
                dtype=np.float64,
            )
            centroids *= 0.5

            tx = (centroids[:, 0] - center[0]) * inv_extent[0]
            ty = (centroids[:, 1] - center[1]) * inv_extent[1]
            tz = (centroids[:, 2] - center[2]) * inv_extent[2]
            np.clip(tx, -1.0, 1.0, out=tx)
            np.clip(ty, -1.0, 1.0, out=ty)
            np.clip(tz, -1.0, 1.0, out=tz)

            p_x = base_px + slope_x * tx
            p_y = base_py + slope_y * ty
            p_z = base_pz + slope_z * tz
            np.clip(p_x, 0.0, 1.0, out=p_x)
            np.clip(p_y, 0.0, 1.0, out=p_y)
            np.clip(p_z, 0.0, 1.0, out=p_z)

            p_eff = 1.0 - (1.0 - p_x) * (1.0 - p_y) * (1.0 - p_z)
            selected |= rng.random(n_lines) < p_eff

        keep_mask = ~selected if keep_mode == "drop" else selected
        return _pack_uniform_two_point_lines(coords, keep_mask)

    def _p_eff_for_range(start: int, end: int) -> float:
        if end <= start:
            p_x = base_px
            p_y = base_py
            p_z = base_pz
        else:
            c = coords[start:end].mean(axis=0, dtype=np.float64)
            t = (c - center) * inv_extent
            tx = float(t[0])
            ty = float(t[1])
            tz = float(t[2])
            if tx < -1.0:
                tx = -1.0
            elif tx > 1.0:
                tx = 1.0
            if ty < -1.0:
                ty = -1.0
            elif ty > 1.0:
                ty = 1.0
            if tz < -1.0:
                tz = -1.0
            elif tz > 1.0:
                tz = 1.0

            p_x = base_px + slope_x * tx
            p_y = base_py + slope_y * ty
            p_z = base_pz + slope_z * tz

            if p_x < 0.0:
                p_x = 0.0
            elif p_x > 1.0:
                p_x = 1.0
            if p_y < 0.0:
                p_y = 0.0
            elif p_y > 1.0:
                p_y = 1.0
            if p_z < 0.0:
                p_z = 0.0
            elif p_z > 1.0:
                p_z = 1.0

        return 1.0 - (1.0 - p_x) * (1.0 - p_y) * (1.0 - p_z)

    if by == "line":
        lengths: np.ndarray | None = None
        if use_min or use_max:
            lengths = _compute_polyline_lengths(coords, offsets, close=False)

        keep_mask = np.zeros((n_lines,), dtype=bool)
        for i in range(n_lines):
            cond = False

            if eff_interval is not None:
                cond = cond or (((i - effective_index_offset) % eff_interval) == 0)

            if lengths is not None:
                L = float(lengths[i])
                if use_min and L <= min_length:
                    cond = True
                if use_max and L >= max_length:
                    cond = True

            # 他条件の有無で確率判定が変わらないよう、乱数は全行で消費する。
            if rng is not None:
                start = int(offsets[i])
                end = int(offsets[i + 1])
                p_eff = _p_eff_for_range(start, end)
                if float(rng.random()) < p_eff:
                    cond = True

            if keep_mode == "drop":
                keep_mask[i] = not cond
            else:
                keep_mask[i] = cond

    else:
        face_count = 0
        for i in range(n_lines):
            start = int(offsets[i])
            end = int(offsets[i + 1])
            if end - start >= 3:
                face_count += 1
        if face_count <= 0:
            return coords, offsets

        lengths = None
        if use_min or use_max:
            lengths = _compute_polyline_lengths(coords, offsets, close=True)

        keep_mask = np.ones((n_lines,), dtype=bool)
        face_index = 0
        for i in range(n_lines):
            start = int(offsets[i])
            end = int(offsets[i + 1])
            if end - start < 3:
                continue

            cond = False
            if eff_interval is not None:
                cond = cond or (
                    ((face_index - effective_index_offset) % eff_interval) == 0
                )

            if lengths is not None:
                L = float(lengths[i])
                if use_min and L <= min_length:
                    cond = True
                if use_max and L >= max_length:
                    cond = True

            if rng is not None:
                p_eff = _p_eff_for_range(start, end)
                if float(rng.random()) < p_eff:
                    cond = True

            if keep_mode == "drop":
                keep_mask[i] = not cond
            else:
                keep_mask[i] = cond

            face_index += 1

    if not np.any(keep_mask):
        return empty_packed_geometry()

    out_coords_list: list[np.ndarray] = []
    out_offsets_list: list[int] = [0]
    cursor = 0

    for i in range(n_lines):
        if not keep_mask[i]:
            continue
        start = int(offsets[i])
        end = int(offsets[i + 1])
        if end <= start:
            continue
        seg = coords[start:end]
        out_coords_list.append(seg)
        cursor += int(seg.shape[0])
        out_offsets_list.append(cursor)

    if len(out_offsets_list) == 1:
        return empty_packed_geometry()

    out_coords = np.concatenate(out_coords_list, axis=0)
    out_offsets = np.asarray(out_offsets_list, dtype=np.int32)
    return out_coords, out_offsets
