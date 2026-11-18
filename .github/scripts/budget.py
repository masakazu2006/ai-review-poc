"""Gemini API 呼び出し回数の上限管理（ChatGPT追加条件1）。

仕組み:
- review job は全PR共通の concurrency グループで直列化される（同時実行なし）。
- Gemini を呼ぶ前に、予約用Artifact `gemini-call-*` の件数を数える。
  上限未満なら予約Artifactをアップロードしてから呼び出す（1 job = 最大1回、再試行なし）。
- 再実行（run attempt）も新しい予約として数える。数え方は常に「多めに」なる側に倒す。
- APIエラー等で件数が数えられなければ、呼び出さない（fail closed）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c  # noqa: E402

CALL_LIMIT = 70            # 変更には main へのPRとユーザーのマージが必要
PREFIX = "gemini-call-"


def count_reservations(repository: str) -> int:
    n, page = 0, 1
    while True:
        res = c.gh_get_json(f"/repos/{repository}/actions/artifacts", f"per_page=100&page={page}")
        arts = res.get("artifacts", [])
        n += sum(1 for x in arts if x.get("name", "").startswith(PREFIX))  # 期限切れも数える
        if len(arts) < 100:
            return n
        page += 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--reservation-dir", required=True)
    a = ap.parse_args(argv)
    state = c.load_state(a.out)

    try:
        used = count_reservations(c.repo())
    except c.HttpError as e:
        state.update(status=c.BUDGET_CHECK_FAILED, reasons=[f"予約件数の取得失敗: HTTP {e.status}"])
        c.save_state(a.out, state)
        c.set_output("allowed", "false")
        print("::error::呼び出し回数を確認できないため、Geminiを呼びません")
        return 0

    state["budget"] = {"limit": CALL_LIMIT, "used_before": used}
    if used >= CALL_LIMIT:
        state.update(status=c.BUDGET_EXHAUSTED, reasons=[f"呼び出し上限に到達（{used}/{CALL_LIMIT}）"])
        c.save_state(a.out, state)
        c.set_output("allowed", "false")
        print(f"::error::呼び出し上限に到達（{used}/{CALL_LIMIT}）")
        return 0

    name = f"{PREFIX}pr{state['pr_number']}-run{state.get('run_id')}-{state.get('run_attempt')}"
    rd = Path(a.reservation_dir)
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "reservation.json").write_text(json.dumps({
        "pr_number": state["pr_number"], "head_sha": state["head_sha"], "base_sha": state["base_sha"],
        "run_id": state.get("run_id"), "run_attempt": state.get("run_attempt"), "sequence": used + 1,
    }), encoding="utf-8")
    c.save_state(a.out, state)
    c.set_output("allowed", "true")
    c.set_output("reservation_name", name)
    c.notice(f"Gemini呼び出し予約 {used + 1}/{CALL_LIMIT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
