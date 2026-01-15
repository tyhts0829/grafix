"""
どこで: `generate_report.py`。
何を: `data/output/benchmarks/runs/*.json` を集約し、`data/output/benchmarks/report.html` を生成する。
なぜ: 最適化前後の改善度合いを、ケース別×effect 別の時系列グラフで把握するため。

入力（想定）
------------
- `runs_dir` 配下の `*.json`（ファイル名 stem が run_id）。
- run_id は `%Y%m%d_%H%M%S` 形式の日時として解釈し、これを時系列の基準にする。
- JSON は概ね `{meta, cases, effects}` を想定する（壊れたファイルや想定外の形式は静かに無視する）。

出力
----
- `data/output/benchmarks/report.html`（上書き）。
- HTML 内にベンチ結果の JSON を埋め込み、Chart.js（CDN）で折れ線グラフを描画する。
  そのためネット接続が無い環境ではグラフを描けず、表だけが残る。

読む順番（主要フロー）
----------------------
1. `_load_runs()` で runs_dir から JSON を読み、実行（run）単位に正規化する
2. `build_timeseries_report()` で「ケース × effect の時系列」データ構造に変換する
3. `render_report_html()` で HTML をレンダリングし、`report.html` に書き出す
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any

_RUN_ID_FORMAT = "%Y%m%d_%H%M%S"
_CANVAS_HEIGHT = 600


@dataclass(frozen=True, slots=True)
class _Run:
    """1 回分のベンチマーク実行（run）を表す内部データ。

    JSON の生データをそのまま持ち回すのではなく、レポート生成に必要な情報だけを
    取り出して正規化した形。

    Attributes
    ----------
    run_id
        `runs/*.json` のファイル名 stem。`YYYYmmdd_HHMMSS` を想定する。
    dt
        run_id を `_RUN_ID_FORMAT` でパースした datetime（時系列ソート用）。
    meta
        JSON の `meta` を dict にしたもの（`created_at` / `git_sha` など）。
    cases
        case_id -> case dict。`cases[]` を `id` で引ける形にしたもの。
    effect_names
        JSON の `effects[].name` を「初出順」で並べたリスト（重複は除去）。
    means_ms
        case_id -> effect_name -> mean_ms。`status == "ok"` のものだけを拾う。
    """

    run_id: str
    dt: datetime
    meta: dict[str, Any]
    cases: dict[str, dict[str, Any]]
    effect_names: list[str]
    means_ms: dict[str, dict[str, float]]


def main() -> int:
    """ベンチマーク run JSON を集約して HTML レポートを書き出す。

    Side Effects
    ------------
    - `data/output/benchmarks/runs/*.json` を読む。
    - `data/output/benchmarks/report.html` を生成して上書きする。
    - 標準出力に生成先パスを表示する。
    """

    project_root = Path(__file__).resolve().parents[2]
    out_root = project_root / "data" / "output" / "benchmarks"
    runs_dir = out_root / "runs"
    report_path = out_root / "report.html"

    report = build_timeseries_report(runs_dir=runs_dir)
    html = render_report_html(report)

    out_root.mkdir(parents=True, exist_ok=True)
    report_path.write_text(html, encoding="utf-8")
    print(f"[grafix-bench] wrote: {report_path}")  # noqa: T201
    return 0


def build_timeseries_report(*, runs_dir: Path) -> dict[str, Any]:
    """runs_dir 配下のベンチ run JSON を集約し、HTML 描画向けの辞書に変換する。

    この関数は「レポートの中身（データ構造）」を作るところまでを担当し、
    HTML テンプレートの組み立ては `render_report_html()` に委譲する。

    Notes
    -----
    - 表示する case 一覧・effect 一覧は「最新 run」の内容を基準にする。
      （過去に存在しても最新 run に無いケース/エフェクトはレポート対象外になる）
    - 時系列の欠損（特定 run に結果が無い等）は `None` を入れてギャップとして扱う。

    Raises
    ------
    SystemExit
        runs_dir から有効な run が 1 つも読めない場合。
    """

    runs = _load_runs(runs_dir=runs_dir)
    if not runs:
        raise SystemExit(f"no runs found: {runs_dir}")

    latest = runs[-1]
    # レポートの「ケース×エフェクト」の軸は最新 run を基準に固定する。
    # （ベンチスイートが変化したときに、過去データに引きずられないようにする）
    case_list = list(latest.cases.values())
    effect_names = list(latest.effect_names)

    run_rows = [
        {
            "run_id": r.run_id,
            "created_at": r.meta.get("created_at", ""),
            "git_sha": r.meta.get("git_sha", ""),
        }
        for r in runs
    ]

    chart_specs: list[dict[str, Any]] = []
    for case in case_list:
        case_id = str(case.get("id", ""))
        if not case_id:
            continue

        # effect ごとに、run の並び順（時系列）に対応する点列を作る。
        # 欠損は None にし、Chart.js 側で線のギャップとして扱う。
        series: dict[str, list[float | None]] = {}
        for eff in effect_names:
            pts: list[float | None] = []
            for r in runs:
                v = r.means_ms.get(case_id, {}).get(eff)
                pts.append(float(v) if v is not None else None)
            series[eff] = pts

        latest_means = latest.means_ms.get(case_id, {})
        # 最新 run の mean_ms を基準に「重い順」に並べる。
        # 目的: 表（Improvement）と凡例の先頭に、支配的なコストを持つ effect を出したい。
        ordered_effects = sorted(
            effect_names,
            key=lambda e: float(latest_means.get(e, -1.0)),
            reverse=True,
        )

        datasets = []
        for eff in ordered_effects:
            color = _color_for_label(eff)
            datasets.append(
                {
                    "label": eff,
                    "data": series.get(eff, []),
                    "borderColor": color,
                    "backgroundColor": color,
                    "tension": 0.2,
                }
            )

        table_rows = []
        for eff in ordered_effects:
            pts = series.get(eff, [])
            # first/last は「欠損を除いた最初/最後」。未計測の run が混ざっても比率が出る。
            first = next((v for v in pts if v is not None), None)
            last = next((v for v in reversed(pts) if v is not None), None)
            ratio = ""
            if first is not None and last is not None and float(first) > 0.0:
                ratio = f"{float(last) / float(first):.3f}x"
            table_rows.append(
                {
                    "effect": eff,
                    "first_ms": first,
                    "last_ms": last,
                    "ratio": ratio,
                }
            )

        chart_specs.append(
            {
                "case_id": case_id,
                "case_label": str(case.get("label", case_id)),
                "case_description": str(case.get("description", "")),
                "n_vertices": case.get("n_vertices", ""),
                "n_lines": case.get("n_lines", ""),
                "closed_lines": case.get("closed_lines", ""),
                "datasets": datasets,
                "table": table_rows,
            }
        )

    meta = {
        # `generated_at` はレポート生成時刻（データの run 時刻とは別）。
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "runs": len(runs),
        "first_run": runs[0].run_id,
        "last_run": runs[-1].run_id,
    }
    return {
        "meta": meta,
        "runs": run_rows,
        "cases": [
            {"id": c.get("id", ""), "label": c.get("label", "")} for c in case_list
        ],
        "charts": chart_specs,
    }


def render_report_html(report: dict[str, Any]) -> str:
    """`build_timeseries_report()` が返す辞書を HTML にレンダリングする。

    Notes
    -----
    - ベンチ結果のペイロード（runs/charts）は HTML に埋め込み、Chart.js で描画する。
    - Chart.js は CDN から読み込むため、ネット接続が無いとグラフは描けない。
    """

    meta: dict[str, Any] = dict(report.get("meta", {}))
    runs: list[dict[str, Any]] = list(report.get("runs", []))
    cases: list[dict[str, Any]] = list(report.get("cases", []))
    charts: list[dict[str, Any]] = list(report.get("charts", []))

    # JS 側で参照する分（runs/charts）のみを埋め込む。HTML には meta/cases を別途描画する。
    payload_json = json.dumps(
        {
            "runs": runs,
            "charts": charts,
        },
        ensure_ascii=False,
    )

    head = _render_head(title="grafix effect benchmark (timeseries)")
    body = []
    body.append("<h1>grafix effect benchmark (timeseries)</h1>")
    body.append(_render_meta(meta))
    body.append(_render_case_index(cases))

    body.append('<div class="panel">')
    body.append('<div class="muted">Note</div>')
    body.append("<ul>")
    body.append(
        "<li>グラフは Chart.js（CDN）で描画する。ネット接続が無いと表だけになる。</li>"
    )
    body.append("<li>凡例クリックで effect の表示/非表示を切り替えできる。</li>")
    body.append("</ul>")
    body.append("</div>")

    for chart in charts:
        case_id = str(chart.get("case_id", ""))
        case_label = str(chart.get("case_label", case_id))
        case_desc = str(chart.get("case_description", ""))
        n_vertices = chart.get("n_vertices", "")
        n_lines = chart.get("n_lines", "")
        closed_lines = chart.get("closed_lines", "")

        body.append(f'<h2 id="case-{escape(case_id)}">Case: {escape(case_label)}</h2>')
        parts = [
            f'<div class="muted">{escape(case_desc)}</div>' if case_desc else "",
            '<div style="margin-top:6px" class="mono">'
            f"verts={escape(str(n_vertices))} lines={escape(str(n_lines))} closed_lines={escape(str(closed_lines))}"
            "</div>",
        ]
        body.append('<div class="panel">' + "\n".join(p for p in parts if p) + "</div>")

        body.append('<div class="panel">')
        body.append(
            f'<canvas id="chart-{escape(case_id)}" height="{_CANVAS_HEIGHT}"></canvas>'
        )
        body.append("</div>")

        table_rows: list[dict[str, Any]] = list(chart.get("table", []))
        body.append(_render_improvement_table(rows=table_rows))

    body.append("<hr />")
    body.append('<p class="muted">generated by generate_report.py</p>')

    js = _render_scripts(payload_json=payload_json)
    return head + "\n<body>\n" + "\n".join(body) + "\n" + js + "\n</body>\n</html>\n"


def _render_head(*, title: str) -> str:
    """HTML の `<head>`（CSS を含む）を返す。"""
    return f"""<!doctype html>
