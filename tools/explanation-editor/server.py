from __future__ import annotations

import argparse
import json
import mimetypes
import re
import secrets
import sys
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


ROOT = Path(__file__).resolve().parents[2]
TOOLS_DIR = ROOT / "tools"
sys.path.insert(0, str(TOOLS_DIR))

from explanation_editor_core import (  # noqa: E402
    EditorError,
    apply_publication,
    atomic_write_json,
    build_publication_plan,
    decode_image_data,
    empty_public,
    empty_workspace,
    ensure_within,
    import_missing_public_items,
    item_state,
    normalize_workspace_item,
    now_iso,
    read_json,
    reconcile_workspace,
    run_process,
    save_local_asset,
    validate_question_id,
    validate_workspace,
)


EDITOR_DIR = Path(__file__).resolve().parent
QUESTIONS_PATH = ROOT / "site" / "data" / "questions.json"
PUBLIC_PATH = ROOT / "site" / "data" / "explanations.json"
WORKSPACE_PATH = ROOT / "local-data" / "explanations-workspace.json"
LOCAL_ASSET_ROOT = ROOT / "local-data" / "explanation-assets"
MAX_REQUEST_BYTES = 12 * 1024 * 1024
COMMIT_MESSAGE = "content: update question explanations"


def load_questions() -> tuple[dict, set[str]]:
    payload = read_json(QUESTIONS_PATH, {})
    questions = payload.get("questions")
    if payload.get("schema_version") != 1 or not isinstance(questions, list):
        raise EditorError("questions.json 格式不正確")
    ids = {question.get("id") for question in questions if isinstance(question, dict)}
    if len(ids) != len(questions) or None in ids:
        raise EditorError("questions.json 包含空白或重複 ID")
    return payload, ids


def load_state() -> tuple[dict, dict, dict, set[str]]:
    questions, valid_ids = load_questions()
    workspace = validate_workspace(read_json(WORKSPACE_PATH, empty_workspace()), valid_ids)
    public_payload = read_json(PUBLIC_PATH, empty_public())
    if import_missing_public_items(ROOT, workspace, public_payload):
        atomic_write_json(WORKSPACE_PATH, workspace)
    return questions, workspace, public_payload, valid_ids


def save_workspace(workspace: dict) -> None:
    workspace["updated_at"] = now_iso()
    atomic_write_json(WORKSPACE_PATH, workspace)


def git_args(*parts: str) -> list[str]:
    return ["git", "-c", f"safe.directory={ROOT.as_posix()}", *parts]


def repository_info() -> dict[str, str]:
    fallback = {
        "repository_url": "https://github.com/TEA-CARSON/ai-application-planner-middle-exam",
        "site_url": "https://tea-carson.github.io/ai-application-planner-middle-exam/",
        "actions_url": "https://github.com/TEA-CARSON/ai-application-planner-middle-exam/actions",
    }
    try:
        remote = run_process(git_args("remote", "get-url", "origin"), ROOT).stdout.strip()
    except EditorError:
        return fallback
    match = re.search(r"github\.com[/:]([^/]+)/([^/]+?)(?:\.git)?$", remote)
    if not match:
        return fallback
    owner, repository = match.groups()
    return {
        "repository_url": f"https://github.com/{owner}/{repository}",
        "site_url": f"https://{owner.lower()}.github.io/{repository}/",
        "actions_url": f"https://github.com/{owner}/{repository}/actions",
    }


def branch_counts() -> tuple[int, int]:
    output = run_process(
        git_args("rev-list", "--left-right", "--count", "HEAD...origin/main"),
        ROOT,
    ).stdout.strip()
    try:
        ahead, behind = [int(value) for value in output.split()]
    except (TypeError, ValueError) as exc:
        raise EditorError("無法判斷本機與 GitHub 分支差異") from exc
    return ahead, behind


