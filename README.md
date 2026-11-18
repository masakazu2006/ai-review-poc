# ai-review-poc

AI自動レビューの技術検証用リポジトリです（ダミーデータのみ）。
PRを作成すると、GitHub ActionsからGemini APIを呼び出し、レビュー結果をPRコメントとして記録します。

- 設計：AI連携基盤PoC 設計案 v0.2.1 ＋ 実装時の追加条件
- 自動マージ・デプロイは行いません。マージの判断は常に人が行います。
- `poc_app/` は架空の会費精算ツールで、実在のデータとは無関係です。

テスト（ネットワークに接続しない）: `python3 -m unittest discover -s tests -t .`
