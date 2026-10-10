from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


SCHEMA_VERSION = 1
MAX_MARKDOWN_LENGTH = 50_000
MAX_IMAGE_BYTES = 8 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
QUESTION_ID = re.compile(r"^\d{3}-\d+-L-S[123]-Q\d{3}$")
ASSET_NAME = re.compile(r"^asset-[a-f0-9]{16}\.(?:png|jpg|webp)$")


class EditorError(ValueError):
    pass


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def today_iso() -> str:
    return datetime.now().astimezone().date().isoformat()


def empty_workspace() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "updated_at": now_iso(), "items": {}}


def empty_public() -> dict[str, Any]:
    return {"schema_version": SCHEMA_VERSION, "generated_at": None, "items": {}}


def read_json(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    if not path.exists():
        return json.loads(json.dumps(default))
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EditorError(f"無法讀取 {path.name}：{exc}") from exc
    if not isinstance(value, dict):
        raise EditorError(f"{path.name} 必須是 JSON 物件")
    return value


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    backup = path.with_suffix(path.suffix + ".bak")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if path.exists():
        shutil.copy2(path, backup)
    os.replace(temporary, path)


def ensure_within(path: Path, root: Path) -> Path:
    resolved_root = root.resolve()
    resolved = path.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise EditorError("路徑超出允許範圍")
    return resolved


def validate_question_id(question_id: Any, valid_ids: set[str]) -> str:
    if not isinstance(question_id, str) or not QUESTION_ID.fullmatch(question_id):
        raise EditorError("題目 ID 格式不正確")
    if question_id not in valid_ids:
        raise EditorError(f"題目 ID 不存在：{question_id}")
    return question_id


def normalize_workspace_item(source: Any) -> dict[str, Any]:
    if not isinstance(source, dict):
        raise EditorError("解析項目必須是物件")
    markdown = source.get("markdown", "")
    if not isinstance(markdown, str) or len(markdown) > MAX_MARKDOWN_LENGTH:
        raise EditorError("解析文字格式不正確或超過長度限制")
    status = source.get("status", "draft")
    if status not in {"draft", "reviewed"}:
        raise EditorError("解析狀態只允許 draft 或 reviewed")
    images = []
    raw_images = source.get("images", [])
    if not isinstance(raw_images, list) or len(raw_images) > 20:
        raise EditorError("解析圖片清單格式不正確或數量超過限制")
    for image in raw_images:
        if not isinstance(image, dict) or not ASSET_NAME.fullmatch(str(image.get("name", ""))):
            raise EditorError("解析圖片名稱不正確")
        alt = image.get("alt", "")
        if not isinstance(alt, str) or len(alt) > 200:
            raise EditorError("圖片替代文字超過限制")
        images.append({"name": image["name"], "alt": alt.strip()})

    published_revision = source.get("published_revision")
    if published_revision is not None and not re.fullmatch(r"[a-f0-9]{64}", str(published_revision)):
        raise EditorError("已發布版本格式不正確")
    return {
        "status": status,
        "markdown": markdown,
        "images": images,
        "updated_at": str(source.get("updated_at") or now_iso()),
        "published_revision": published_revision,
        "unpublish": bool(source.get("unpublish", False)),
    }


def item_revision(item: dict[str, Any]) -> str:
    canonical = {
        "markdown": item.get("markdown", "").strip(),
        "images": [
            {"name": image["name"], "alt": image.get("alt", "")}
            for image in item.get("images", [])
        ],
    }
    data = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def item_state(item: dict[str, Any] | None, public_item: dict[str, Any] | None) -> str:
    if item and item.get("unpublish"):
        return "unpublish-pending"
    if item is None:
        return "published" if public_item else "empty"
    has_content = bool(item.get("markdown", "").strip())
    if not has_content:
        return "published-modified" if public_item else "empty"
    revision = item_revision(item)
    published_revision = item.get("published_revision") or (public_item or {}).get("revision")
    if public_item and revision == published_revision:
        return "published"
    if item.get("status") == "reviewed":
        return "reviewed-unpublished"
    return "published-modified" if public_item else "draft"


def inspect_image(data: bytes) -> tuple[str, str, int, int]:
    if len(data) > MAX_IMAGE_BYTES:
        raise EditorError("圖片超過 8 MB 限制")
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        result = ("png", "image/png", width, height)
    elif data.startswith(b"\xff\xd8"):
        index = 2
        width = height = 0
        while index + 9 < len(data):
            if data[index] != 0xFF:
                index += 1
                continue
            marker = data[index + 1]
            index += 2
            if marker in {0xD8, 0xD9}:
                continue
            if index + 2 > len(data):
                break
            length = struct.unpack(">H", data[index:index + 2])[0]
            if length < 2 or index + length > len(data):
                break
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                height, width = struct.unpack(">HH", data[index + 3:index + 7])
                break
            index += length
        if not width or not height:
            raise EditorError("無法辨識 JPEG 尺寸")
        result = ("jpg", "image/jpeg", width, height)
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP" and len(data) >= 30:
        kind = data[12:16]
        if kind == b"VP8X":
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
        elif kind == b"VP8L" and len(data) >= 25:
            bits = int.from_bytes(data[21:25], "little")
            width = (bits & 0x3FFF) + 1
            height = ((bits >> 14) & 0x3FFF) + 1
        elif kind == b"VP8 " and len(data) >= 30:
            width, height = struct.unpack("<HH", data[26:30])
            width &= 0x3FFF
            height &= 0x3FFF
        else:
            raise EditorError("無法辨識 WebP 尺寸")
        result = ("webp", "image/webp", width, height)
    else:
        raise EditorError("只接受 PNG、JPEG 或 WebP 圖片")

    _, _, width, height = result
    if width < 16 or height < 16 or width * height > MAX_IMAGE_PIXELS:
        raise EditorError("圖片尺寸不正確或像素超過限制")
    return result


def decode_image_data(value: Any) -> bytes:
    if not isinstance(value, str):
        raise EditorError("圖片資料格式不正確")
    if value.startswith("data:"):
        try:
            value = value.split(",", 1)[1]
        except IndexError as exc:
            raise EditorError("圖片資料格式不正確") from exc
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, TypeError) as exc:
        raise EditorError("圖片不是有效的 Base64") from exc


