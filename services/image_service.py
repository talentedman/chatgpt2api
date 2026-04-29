from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from services.config import config

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tiff", ".svg"}


def _is_image_file(path: Path) -> bool:
    if not path.is_file():
        return False
    name = path.name.lower()
    if name.endswith(".meta.json"):
        return False
    return path.suffix.lower() in IMAGE_EXTENSIONS


def _meta_file(path: Path) -> Path:
    return Path(f"{path.as_posix()}.meta.json")


def _read_meta(path: Path) -> dict[str, object]:
    meta_path = _meta_file(path)
    if not meta_path.exists() or not meta_path.is_file():
        return {}
    try:
        data = json.loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def _read_prompt(meta: dict[str, object]) -> str:
    return str(meta.get("prompt") or meta.get("revised_prompt") or meta.get("original_prompt") or "").strip()


def _normalize_relative_path(raw: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if text.startswith("http://") or text.startswith("https://"):
        text = urlparse(text).path
    text = text.strip().lstrip("/")
    if text.startswith("images/"):
        text = text[len("images/"):]
    return Path(text).as_posix().lstrip("/")


def _resolve_reference_url(raw: object, base_url: str) -> str:
    text = str(raw or "").strip()
    if not text:
        return ""
    if text.startswith("http://") or text.startswith("https://") or text.startswith("data:"):
        return text
    rel = _normalize_relative_path(text)
    if not rel:
        return ""
    return f"{base_url.rstrip('/')}/images/{rel}"


def list_images(base_url: str, start_date: str = "", end_date: str = "") -> dict[str, object]:
    config.cleanup_old_images()
    items = []
    root = config.images_dir.resolve()
    for path in root.rglob("*"):
        if not _is_image_file(path):
            continue
        rel = path.relative_to(root).as_posix()
        if rel.startswith("references/"):
            continue
        meta = _read_meta(path)
        request_type = str(meta.get("request_type") or "").strip().lower()
        if request_type not in {"generation", "edit"}:
            request_type = "edit" if meta.get("reference_image_url") else "generation"
        parts = rel.split("/")
        day = "-".join(parts[:3]) if len(parts) >= 4 else datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
        if start_date and day < start_date:
            continue
        if end_date and day > end_date:
            continue
        items.append({
            "name": path.name,
            "path": rel,
            "date": day,
            "size": path.stat().st_size,
            "url": f"{base_url.rstrip('/')}/images/{rel}",
            "created_at": datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "prompt": _read_prompt(meta),
            "request_type": request_type,
            "reference_image_url": _resolve_reference_url(meta.get("reference_image_url"), base_url),
        })
    items.sort(key=lambda item: str(item["created_at"]), reverse=True)
    groups: dict[str, list[dict[str, object]]] = {}
    for item in items:
        groups.setdefault(str(item["date"]), []).append(item)
    return {"items": items, "groups": [{"date": key, "items": value} for key, value in groups.items()]}


def delete_images(paths: list[str]) -> dict[str, object]:
    root = config.images_dir.resolve()
    removed = 0
    missing: list[str] = []
    errors: list[dict[str, str]] = []

    for raw_path in paths:
        rel = _normalize_relative_path(str(raw_path or ""))
        if not rel:
            continue
        target = root / rel
        try:
            resolved_target = target.resolve()
            resolved_target.relative_to(root)
        except Exception:
            errors.append({"path": str(raw_path or ""), "error": "invalid image path"})
            continue

        if not _is_image_file(resolved_target):
            missing.append(rel)
            continue

        try:
            resolved_target.unlink()
            meta = _meta_file(resolved_target)
            if meta.exists() and meta.is_file():
                meta.unlink()
            removed += 1
        except Exception as exc:
            errors.append({"path": rel, "error": str(exc)})

    for directory in sorted((item for item in root.rglob("*") if item.is_dir()), key=lambda item: len(item.parts), reverse=True):
        try:
            directory.rmdir()
        except OSError:
            pass

    return {"removed": removed, "missing": missing, "errors": errors}
