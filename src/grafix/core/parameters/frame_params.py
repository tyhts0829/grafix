# どこで: `src/grafix/core/parameters/frame_params.py`。
# 何を: フレーム内で観測・解決したパラメータを貯めるバッファを定義する。
# なぜ: ParamStore へのマージをフレーム境界でまとめ、スレッド安全に扱うため。

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .key import ParameterKey
from .meta import ParamMeta
from .effects import EffectStepTopology
from .source import ValueSource


@dataclass
class FrameParamRecord:
    """1 引数ぶんの観測・解決結果。"""

    key: ParameterKey
    base: Any
    meta: ParamMeta
    effective: Any | None = None
    source: ValueSource | None = None
    explicit: bool = True
    chain_id: str | None = None
    step_index: int | None = None


@dataclass
class FrameLabelRecord:
    """(op, site_id) に紐づくラベル設定の記録。"""

    op: str
    site_id: str
    label: str


@dataclass(frozen=True, slots=True)
class FrameEffectChainRecord:
    """1回のEffectBuilder適用で観測した完全なcode topology。"""

    chain_id: str
    steps: tuple[EffectStepTopology, ...]


class FrameParamsBuffer:
    """フレーム内のパラメータ観測を蓄積する単純なバッファ。"""

    def __init__(self) -> None:
        self._records: list[FrameParamRecord] = []
        self._labels: list[FrameLabelRecord] = []
        self._effect_chains: list[FrameEffectChainRecord] = []
        self._effect_chain_observation_complete = False

    def record(
        self,
        *,
        key: ParameterKey,
        base: Any,
        meta: ParamMeta,
        effective: Any | None = None,
        source: ValueSource | None = None,
        explicit: bool = True,
        chain_id: str | None = None,
        step_index: int | None = None,
    ) -> None:
        self._records.append(
            FrameParamRecord(
                key=key,
                base=base,
                meta=meta,
                effective=effective,
                source=source,
                explicit=bool(explicit),
                chain_id=chain_id,
                step_index=step_index,
            )
        )

    def set_label(self, *, op: str, site_id: str, label: str) -> None:
        self._labels.append(
            FrameLabelRecord(op=str(op), site_id=str(site_id), label=str(label))
        )

    def record_effect_chain(
        self,
        *,
        chain_id: str,
        steps: tuple[EffectStepTopology, ...],
    ) -> None:
        """effect chainのcode topologyを記録する。"""

        self._effect_chains.append(
            FrameEffectChainRecord(
                chain_id=str(chain_id),
                steps=tuple(steps),
            )
        )

    @property
    def records(self) -> list[FrameParamRecord]:
        return self._records

    @property
    def labels(self) -> list[FrameLabelRecord]:
        return self._labels

    @property
    def effect_chains(self) -> list[FrameEffectChainRecord]:
        return self._effect_chains

    @property
    def effect_chain_observation_complete(self) -> bool:
        """このbufferが一つの完全な成功evaluationを表すか返す。"""

        return bool(self._effect_chain_observation_complete)

    def complete_effect_chain_observation(self) -> None:
        """effect chainが0件の場合も含め、成功evaluationの完了を記録する。"""

        self._effect_chain_observation_complete = True

    def clear(self) -> None:
        self._records.clear()
        self._labels.clear()
        self._effect_chains.clear()
        self._effect_chain_observation_complete = False
