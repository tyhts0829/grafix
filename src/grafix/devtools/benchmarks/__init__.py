"""
どこで: `src/grafix/devtools/benchmarks/__init__.py`。
何を: effect ベンチ用ユーティリティ群をまとめる。
なぜ: `python -m grafix benchmark ...` から実行できるようにするため。
"""

from __future__ import annotations

BENCHMARK_SCHEMA_VERSION = 2
"""effect benchmark の結果 JSON schema version。"""

__all__ = ["BENCHMARK_SCHEMA_VERSION"]