def deployment_status(commit: str) -> dict:
    info = repository_info()
    try:
        result = run_process(
            [
                "gh", "run", "list", "--commit", commit, "--workflow", "pages.yml",
                "--limit", "1", "--json", "status,conclusion,url",
            ],
            ROOT,
        )
        rows = json.loads(result.stdout or "[]")
        if rows:
            return {**rows[0], **info}
    except (EditorError, json.JSONDecodeError):
        pass
    return {"status": "pending", "conclusion": "", "url": info["actions_url"], **info}


def publish_explanations() -> dict:
    questions, workspace, public_payload, valid_ids = load_state()
    del questions
    run_process(git_args("fetch", "origin", "main"), ROOT)
    ahead, behind = branch_counts()
    if behind:
        raise EditorError("本機 main 落後或已與 GitHub 分歧，請先同步後再發布")
    if ahead:
        latest_message = run_process(git_args("log", "-1", "--pretty=%s"), ROOT).stdout.strip()
        if ahead == 1 and latest_message == COMMIT_MESSAGE:
            run_process(git_args("push", "origin", "main"), ROOT)
            current_public = read_json(PUBLIC_PATH, empty_public())
            save_workspace(reconcile_workspace(workspace, current_public))
            commit = run_process(git_args("rev-parse", "HEAD"), ROOT).stdout.strip()
            return {"commit": commit, "retried": True, **deployment_status(commit)}
        raise EditorError("本機 main 有尚未發布的其他提交，解析編輯器不會自動處理")

    plan = build_publication_plan(ROOT, workspace, public_payload, valid_ids)
    if not plan.changed_ids and not plan.unpublished_ids:
        return {"no_changes": True, **plan.summary(), **repository_info()}

    apply_publication(ROOT, plan)
    run_process(
        git_args(
            "add", "-A", "--", "site/data/explanations.json", "site/assets/explanations"
        ),
        ROOT,
    )
    staged = run_process(git_args("diff", "--cached", "--quiet"), ROOT, check=False)
    if staged.returncode == 0:
        return {"no_changes": True, **plan.summary(), **repository_info()}
    if staged.returncode != 1:
        raise EditorError("無法檢查解析發布差異")

    run_process(git_args("commit", "-m", COMMIT_MESSAGE), ROOT)
    commit = run_process(git_args("rev-parse", "HEAD"), ROOT).stdout.strip()
    run_process(git_args("push", "origin", "main"), ROOT)
    current_public = read_json(PUBLIC_PATH, empty_public())
    save_workspace(reconcile_workspace(workspace, current_public))
    return {"commit": commit, **plan.summary(), **deployment_status(commit)}


class EditorServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, handler, token: str):
        super().__init__(address, handler)
        self.token = token
        host, port = self.server_address
        self.origin = f"http://{host}:{port}"


