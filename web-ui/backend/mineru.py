"""MinerU document conversion client used by the HyperChE web API."""

from __future__ import annotations

import io
import json
import os
import re
import zipfile
from pathlib import Path
from typing import Any

import aiohttp

DEFAULT_MINERU_BASE_URL = "https://mineru.net/api/v4"
DEFAULT_ALLOWED_EXTENSIONS = {
    ".pdf", ".doc", ".docx", ".ppt", ".pptx", ".png", ".jpg", ".jpeg", ".jp2", ".webp", ".gif", ".bmp", ".html"
}


def _coerce_int(value: Any, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _coerce_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    if value is None:
        return default
    return bool(value)


def load_mineru_config(settings_file: str | Path) -> dict[str, Any]:
    settings: dict[str, Any] = {}
    try:
        path = Path(settings_file)
        if path.is_file():
            settings = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        settings = {}

    extra_formats = settings.get("mineruExtraFormats", ["docx", "html"])
    if isinstance(extra_formats, str):
        extra_formats = [item.strip() for item in re.split(r"[,;\n]+", extra_formats) if item.strip()]
    if not isinstance(extra_formats, list):
        extra_formats = ["docx", "html"]

    return {
        "base_url": str(settings.get("mineruApiBaseUrl") or os.getenv("MINERU_API_BASE_URL") or DEFAULT_MINERU_BASE_URL).rstrip("/"),
        "token": str(settings.get("mineruApiToken") or os.getenv("MINERU_API_TOKEN") or "").strip(),
        "model_version": str(settings.get("mineruModelVersion") or "pipeline").strip(),
        "language": str(settings.get("mineruLanguage") or "ch").strip(),
        "enable_ocr": _coerce_bool(settings.get("mineruEnableOcr"), True),
        "enable_formula": _coerce_bool(settings.get("mineruEnableFormula"), True),
        "enable_table": _coerce_bool(settings.get("mineruEnableTable"), True),
        "extra_formats": [str(item).strip() for item in extra_formats if str(item).strip()],
        "poll_interval_seconds": _coerce_int(settings.get("mineruPollIntervalSeconds"), 3, 1, 30),
        "max_poll_attempts": _coerce_int(settings.get("mineruMaxPollAttempts"), 100, 1, 1000),
        "max_file_mb": _coerce_int(settings.get("mineruMaxFileMb"), 200, 1, 200),
        "max_result_mb": _coerce_int(settings.get("mineruMaxResultMb"), 300, 1, 1000),
    }


def public_mineru_config(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "configured": bool(config.get("token")),
        "model_version": config.get("model_version"),
        "language": config.get("language"),
        "enable_ocr": config.get("enable_ocr"),
        "enable_formula": config.get("enable_formula"),
        "enable_table": config.get("enable_table"),
        "extra_formats": config.get("extra_formats", []),
        "poll_interval_seconds": config.get("poll_interval_seconds"),
        "max_poll_attempts": config.get("max_poll_attempts"),
        "max_file_mb": config.get("max_file_mb"),
        "allowed_extensions": sorted(DEFAULT_ALLOWED_EXTENSIONS),
    }


def validate_upload(filename: str, size: int, config: dict[str, Any]) -> str:
    safe_name = Path(filename or "document.pdf").name
    extension = Path(safe_name).suffix.lower()
    if extension not in DEFAULT_ALLOWED_EXTENSIONS:
        raise ValueError("暂不支持该文件类型，请上传 PDF、Word、PowerPoint、图片或 HTML 文件")
    if size <= 0:
        raise ValueError("上传文件为空")
    max_bytes = int(config["max_file_mb"]) * 1024 * 1024
    if size > max_bytes:
        raise ValueError(f"文件超过管理员设置的 {config['max_file_mb']} MB 上限")
    return safe_name


async def _read_json(response: aiohttp.ClientResponse) -> dict[str, Any]:
    text = await response.text()
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"MinerU 返回了无法解析的响应：{text[:300]}") from exc
    if response.status >= 400:
        raise RuntimeError(data.get("msg") or data.get("message") or f"MinerU 请求失败（HTTP {response.status}）")
    code = data.get("code")
    if code not in (None, 0, "0"):
        raise RuntimeError(data.get("msg") or data.get("message") or f"MinerU 请求失败（code={code}）")
    return data