def save_local_asset(asset_root: Path, question_id: str, data: bytes) -> dict[str, str]:
    extension, _, _, _ = inspect_image(data)
    digest = hashlib.sha256(data).hexdigest()[:16]
    name = f"asset-{digest}.{extension}"
    directory = ensure_within(asset_root / question_id, asset_root)
    directory.mkdir(parents=True, exist_ok=True)
    destination = ensure_within(directory / name, directory)
    if not destination.exists():
        destination.write_bytes(data)
    return {"name": name, "alt": ""}


def validate_workspace(workspace: dict[str, Any], valid_ids: set[str]) -> dict[str, Any]:
    if workspace.get("schema_version") != SCHEMA_VERSION or not isinstance(workspace.get("items"), dict):
        raise EditorError("本機解析工作檔格式不正確")
    normalized = empty_workspace()
    normalized["updated_at"] = str(workspace.get("updated_at") or now_iso())
    for question_id, item in workspace["items"].items():
        validate_question_id(question_id, valid_ids)
        normalized["items"][question_id] = normalize_workspace_item(item)
    return normalized


def import_missing_public_items(
    root: Path,
    workspace: dict[str, Any],
    public_payload: dict[str, Any],
) -> bool:
    changed = False
    public_items = public_payload.get("items", {})
    local_assets = root / "local-data" / "explanation-assets"
    for question_id, public_item in public_items.items():
        if question_id in workspace["items"]:
            continue
        local_images = []
        for public_path in public_item.get("images", []):
            source = ensure_within(root / "site" / public_path, root / "site" / "assets" / "explanations")
            data = source.read_bytes()
            local_image = save_local_asset(local_assets, question_id, data)
            local_image["alt"] = ""
            local_images.append(local_image)
        item = {
            "status": "reviewed",
            "markdown": public_item.get("markdown", ""),
            "images": local_images,
            "updated_at": now_iso(),
            "published_revision": None,
            "unpublish": False,
        }
        item["published_revision"] = public_item.get("revision") or item_revision(item)
        workspace["items"][question_id] = item
        changed = True
    return changed


@dataclass
class PublicationPlan:
    payload: dict[str, Any]
    changed_ids: list[str]
    unpublished_ids: list[str]
    asset_sources: dict[str, list[Path]]
    revisions: dict[str, str]

    def summary(self) -> dict[str, Any]:
        return {
            "updates": len(self.changed_ids),
            "unpublishes": len(self.unpublished_ids),
            "question_ids": self.changed_ids,
            "unpublished_ids": self.unpublished_ids,
            "image_count": sum(len(paths) for paths in self.asset_sources.values()),
        }


