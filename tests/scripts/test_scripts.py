"""レビュー用スクリプトの単体テスト（ネットワーク非接続。HTTPは模擬応答に差し替え）。"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / ".github" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import budget  # noqa: E402
import common as c  # noqa: E402
import fetch_diff  # noqa: E402
import gemini_review  # noqa: E402
import guard  # noqa: E402
import post_comment  # noqa: E402

REPO = "masakazu2006/ai-review-poc"
FAKE_KEY = "AIzaFAKE_TEST_KEY_DO_NOT_LEAK_1234567890"
HEAD, BASE, MB = "h" * 40, "b" * 40, "m" * 40

DIFF_OK = """diff --git a/poc_app/a.py b/poc_app/a.py
index 1..2 100644
--- a/poc_app/a.py
+++ b/poc_app/a.py
@@ -1,2 +1,3 @@
 x = 1
-y = 2
+y = 3
+z = 4
diff --git a/README.md b/README.md
--- a/README.md
+++ b/README.md
@@ -1 +1 @@
-old
+new
"""


def pr_obj(**kw):
    d = {"number": 5, "state": "open", "draft": False, "changed_files": 2, "additions": 3, "deletions": 2,
         "head": {"sha": HEAD, "ref": "t", "repo": {"full_name": REPO}},
         "base": {"sha": BASE, "ref": "main", "repo": {"full_name": REPO}}}
    for k, v in kw.items():
        d[k] = v
    return d


FILES_OK = [
    {"filename": "poc_app/a.py", "status": "modified", "additions": 2, "deletions": 1, "changes": 3, "patch": "@@"},
    {"filename": "README.md", "status": "modified", "additions": 1, "deletions": 1, "changes": 2, "patch": "@@"},
]


class FakeHttp:
    """(method, パスの部分文字列) → 応答 or 例外。呼び出し履歴を記録する。"""

    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, method, url, headers=None, data=None, timeout=60):
        self.calls.append({"method": method, "url": url, "headers": dict(headers or {}), "data": data})
        for (m, frag), resp in self.routes:
            if m == method and frag in url:
                if callable(resp):
                    resp = resp(url, headers, data)
                if isinstance(resp, Exception):
                    raise resp
                body = resp if isinstance(resp, bytes) else json.dumps(resp).encode("utf-8")
                return 200, {}, body
        raise AssertionError(f"未定義のリクエスト: {method} {url}")


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "out"
        self.env = {"GITHUB_REPOSITORY": REPO, "GH_TOKEN": "ghs_fake", "PR_NUMBER": "5",
                    "GITHUB_RUN_ID": "100", "GITHUB_RUN_ATTEMPT": "1", "TRUSTED_SHA": "w" * 40}
        self._old_env = dict(os.environ)
        os.environ.update(self.env)
        os.environ.pop("GITHUB_OUTPUT", None)
        os.environ.pop("GITHUB_STEP_SUMMARY", None)
        self._orig_http = c.http_request

    def tearDown(self):
        c.http_request = self._orig_http
        os.environ.clear()
        os.environ.update(self._old_env)
        self.tmp.cleanup()

    def use(self, routes):
        fake = FakeHttp(routes)
        c.http_request = fake
        return fake

    def run_quiet(self, fn, *args):
        with redirect_stdout(io.StringIO()) as buf:
            rc = fn(*args)
        return rc, buf.getvalue()

    def state(self):
        return c.load_state(self.out)

    def guard_ok(self, pr=None):
        self.use([(("GET", "/pulls/5"), pr or pr_obj())])
        return self.run_quiet(guard.main, ["--out", str(self.out)])


class TestGuard(Base):
    def test_ok(self):
        rc, _ = self.guard_ok()
        self.assertEqual(rc, 0)
        self.assertEqual(self.state()["status"], c.PENDING)
        self.assertEqual(self.state()["workflow_sha"], "w" * 40)

    def test_fork_rejected(self):
        pr = pr_obj(head={"sha": HEAD, "ref": "t", "repo": {"full_name": "someone/fork"}})
        rc, _ = self.guard_ok(pr)
        self.assertEqual(rc, 1)
        self.assertEqual(self.state()["status"], c.BLOCKED)

    def test_non_main_and_draft_rejected(self):
        pr = pr_obj(draft=True, base={"sha": BASE, "ref": "dev", "repo": {"full_name": REPO}})
        rc, _ = self.guard_ok(pr)
        self.assertEqual(rc, 1)
        self.assertEqual(len(self.state()["reasons"]), 2)


class TestFetchDiff(Base):
    def run_fetch(self, diff=DIFF_OK, files=FILES_OK, pr_after=None, diff_exc=None, max_bytes=102400):
        self.guard_ok()
        diff_resp = diff_exc if diff_exc else diff.encode("utf-8")
        routes = [
            (("GET", "/pulls/5/files"), lambda u, h, d: files if "page=1" in u else []),
            (("GET", "/pulls/5"), pr_after or pr_obj()),
        ]

        def compare(u, h, d):
            return diff_resp if h.get("Accept") == "application/vnd.github.diff" else {"merge_base_commit": {"sha": MB}}
        routes.append((("GET", f"/compare/{BASE}...{HEAD}"), compare))
        self.use(routes)
        diff_out = Path(self.tmp.name) / "pr.diff"
        rc, _ = self.run_quiet(fetch_diff.main, ["--out", str(self.out), "--diff-out", str(diff_out),
                                                 "--max-bytes", str(max_bytes)])
        return rc, diff_out

    def test_complete(self):
        rc, diff_out = self.run_fetch()
        st = self.state()
        self.assertEqual(st["status"], c.PENDING, st.get("reasons"))
        self.assertEqual(st["merge_base_sha"], MB)
        self.assertTrue(st["verification"]["ok"])
        self.assertTrue(diff_out.exists())

    def test_too_large_406(self):
        _, diff_out = self.run_fetch(diff_exc=c.HttpError(406, "Not Acceptable"))
        self.assertEqual(self.state()["status"], c.INCOMPLETE_DIFF)
        self.assertFalse(diff_out.exists())

    def test_size_cap_no_truncation(self):
        _, diff_out = self.run_fetch(max_bytes=50)
        self.assertEqual(self.state()["status"], c.INCOMPLETE_DIFF)
        self.assertFalse(diff_out.exists())

    def test_missing_patch(self):
        files = [dict(FILES_OK[0]), {k: v for k, v in FILES_OK[1].items() if k != "patch"}]
        self.run_fetch(files=files)
        self.assertEqual(self.state()["status"], c.INCOMPLETE_DIFF)

    def test_file_set_mismatch(self):
        self.run_fetch(files=[FILES_OK[0]])
        self.assertEqual(self.state()["status"], c.INCOMPLETE_DIFF)

    def test_line_count_mismatch(self):
        files = [dict(FILES_OK[0], additions=5), FILES_OK[1]]
        self.run_fetch(files=files)
        self.assertEqual(self.state()["status"], c.INCOMPLETE_DIFF)

    def test_binary(self):
        diff = DIFF_OK + "diff --git a/img.png b/img.png\nBinary files a/img.png and b/img.png differ\n"
        files = FILES_OK + [{"filename": "img.png", "status": "added", "additions": 0, "deletions": 0, "changes": 0}]
        self.run_fetch(diff=diff, files=files)
        self.assertEqual(self.state()["status"], c.INCOMPLETE_DIFF)

    def test_head_moved(self):
        pr_after = pr_obj(head={"sha": "n" * 40, "ref": "t", "repo": {"full_name": REPO}})
        # guard は元のheadで確定済み、照合後の再確認で新しいheadを返す
        self.guard_ok()
        calls = {"n": 0}

        def pulls(u, h, d):
            calls["n"] += 1
            return pr_after
        self.use([
            (("GET", "/pulls/5/files"), lambda u, h, d: FILES_OK if "page=1" in u else []),
            (("GET", "/pulls/5"), pulls),
            (("GET", "/compare/"), lambda u, h, d: DIFF_OK.encode() if h.get("Accept") == "application/vnd.github.diff"
             else {"merge_base_commit": {"sha": MB}}),
        ])
        self.run_quiet(fetch_diff.main, ["--out", str(self.out), "--diff-out", str(Path(self.tmp.name) / "d")])
        self.assertEqual(self.state()["status"], c.SUPERSEDED)


class TestBudget(Base):
    """予約記録コメント方式の呼び出し回数管理。"""
    IN_PERIOD = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)
    BOT = "github-actions[bot]"

    def setUp(self):
        super().setUp()
        self._orig_now = budget.now_utc
        budget.now_utc = lambda: self.IN_PERIOD

    def tearDown(self):
        budget.now_utc = self._orig_now
        super().tearDown()

    def ledger(self, n, user=None):
        return [{"id": 1000 + i, "user": {"login": user or self.BOT},
                 "body": budget.LEDGER_MARKER + f"\n予約 {i}"} for i in range(n)]

    def run_budget(self, comments, list_exc=None, post_resp=None, post_exc=None, now=None):
        self.guard_ok()
        if now:
            budget.now_utc = lambda: now

        def listing(u, h, d):
            if list_exc:
                return list_exc
            from urllib.parse import parse_qs, urlparse
            page = int(parse_qs(urlparse(u).query)["page"][0])
            return comments[(page - 1) * 100: page * 100]

        def post(u, h, d):
            if post_exc:
                return post_exc
            return post_resp if post_resp is not None else {"id": 777}
        fake = self.use([
            (("GET", "/issues/comments?"), listing),
            (("POST", "/issues/5/comments"), post),
        ])
        rc, out = self.run_quiet(budget.main, ["--out", str(self.out)])
        return fake, rc, out

    def posts(self, fake):
        return [x for x in fake.calls if x["method"] == "POST"]

    def test_baseline_carried_over(self):
        # 導入前の実績4回を引き継ぎ、最初の予約は 5/70 になる
        self.assertEqual(budget.LEDGER_BASELINE, 4)
        fake, _, _ = self.run_budget([])
        st = self.state()
        self.assertEqual(st["budget"]["used_before"], 4)
        self.assertEqual(st["budget"]["sequence"], 5)
        body = json.loads(self.posts(fake)[0]["data"])["body"]
        self.assertTrue(body.startswith(budget.LEDGER_MARKER))
        self.assertIn("5/70", body)
        self.assertIn("attempt `1`", body)
        self.assertEqual(st["ledger_comment_id"], 777)

    def test_counts_across_pages_and_ignores_others(self):
        noise = [{"id": 1, "user": {"login": "masakazu2006"}, "body": "普通のコメント"}] * 150
        fake, _, _ = self.run_budget(self.ledger(60) + noise)   # 2ページ目にまたがる
        self.assertEqual(self.state()["budget"]["used_before"], 64)
        self.assertEqual(len(self.posts(fake)), 1)

    def test_limit_reached_no_post(self):
        fake, _, _ = self.run_budget(self.ledger(66))          # 4 + 66 = 70
        self.assertEqual(self.state()["status"], c.BUDGET_EXHAUSTED)
        self.assertEqual(self.posts(fake), [])

    def test_last_call_allowed(self):
        self.run_budget(self.ledger(65))                        # 4 + 65 = 69 → 70回目は許可
        self.assertEqual(self.state()["budget"]["sequence"], 70)

    def test_marker_by_non_bot_not_counted(self):
        # bot以外が目印付きコメントを書いても件数は増減しない
        fake, _, _ = self.run_budget(self.ledger(5, user="masakazu2006") + self.ledger(2))
        self.assertEqual(self.state()["budget"]["used_before"], 6)

    def test_marker_not_at_start_not_counted(self):
        quoted = [{"id": 9, "user": {"login": self.BOT}, "body": "引用: " + budget.LEDGER_MARKER}]
        self.run_budget(quoted)
        self.assertEqual(self.state()["budget"]["used_before"], 4)

    def test_rerun_is_counted(self):
        # 再実行（attempt 2）でも、前の試行の予約記録コメントは残り、数えられる
        os.environ["GITHUB_RUN_ATTEMPT"] = "2"
        prev = self.ledger(1)
        fake, _, _ = self.run_budget(prev)
        self.assertEqual(self.state()["budget"]["sequence"], 6)
        self.assertIn("attempt `2`", json.loads(self.posts(fake)[0]["data"])["body"])

    def test_list_failure_fail_closed(self):
        fake, _, _ = self.run_budget([], list_exc=c.HttpError(500))
        self.assertEqual(self.state()["status"], c.BUDGET_CHECK_FAILED)
        self.assertEqual(self.posts(fake), [])

    def test_post_failure_fail_closed(self):
        self.run_budget([], post_exc=c.HttpError(403))
        st = self.state()
        self.assertEqual(st["status"], c.BUDGET_CHECK_FAILED)
        self.assertNotIn("ledger_comment_id", st)

    def test_post_without_id_fail_closed(self):
        self.run_budget([], post_resp={})
        self.assertEqual(self.state()["status"], c.BUDGET_CHECK_FAILED)

    def test_after_end_denied_without_api_call(self):
        fake, _, _ = self.run_budget([], now=budget.POC_END)
        self.assertEqual(self.state()["status"], c.OUTSIDE_POC_PERIOD)
        self.assertEqual(fake.calls, [])

    def test_before_start_denied(self):
        fake, _, _ = self.run_budget([], now=budget.POC_START - timedelta(seconds=1))
        self.assertEqual(self.state()["status"], c.OUTSIDE_POC_PERIOD)
        self.assertEqual(fake.calls, [])

    def test_period_edges_allowed(self):
        self.run_budget([], now=budget.POC_START)
        self.assertEqual(self.state()["budget"]["sequence"], 5)

    def test_workflow_uses_ledger_without_extra_permissions(self):
        wf = (SCRIPTS.parent / "workflows" / "gemini-pr-review.yml").read_text(encoding="utf-8")
        self.assertNotIn("Reserve one Gemini call", wf)
        self.assertNotIn("actions: read", wf)
        self.assertNotIn("issues: write", wf)
        self.assertIn("if: steps.budget.outputs.allowed == 'true'", wf)

def gemini_ok_response(result, usage=None):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(result, ensure_ascii=False)}]}, "finishReason": "STOP"}],
            "usageMetadata": usage or {"promptTokenCount": 5000, "candidatesTokenCount": 1500,
                                       "thoughtsTokenCount": 1500, "totalTokenCount": 8000},
            "modelVersion": "gemini-3.8-flash"}


class TestGemini(Base):
    def run_gemini(self, resp):
        self.guard_ok()
        diff = Path(self.tmp.name) / "pr.diff"
        diff.write_text(DIFF_OK, encoding="utf-8")
        crit = Path(self.tmp.name) / "criteria.md"
        crit.write_text("基準", encoding="utf-8")
        os.environ["GEMINI_API_KEY"] = FAKE_KEY
        os.environ["GEMINI_MODEL"] = "gemini-3.8-flash"
        fake = self.use([(("POST", "generativelanguage.googleapis.com"), resp)])
        _, out = self.run_quiet(gemini_review.main, ["--out", str(self.out), "--diff", str(diff), "--criteria", str(crit)])
        return fake, out

    def test_success_and_key_only_in_header(self):
        result = {"verdict": "要修正", "summary": "s", "findings": [
            {"severity": "high", "file": "poc_app/a.py", "line": 2, "category": "正しさ", "message": "m"}]}
        fake, _ = self.run_gemini(gemini_ok_response(result))
        st = self.state()
        self.assertEqual(st["status"], c.COMPLETED)
        self.assertEqual(st["usage"]["thoughts"], 1500)
        self.assertAlmostEqual(st["estimated_cost_usd_if_paid"], 5000 / 1e6 * 0.75 + 3000 / 1e6 * 3.75)
        call = fake.calls[0]
        self.assertNotIn(FAKE_KEY, call["url"])
        self.assertEqual(call["headers"]["x-goog-api-key"], FAKE_KEY)
        self.assertEqual(len(fake.calls), 1)   # 1 job 1回

    def test_rate_limited_no_retry(self):
        err = c.HttpError(429, "Too Many Requests", json.dumps({"error": {"status": "RESOURCE_EXHAUSTED"}}).encode())
        fake, _ = self.run_gemini(err)
        self.assertEqual(self.state()["status"], c.RATE_LIMITED)
        self.assertEqual(len(fake.calls), 1)

    def test_invalid_output(self):
        self.run_gemini(gemini_ok_response({"verdict": "たぶんOK", "summary": "s", "findings": []}))
        self.assertEqual(self.state()["status"], c.INVALID_OUTPUT)

    def test_timeout_recorded_accurately(self):
        # 2026-11-18 スモークテストで発生した事象（応答待ちタイムアウト）の再現
        fake, stdout = self.run_gemini(c.HttpError(0, "timeout (180s)"))
        st = self.state()
        self.assertEqual(st["status"], c.API_ERROR)
        self.assertIn("タイムアウト（180秒）", st["reasons"][0])
        self.assertEqual(st["model"], "gemini-3.8-flash")
        self.assertTrue(st["gemini_attempted"])
        self.assertEqual(len(fake.calls), 1)               # 再試行しない
        self.assertNotIn(FAKE_KEY, stdout)

    def test_network_error_recorded(self):
        self.run_gemini(c.HttpError(0, "network error: ConnectionResetError"))
        st = self.state()
        self.assertEqual(st["status"], c.API_ERROR)
        self.assertIn("通信エラー", st["reasons"][0])

    def test_unexpected_exception_recorded_without_key(self):
        def boom(u, h, d):
            raise RuntimeError(f"secret in message {FAKE_KEY}")
        _, stdout = self.run_gemini(boom)
        st = self.state()
        self.assertEqual(st["status"], c.API_ERROR)
        self.assertEqual(st["reasons"], ["予期しない例外: RuntimeError"])
        self.assertTrue(st["gemini_attempted"])
        self.assertNotIn(FAKE_KEY, stdout)
        for p in self.out.rglob("*"):
            if p.is_file():
                self.assertNotIn(FAKE_KEY, p.read_text(encoding="utf-8"))

    # ---- 思考レベル（PR #5） ----
    def sent_body(self, fake):
        return json.loads(fake.calls[0]["data"])

    def ok(self):
        return gemini_ok_response({"verdict": "OK", "summary": "s", "findings": []})

    def test_thinking_level_low_by_default(self):
        os.environ.pop("GEMINI_THINKING_LEVEL", None)
        fake, _ = self.run_gemini(self.ok())
        gen = self.sent_body(fake)["generationConfig"]
        self.assertEqual(gen["thinkingConfig"], {"thinkingLevel": "LOW"})
        self.assertEqual(gen["responseMimeType"], "application/json")   # 既存の設定は維持
        self.assertIn("responseSchema", gen)
        self.assertEqual(self.state()["thinking_level"], "LOW")

    def test_thinking_level_empty_variable_means_low(self):
        os.environ["GEMINI_THINKING_LEVEL"] = "  "
        fake, _ = self.run_gemini(self.ok())
        self.assertEqual(self.sent_body(fake)["generationConfig"]["thinkingConfig"]["thinkingLevel"], "LOW")

    def test_thinking_level_medium_for_comparison(self):
        os.environ["GEMINI_THINKING_LEVEL"] = "medium"            # 小文字も受け付けて正規化
        fake, _ = self.run_gemini(self.ok())
        self.assertEqual(self.sent_body(fake)["generationConfig"]["thinkingConfig"]["thinkingLevel"], "MEDIUM")
        self.assertEqual(self.state()["thinking_level"], "MEDIUM")

    def test_thinking_level_model_default_omits_config(self):
        os.environ["GEMINI_THINKING_LEVEL"] = "MODEL_DEFAULT"
        fake, _ = self.run_gemini(self.ok())
        self.assertNotIn("thinkingConfig", self.sent_body(fake)["generationConfig"])
        self.assertEqual(self.state()["thinking_level"], "MODEL_DEFAULT")

    def test_thinking_level_invalid_no_request(self):
        os.environ["GEMINI_THINKING_LEVEL"] = "ULTRA"
        fake, _ = self.run_gemini(self.ok())
        st = self.state()
        self.assertEqual(fake.calls, [])                          # 送信しない
        self.assertEqual(st["status"], c.API_ERROR)
        self.assertEqual(st["thinking_level"], "INVALID")
        self.assertNotIn("gemini_attempted", st)

    def test_thinking_tokens_recorded(self):
        os.environ.pop("GEMINI_THINKING_LEVEL", None)
        usage = {"promptTokenCount": 4000, "candidatesTokenCount": 100, "thoughtsTokenCount": 250, "totalTokenCount": 4350}
        self.run_gemini(gemini_ok_response({"verdict": "OK", "summary": "s", "findings": []}, usage))
        st = self.state()
        self.assertEqual(st["usage"]["thoughts"], 250)
        self.assertEqual(st["thinking_level"], "LOW")
        self.assertIn("duration_sec", st)

    def test_out_dir_from_args_boundaries(self):
        f = gemini_review.out_dir_from_args
        self.assertEqual(f(["--diff", "d", "--out", "o"]), "o")
        self.assertEqual(f(["--out=o", "--diff", "d"]), "o")
        self.assertIsNone(f(["--diff", "d", "--out"]))          # 末尾で値なし（指摘のケース）
        self.assertIsNone(f(["--out", "--diff", "d"]))          # 次のオプションを値と誤認しない
        self.assertIsNone(f(["--out="]))
        self.assertIsNone(f(["--out", ""]))
        self.assertIsNone(f([]))

    def test_exception_handler_with_missing_out_value(self):
        # run() が例外を出し、かつ --out が末尾で値なしでも、ハンドラ自体は異常終了しない
        orig = gemini_review.run

        def boom(argv=None):
            raise RuntimeError("x")
        gemini_review.run = boom
        try:
            rc, out = self.run_quiet(gemini_review.main, ["--diff", "d", "--out"])
        finally:
            gemini_review.run = orig
        self.assertEqual(rc, 0)
        self.assertIn("予期しない例外 RuntimeError", out)

    def test_exception_handler_survives_unwritable_out(self):
        orig = gemini_review.run

        def boom(argv=None):
            raise RuntimeError("x")
        gemini_review.run = boom
        blocker = Path(self.tmp.name) / "file_not_dir"
        blocker.write_text("x", encoding="utf-8")
        try:
            rc, out = self.run_quiet(gemini_review.main, ["--out", str(blocker / "sub")])
        finally:
            gemini_review.run = orig
        self.assertEqual(rc, 0)
        self.assertIn("状態の保存に失敗", out)

    def test_success_clears_placeholder_reason(self):
        self.run_gemini(gemini_ok_response({"verdict": "OK", "summary": "s", "findings": []}))
        self.assertNotIn("reasons", self.state())

    def test_key_not_written_anywhere(self):
        _, stdout = self.run_gemini(c.HttpError(400, "Bad Request", b'{"error":{"status":"INVALID_ARGUMENT"}}'))
        self.assertNotIn(FAKE_KEY, stdout)
        for p in self.out.rglob("*"):
            if p.is_file():
                self.assertNotIn(FAKE_KEY, p.read_text(encoding="utf-8"))


class TestHttpTimeoutMapping(unittest.TestCase):
    """common.http_request が実際のソケットのタイムアウトを HttpError(0, 'timeout') に変換すること。"""

    def test_read_timeout(self):
        import socket
        import threading
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        conns = []

        def accept():
            conn, _ = srv.accept()   # 受け付けるが応答しない
            conns.append(conn)
        th = threading.Thread(target=accept, daemon=True)
        th.start()
        try:
            with self.assertRaises(c.HttpError) as cm:
                self._orig = c.http_request
                c.http_request("POST", f"http://127.0.0.1:{port}/", {}, b"{}", timeout=1)
            self.assertEqual(cm.exception.status, 0)
            self.assertTrue(cm.exception.reason.startswith("timeout"))
        finally:
            for x in conns:
                x.close()
            srv.close()


class TestPostComment(Base):
    def prepare(self, status, result=None, head_after=HEAD, existing=None):
        self.guard_ok()
        st = self.state()
        st["status"] = status
        st["verification"] = {"ok": status == c.COMPLETED}
        if status != c.COMPLETED:
            st["reasons"] = ["理由"]
        c.save_state(self.out, st)
        if result:
            (self.out / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
        return self.use([
            (("GET", "/issues/5/comments"), lambda u, h, d: (existing or []) if "page=1" in u else []),
            (("PATCH", "/issues/comments/"), {"id": 1}),
            (("POST", "/issues/5/comments"), {"id": 2}),
            (("GET", "/pulls/5"), pr_obj(head={"sha": head_after, "ref": "t", "repo": {"full_name": REPO}})),
        ])

    def test_completed_creates_and_sanitizes(self):
        result = {"verdict": "OK", "summary": "@masakazu2006 確認 <!-- x -->", "findings": []}
        fake = self.prepare(c.COMPLETED, result)
        rc, _ = self.run_quiet(post_comment.main, ["--out", str(self.out)])
        self.assertEqual(rc, 0)
        post = [x for x in fake.calls if x["method"] == "POST"][0]
        body = json.loads(post["data"])["body"]
        self.assertIn("判定：OK", body)
        self.assertIn(HEAD, body)
        self.assertNotIn("@masakazu2006", body)
        self.assertEqual(body.count("<!--"), 1)   # マーカーのみ
        self.assertTrue((self.out / "meta.json").exists())

    def test_updates_existing(self):
        existing = [{"id": 9, "user": {"login": "github-actions[bot]"}, "body": post_comment.MARKER + "old"}]
        fake = self.prepare(c.COMPLETED, {"verdict": "OK", "summary": "s", "findings": []}, existing=existing)
        self.run_quiet(post_comment.main, ["--out", str(self.out)])
        self.assertTrue(any(x["method"] == "PATCH" and x["url"].endswith("/comments/9") for x in fake.calls))
        self.assertFalse(any(x["method"] == "POST" for x in fake.calls))

    def test_ignores_marker_from_other_user(self):
        existing = [{"id": 9, "user": {"login": "attacker"}, "body": post_comment.MARKER}]
        fake = self.prepare(c.COMPLETED, {"verdict": "OK", "summary": "s", "findings": []}, existing=existing)
        self.run_quiet(post_comment.main, ["--out", str(self.out)])
        self.assertTrue(any(x["method"] == "POST" for x in fake.calls))

    def test_incomplete_fails_without_verdict(self):
        fake = self.prepare(c.INCOMPLETE_DIFF)
        rc, _ = self.run_quiet(post_comment.main, ["--out", str(self.out)])
        self.assertEqual(rc, 1)
        body = json.loads([x for x in fake.calls if x["method"] == "POST"][0]["data"])["body"]
        self.assertIn("レビュー未完了", body)
        self.assertNotIn("判定：", body)

    def with_ledger(self):
        st = self.state()
        st["ledger_comment_id"] = 777
        st["ledger_body"] = budget.LEDGER_MARKER + "\n予約 5/70"
        st["usage"] = {"input": 10, "output": 2, "thoughts": 3}
        c.save_state(self.out, st)

    def test_ledger_updated_with_result(self):
        fake = self.prepare(c.COMPLETED, {"verdict": "OK", "summary": "s", "findings": []})
        self.with_ledger()
        rc, _ = self.run_quiet(post_comment.main, ["--out", str(self.out)])
        self.assertEqual(rc, 0)
        patch = [x for x in fake.calls if x["method"] == "PATCH" and x["url"].endswith("/comments/777")]
        self.assertEqual(len(patch), 1)
        body = json.loads(patch[0]["data"])["body"]
        self.assertTrue(body.startswith(budget.LEDGER_MARKER))   # 追記後も予約記録として数えられる
        self.assertIn("COMPLETED", body)
        self.assertTrue(self.state()["ledger_updated"])

    def test_thinking_level_shown_in_comment_and_ledger(self):
        fake = self.prepare(c.COMPLETED, {"verdict": "OK", "summary": "s", "findings": []})
        self.with_ledger()
        st = self.state()
        st["thinking_level"] = "LOW"
        c.save_state(self.out, st)
        self.run_quiet(post_comment.main, ["--out", str(self.out)])
        post = json.loads([x for x in fake.calls if x["method"] == "POST"][0]["data"])["body"]
        self.assertIn("| 思考レベル | `LOW` |", post)
        patch = json.loads([x for x in fake.calls if x["method"] == "PATCH" and x["url"].endswith("/comments/777")][0]["data"])["body"]
        self.assertIn("思考レベル LOW", patch)

    def test_ledger_update_failure_does_not_change_result(self):
        self.prepare(c.COMPLETED, {"verdict": "OK", "summary": "s", "findings": []})
        self.with_ledger()

        def fail_patch(u, h, d):
            return c.HttpError(500) if u.endswith("/comments/777") else {"id": 1}
        c.http_request.routes.insert(0, (("PATCH", "/issues/comments/777"), fail_patch))
        rc, out = self.run_quiet(post_comment.main, ["--out", str(self.out)])
        self.assertEqual(rc, 0)
        self.assertFalse(self.state()["ledger_updated"])
        self.assertIn("結果追記に失敗", out)

    def test_ledger_comment_not_mistaken_for_review_comment(self):
        existing = [{"id": 777, "user": {"login": "github-actions[bot]"}, "body": budget.LEDGER_MARKER + "\n予約"}]
        fake = self.prepare(c.COMPLETED, {"verdict": "OK", "summary": "s", "findings": []}, existing=existing)
        self.run_quiet(post_comment.main, ["--out", str(self.out)])
        self.assertTrue(any(x["method"] == "POST" for x in fake.calls))   # 予約記録を上書きしない

    def test_superseded_skips_post(self):
        fake = self.prepare(c.COMPLETED, {"verdict": "OK", "summary": "s", "findings": []}, head_after="n" * 40)
        rc, _ = self.run_quiet(post_comment.main, ["--out", str(self.out)])
        self.assertEqual(rc, 0)
        self.assertFalse(any(x["method"] in ("POST", "PATCH") for x in fake.calls))
        self.assertEqual(self.state()["status"], c.SUPERSEDED)


if __name__ == "__main__":
    unittest.main()
