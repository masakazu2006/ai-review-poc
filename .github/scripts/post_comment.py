"""PRコメント（最新1件）の更新と記録の確定（設計書 v0.2.1 §5.1, §5.2）。

- 隠しマーカー付きの bot コメントを上書き。無ければ作成。
- 投稿直前に head SHA を照合し、変わっていれば投稿しない（SUPERSEDED）。
- 判定（verdict）を表示するのは COMPLETED のときだけ。
- 終了コード: COMPLETED / SUPERSEDED は 0、それ以外は 1（job を失敗にする）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c  # noqa: E402

MARKER = "<!-- gemini-pr-review -->"
BOT_LOGIN = "github-actions[bot]"
ZWSP = "\u200b"


def sanitize(s: str) -> str:
    """モデル出力をコメントに載せる前の無害化。"""
    s = s.replace("<!--", "&lt;!--").replace("-->", "--&gt;")
    s = re.sub(r"@(?=[A-Za-z0-9-])", "@" + ZWSP, s)       # メンション通知を防ぐ
    s = s.replace("|", "\\|").replace("\r", " ").replace("\n", " ")
    return s


def render(state: dict, result: dict | None, run_url: str) -> str:
    st = state.get("status")
    v = state.get("verification") or {}
    lines = [MARKER, "## Gemini 自動レビュー（PoC）", ""]
    if st == c.COMPLETED and result:
        lines.append(f"**判定：{sanitize(result['verdict'])}**　（状態：COMPLETED）")
        lines += ["", sanitize(result.get("summary", "")), ""]
    else:
        lines.append(f"**⚠ レビュー未完了：{st}**")
        for r in state.get("reasons", []):
            lines.append(f"- {sanitize(str(r))}")
        lines.append("")
        lines.append("※ この状態はレビュー完了として扱いません。")
        lines.append("")
    lines += [
        "| 項目 | 値 |", "|---|---|",
        f"| head_sha | `{state.get('head_sha')}` |",
        f"| base_sha | `{state.get('base_sha')}` |",
        f"| merge_base_sha | `{state.get('merge_base_sha')}` |",
        f"| 差分照合 | {'一致' if v.get('ok') else '未確認/不一致'}（ファイル {v.get('files_diff')}/{v.get('files_pr')}、"
        f"+{v.get('additions_diff')}/-{v.get('deletions_diff')}） |",
        f"| スクリプトの取得元SHA | `{state.get('workflow_sha')}` |",
        f"| モデル | `{state.get('model', '-')}` |",
        f"| 実行ログ | {run_url} |",
    ]
    if st == c.COMPLETED and result:
        lines += ["", "### 指摘", ""]
        if result.get("findings"):
            lines += ["| 重大度 | ファイル | 行 | 分類 | 内容 |", "|---|---|---|---|---|"]
            for f in result["findings"]:
                lines.append(f"| {sanitize(f['severity'])} | {sanitize(f['file'])} | {f['line']} | "
                             f"{sanitize(f['category'])} | {sanitize(f['message'])} |")
        else:
            lines.append("指摘なし")
    u = state.get("usage") or {}
    b = state.get("budget") or {}
    cost = state.get("estimated_cost_usd_if_paid")
    lines += ["", "<sub>"
              f"トークン 入力 {u.get('input', '-')} / 出力 {u.get('output', '-')} / 思考 {u.get('thoughts', '-')}　"
              f"有料枠換算 {('$' + format(cost, '.4f')) if cost is not None else '-'}（無料枠利用のため実費0円）　"
              f"所要 {state.get('duration_sec', '-')} 秒　"
              f"呼び出し {b.get('used_before', '-')}+1/{b.get('limit', '-')}"
              "</sub>",
              "", "> この結果は参考情報です。マージの判断はユーザーが行います。"]
    return "\n".join(lines) + "\n"


def find_comment(repository: str, number: int) -> int | None:
    page = 1
    while True:
        cs = c.gh_get_json(f"/repos/{repository}/issues/{number}/comments", f"per_page=100&page={page}")
        for cm in cs:
            if (cm.get("user") or {}).get("login") == BOT_LOGIN and MARKER in (cm.get("body") or ""):
                return cm["id"]
        if len(cs) < 100:
            return None
        page += 1


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    out = Path(a.out)
    state = c.load_state(out)
    repository = c.repo()
    number = state["pr_number"]
    if state.get("status") == c.PENDING:   # 呼び出し前に止まった（予算確認の失敗など）
        state.update(status=c.API_ERROR, reasons=state.get("reasons") or ["Gemini呼び出しが実行されなかった"])

    run_url = f"{os.environ.get('GITHUB_SERVER_URL', 'https://github.com')}/{repository}/actions/runs/{state.get('run_id')}"
    rp = out / "result.json"
    result = json.loads(rp.read_text(encoding="utf-8")) if rp.exists() else None

    if state.get("status") != c.SUPERSEDED:
        latest = c.gh_get_json(f"/repos/{repository}/pulls/{number}")["head"]["sha"]
        if latest != state["head_sha"]:
            state["status"] = c.SUPERSEDED
            state.setdefault("reasons", []).append(f"投稿前にheadが更新された（→ {latest[:7]}）")

    body = render(state, result, run_url)
    (out / "review.md").write_text(body, encoding="utf-8")

    if state["status"] != c.SUPERSEDED:
        cid = find_comment(repository, number)
        if cid:
            c.gh_send_json("PATCH", f"/repos/{repository}/issues/comments/{cid}", {"body": body})
        else:
            c.gh_send_json("POST", f"/repos/{repository}/issues/{number}/comments", {"body": body})
        state["comment"] = "updated" if cid else "created"

    state["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    c.save_state(out, state)
    (out / "meta.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(body)
    c.notice(f"PR #{number} status={state['status']} verdict={state.get('verdict', '-')} head={state['head_sha'][:7]}")
    return 0 if state["status"] in c.NON_FAILING_STATES else 1


if __name__ == "__main__":
    sys.exit(main())