def build_publication_plan(
    root: Path,
    workspace: dict[str, Any],
    public_payload: dict[str, Any],
    valid_ids: set[str],
) -> PublicationPlan:
    normalized_workspace = validate_workspace(workspace, valid_ids)
    current_items = public_payload.get("items", {})
    if public_payload.get("schema_version") != SCHEMA_VERSION or not isinstance(current_items, dict):
        raise EditorError("公開解析檔格式不正確")
    next_items = json.loads(json.dumps(current_items))
    changed_ids: list[str] = []
    unpublished_ids: list[str] = []
    asset_sources: dict[str, list[Path]] = {}
    revisions: dict[str, str] = {}
    local_assets = root / "local-data" / "explanation-assets"

    for question_id, item in normalized_workspace["items"].items():
        if item["unpublish"]:
            if question_id in next_items:
                next_items.pop(question_id, None)
                unpublished_ids.append(question_id)
            continue
        if item["status"] != "reviewed":
            continue
        markdown = item["markdown"].strip()
        if not markdown:
            raise EditorError(f"{question_id} 已審核，但解析內容為空白")
        revision = item_revision(item)
        if question_id in next_items and next_items[question_id].get("revision") == revision:
            continue

        sources = []
        public_images = []
        for index, image in enumerate(item["images"], start=1):
            source = ensure_within(local_assets / question_id / image["name"], local_assets / question_id)
            if not source.is_file():
                raise EditorError(f"{question_id} 缺少解析圖片：{image['name']}")
            extension, _, _, _ = inspect_image(source.read_bytes())
            public_name = f"image-{index:02d}.{extension}"
            sources.append(source)
            public_images.append(f"assets/explanations/{question_id}/{public_name}")

        next_items[question_id] = {
            "markdown": markdown,
            "images": public_images,
            "updated_at": today_iso(),
            "revision": revision,
        }
        changed_ids.append(question_id)
        asset_sources[question_id] = sources
        revisions[question_id] = revision

    payload = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": now_iso(),
        "items": dict(sorted(next_items.items())),
    }
    return PublicationPlan(payload, changed_ids, unpublished_ids, asset_sources, revisions)


def replace_public_assets(root: Path, plan: PublicationPlan) -> None:
    public_root = root / "site" / "assets" / "explanations"
    public_root.mkdir(parents=True, exist_ok=True)
    for question_id in [*plan.changed_ids, *plan.unpublished_ids]:
        target = ensure_within(public_root / question_id, public_root)
        if question_id in plan.unpublished_ids:
            if target.exists():
                shutil.rmtree(target)
            continue

        temporary = public_root / f".{question_id}.{uuid.uuid4().hex}.tmp"
        temporary.mkdir(parents=True)
        try:
            for index, source in enumerate(plan.asset_sources[question_id], start=1):
                extension = source.suffix.lower().lstrip(".")
                shutil.copy2(source, temporary / f"image-{index:02d}.{extension}")
            backup = public_root / f".{question_id}.{uuid.uuid4().hex}.bak"
            if target.exists():
                target.rename(backup)
            temporary.rename(target)
            if backup.exists():
                shutil.rmtree(backup)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)


def apply_publication(root: Path, plan: PublicationPlan) -> None:
    replace_public_assets(root, plan)
    atomic_write_json(root / "site" / "data" / "explanations.json", plan.payload)


def reconcile_workspace(workspace: dict[str, Any], public_payload: dict[str, Any]) -> dict[str, Any]:
    public_items = public_payload.get("items", {})
    for question_id, item in workspace.get("items", {}).items():
        public_item = public_items.get(question_id)
        if item.get("unpublish") and not public_item:
            item["unpublish"] = False
            item["published_revision"] = None
            item["status"] = "draft"
        elif public_item and public_item.get("revision") == item_revision(item):
            item["published_revision"] = public_item["revision"]
            item["status"] = "reviewed"
    workspace["updated_at"] = now_iso()
    return workspace


def run_process(args: list[str], root: Path, check: bool = True) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        args,
        cwd=root,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if check and completed.returncode:
        message = completed.stderr.strip() or completed.stdout.strip() or "命令執行失敗"
        raise EditorError(message)
    return completed