async def submit_mineru_batch(filename: str, content: bytes, config: dict[str, Any]) -> dict[str, Any]:
    if not config.get("token"):
        raise RuntimeError("MinerU API Token 尚未配置，请管理员先在后台填写")

    payload = {
        "files": [
            {
                "name": filename,
                "is_ocr": bool(config.get("enable_ocr", True)),
                "data_id": filename,
            }
        ],
        "model_version": config.get("model_version", "pipeline"),
        "language": config.get("language", "ch"),
        "enable_formula": bool(config.get("enable_formula", True)),
        "enable_table": bool(config.get("enable_table", True)),
        "extra_formats": config.get("extra_formats", []),
    }
    headers = {
        "Authorization": f"Bearer {config['token']}",
        "Content-Type": "application/json",
    }
    timeout = aiohttp.ClientTimeout(total=180)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.post(f"{config['base_url']}/file-urls/batch", headers=headers, json=payload) as response:
            data = await _read_json(response)
        result = data.get("data") or {}
        batch_id = result.get("batch_id")
        upload_urls = result.get("file_urls") or []
        if not batch_id or not upload_urls:
            raise RuntimeError("MinerU 未返回 batch_id 或文件上传地址")

        async with session.put(upload_urls[0], data=content) as upload_response:
            if upload_response.status >= 400:
                detail = (await upload_response.text())[:300]
                raise RuntimeError(f"向 MinerU 上传文件失败（HTTP {upload_response.status}）：{detail}")

    return {"batch_id": str(batch_id), "filename": filename}


def _first_extract_result(data: dict[str, Any]) -> dict[str, Any]:
    payload = data.get("data") or {}
    results = payload.get("extract_result") or payload.get("extract_results") or []
    if isinstance(results, dict):
        return results
    if isinstance(results, list) and results:
        return results[0] or {}
    return payload if isinstance(payload, dict) else {}


async def get_mineru_batch_status(batch_id: str, config: dict[str, Any]) -> dict[str, Any]:
    if not config.get("token"):
        raise RuntimeError("MinerU API Token 尚未配置")
    headers = {"Authorization": f"Bearer {config['token']}"}
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(f"{config['base_url']}/extract-results/batch/{batch_id}", headers=headers) as response:
            data = await _read_json(response)

    task = _first_extract_result(data)
    state = str(task.get("state") or task.get("status") or "pending").lower()
    progress_data = task.get("extract_progress") or task.get("progress") or {}
    extracted_pages = int(progress_data.get("extracted_pages") or progress_data.get("current") or 0)
    total_pages = int(progress_data.get("total_pages") or progress_data.get("total") or 0)
    percent = round(extracted_pages / total_pages * 100) if total_pages else (100 if state in {"done", "completed", "success"} else 0)
    return {
        "batch_id": batch_id,
        "state": state,
        "progress": {
            "current": extracted_pages,
            "total": total_pages,
            "percent": max(0, min(100, percent)),
        },
        "full_zip_url": task.get("full_zip_url") or task.get("zip_url") or "",
        "error": task.get("err_msg") or task.get("error") or task.get("message") or "",
        "raw": task,
    }


async def download_mineru_markdown(batch_id: str, config: dict[str, Any]) -> dict[str, Any]:
    status = await get_mineru_batch_status(batch_id, config)
    if status["state"] not in {"done", "completed", "success"}:
        raise RuntimeError("MinerU 转换尚未完成")
    zip_url = status.get("full_zip_url")
    if not zip_url:
        raise RuntimeError("MinerU 已完成，但没有返回结果 ZIP 地址")

    timeout = aiohttp.ClientTimeout(total=180)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(zip_url) as response:
            if response.status >= 400:
                raise RuntimeError(f"下载 MinerU 结果失败（HTTP {response.status}）")
            content_length = int(response.headers.get("Content-Length") or 0)
            max_bytes = int(config["max_result_mb"]) * 1024 * 1024
            if content_length and content_length > max_bytes:
                raise RuntimeError(f"MinerU 结果超过 {config['max_result_mb']} MB 下载上限")
            archive_bytes = await response.read()
            if len(archive_bytes) > max_bytes:
                raise RuntimeError(f"MinerU 结果超过 {config['max_result_mb']} MB 下载上限")

    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            names = [name for name in archive.namelist() if not name.endswith("/") and not name.startswith("__MACOSX/")]
            markdown_names = [name for name in names if name.lower().endswith(".md")]
            if not markdown_names:
                raise RuntimeError("MinerU 结果 ZIP 中没有找到 Markdown 文件")
            markdown_name = max(markdown_names, key=lambda name: archive.getinfo(name).file_size)
            markdown = archive.read(markdown_name).decode("utf-8", errors="replace")
    except zipfile.BadZipFile as exc:
        raise RuntimeError("MinerU 返回的结果不是有效 ZIP 文件") from exc

    return {
        "batch_id": batch_id,
        "markdown": markdown,
        "markdown_file": markdown_name,
        "files": names,
        "full_zip_url": zip_url,
    }
