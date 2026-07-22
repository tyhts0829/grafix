"""
どこで: `src/grafix/api/runner.py`。公開 API のランナー実装。
何を: pyglet + ModernGL を使い、`draw(t)` が返す Geometry/Layer/シーンをウィンドウに描画するランナーを提供する。
なぜ: `main.py` を実行して実際に線をプレビューできる経路を用意するため。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

import pyglet

from grafix.core.authoring_definitions import AuthoringDefinitionsSnapshot
from grafix.core.authoring_loader import authoring_definitions_for_draw
from grafix.core.lifecycle import CleanupErrors
from grafix.core.runtime_config import (
    RuntimeConfig,
    RuntimeConfigFallback,
    runtime_config_with_fallback,
)
from grafix.export.output_paths import default_param_store_path, output_path_for_draw
from grafix.core.runtime_limits import (
    DEFAULT_RUNTIME_LIMIT_PROFILES,
    RuntimeLimitProfiles,
)
from grafix.core.scene import SceneItem
from grafix.core.value_validation import (
    exact_bool,
    exact_integer,
    exact_string_choice,
    finite_real,
)
from grafix.interactive.midi.factory import create_midi_session
from grafix.interactive.midi import MidiSession
from grafix.api.render import RenderOptions
from grafix.interactive.runtime.draw_window_system import DrawWindowSystem
from grafix.interactive.diagnostics import DiagnosticAction, DiagnosticEvent
from grafix.interactive.runtime.parameter_session import (
    ParameterSession,
    known_operation_schema_snapshot,
)
from grafix.interactive.runtime.window_loop import MultiWindowLoop, WindowTask
from grafix.interactive.runtime.workspace_window_controller import (
    WorkspaceWindowController,
)

_logger = logging.getLogger(__name__)


def _run_cleanup_steps(
    steps: list[tuple[str, Callable[[], None]]],
    *,
    initial_error: BaseException | None = None,
) -> None:
    """shutdown step を全て試し、最初の例外を最後に再送出する。"""

    def report_secondary(label: str) -> None:
        _logger.exception(
            "Shutdown step failed after an earlier error: %s",
            label,
        )

    errors = CleanupErrors(
        initial_error=initial_error,
        report_secondary=report_secondary,
    )
    for label, step in steps:
        errors.attempt(step, label)
    errors.raise_if_any()


def _publish_runtime_config_fallback(
    monitor: Any,
    fallback: RuntimeConfigFallback,
) -> DiagnosticEvent:
    """interactive config fallbackを共通DiagnosticCenterへ常設する。"""

    actions = [DiagnosticAction("copy", "Copy details")]
    if fallback.source is not None:
        actions.append(DiagnosticAction("open", "Open config"))
    return monitor.publish_diagnostic(
        DiagnosticEvent(
            category="config",
            severity="error",
            summary="Runtime config is invalid; using packaged defaults",
            details=fallback.details,
            source=None if fallback.source is None else str(fallback.source),
            actions=tuple(actions),
            dedupe_key=f"config-fallback:{fallback.summary}",
        )
    )


def run(
    draw: Callable[[float], SceneItem],
    *,
    config_path: str | Path | None = None,
    config: RuntimeConfig | None = None,
    config_fallback: RuntimeConfigFallback | None = None,
    run_id: str | None = None,
    background_color: tuple[float, float, float] = (1.0, 1.0, 1.0),
    line_thickness: float = 0.001,
    line_color: tuple[float, float, float] = (0.0, 0.0, 0.0),
    render_scale: float = 1.0,
    canvas_size: tuple[int, int] = (800, 800),
    parameter_gui: bool = True,
    parameter_persistence: bool = True,
    midi_port_name: str | None = "auto",
    midi_mode: str = "7bit",
    n_worker: int = 1,
    evaluation_timeout: float | None = 5.0,
    fps: float = 60.0,
    seed: int | None = None,
    runtime_limit_profiles: RuntimeLimitProfiles = DEFAULT_RUNTIME_LIMIT_PROFILES,
) -> None:
    """pyglet ウィンドウを生成し `draw(t)` のシーンをリアルタイム描画する。

    Parameters
    ----------
    draw : Callable[[float], SceneItem]
        フレーム経過秒 t を受け取り Geometry / Layer / それらの列を返すコールバック。
    config_path : str | Path | None
        設定ファイル（config.yaml）のパス。指定した場合は探索より優先する。
    config : RuntimeConfig | None
        呼び出し元で確定済みの設定。``config_path`` との同時指定はできない。
    config_fallback : RuntimeConfigFallback | None
        ``config`` が不正なユーザー設定から packaged default へ退避した結果なら、
        その診断情報を渡す。``config`` との併用だけを許可する。
    run_id : str | None
        作品スクリプトの同一性を表す識別子。出力ファイル名の接尾辞として使う。
        interactive capture は同名の完成品を上書きせず、必要に応じて連番を付ける。
    background_color : tuple[float, float, float]
        背景色 RGB。alpha は 1.0 固定。既定は白。
    line_thickness : float
        Layer.thickness 未指定時の線幅。キャンバス短辺に対する比率で、既定
        ``0.001`` は短辺の 0.1% に相当する。
    line_color : tuple[float, float, float]
        線色 RGB。既定は黒。
    render_scale : float
        キャンバス寸法に掛けるピクセル倍率。高精細プレビュー用。
    canvas_size : tuple[int, int]
        キャンバス寸法（任意単位）。投影行列生成とウィンドウサイズ決定に使用。
    parameter_gui : bool
        True の場合、別ウィンドウで Parameter GUI を起動し、ParamStore を編集できるようにする。
    parameter_persistence : bool
        True の場合、ParamStore を JSON 保存し、次回起動時に復元する。
        保存先は `output/param_store/` 配下で sketch_dir の構造をミラーし、run_id があればファイル名に付く。
        GUI 変更は短い debounce 後に atomic autosave し、終了時にも未保存分を確定する。
    midi_port_name : str | None
        MIDI 入力ポート名。
        - `"auto"`: 利用可能な入力ポートがあれば 1 つ目へ自動接続する（既定）。
          config.yaml に `midi.inputs`（接続優先リスト）があれば、その順に接続を試す。
          優先リストがある場合、どの候補も見つからなければ接続しない。
          接続できない場合でも、前回保存した CC スナップショットを凍結して使う（描画が変わらない）。
        - `"TX-6 Bluetooth"` のような文字列: 指定ポートへ接続する。
        - None: MIDI を無効化する。
    midi_mode : str
        MIDI CC の解釈モード。`"7bit"` または `"14bit"`。
    n_worker : int
        `draw(t)` を multiprocessing で実行する background worker 数。
        既定の 1 は UI event loop を塞がない 1 worker 非同期評価。`>=1` は
        spawn + Queue（pickle）で非同期化し、`0` の場合だけ main process で同期実行する。
        非同期評価では `draw` をモジュールトップレベルに定義し、起動側に
        `if __name__ == "__main__":` guard を置く必要がある。
    evaluation_timeout : float | None
        background worker の 1 回の `draw(t)` を待つ秒数。超過時は直近の成功表示を
        保ったまま worker を再起動する。`None` の場合は timeout を無効にする。
    fps : float
        目標フレームレート。`<=0` の場合はフレーム末尾で sleep せず、可能な限り速く回す。
        録画機能（V キー）は fps > 0 が必要。
    seed : int or None
        capture manifest に記録する作品 seed。乱数 global state は変更しない。
    runtime_limit_profiles : RuntimeLimitProfiles
        preview/final ごとの per-operation、scene aggregate、CPU/GPU cache、
        capture queue 上限。

    Returns
    -------
    None
        preview ウィンドウを閉じると制御を返す。
        Inspector の close はウィンドウを hide し、Cmd/Ctrl+I で再表示できる。
    """

    gui_enabled = exact_bool(parameter_gui, name="parameter_gui")
    persistence_enabled = exact_bool(
        parameter_persistence,
        name="parameter_persistence",
    )
    midi_mode_value = exact_string_choice(
        midi_mode,
        name="midi_mode",
        choices=("7bit", "14bit"),
    )
    worker_count = exact_integer(n_worker, name="n_worker", minimum=0)
    timeout = (
        None
        if evaluation_timeout is None
        else finite_real(
            evaluation_timeout,
            name="evaluation_timeout",
            minimum=0.0,
            minimum_inclusive=False,
        )
    )
    frame_rate = finite_real(fps, name="fps")
    preview_scale = finite_real(
        render_scale,
        name="render_scale",
        minimum=0.0,
        minimum_inclusive=False,
    )
    capture_seed = None if seed is None else exact_integer(seed, name="seed")
    if type(runtime_limit_profiles) is not RuntimeLimitProfiles:
        raise TypeError("runtime_limit_profiles は RuntimeLimitProfiles である必要があります")
    profiles = runtime_limit_profiles

    from grafix.interactive.runtime.source_reload import current_source_reload

    source_reload = current_source_reload()
    if config is not None and not isinstance(config, RuntimeConfig):
        raise TypeError("config は RuntimeConfig または None である必要があります")
    if config_fallback is not None and not isinstance(
        config_fallback,
        RuntimeConfigFallback,
    ):
        raise TypeError("config_fallback は RuntimeConfigFallback または None である必要があります")
    if config is not None and config_path is not None:
        raise ValueError("config と config_path は同時に指定できません")
    if config is None and config_fallback is not None:
        raise ValueError("config_fallback は config と同時に指定する必要があります")
    if config is None:
        cfg, config_fallback = runtime_config_with_fallback(config_path)
    else:
        cfg = config
    session_definitions = authoring_definitions_for_draw(
        draw,
        config=cfg,
    )
    if config_fallback is not None and not gui_enabled:
        _logger.error(
            "Runtime config invalid; using packaged defaults: %s\n%s",
            config_fallback.summary,
            config_fallback.details,
        )

    # pyglet の Window 作成前にオプションを設定する。
    # （vsync はウィンドウ作成時に参照される想定のため、ここで固定しておく）
    # True にすると Parameter GUI のクリックやドラッグが抜ける事がある。
    pyglet.options["vsync"] = False

    # headless/export と同じ検証済み描画契約を interactive preview でも使う。
    options = RenderOptions(
        background_color=background_color,
        line_thickness=line_thickness,
        line_color=line_color,
        canvas_size=canvas_size,
    )
    # パラメータは「描画」と「GUI」で共有する。
    # GUI で値を変えると、次フレーム以降の parameter_context 参照に反映される。
    default_store_path = default_param_store_path(draw, run_id=run_id, config=cfg)

    workspace_path = output_path_for_draw(
        kind="workspace",
        ext="json",
        draw=draw,
        run_id=run_id,
        config=cfg,
    )
    preview_width = max(1, int(round(options.canvas_size[0] * preview_scale)))
    preview_height = max(1, int(round(options.canvas_size[1] * preview_scale)))
    workspace_windows = WorkspaceWindowController.load(
        path=workspace_path,
        preview_size=(preview_width, preview_height),
        inspector_size=cfg.parameter_gui_window_size,
        preferred_preview_position=cfg.window_pos_draw,
        preferred_inspector_position=cfg.window_pos_parameter_gui,
    )

    param_store_path = default_store_path if persistence_enabled else None
    parameter_session = ParameterSession(
        primary_path=param_store_path,
        gui_enabled=gui_enabled,
        known_operations=known_operation_schema_snapshot(
            session_definitions.operations,
            session_definitions.presets,
        ),
    )
    param_store = parameter_session.store
    param_history = parameter_session.history
    param_snapshot_slots = parameter_session.snapshot_slots
    param_autosave = parameter_session.autosave
    parameter_schema_definitions = session_definitions

    def adopt_parameter_schema(
        definitions: AuthoringDefinitionsSnapshot,
    ) -> None:
        """採用 generation が変わったときだけ終了時 schema を射影し直す。"""

        nonlocal parameter_schema_definitions
        if definitions is parameter_schema_definitions:
            return
        projected = known_operation_schema_snapshot(
            definitions.operations,
            definitions.presets,
        )
        parameter_session.replace_known_operations(projected)
        parameter_schema_definitions = definitions

    # resource acquisition も loop と同じ保護範囲に入れる。GUI constructor や
    # window 配置で失敗しても、それまでに取得した MIDI/window/worker を解放する。
    closers: list[Callable[[], None]] = []
    unowned_midi_session: MidiSession | None = None
    draw_window: DrawWindowSystem | None = None
    monitor: Any | None = None
    session_completed_cleanly = False
    session_error: BaseException | None = None
    try:
        midi_path = output_path_for_draw(
            kind="midi",
            ext="json",
            draw=draw,
            run_id=run_id,
            config=cfg,
        )
        midi_profile_name = midi_path.stem
        midi_save_dir = midi_path.parent

        if gui_enabled:
            from grafix.interactive.runtime.monitor import RuntimeMonitor

            monitor = RuntimeMonitor()

        midi_session = create_midi_session(
            port_name=midi_port_name,
            mode=midi_mode_value,
            profile_name=midi_profile_name,
            save_dir=midi_save_dir,
            snapshot_path=midi_path,
            priority_inputs=cfg.midi_inputs,
            diagnostics=None if monitor is None else monitor.diagnostic_center,
        )
        unowned_midi_session = midi_session

        def close_unowned_midi() -> None:
            nonlocal unowned_midi_session
            session = unowned_midi_session
            unowned_midi_session = None
            if session is not None:
                session.close()

        # DrawWindowSystem が完成するまでは runner が MIDI を所有する。
        closers.append(close_unowned_midi)

        workspace_diagnostic = workspace_windows.diagnostic
        if workspace_diagnostic is not None:
            if monitor is not None:
                monitor.publish_diagnostic(workspace_diagnostic)
            else:
                _logger.warning(
                    "%s: %s",
                    workspace_diagnostic.summary,
                    workspace_diagnostic.details,
                )

        if monitor is not None:
            parameter_session.install_diagnostic_actions(monitor)
            center = monitor.diagnostic_center

            if config_fallback is not None:
                _publish_runtime_config_fallback(monitor, config_fallback)

            def retry_midi(event: DiagnosticEvent) -> None:
                midi_session.retry_for_diagnostic(event)

            def clear_frozen_midi(event: DiagnosticEvent) -> None:
                midi_session.discard_for_diagnostic(event)

            center.register_action("retry", retry_midi, category="midi")
            center.register_action("discard", clear_frozen_midi, category="midi")

        # --- サブシステムの組み立て ---
        # 描画ウィンドウは常に有効（メイン描画）。constructor が戻った直後に
        # closer を登録し、後続の set_location/GUI 構築失敗も回収する。
        draw_window = DrawWindowSystem(
            draw,
            options=options,
            render_scale=preview_scale,
            store=param_store,
            midi_session=midi_session,
            monitor=monitor,
            fps=frame_rate,
            n_worker=worker_count,
            evaluation_timeout=timeout,
            run_id=run_id,
            runtime_limit_profiles=profiles,
            source_reload=source_reload,
            definitions=session_definitions,
            effective_config=cfg,
            parameter_source=parameter_session.source,
            parameter_store_path=param_store_path,
            seed=capture_seed,
        )
        # 正常構築後は DrawWindowSystem が MIDI の save/close を所有する。
        unowned_midi_session = None
        closers.append(draw_window.close)
        workspace_windows.attach_preview(draw_window.window)

        # `tasks` はループ駆動用（イベント処理→描画→flip の対象）。
        tasks = [
            WindowTask(
                window=draw_window.window,
                draw_frame=draw_window.draw_frame,
                on_close=pyglet.app.exit,
                on_presented=lambda elapsed_ns: draw_window.record_window_present(
                    "preview_draw_flip",
                    elapsed_ns,
                ),
            )
        ]

        if gui_enabled:
            # Parameter GUI は依存が重い（pyimgui）なので、使うときだけ遅延 import する。
            from grafix.interactive.parameter_gui.variation_thumbnail import (
                variation_thumbnail_callbacks,
            )
            from grafix.interactive.parameter_gui.catalog import ParameterGuiCatalog
            from grafix.interactive.runtime.parameter_gui_system import (
                ParameterGUIWindowSystem,
            )

            variation_thumbnail_base = output_path_for_draw(
                kind="variation_thumbnail",
                ext="png",
                draw=draw,
                run_id=run_id,
                canvas_size=canvas_size,
                config=cfg,
            )
            (
                variation_thumbnail_capture,
                variation_thumbnail_preview,
            ) = variation_thumbnail_callbacks(
                draw_window.capture_service,
                frame_provider=draw_window.final_capture_frame,
                base_path=variation_thumbnail_base,
                canvas_size=canvas_size,
            )

            catalog_definitions = session_definitions
            parameter_gui_catalog = ParameterGuiCatalog.capture(
                catalog_definitions.operations,
                catalog_definitions.presets,
            )

            def current_parameter_gui_catalog() -> ParameterGuiCatalog:
                nonlocal catalog_definitions, parameter_gui_catalog
                active = draw_window.authoring_definitions
                if active is not catalog_definitions:
                    projected_catalog = ParameterGuiCatalog.capture(
                        active.operations,
                        active.presets,
                    )
                    adopt_parameter_schema(active)
                    parameter_gui_catalog = projected_catalog
                    catalog_definitions = active
                return parameter_gui_catalog

            gui = ParameterGUIWindowSystem(
                effective_config=cfg,
                store=param_store,
                midi_session=midi_session,
                monitor=monitor,
                transport=draw_window.transport,
                transport_fps=frame_rate,
                history=param_history,
                snapshot_slots=param_snapshot_slots,
                autosave=param_autosave,
                is_recording=lambda: draw_window.is_recording,
                variation_thumbnail_capture=variation_thumbnail_capture,
                variation_thumbnail_preview=variation_thumbnail_preview,
                ui_scale=workspace_windows.ui_scale,
                catalog=parameter_gui_catalog,
                catalog_provider=current_parameter_gui_catalog,
                on_parameter_revision_created=(draw_window.record_parameter_revision_created),
            )
            closers.append(gui.close)
            workspace_windows.attach_inspector(gui.window)
            workspace_windows.apply_layout()
            # Inspector を preview より先に描く。pyglet が配送済みの slider edit を
            # 同じ tick の preview evaluation へ渡し、固定 1-frame 遅延を生じさせない。
            # GUI hot path は値変更時も全 table rebuild を行わないため、先行描画が
            # preview の critical path を不必要に伸ばさない。
            tasks.insert(
                0,
                WindowTask(
                    window=gui.window,
                    draw_frame=gui.draw_frame,
                    on_close=workspace_windows.hide_inspector,
                    on_presented=lambda elapsed_ns: draw_window.record_window_present(
                        "parameter_gui_draw_flip",
                        elapsed_ns,
                    ),
                ),
            )
            workspace_windows.install_visibility_shortcut()
        elif workspace_windows.restored:
            workspace_windows.apply_layout()

        # macOS + unbundled CLI 起動では、起動直後にウィンドウが他アプリの背面に残る事がある。
        # event loop 開始直後に 1 回だけ明示 activate して前面化する。
        def _activate_windows(_dt: float) -> None:
            # 最後に GUI を activate し、preview が操作面を覆わない状態で開始する。
            workspace_windows.activate()

        pyglet.clock.schedule_once(_activate_windows, 0.0)
        closers.append(lambda: pyglet.clock.unschedule(_activate_windows))

        # --- ループの実行 ---
        # ここで複数ウィンドウを 1 つの pyglet.app.run() で回す。
        loop = MultiWindowLoop(
            tuple(tasks),
            fps=frame_rate,
            on_frame_start=None if monitor is None else monitor.tick_frame,
            on_frame_finished=draw_window.record_full_loop,
            on_scheduler_jitter=draw_window.record_scheduler_jitter,
        )
        loop.run()
        session_completed_cleanly = True
    except BaseException as exc:
        session_error = exc

    def persist_parameter_session() -> None:
        """最後に採用された catalog schema で prune/finalize する。"""

        if draw_window is not None:
            active = draw_window.authoring_definitions
            adopt_parameter_schema(active)
        parameter_session.persist(
            session_completed_cleanly=session_completed_cleanly,
            monitor=monitor,
        )

    cleanup_steps: list[tuple[str, Callable[[], None]]] = [
        (
            "persist ParameterStore",
            persist_parameter_session,
        ),
        (
            "persist WorkspaceState",
            workspace_windows.persist,
        ),
    ]
    cleanup_steps.extend(
        (f"close subsystem {index}", close)
        for index, close in enumerate(reversed(closers), start=1)
    )
    _run_cleanup_steps(cleanup_steps, initial_error=session_error)