<html lang="ja">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{escape(title)}</title>
  <style>
    :root {{
      --bg: #0b1020;
      --panel: #121a33;
      --text: #e7ecff;
      --muted: #aab3d6;
      --grid: rgba(255,255,255,0.08);
      --bar: #4aa3ff;
      --bar2: #7fdbca;
      --warn: #ffcc66;
      --err: #ff6b6b;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", "Courier New", monospace;
      --sans: ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, "Apple Color Emoji", "Segoe UI Emoji";
    }}
    body {{
      margin: 0;
      padding: 28px;
      font-family: var(--sans);
      background: linear-gradient(180deg, var(--bg), #070a14);
      color: var(--text);
    }}
    a {{ color: var(--bar); }}
    h1 {{ margin: 0 0 8px 0; font-size: 24px; }}
    h2 {{ margin: 28px 0 10px 0; font-size: 18px; }}
    .muted {{ color: var(--muted); }}
    .panel {{
      background: rgba(18,26,51,0.9);
      border: 1px solid var(--grid);
      border-radius: 12px;
      padding: 12px 14px;
      margin: 10px 0;
      backdrop-filter: blur(10px);
    }}
    .mono {{ font-family: var(--mono); }}
    .case-index a {{ margin-right: 10px; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 10px;
      font-family: var(--mono);
      font-size: 12px;
    }}
    th, td {{
      border-bottom: 1px solid var(--grid);
      padding: 8px 6px;
      text-align: left;
      vertical-align: top;
    }}
    th {{ color: var(--muted); font-weight: 600; }}
  </style>
</head>
"""


def _render_meta(meta: dict[str, Any]) -> str:
    """メタ情報パネル（generated_at など）を HTML としてレンダリングする。"""
    items: list[str] = []
    for key in (
        "generated_at",
        "runs",
        "first_run",
        "last_run",
    ):
        if key in meta:
            items.append(
                f'<div><span class="muted">{escape(key)}</span>: <span class="mono">{escape(str(meta[key]))}</span></div>'
            )
    if not items:
        return ""
    return '<div class="panel">' + "\n".join(items) + "</div>"


def _render_case_index(cases: list[dict[str, Any]]) -> str:
    """ページ内ジャンプ用のケース一覧（リンク）をレンダリングする。"""
    links: list[str] = []
    for case in cases:
        cid = str(case.get("id", ""))
        label = str(case.get("label", cid))
        if not cid:
            continue
        links.append(f'<a href="#case-{escape(cid)}">{escape(label)}</a>')
    if not links:
        return ""
    return (
        '<div class="panel case-index"><div class="muted">Cases</div>'
        + " ".join(links)
        + "</div>"
    )


def _render_improvement_table(*, rows: list[dict[str, Any]]) -> str:
    """1 ケース分の Improvement 表（first → last）をレンダリングする。"""
    out = []
    out.append('<div class="panel">')
    out.append('<div class="muted">Improvement (first → last)</div>')
    out.append("<table>")
    out.append(
        "<tr>"
        "<th>effect</th>"
        "<th>first_ms</th>"
        "<th>last_ms</th>"
        "<th>ratio</th>"
        "</tr>"
    )

    for r in rows:
        name = escape(str(r.get("effect", "")))
        first_ms = _fmt_num(r.get("first_ms"))
        last_ms = _fmt_num(r.get("last_ms"))
        ratio = escape(str(r.get("ratio", "")))
        out.append(
            "<tr>"
            f"<td>{name}</td>"
            f"<td>{first_ms}</td>"
            f"<td>{last_ms}</td>"
            f"<td>{ratio}</td>"
            "</tr>"
        )

    out.append("</table></div>")
    return "\n".join(out)


def _fmt_num(value: Any) -> str:
    """数値を表のセル向けに整形する（不正な場合は文字列化してエスケープ）。"""
    if value is None:
        return ""
    try:
        return f"{float(value):.3f}"
    except Exception:
        return escape(str(value))


def _render_scripts(*, payload_json: str) -> str:
    """Chart.js を読み込み、埋め込んだ payload からグラフを描画する `<script>` を返す。"""
    template = """
<script>
  const REPORT = __GRAFIX_BENCH_PAYLOAD__;
</script>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
<script>
  function tooltipTitle(items) {
    if (!items || items.length === 0) return '';
    const idx = items[0].dataIndex;
    const r = REPORT.runs[idx] || {};
    const sha = (r.git_sha || '').slice(0, 10);
    const created = r.created_at ? ` (${r.created_at})` : '';
    return `${r.run_id || idx}${created}${sha ? ' ' + sha : ''}`;
  }

  function tooltipLabel(ctx) {
    const label = ctx.dataset.label || '';
    const v = ctx.raw;
    if (v === null || v === undefined) return `${label}: (missing)`;
    return `${label}: ${Number(v).toFixed(3)} ms`;
  }

  function buildChart(caseId, spec) {
    const canvas = document.getElementById(`chart-${caseId}`);
    if (!canvas) return;

    const labels = REPORT.runs.map(r => r.run_id);
    const datasets = (spec.datasets || []).map(ds => {
      const data = (ds.data || []).map(v => {
        if (v === null || v === undefined) return null;
        const n = Number(v);
        return Number.isFinite(n) && n > 0 ? n : null;
      });
      return { ...ds, data };
    });

    const chart = new Chart(canvas, {
      type: 'line',
      data: {
        labels,
        datasets,
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: {
          mode: 'nearest',
          intersect: false,
        },
        scales: {
          x: {
            ticks: {
              maxRotation: 60,
              minRotation: 45,
              autoSkip: true,
              maxTicksLimit: 12,
            },
            grid: { color: 'rgba(255,255,255,0.06)' },
          },
          y: {
            type: 'logarithmic',
            title: { display: true, text: 'mean_ms (log10)' },
            grid: { color: 'rgba(255,255,255,0.06)' },
            ticks: {
              callback: (value) => {
                const v = Number(value);
                if (!Number.isFinite(v)) return '';
                if (v >= 10) return `${v.toFixed(0)} ms`;
                if (v >= 1) return `${v.toFixed(1)} ms`;
                if (v >= 0.1) return `${v.toFixed(2)} ms`;
                return `${v.toFixed(3)} ms`;
              },
            },
          },
        },
        plugins: {
          legend: {
            labels: {
              boxWidth: 12,
            },
          },
          tooltip: {
            callbacks: {
              title: tooltipTitle,
              label: tooltipLabel,
            },
          },
        },
        elements: {
          point: {
            radius: 2,
            hoverRadius: 4,
          },
          line: {
            borderWidth: 2,
          },
        },
      },
    });
    return chart;
  }

  function main() {
    if (typeof Chart === 'undefined') {
      console.warn('Chart.js not loaded. Showing tables only.');
      return;
    }

    Chart.defaults.color = '#e7ecff';
    Chart.defaults.borderColor = 'rgba(255,255,255,0.12)';

    for (const spec of REPORT.charts) {
      buildChart(spec.case_id, spec);
    }
  }
  main();
</script>
"""
    # payload_json は `json.dumps()` が返す「JSON 文字列」そのもの。
    # 文字列リテラルではなく JS のオブジェクトとして埋め込むため、単純置換で差し込む。
    return template.replace("__GRAFIX_BENCH_PAYLOAD__", payload_json)


def _parse_run_id(run_id: str) -> datetime | None:
    """run_id（ファイル名 stem）を日時として解釈する。失敗したら None。"""
    try:
        return datetime.strptime(run_id, _RUN_ID_FORMAT)
    except ValueError:
        return None


def _load_runs(*, runs_dir: Path) -> list[_Run]:
    """runs_dir 配下の `*.json` を読み、時系列に並べた `_Run` の配列を返す。

    - ファイル名が `_RUN_ID_FORMAT` でパースできないものは対象外。
    - JSON のパースに失敗したもの、想定外の構造のものも静かにスキップする。
      （レポート生成は「できる範囲で出す」ことを優先し、1 ファイルの不良で落とさない）
    """

    runs: list[_Run] = []
    for fp in sorted(runs_dir.glob("*.json")):
        dt = _parse_run_id(fp.stem)
        if dt is None:
            continue
        try:
            raw = json.loads(fp.read_text(encoding="utf-8"))
        except Exception:
            continue

        meta = dict(raw.get("meta", {}))
        cases = {
            str(c.get("id", "")): dict(c)
            for c in raw.get("cases", [])
            if str(c.get("id", ""))
        }

        effect_names: list[str] = []
        seen_effects: set[str] = set()
        means_ms: dict[str, dict[str, float]] = {}
        for eff in raw.get("effects", []):
            name = str(eff.get("name", ""))
            if not name:
                continue
            if name not in seen_effects:
                seen_effects.add(name)
                effect_names.append(name)
            for case_id, res in dict(eff.get("results", {})).items():
                if str(res.get("status", "")) != "ok":
                    continue
                try:
                    mean_ms = float(res.get("mean_ms", 0.0))
                except Exception:
                    continue
                means_ms.setdefault(str(case_id), {})[name] = mean_ms

        runs.append(
            _Run(
                run_id=fp.stem,
                dt=dt,
                meta=meta,
                cases=cases,
                effect_names=effect_names,
                means_ms=means_ms,
            )
        )

    runs.sort(key=lambda r: r.dt)
    return runs


def _color_for_label(label: str) -> str:
    """label から安定した HSL 色を作る（レポート間で色が変わりにくいようにする）。"""
    h = 0
    for ch in label:
        h = (h * 131 + ord(ch)) % 360
    return f"hsl({h}, 70%, 60%)"


if __name__ == "__main__":
    raise SystemExit(main())
