"""共通処理（Python標準ライブラリのみ）。

方針:
- 認証情報（GH_TOKEN / GEMINI_API_KEY）はHTTPヘッダーでのみ送り、ログ・ファイルに書かない。
- 状態は out ディレクトリの state.json に集約し、各スクリプトが読み書きする。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

API_URL = os.environ.get("GITHUB_API_URL", "https://api.github.com")

# 状態の定義（設計書 v0.2.1 §5.0）
COMPLETED = "COMPLETED"
INCOMPLETE_DIFF = "INCOMPLETE_DIFF"
SUPERSEDED = "SUPERSEDED"
RATE_LIMITED = "RATE_LIMITED"
API_ERROR = "API_ERROR"
INVALID_OUTPUT = "INVALID_OUTPUT"
BLOCKED = "BLOCKED"
BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"
BUDGET_CHECK_FAILED = "BUDGET_CHECK_FAILED"
OUTSIDE_POC_PERIOD = "OUTSIDE_POC_PERIOD"  # PoC実行期間外（Geminiを呼ばない）
PENDING = "PENDING"  # 差分取得は完了し、Gemini呼び出し前

# レビュー完了扱いにしてよい状態はこれだけ
SUCCESS_STATES = {COMPLETED}
# job を成功で終えてよい状態（SUPERSEDED は新しい実行に任せる）
NON_FAILING_STATES = {COMPLETED, SUPERSEDED}


class HttpError(Exception):
    def __init__(self, status: int, reason: str = "", body: bytes = b""):
        super().__init__(f"HTTP {status} {reason}".strip())
        self.status = status
        self.reason = reason
        self.body = body


def http_request(method: str, url: str, headers: dict | None = None,
                 data: bytes | None = None, timeout: int = 60) -> tuple[int, dict, bytes]:
    """HTTPリクエスト。テストではこの関数を差し替える。

    例外メッセージにはURLとステータスのみを含め、ヘッダー（認証情報）は含めない。
    """
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as e:  # noqa: PERF203
        body = b""
        try:
            body = e.read()
        except Exception:  # pragma: no cover
            pass
        raise HttpError(e.code, str(e.reason), body) from None
    except urllib.error.URLError as e:
        raise HttpError(0, f"network error: {type(e.reason).__name__}") from None


def gh_headers(accept: str = "application/vnd.github+json") -> dict:
    token = os.environ.get("GH_TOKEN", "")
    h = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "ai-review-poc"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def gh_get_json(path: str, params: str = ""):
    url = f"{API_URL}{path}" + (f"?{params}" if params else "")
    _, _, body = http_request("GET", url, gh_headers())
    return json.loads(body.decode("utf-8"))


def gh_get_text(path: str, accept: str) -> bytes:
    _, _, body = http_request("GET", f"{API_URL}{path}", gh_headers(accept))
    return body


def gh_send_json(method: str, path: str, payload: dict):
    data = json.dumps(payload).encode("utf-8")
    headers = gh_headers()
    headers["Content-Type"] = "application/json"
    _, _, body = http_request(method, f"{API_URL}{path}", headers, data)
    return json.loads(body.decode("utf-8")) if body else {}


def repo() -> str:
    return os.environ["GITHUB_REPOSITORY"]


# ---- 状態ファイル ----
def load_state(out_dir: str | Path) -> dict:
    p = Path(out_dir) / "state.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def save_state(out_dir: str | Path, state: dict) -> None:
    p = Path(out_dir)
    p.mkdir(parents=True, exist_ok=True)
    (p / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def set_output(name: str, value: str) -> None:
    """GITHUB_OUTPUT へ書き出す（ローカル実行時は何もしない）。"""
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"{name}={value}\n")


def notice(msg: str) -> None:
    print(f"::notice::{msg}")
