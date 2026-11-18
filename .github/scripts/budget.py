"""Gemini API 呼び出し回数の上限管理（ChatGPT追加条件1、PR #1レビュー指摘を反映）。

仕組み:
- review job は全PR共通の concurrency グループで直列化される（同時実行なし）。
- Gemini を呼ぶ前に、予約用Artifact `gemini-call-*` の件数を数える。
  上限未満なら予約Artifactをアップロードしてから呼び出す（1 job = 最大1回、再試行なし）。
- 再実行（run attempt）も新しい予約として数える。数え方は常に「多めに」なる側に倒す。
- APIエラー等で件数が数えられなければ、呼び出さない（fail closed）。

PoC実行期間の制限（「PoC全期間で70回以内」を保証するため）:
- 予約Artifactの保存期間は90日。期限切れで件数が減らないよう、PoCの実行期間を
  POC_START 以降・POC_END 未満（89日間）に限定し、期間外では Gemini を呼ばない。
- 期間内に作られた予約は、期間内のどの時点でも作成から90日未満なので、期限切れで消えない。
- 期間の延長・変更には main へのPRとユーザーのマージが必要。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c  # noqa: E402

CALL_LIMIT = 70                     # 変更には main へのPRとユーザーのマージが必要
PREFIX = "gemini-call-"
RESERVATION_RETENTION_DAYS = 90     # ワークフローの retention-days と一致させる
POC_START = datetime(2026, 11, 18, 0, 0, 0, tzinfo=timezone.utc)
POC_END = datetime(2027, 2, 15, 0, 0, 0, tzinfo=timezone.utc)   # この時刻以降は呼び出さない

# 期間は保存期間より短くなければならない（読み込み時に検証し、満たさなければ起動しない）
assert POC_END > POC_START
assert POC_END - POC_START < timedelta(days=RESERVATION_RETENTION_DAYS), "PoC期間が予約の保存期間以上"


def now_utc() -> datetime:
    """現在時刻（UTC）。テストではこの関数を差し替える。"""
    return datetime.now(timezone.utc)


def period_check(now: datetime) -> str | None:
    """期間外なら理由を返す。期間内なら None。"""
    if now < POC_START:
        return f"PoC開始前（開始 {POC_START.isoformat()}、現在 {now.isoformat()}）"
    if now >= POC_END:
        return f"PoC実行期間の終了後（期限 {POC_END.isoformat()}、現在 {now.isoformat()}）"
    return None


def count_reservations(repository: str) -> int:
    n, page = 0, 1
    while True:
        res = c.gh_get_json(f"/repos/{repository}/actions/artifacts", f"per_page=100&page={page}")
        arts = res.get("artifacts", [])
        n += sum(1 for x in arts if x.get("name", "").startswith(PREFIX))  # 期限切れ表示のものも数える
        if len(arts) < 100:
            return n
        page += 1


def deny(out: str, state: dict, status: str, reason: str) -> int:
    state.update(status=status, reasons=[reason])
    c.save_state(out, state)
    c.set_output("allowed", "false")
    print(f"::error::{reason}。Geminiを呼びません")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--reservation-dir", required=True)
    a = ap.parse_args(argv)
    state = c.load_state(a.out)

    now = now_utc()
    state["poc_period"] = {"start": POC_START.isoformat(), "end": POC_END.isoformat(), "checked_at": now.isoformat()}
    reason = period_check(now)
    if reason:
        return deny(a.out, state, c.OUTSIDE_POC_PERIOD, reason)

    try:
        used = count_reservations(c.repo())
    except c.HttpError as e:
        return deny(a.out, state, c.BUDGET_CHECK_FAILED, f"予約件数の取得失敗: HTTP {e.status}")

    state["budget"] = {"limit": CALL_LIMIT, "used_before": used}
    if used >= CALL_LIMIT:
        return deny(a.out, state, c.BUDGET_EXHAUSTED, f"呼び出し上限に到達（{used}/{CALL_LIMIT}）")

    name = f"{PREFIX}pr{state['pr_number']}-run{state.get('run_id')}-{state.get('run_attempt')}"
    rd = Path(a.reservation_dir)
    rd.mkdir(parents=True, exist_ok=True)
    (rd / "reservation.json").write_text(json.dumps({
        "pr_number": state["pr_number"], "head_sha": state["head_sha"], "base_sha": state["base_sha"],
        "run_id": state.get("run_id"), "run_attempt": state.get("run_attempt"), "sequence": used + 1,
        "reserved_at": now.isoformat(),
    }), encoding="utf-8")
    c.save_state(a.out, state)
    c.set_output("allowed", "true")
    c.set_output("reservation_name", name)
    c.notice(f"Gemini呼び出し予約 {used + 1}/{CALL_LIMIT}（PoC期限 {POC_END.date()}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
