"""Gemini API 呼び出し回数の上限管理（永続的な予約記録方式）。

経緯:
- 当初は予約用Artifactの件数で数えていたが、GitHub Actionsの「再実行」で前回試行の
  Artifactが一覧から消え、数え漏れが起きた（2026-11-18、run 44296992155）。
- そこで予約記録を「PRへのbotコメント（予約記録コメント）」に変更した。
  コメントは再実行でも保存期間でも消えない。

仕組み:
- review job は全PR共通の concurrency グループで直列化される（同時実行なし）。
- Gemini を呼ぶ前に、リポジトリ全体の issue/PR コメントから
  「github-actions[bot] が投稿し、LEDGER_MARKER で始まるコメント」の件数を数える。
  使用済み回数 = LEDGER_BASELINE（予約記録の導入前の実績）＋ 予約記録コメントの件数。
- 上限未満なら、対象PRに予約記録コメントを投稿してから呼び出す（1 job = 最大1回、再試行なし）。
  投稿に失敗したら呼び出さない（fail closed）。件数を数えられない場合も呼び出さない。
- 再実行（run attempt 2以上）も、新しい予約記録コメントとして数える。
- bot以外のユーザーが同じ目印を含むコメントを書いても数えない（水増し・改ざんの防止）。
- 追加の権限は不要（PRへのコメントは既存の pull-requests: write で行う）。

PoC実行期間（POC_START〜POC_END）の外では呼び出さない（承認済みの運用条件として維持）。
定数の変更には main へのPRとユーザーのマージが必要。
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c  # noqa: E402

CALL_LIMIT = 70
LEDGER_MARKER = "<!-- gemini-call-ledger -->"
BOT_LOGIN = "github-actions[bot]"

# 予約記録コメントの導入前に Gemini へ送ったリクエスト（2026-11-18、すべて JST）
#  1. 20:06 PR #2  run 44291523340 attempt 1  … 応答待ちタイムアウト（180秒）
#  2. 20:17 PR #3  run 44293262846 attempt 1  … COMPLETED
#  3. 20:41 PR #3  run 44296992155 attempt 1  … HTTP 503（再実行で予約Artifactが消失）
#  4. 20:44 PR #3  run 44296992155 attempt 2  … COMPLETED
LEDGER_BASELINE = 4

POC_START = datetime(2026, 11, 18, 0, 0, 0, tzinfo=timezone.utc)
POC_END = datetime(2027, 2, 15, 0, 0, 0, tzinfo=timezone.utc)   # この時刻以降は呼び出さない
assert POC_END > POC_START
assert 0 <= LEDGER_BASELINE < CALL_LIMIT


def now_utc() -> datetime:
    """現在時刻（UTC）。テストではこの関数を差し替える。"""
    return datetime.now(timezone.utc)


def period_check(now: datetime) -> str | None:
    if now < POC_START:
        return f"PoC開始前（開始 {POC_START.isoformat()}、現在 {now.isoformat()}）"
    if now >= POC_END:
        return f"PoC実行期間の終了後（期限 {POC_END.isoformat()}、現在 {now.isoformat()}）"
    return None


def is_ledger_entry(comment: dict) -> bool:
    return ((comment.get("user") or {}).get("login") == BOT_LOGIN
            and (comment.get("body") or "").startswith(LEDGER_MARKER))


def count_ledger(repository: str) -> int:
    """リポジトリ全体（全PR・全Issue）の予約記録コメントを数える。"""
    n, page = 0, 1
    since = POC_START.strftime("%Y-%m-%dT%H:%M:%SZ")
    while True:
        cs = c.gh_get_json(f"/repos/{repository}/issues/comments",
                           f"per_page=100&page={page}&since={since}")
        n += sum(1 for x in cs if is_ledger_entry(x))
        if len(cs) < 100:
            return n
        page += 1


def ledger_body(state: dict, seq: int, now: datetime) -> str:
    return "\n".join([
        LEDGER_MARKER,
        f"<sub>🔒 Gemini呼び出し予約 **{seq}/{CALL_LIMIT}**　"
        f"run `{state.get('run_id')}` attempt `{state.get('run_attempt')}`　"
        f"head `{state['head_sha'][:7]}` base `{state['base_sha'][:7]}`　"
        f"予約 {now.strftime('%Y-%m-%dT%H:%M:%SZ')}　（この記録は呼び出し回数の管理用です。削除しないでください）</sub>",
    ])


def deny(out: str, state: dict, status: str, reason: str) -> int:
    state.update(status=status, reasons=[reason])
    c.save_state(out, state)
    c.set_output("allowed", "false")
    print(f"::error::{reason}。Geminiを呼びません")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    state = c.load_state(a.out)
    repository = c.repo()

    now = now_utc()
    state["poc_period"] = {"start": POC_START.isoformat(), "end": POC_END.isoformat(), "checked_at": now.isoformat()}
    reason = period_check(now)
    if reason:
        return deny(a.out, state, c.OUTSIDE_POC_PERIOD, reason)

    try:
        entries = count_ledger(repository)
    except c.HttpError as e:
        return deny(a.out, state, c.BUDGET_CHECK_FAILED, f"予約記録の取得失敗: HTTP {e.status}")

    used = LEDGER_BASELINE + entries
    state["budget"] = {"limit": CALL_LIMIT, "baseline": LEDGER_BASELINE, "ledger_entries": entries, "used_before": used}
    if used >= CALL_LIMIT:
        return deny(a.out, state, c.BUDGET_EXHAUSTED, f"呼び出し上限に到達（{used}/{CALL_LIMIT}）")

    seq = used + 1
    body = ledger_body(state, seq, now)
    try:
        res = c.gh_send_json("POST", f"/repos/{repository}/issues/{state['pr_number']}/comments",
                             {"body": body})
    except c.HttpError as e:
        return deny(a.out, state, c.BUDGET_CHECK_FAILED, f"予約記録の投稿失敗: HTTP {e.status}")
    if not res.get("id"):
        return deny(a.out, state, c.BUDGET_CHECK_FAILED, "予約記録の投稿結果を確認できない")

    state["budget"]["sequence"] = seq
    state["ledger_comment_id"] = res["id"]
    state["ledger_body"] = body
    c.save_state(a.out, state)
    c.set_output("allowed", "true")
    c.notice(f"Gemini呼び出し予約 {seq}/{CALL_LIMIT}（予約記録コメント {res['id']}、PoC期限 {POC_END.date()}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
