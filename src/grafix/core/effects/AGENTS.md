`core/effects` の各 module は互いを import せず独立を保つこと。共有数値処理は責務別の `core/geometry_kernels` だけに置き、effect module 側は validation、diagnostic、kernel composition を担当すること。
また、ここでの各モジュールの冒頭では、ほかのディレクトリには強制している　どこで　なにを　なぜ　という docstring を書くことを禁じる。
その代わり、そのモジュールがどのような効果を与えるかをわかりやすく記載すること。