class Handler(BaseHTTPRequestHandler):
    server: EditorServer

    def log_message(self, format_string: str, *args) -> None:
        sys.stdout.write("[editor] " + format_string % args + "\n")

    def send_common_headers(self, content_type: str, length: int) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()

    def send_bytes(self, data: bytes, content_type: str) -> None:
        self.send_common_headers(content_type, len(data))
        self.wfile.write(data)

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        data = (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def send_error_json(self, message: str, status: HTTPStatus = HTTPStatus.BAD_REQUEST) -> None:
        self.send_json({"error": message}, status)

    def authorized(self, allow_query: bool = False) -> bool:
        parsed = urlparse(self.path)
        query_token = parse_qs(parsed.query).get("token", [""])[0] if allow_query else ""
        token = self.headers.get("X-Editor-Token", "") or query_token
        if not secrets.compare_digest(token, self.server.token):
            self.send_error_json("工作階段權杖不正確", HTTPStatus.FORBIDDEN)
            return False
        origin = self.headers.get("Origin")
        if origin and origin != self.server.origin:
            self.send_error_json("不允許非本機來源", HTTPStatus.FORBIDDEN)
            return False
        return True

    def read_json_body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise EditorError("Content-Length 不正確") from exc
        if length <= 0 or length > MAX_REQUEST_BYTES:
            raise EditorError("請求大小不正確或超過限制")
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EditorError("請求不是有效 JSON") from exc
        if not isinstance(payload, dict):
            raise EditorError("請求必須是 JSON 物件")
        return payload

    def do_GET(self) -> None:  # noqa: N802
        try:
            parsed = urlparse(self.path)
            if parsed.path == "/api/bootstrap":
                if not self.authorized():
                    return
                questions, workspace, public_payload, _ = load_state()
                statuses = {
                    question["id"]: item_state(
                        workspace["items"].get(question["id"]),
                        public_payload.get("items", {}).get(question["id"]),
                    )
                    for question in questions["questions"]
                }
                self.send_json({
                    "questions": questions,
                    "workspace": workspace,
                    "public": public_payload,
                    "statuses": statuses,
                    **repository_info(),
                })
                return
            if parsed.path == "/api/publish-preview":
                if not self.authorized():
                    return
                _, workspace, public_payload, valid_ids = load_state()
                plan = build_publication_plan(ROOT, workspace, public_payload, valid_ids)
                self.send_json({**plan.summary(), **repository_info()})
                return
            if parsed.path == "/api/deployment":
                if not self.authorized():
                    return
                commit = parse_qs(parsed.query).get("commit", [""])[0]
                if not re.fullmatch(r"[a-f0-9]{40}", commit):
                    raise EditorError("Commit 格式不正確")
                self.send_json(deployment_status(commit))
                return
            if parsed.path == "/api/local-asset":
                if not self.authorized(allow_query=True):
                    return
                query = parse_qs(parsed.query)
                _, _, _, valid_ids = load_state()
                question_id = validate_question_id(query.get("question", [""])[0], valid_ids)
                name = query.get("name", [""])[0]
                if not re.fullmatch(r"asset-[a-f0-9]{16}\.(?:png|jpg|webp)", name):
                    raise EditorError("圖片名稱不正確")
                path = ensure_within(LOCAL_ASSET_ROOT / question_id / name, LOCAL_ASSET_ROOT / question_id)
                if not path.is_file():
                    raise EditorError("找不到解析圖片")
                self.send_bytes(path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")
                return
            self.serve_static(parsed.path)
        except EditorError as exc:
            self.send_error_json(str(exc))
        except Exception as exc:  # pragma: no cover - defensive HTTP boundary
            self.send_error_json(f"未預期錯誤：{exc}", HTTPStatus.INTERNAL_SERVER_ERROR)

    def serve_static(self, raw_path: str) -> None:
        if raw_path in {"", "/"}:
            path = EDITOR_DIR / "index.html"
        elif raw_path.startswith("/site/"):
            path = ensure_within(ROOT / unquote(raw_path.lstrip("/")), ROOT / "site")
        else:
            relative = unquote(raw_path.lstrip("/"))
            if relative not in {"editor.js", "editor.css"}:
                self.send_error_json("找不到檔案", HTTPStatus.NOT_FOUND)
                return
            path = EDITOR_DIR / relative
        if not path.is_file():
            self.send_error_json("找不到檔案", HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        if path.suffix in {".js", ".mjs"}:
            content_type = "text/javascript; charset=utf-8"
        elif path.suffix in {".html", ".css", ".json"}:
            content_type += "; charset=utf-8"
        self.send_bytes(path.read_bytes(), content_type)

    def do_POST(self) -> None:  # noqa: N802
        if not self.authorized():
            return
        try:
            parsed = urlparse(self.path)
            payload = self.read_json_body()
            questions, workspace, public_payload, valid_ids = load_state()
            del questions
            question_id = payload.get("question_id")
            if parsed.path != "/api/publish":
                question_id = validate_question_id(question_id, valid_ids)

            if parsed.path == "/api/item":
                incoming = normalize_workspace_item(payload.get("item", {}))
                existing = workspace["items"].get(question_id, {})
                incoming["status"] = "draft"
                incoming["published_revision"] = existing.get("published_revision")
                incoming["unpublish"] = bool(existing.get("unpublish", False))
                incoming["updated_at"] = now_iso()
                workspace["items"][question_id] = incoming
                save_workspace(workspace)
                self.send_json({
                    "item": incoming,
                    "state": item_state(incoming, public_payload.get("items", {}).get(question_id)),
                })
                return

            if parsed.path == "/api/review":
                item = workspace["items"].get(question_id)
                if not item or not item.get("markdown", "").strip():
                    raise EditorError("解析內容為空白，無法標記已審核")
                for image in item.get("images", []):
                    image_path = ensure_within(
                        LOCAL_ASSET_ROOT / question_id / image["name"],
                        LOCAL_ASSET_ROOT / question_id,
                    )
                    if not image_path.is_file():
                        raise EditorError(f"缺少解析圖片：{image['name']}")
                item["status"] = "reviewed"
                item["updated_at"] = now_iso()
                save_workspace(workspace)
                self.send_json({
                    "item": item,
                    "state": item_state(item, public_payload.get("items", {}).get(question_id)),
                })
                return

            if parsed.path == "/api/unpublish":
                item = workspace["items"].setdefault(
                    question_id,
                    normalize_workspace_item({"markdown": "", "status": "draft"}),
                )
                item["unpublish"] = bool(payload.get("unpublish", True))
                item["updated_at"] = now_iso()
                save_workspace(workspace)
                self.send_json({
                    "item": item,
                    "state": item_state(item, public_payload.get("items", {}).get(question_id)),
                })
                return

            if parsed.path == "/api/image":
                item = workspace["items"].setdefault(
                    question_id,
                    normalize_workspace_item({"markdown": "", "status": "draft"}),
                )
                asset = save_local_asset(
                    LOCAL_ASSET_ROOT,
                    question_id,
                    decode_image_data(payload.get("data")),
                )
                alt = payload.get("alt", "")
                if not isinstance(alt, str) or len(alt) > 200:
                    raise EditorError("圖片替代文字超過限制")
                asset["alt"] = alt.strip()
                if asset["name"] not in {image["name"] for image in item.get("images", [])}:
                    item.setdefault("images", []).append(asset)
                item["status"] = "draft"
                item["updated_at"] = now_iso()
                save_workspace(workspace)
                self.send_json({
                    "item": item,
                    "state": item_state(item, public_payload.get("items", {}).get(question_id)),
                })
                return

            if parsed.path == "/api/image/remove":
                item = workspace["items"].get(question_id)
                name = payload.get("name", "")
                if not item or not re.fullmatch(r"asset-[a-f0-9]{16}\.(?:png|jpg|webp)", str(name)):
                    raise EditorError("圖片項目不存在")
                item["images"] = [image for image in item.get("images", []) if image["name"] != name]
                path = ensure_within(LOCAL_ASSET_ROOT / question_id / name, LOCAL_ASSET_ROOT / question_id)
                if path.is_file():
                    path.unlink()
                item["status"] = "draft"
                item["updated_at"] = now_iso()
                save_workspace(workspace)
                self.send_json({
                    "item": item,
                    "state": item_state(item, public_payload.get("items", {}).get(question_id)),
                })
                return

            if parsed.path == "/api/publish":
                if payload.get("confirm") is not True:
                    raise EditorError("發布前必須再次確認")
                self.send_json(publish_explanations())
                return

            self.send_error_json("找不到 API", HTTPStatus.NOT_FOUND)
        except EditorError as exc:
            self.send_error_json(str(exc))
        except Exception as exc:  # pragma: no cover - defensive HTTP boundary
            self.send_error_json(f"未預期錯誤：{exc}", HTTPStatus.INTERNAL_SERVER_ERROR)


def main() -> None:
    parser = argparse.ArgumentParser(description="AI 應用規劃師中級題庫解析編輯器")
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()

    load_state()
    token = secrets.token_urlsafe(32)
    server = EditorServer(("127.0.0.1", args.port), Handler, token)
    url = f"{server.origin}/?token={token}"
    print(f"解析編輯器已啟動：{server.origin}", flush=True)
    print(f"測試網址：{url}", flush=True)
    print("關閉此視窗即可停止編輯器。", flush=True)
    if not args.no_browser:
        threading.Timer(0.35, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
