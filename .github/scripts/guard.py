"""PRの検査とSHAの確定（設計書 v0.2.1 §3.2）。

APIで再検査し、条件を満たさなければ BLOCKED として job を失敗させる。
PR由来の文字列はコマンドに埋め込まず、データとしてのみ扱う。
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c  # noqa: E402


def check(pr: dict, repository: str) -> list[str]:
    reasons = []
    head_repo = ((pr.get("head") or {}).get("repo") or {}).get("full_name")
    if head_repo != repository:
        reasons.append("フォーク（別リポジトリ）からのPR")
    if (pr.get("base") or {}).get("ref") != "main":
        reasons.append("宛先がmainではない")
    if pr.get("state") != "open":
        reasons.append("PRがオープンではない")
    if pr.get("draft"):
        reasons.append("Draft PR")
    return reasons


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)

    number = int(os.environ["PR_NUMBER"])
    repository = c.repo()
    pr = c.gh_get_json(f"/repos/{repository}/pulls/{number}")
    reasons = check(pr, repository)

    head_sha = pr["head"]["sha"]
    state = {
        "status": c.BLOCKED if reasons else c.PENDING,
        "reasons": reasons,
        "pr_number": number,
        "head_sha": head_sha,
        "base_sha": pr["base"]["sha"],
        "changed_files": pr.get("changed_files"),
        "additions": pr.get("additions"),
        "deletions": pr.get("deletions"),
        "event": os.environ.get("GITHUB_EVENT_NAME"),
        "actor": os.environ.get("GITHUB_ACTOR"),
        "triggering_actor": os.environ.get("GITHUB_TRIGGERING_ACTOR"),
        "workflow_sha": os.environ.get("TRUSTED_SHA"),
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    c.save_state(a.out, state)
    c.set_output("number", str(number))
    c.set_output("head_short", head_sha[:7])
    c.set_output("ok", "false" if reasons else "true")
    if reasons:
        print(f"::error::対象外のPRのため中止: {' / '.join(reasons)}")
        return 1
    c.notice(f"PR #{number} head={head_sha[:7]} base={state['base_sha'][:7]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
