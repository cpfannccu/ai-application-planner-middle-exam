from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from explanation_editor_core import (  # noqa: E402
    EditorError,
    build_publication_plan,
    ensure_within,
    inspect_image,
    item_state,
)


QUESTION_ID = "115-1-L-S3-Q048"


def workspace_item(status: str, markdown: str = "解析") -> dict:
    return {
        "status": status,
        "markdown": markdown,
        "images": [],
        "updated_at": "2026-09-02T10:00:00+08:00",
        "published_revision": None,
        "unpublish": False,
    }


class ExplanationEditorTests(unittest.TestCase):
    def test_path_traversal_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "allowed"
            root.mkdir()
            with self.assertRaises(EditorError):
                ensure_within(root / ".." / "outside.txt", root)

    def test_reviewed_item_enters_publication_but_draft_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = {
                "schema_version": 1,
                "updated_at": "2026-09-02T10:00:00+08:00",
                "items": {
                    QUESTION_ID: workspace_item("reviewed"),
                    "115-1-L-S3-Q049": workspace_item("draft", "草稿"),
                },
            }
            public = {"schema_version": 1, "generated_at": None, "items": {}}
            plan = build_publication_plan(
                root,
                workspace,
                public,
                {QUESTION_ID, "115-1-L-S3-Q049"},
            )
            self.assertEqual(plan.changed_ids, [QUESTION_ID])
            self.assertIn(QUESTION_ID, plan.payload["items"])
            self.assertNotIn("115-1-L-S3-Q049", plan.payload["items"])

    def test_unpublish_is_explicit_and_independent_of_draft_status(self) -> None:
        item = workspace_item("draft", "新版草稿")
        item["unpublish"] = True
        workspace = {
            "schema_version": 1,
            "updated_at": "2026-09-02T10:00:00+08:00",
            "items": {QUESTION_ID: item},
        }
        public = {
            "schema_version": 1,
            "generated_at": "2026-09-02T09:00:00+08:00",
            "items": {QUESTION_ID: {"markdown": "舊版", "images": [], "revision": "a" * 64}},
        }
        with tempfile.TemporaryDirectory() as directory:
            plan = build_publication_plan(Path(directory), workspace, public, {QUESTION_ID})
        self.assertEqual(plan.unpublished_ids, [QUESTION_ID])
        self.assertNotIn(QUESTION_ID, plan.payload["items"])
        self.assertEqual(item_state(item, public["items"][QUESTION_ID]), "unpublish-pending")

    def test_png_signature_and_dimensions_are_checked(self) -> None:
        png = b"\x89PNG\r\n\x1a\n" + b"\x00\x00\x00\x0dIHDR" + struct.pack(">II", 32, 24) + b"\x08\x06\x00\x00\x00"
        extension, mime, width, height = inspect_image(png)
        self.assertEqual((extension, mime, width, height), ("png", "image/png", 32, 24))
        with self.assertRaises(EditorError):
            inspect_image(b"not an image")


if __name__ == "__main__":
    unittest.main()
