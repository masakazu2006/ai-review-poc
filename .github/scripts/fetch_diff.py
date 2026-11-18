"""差分の取得と完全性の照合（設計書 v0.2.1 §5.0）。

- 差分本文: Compare API（base_sha...head_sha, diff形式）
- 照合元:   PR Files API（per_page=50、全ページ）と PR API の changed_files / additions / deletions
1つでも不一致・欠落・取得失敗があれば INCOMPLETE_DIFF。切り詰めた差分は作らない。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import common as c  # noqa: E402

FILES_PER_PAGE = 50          # 1ページの件数が多いと patch が欠けることがあるため固定
FILES_API_MAX = 3000         # Files API の上限


def parse_diff(text: str) -> tuple[dict[str, dict], list[str]]:
    """unified diff をファイル単位に集計する。戻り値: ({path: {add, del}}, 問題点)"""
    files: dict[str, dict] = {}
    problems: list[str] = []
    cur = None
    in_hunk = False
    for line in text.split("\n"):
        if line.startswith("diff --git "):
            in_hunk = False
            m = re.match(r"^diff --git a/(.+) b/(.+)$", line)
            if not m or line[len("diff --git "):].startswith('"'):
                problems.append("解析できないファイル見出し（引用符付きのパス等）")
                cur = None
                continue
            cur = m.group(2)
            files[cur] = {"add": 0, "del": 0}
            continue
        if cur is None:
            continue
        if line.startswith("Binary files ") or line.startswith("GIT binary patch"):
            problems.append(f"バイナリ差分: {cur}")
            continue
        if line.startswith("@@"):
            in_hunk = True
            continue
        if not in_hunk:
            continue
        if line.startswith("+"):
            files[cur]["add"] += 1
        elif line.startswith("-"):
            files[cur]["del"] += 1
    return files, problems


def fetch_files_list(repository: str, number: int) -> tuple[list[dict], list[str]]:
    files: list[dict] = []
    problems: list[str] = []
    page = 1
    while True:
        batch = c.gh_get_json(f"/repos/{repository}/pulls/{number}/files",
                              f"per_page={FILES_PER_PAGE}&page={page}")
        if not batch:
            break
        files.extend(batch)
        if len(batch) < FILES_PER_PAGE:
            break
        page += 1
    if len(files) >= FILES_API_MAX:
        problems.append(f"Files APIの上限（{FILES_API_MAX}件）に到達")
    return files, problems


def verify(state: dict, diff_files: dict, api_files: list[dict]) -> list[str]:
    problems = []
    api_names = {f["filename"] for f in api_files}
    diff_names = set(diff_files)
    if api_names != diff_names:
        missing = sorted(api_names - diff_names)[:5]
        extra = sorted(diff_names - api_names)[:5]
        problems.append(f"ファイル集合の不一致（差分に無い: {missing} / 一覧に無い: {extra}）")
    if state.get("changed_files") is not None and len(api_files) != state["changed_files"]:
        problems.append(f"ファイル数の不一致（一覧 {len(api_files)} / PR {state['changed_files']}）")
    for f in api_files:
        name = f["filename"]
        if f.get("changes", 0) > 0 and "patch" not in f:
            problems.append(f"patch省略（バイナリまたは大きすぎる）: {name}")
        d = diff_files.get(name)
        if d and (d["add"] != f.get("additions") or d["del"] != f.get("deletions")):
            problems.append(f"行数の不一致: {name}（差分 +{d['add']}/-{d['del']}, 一覧 +{f.get('additions')}/-{f.get('deletions')}）")
    tot_add = sum(v["add"] for v in diff_files.values())
    tot_del = sum(v["del"] for v in diff_files.values())
    if state.get("additions") is not None and (tot_add, tot_del) != (state["additions"], state["deletions"]):
        problems.append(f"合計行数の不一致（差分 +{tot_add}/-{tot_del}, PR +{state['additions']}/-{state['deletions']}）")
    return problems


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--diff-out", required=True)
    ap.add_argument("--max-bytes", type=int, default=102400)
    a = ap.parse_args(argv)

    state = c.load_state(a.out)
    repository = c.repo()
    number, base, head = state["pr_number"], state["base_sha"], state["head_sha"]
    problems: list[str] = []
    diff_files: dict = {}
    api_files: list[dict] = []

    try:
        cmp_json = c.gh_get_json(f"/repos/{repository}/compare/{base}...{head}", "per_page=1")
        state["merge_base_sha"] = (cmp_json.get("merge_base_commit") or {}).get("sha")
    except c.HttpError as e:
        problems.append(f"Compare API（JSON）取得失敗: HTTP {e.status}")

    raw = b""
    try:
        raw = c.gh_get_text(f"/repos/{repository}/compare/{base}...{head}", "application/vnd.github.diff")
    except c.HttpError as e:
        problems.append(f"差分本文の取得失敗: HTTP {e.status}" + ("（diff too large）" if e.status == 406 else ""))

    if raw and len(raw) > a.max_bytes:
        problems.append(f"差分が上限を超過（{len(raw)} > {a.max_bytes} bytes）。切り詰めは行わない")
    elif raw:
        try:
            diff_files, p = parse_diff(raw.decode("utf-8"))
            problems += p
        except UnicodeDecodeError:
            problems.append("差分本文がUTF-8として読めない")

    try:
        api_files, p = fetch_files_list(repository, number)
        problems += p
    except c.HttpError as e:
        problems.append(f"Files API取得失敗: HTTP {e.status}")

    if not problems:
        problems += verify(state, diff_files, api_files)

    state["diff_bytes"] = len(raw)
    state["verification"] = {
        "files_api": len(api_files), "files_diff": len(diff_files), "files_pr": state.get("changed_files"),
        "additions_diff": sum(v["add"] for v in diff_files.values()),
        "deletions_diff": sum(v["del"] for v in diff_files.values()),
        "additions_pr": state.get("additions"), "deletions_pr": state.get("deletions"),
        "ok": not problems,
    }
    Path(a.out).mkdir(parents=True, exist_ok=True)
    (Path(a.out) / "files.json").write_text(json.dumps(
        [{k: f.get(k) for k in ("filename", "status", "additions", "deletions", "changes", "previous_filename")}
         | {"has_patch": "patch" in f} for f in api_files], ensure_ascii=False, indent=2), encoding="utf-8")

    # 取得完了後に head の移動を確認
    if not problems:
        try:
            latest = c.gh_get_json(f"/repos/{repository}/pulls/{number}")["head"]["sha"]
            if latest != head:
                state["status"] = c.SUPERSEDED
                state["reasons"] = [f"取得中にheadが更新された（{head[:7]} → {latest[:7]}）"]
        except c.HttpError as e:
            problems.append(f"head再確認の失敗: HTTP {e.status}")

    if problems:
        state["status"] = c.INCOMPLETE_DIFF
        state["reasons"] = problems
    elif state.get("status") != c.SUPERSEDED:
        Path(a.diff_out).write_bytes(raw)
        state["status"] = c.PENDING

    c.save_state(a.out, state)
    c.set_output("status", state["status"])
    if state["status"] == c.PENDING:
        c.notice(f"差分の照合OK: {len(api_files)}ファイル +{state['verification']['additions_diff']}/-{state['verification']['deletions_diff']}")
    else:
        print(f"::warning::{state['status']}: {' / '.join(state.get('reasons', []))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
