#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import subprocess
import threading
import webbrowser
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

from product_info_agent import (
    OUTPUT_FIELD_SPECS,
    ROOT,
    collect_profile,
    generate_target_audience_and_pain_points,
    load_agent_config,
    normalize_product_data,
    output_field_values,
    output_field_values_from_data,
    product_data_from_profile,
    product_data_to_markdown,
    resolve_output_path,
    safe_name,
    write_product_data,
    write_profile,
)


HOST = "127.0.0.1"
DEFAULT_PORT = 8791
SAMPLE_PATH = ROOT / "samples" / "product_basic_info.txt"
DEFAULT_ARCHIVE_ROOT = ROOT / "product"


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def text_response(handler: BaseHTTPRequestHandler, status: int, text: str, content_type: str = "text/html; charset=utf-8") -> None:
    body = text.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def read_request_json(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    try:
        data = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"请求 JSON 无效: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("请求体必须是 JSON object")
    return data


def display_path(path: str | Path) -> str:
    path = Path(path)
    try:
        return path.resolve().relative_to(ROOT.resolve()).as_posix()
    except ValueError:
        return path.expanduser().as_posix()


def build_args(payload: dict[str, Any]) -> SimpleNamespace:
    return SimpleNamespace(
        output="",
        output_root="",
        project_slug=str(payload.get("project_slug") or "").strip(),
    )


def archive_root_path(config: dict[str, Any] | None = None) -> Path:
    config = config or load_agent_config()
    configured = str(config.get("default_output_root") or "product").strip()
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    try:
        path.relative_to(ROOT.resolve())
    except ValueError:
        path = DEFAULT_ARCHIVE_ROOT.resolve()
    return path


def product_markdown_filename(data: dict[str, Any]) -> str:
    data = normalize_product_data(data)
    parts: list[str] = []
    if data.get("country"):
        parts.append(data["country"])
    seen_categories: set[str] = set()
    for item in data.get("categories", []):
        category = str(item).strip()
        if category and category not in seen_categories:
            parts.append(category)
            seen_categories.add(category)
    parts.append(data.get("productNameZh") or data.get("productNameLocal") or "产品信息")
    return f"{safe_name('_'.join(parts), default='product_info', max_length=180)}.md"


def unique_output_path(path: Path) -> Path:
    if not path.exists():
        return path
    for index in range(2, 10000):
        candidate = path.with_name(f"{path.stem}_{index}{path.suffix}")
        if not candidate.exists():
            return candidate
    raise ValueError(f"无法生成不重复的文件名: {path}")


def resolve_product_markdown_path(data: dict[str, Any]) -> Path:
    return unique_output_path((archive_root_path() / product_markdown_filename(data)).resolve())


def first_markdown_title(path: Path) -> str:
    try:
        for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
            text = line.strip()
            if text.startswith("# "):
                return text[2:].strip()
    except OSError:
        return ""
    return ""


def product_library_items() -> list[dict[str, Any]]:
    root = archive_root_path()
    root.mkdir(parents=True, exist_ok=True)
    paths = [path for path in root.rglob("*.md") if path.is_file()]
    paths.sort(key=lambda item: item.stat().st_mtime, reverse=True)
    items: list[dict[str, Any]] = []
    for path in paths:
        stat = path.stat()
        display = display_path(path)
        title = first_markdown_title(path) or path.stem
        items.append(
            {
                "title": title,
                "name": path.name,
                "path": display,
                "updated": datetime.fromtimestamp(stat.st_mtime).strftime("%m-%d %H:%M"),
                "size": stat.st_size,
            }
        )
    return items


def resolve_library_file(value: str) -> Path:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("缺少产品文件路径。")
    root = archive_root_path().resolve()
    path = Path(raw)
    if not path.is_absolute():
        if raw.startswith("product/"):
            path = ROOT / raw
        else:
            path = root / raw
    path = path.resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise ValueError("只能读取 product 目录内的 Markdown 文件。") from exc
    if path.suffix.lower() != ".md" or not path.is_file():
        raise ValueError("产品文件不存在。")
    return path


def product_data_from_markdown(markdown: str) -> dict[str, Any]:
    match = re.search(r"```json\s*(\{.*?\})\s*```", str(markdown or ""), re.S)
    if not match:
        match = re.search(r">\s*```json\s*\n(?P<body>.*?)(?:\n>\s*```|\n```)", str(markdown or ""), re.S)
        if match:
            body = "\n".join(re.sub(r"^\s*>\s?", "", line) for line in match.group("body").splitlines())
        else:
            body = ""
    else:
        body = match.group(1)
    if body:
        try:
            parsed = json.loads(body)
            if isinstance(parsed, dict):
                return normalize_product_data(parsed)
        except json.JSONDecodeError:
            pass
    return normalize_product_data({})


def has_product_data(data: dict[str, Any]) -> bool:
    data = normalize_product_data(data)
    return any(
        [
            data["productNameZh"],
            data["productNameLocal"],
            data["country"],
            data["categories"],
            data["price"]["originalPrice"],
            data["price"]["promotionalPrice"],
            data["specifications"],
            data["extendedAttributes"],
            data["keySellingPoints"],
            data["skus"],
        ]
    )


def analyze_text_payload(payload: dict[str, Any], write_output: bool) -> dict[str, Any]:
    raw_text = str(payload.get("text") or "").strip()
    if not raw_text:
        raise ValueError("请输入或导入产品基础信息。")

    filename = Path(str(payload.get("filename") or "web_input.txt")).name
    input_path = ROOT / filename
    profile, mode_used = collect_profile(raw_text, input_path)
    config = load_agent_config()
    config["default_output_root"] = str(archive_root_path(config))
    include_empty = bool(config.get("include_empty_sections", True)) and not bool(payload.get("compact", False))
    output_path = resolve_output_path(profile, input_path, config, build_args(payload))
    markdown = product_data_to_markdown(product_data_from_profile(profile), include_empty=include_empty)

    if write_output:
        write_profile(profile, output_path, include_empty=include_empty)

    fields = output_field_values(profile)
    filled_count = sum(1 for item in fields if item["filled"])
    project_slug = safe_name(
        str(payload.get("project_slug") or "")
        or profile.get("english_name")
        or profile.get("product_name")
        or input_path.stem
    )
    return {
        "ok": True,
        "mode": mode_used,
        "profile": profile,
        "fields": fields,
        "markdown": markdown,
        "output_path": str(output_path),
        "display_path": display_path(output_path),
        "project_slug": project_slug,
        "filled_count": filled_count,
        "field_count": len(OUTPUT_FIELD_SPECS),
        "written": write_output,
    }


def analyze_product_payload(payload: dict[str, Any], write_output: bool) -> dict[str, Any]:
    data = normalize_product_data(payload.get("product_data", {}))
    if not has_product_data(data):
        raise ValueError("请至少填写一个产品名称或基础字段。")

    if not data["targetAudienceAndPainPoints"]:
        data["targetAudienceAndPainPoints"] = generate_target_audience_and_pain_points(data)

    config = load_agent_config()
    config["default_output_root"] = str(archive_root_path(config))
    include_empty = bool(config.get("include_empty_sections", True)) and not bool(payload.get("compact", False))
    overwrite_path_value = str(payload.get("overwrite_path") or "").strip()
    output_path = resolve_library_file(overwrite_path_value) if overwrite_path_value else resolve_product_markdown_path(data)
    markdown = product_data_to_markdown(data, include_empty=include_empty)

    if write_output:
        write_product_data(data, output_path, include_empty=include_empty)

    fields = output_field_values_from_data(data)
    filled_count = sum(1 for item in fields if item["filled"])
    project_slug = safe_name(
        Path(output_path).stem,
        default="product_info",
    )
    return {
        "ok": True,
        "mode": "manual-local",
        "product_data": data,
        "fields": fields,
        "markdown": markdown,
        "output_path": str(output_path),
        "display_path": display_path(output_path),
        "project_slug": project_slug,
        "filled_count": filled_count,
        "field_count": len(OUTPUT_FIELD_SPECS),
        "written": write_output,
    }


def analyze_payload(payload: dict[str, Any], write_output: bool) -> dict[str, Any]:
    if "product_data" in payload:
        return analyze_product_payload(payload, write_output=write_output)
    return analyze_text_payload(payload, write_output=write_output)


def product_data_from_text(raw_text: str, filename: str = "web_input.txt") -> tuple[dict[str, Any], str]:
    input_path = ROOT / Path(filename or "web_input.txt").name
    profile, mode_used = collect_profile(raw_text, input_path)
    data = product_data_from_profile(profile)
    if not data.get("targetAudienceAndPainPoints"):
        data["targetAudienceAndPainPoints"] = generate_target_audience_and_pain_points(data)
    return normalize_product_data(data), mode_used


HTML_TEMPLATE = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>产品信息收集</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f5f5f7;
      --surface: rgba(255, 255, 255, 0.84);
      --surface-strong: rgba(255, 255, 255, 0.94);
      --line: rgba(0, 0, 0, 0.11);
      --line-soft: rgba(0, 0, 0, 0.06);
      --text: #1d1d1f;
      --muted: #6e6e73;
      --soft: #8e8e93;
      --accent: #007aff;
      --accent-press: #0068d6;
      --ok: #248a3d;
      --warn: #b35c00;
      --shadow: 0 18px 45px rgba(0, 0, 0, 0.07);
      --radius: 8px;
      --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
      --font: -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Arial, "PingFang SC", "Microsoft YaHei", sans-serif;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      height: 100vh;
      overflow: hidden;
      background: linear-gradient(180deg, #fbfbfd 0%, #f5f5f7 48%, #eeeeef 100%);
      color: var(--text);
      font-family: var(--font);
      letter-spacing: 0;
      -webkit-font-smoothing: antialiased;
    }
    button, input, textarea { font: inherit; letter-spacing: 0; }
    .shell {
      height: 100vh;
      display: grid;
      grid-template-rows: 56px minmax(0, 1fr);
      overflow: hidden;
    }
    .topbar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 0 18px;
      background: rgba(245, 245, 247, 0.78);
      border-bottom: 1px solid rgba(0, 0, 0, 0.08);
      backdrop-filter: saturate(180%) blur(18px);
      -webkit-backdrop-filter: saturate(180%) blur(18px);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: 216px;
    }
    .appIcon {
      width: 32px;
      height: 32px;
      display: grid;
      place-items: center;
      border: 1px solid rgba(0, 113, 227, 0.22);
      border-radius: 8px;
      background: linear-gradient(180deg, #ffffff, #e9f2ff);
      color: var(--accent);
      box-shadow: 0 8px 20px rgba(0, 113, 227, 0.12);
    }
    h1 {
      margin: 0;
      font-size: 17px;
      line-height: 1.15;
      font-weight: 720;
    }
    .subtitle {
      margin-top: 2px;
      color: var(--muted);
      font-size: 12px;
      line-height: 1.2;
    }
    .toolbar {
      display: flex;
      justify-content: flex-end;
      align-items: center;
      gap: 8px;
      min-width: 0;
    }
    .btn {
      min-height: 32px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      gap: 7px;
      padding: 7px 11px;
      border: 1px solid rgba(0, 0, 0, 0.1);
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.78);
      color: var(--text);
      cursor: pointer;
      font-size: 12px;
      font-weight: 650;
      line-height: 1.2;
      user-select: none;
      white-space: nowrap;
      box-shadow: 0 1px 0 rgba(255, 255, 255, 0.76) inset, 0 1px 2px rgba(0, 0, 0, 0.045);
    }
    .btn:hover {
      background: #ffffff;
      border-color: rgba(0, 0, 0, 0.18);
    }
    .btn:focus { outline: none; }
    .btn:focus-visible {
      border-color: rgba(0, 113, 227, 0.72);
      box-shadow: 0 0 0 3px rgba(0, 113, 227, 0.16);
    }
    .btn:active { transform: scale(0.98); }
    .btn.primary {
      border-color: rgba(0, 99, 210, 0.4);
      background: var(--accent);
      color: #ffffff;
      box-shadow: 0 1px 0 rgba(255, 255, 255, 0.24) inset, 0 1px 2px rgba(0, 0, 0, 0.08);
    }
    .btn.primary:hover { background: var(--accent-press); }
    .btn.iconOnly {
      width: 34px;
      padding: 0;
    }
    .btn:disabled {
      opacity: 0.46;
      cursor: not-allowed;
      box-shadow: none;
    }
    .btn svg, .appIcon svg {
      width: 16px;
      height: 16px;
      stroke: currentColor;
      stroke-width: 2;
      stroke-linecap: round;
      stroke-linejoin: round;
      fill: none;
      flex: 0 0 auto;
    }
    .workspace {
      min-height: 0;
      height: calc(100vh - 56px);
      display: grid;
      grid-template-columns: 640px 460px minmax(360px, 1fr);
      gap: 12px;
      padding: 12px;
      overflow: hidden;
    }
    .panel {
      min-width: 0;
      min-height: 0;
      height: 100%;
      display: flex;
      flex-direction: column;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      background: var(--surface);
      box-shadow: var(--shadow);
      overflow: hidden;
      backdrop-filter: saturate(180%) blur(20px);
      -webkit-backdrop-filter: saturate(180%) blur(20px);
    }
    .panelHeader {
      min-height: 40px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 10px;
      padding: 7px 12px;
      border-bottom: 1px solid var(--line-soft);
      background: rgba(255, 255, 255, 0.45);
    }
    .panelTitle {
      margin: 0;
      font-size: 13px;
      font-weight: 720;
      color: #2c2c2e;
    }
    .panelMeta {
      min-width: 0;
      color: var(--muted);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .panelBody {
      min-height: 0;
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 7px;
      padding: 10px 12px;
      overflow: hidden;
    }
    .formScroll {
      min-height: 0;
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 7px;
      overflow: hidden;
    }
    .grid2 {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 6px;
    }
    label.field {
      display: flex;
      flex-direction: column;
      gap: 4px;
      min-width: 0;
      color: var(--muted);
      font-size: 11px;
      font-weight: 650;
    }
    input.textInput, textarea {
      width: 100%;
      border: 1px solid rgba(0, 0, 0, 0.11);
      border-radius: 6px;
      outline: none;
      background: var(--surface-strong);
      color: var(--text);
      font-size: 12px;
      box-shadow: 0 1px 0 rgba(255, 255, 255, 0.72) inset;
    }
    input.textInput {
      height: 28px;
      padding: 0 8px;
    }
    textarea {
      resize: none;
      padding: 8px;
      line-height: 1.38;
      overflow: auto;
    }
    input.textInput:focus, textarea:focus {
      border-color: rgba(0, 113, 227, 0.65);
      background: #ffffff;
      box-shadow: 0 0 0 4px rgba(0, 122, 255, 0.14);
    }
    .miniArea { height: 51px; }
    .midArea { height: 60px; }
    #keySellingPointsText { height: 156px; }
    .archiveLine {
      display: grid;
      grid-template-columns: 62px 1fr;
      gap: 8px;
      align-items: center;
      min-height: 24px;
      padding: 2px 0 4px;
      border-bottom: 1px solid var(--line-soft);
      color: var(--muted);
      font-size: 12px;
    }
    .archiveLine strong {
      min-width: 0;
      color: var(--text);
      font-family: var(--mono);
      font-size: 12px;
      font-weight: 500;
      overflow-wrap: anywhere;
    }
    .submitRow {
      display: grid;
      grid-template-columns: 84px minmax(0, 1fr);
      gap: 8px;
      align-items: center;
      padding-top: 2px;
    }
    .submitRow .btn {
      width: 84px;
    }
    .libraryBox {
      min-height: 112px;
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 6px;
      padding-top: 6px;
      border-top: 1px solid var(--line-soft);
      overflow: hidden;
    }
    .libraryHeader {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      min-height: 24px;
    }
    .libraryActions {
      display: flex;
      align-items: center;
      gap: 6px;
      min-width: 0;
    }
    .libraryTitle {
      font-size: 12px;
      font-weight: 720;
      color: var(--text);
    }
    .libraryMeta {
      color: var(--muted);
      font-size: 11px;
      white-space: nowrap;
    }
    .libraryList {
      min-height: 0;
      flex: 1;
      display: flex;
      flex-direction: column;
      gap: 5px;
      overflow: auto;
      padding-right: 2px;
    }
    .libraryItem {
      min-height: 34px;
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 8px;
      align-items: center;
      padding: 6px 7px;
      border: 1px solid rgba(0, 0, 0, 0.08);
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.72);
      color: var(--text);
      cursor: pointer;
      text-align: left;
      box-shadow: 0 1px 0 rgba(255, 255, 255, 0.7) inset;
    }
    .libraryItem:hover {
      background: #ffffff;
      border-color: rgba(0, 0, 0, 0.16);
    }
    .libraryItem.active {
      border-color: rgba(0, 122, 255, 0.45);
      background: rgba(0, 122, 255, 0.08);
    }
    .libraryName {
      min-width: 0;
      font-size: 12px;
      font-weight: 650;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .libraryTime {
      color: var(--muted);
      font-size: 11px;
      white-space: nowrap;
    }
    .libraryEmpty {
      color: var(--muted);
      font-size: 12px;
      padding: 8px 2px;
    }
    .targetTools {
      display: grid;
      grid-template-columns: auto 1fr;
      gap: 8px;
      align-items: center;
    }
    .hint {
      min-width: 0;
      color: var(--muted);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    #targetText {
      height: 220px;
      font-family: var(--font);
      font-size: 12px;
    }
    .stats {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 8px;
    }
    .stat {
      min-height: 38px;
      display: flex;
      flex-direction: column;
      justify-content: center;
      gap: 2px;
      padding: 6px 9px;
      border: 1px solid rgba(0, 0, 0, 0.09);
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.72);
      box-shadow: 0 1px 0 rgba(255, 255, 255, 0.7) inset;
    }
    .stat b {
      font-size: 17px;
      line-height: 1;
      font-weight: 720;
    }
    .stat span {
      color: var(--muted);
      font-size: 12px;
    }
    .fieldList {
      min-height: 0;
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      align-content: start;
      gap: 5px;
      overflow: hidden;
      padding-right: 2px;
    }
    .fieldItem {
      display: grid;
      grid-template-columns: 8px minmax(0, 1fr);
      gap: 5px 7px;
      align-items: center;
      min-height: 42px;
      padding: 4px 7px;
      border: 1px solid rgba(0, 0, 0, 0.08);
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.72);
      box-shadow: 0 1px 0 rgba(255, 255, 255, 0.7) inset;
    }
    .dot {
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: #c7c7cc;
    }
    .fieldItem.filled .dot { background: var(--ok); }
    .fieldName {
      min-width: 0;
      font-size: 12px;
      font-weight: 720;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .fieldValue {
      grid-column: 2;
      min-width: 0;
      color: var(--muted);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    #markdownPreview {
      flex: 1;
      min-height: 0;
      font-family: var(--mono);
      font-size: 12px;
      line-height: 1.48;
      white-space: pre;
      overflow: auto;
    }
    .statusBar {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      min-height: 34px;
      padding: 7px 12px;
      border-top: 1px solid var(--line-soft);
      color: var(--muted);
      font-size: 12px;
      background: rgba(255, 255, 255, 0.56);
    }
    .path {
      max-width: 72%;
      color: var(--text);
      font-family: var(--mono);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .toast {
      position: fixed;
      right: 18px;
      bottom: 18px;
      z-index: 40;
      max-width: min(440px, calc(100vw - 36px));
      padding: 10px 12px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: rgba(255, 255, 255, 0.92);
      box-shadow: 0 16px 42px rgba(0, 0, 0, 0.16);
      color: var(--text);
      opacity: 0;
      transform: translateY(10px);
      pointer-events: none;
      transition: opacity 170ms ease, transform 170ms ease;
      backdrop-filter: blur(18px);
      -webkit-backdrop-filter: blur(18px);
    }
    .toast.show {
      opacity: 1;
      transform: translateY(0);
    }
    .toast.error {
      border-color: rgba(188, 72, 0, 0.28);
      color: #8a2d00;
    }
    @media (max-width: 1440px) {
      .workspace {
        grid-template-columns: 560px 360px minmax(320px, 1fr);
      }
      #keySellingPointsText {
        height: 132px;
      }
      #targetText {
        height: 190px;
      }
      .fieldList {
        grid-template-columns: 1fr;
      }
      .fieldItem {
        min-height: 31px;
        grid-template-columns: 8px 84px minmax(0, 1fr);
      }
      .fieldValue {
        grid-column: auto;
      }
    }
    @media (max-width: 1120px) {
      .workspace {
        grid-template-columns: 500px 300px minmax(260px, 1fr);
      }
      #keySellingPointsText {
        height: 118px;
      }
      .toolbar .btn span { display: none; }
    }
  </style>
</head>
<body>
  <div class="shell">
    <header class="topbar">
      <div class="brand">
        <div class="appIcon" aria-hidden="true">
          <svg viewBox="0 0 24 24"><path d="M6 3h8l4 4v14H6z"></path><path d="M14 3v5h5"></path><path d="M8.5 12h7"></path><path d="M8.5 16h7"></path></svg>
        </div>
        <div>
          <h1>产品信息收集</h1>
          <div class="subtitle">本地整理 · BunnyAI 产品模板</div>
        </div>
      </div>
      <div class="toolbar">
        <button class="btn" id="previewBtn" title="刷新预览">
          <svg viewBox="0 0 24 24"><path d="M21 12s-3.5 6-9 6-9-6-9-6 3.5-6 9-6 9 6 9 6z"></path><circle cx="12" cy="12" r="3"></circle></svg>
          <span>预览</span>
        </button>
        <button class="btn primary" id="generateBtn" title="生成 Markdown 文件">
          <svg viewBox="0 0 24 24"><path d="M19 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11l5 5v11a2 2 0 0 1-2 2z"></path><path d="M17 21v-8H7v8"></path><path d="M7 3v5h8"></path></svg>
          <span>生成</span>
        </button>
      </div>
    </header>

    <main class="workspace">
      <section class="panel">
        <div class="panelHeader">
          <h2 class="panelTitle">产品录入</h2>
          <div class="panelMeta">手动输入</div>
        </div>
        <div class="panelBody">
          <div class="formScroll">
            <div class="grid2">
              <label class="field">中文名称
                <input class="textInput productInput" id="productNameZh" />
              </label>
              <label class="field">本地名称
                <input class="textInput productInput" id="productNameLocal" />
              </label>
              <label class="field">国家/地区
                <input class="textInput productInput" id="country" />
              </label>
              <label class="field">分类 ID
                <input class="textInput productInput" id="categories" placeholder="1, 2, 3" />
              </label>
              <label class="field">原价
                <input class="textInput productInput" id="originalPrice" />
              </label>
              <label class="field">促销价
                <input class="textInput productInput" id="promotionalPrice" />
              </label>
            </div>

            <div class="archiveLine">
              <span>存储目录</span>
              <strong id="archiveRoot">当前智能体 / product</strong>
            </div>

            <label class="field">规格
              <textarea class="productInput miniArea" id="specificationsText" spellcheck="false" placeholder="容量: 500ml / 300ml"></textarea>
            </label>
            <label class="field">扩展属性
              <textarea class="productInput miniArea" id="extendedAttributesText" spellcheck="false" placeholder="适用场景: 日常使用"></textarea>
            </label>
            <label class="field">核心卖点
              <textarea class="productInput midArea" id="keySellingPointsText" spellcheck="false" placeholder="标题: 描述"></textarea>
            </label>
            <label class="field">SKU 清单
              <textarea class="productInput midArea" id="skusText" spellcheck="false" placeholder="SKU001 | 容量=500ml | 99 | 79"></textarea>
            </label>
            <div class="submitRow">
              <button class="btn primary" id="submitBtn" title="生成目标用户并存储 Markdown">
                <svg viewBox="0 0 24 24"><path d="M20 6 9 17l-5-5"></path></svg>
                提交
              </button>
              <span class="hint">生成目标用户并存储</span>
            </div>
            <div class="libraryBox">
              <div class="libraryHeader">
                <span class="libraryTitle">产品库</span>
                <div class="libraryActions">
                  <span class="libraryMeta" id="libraryMeta">0 个</span>
                  <button class="btn iconOnly" id="openLibraryDirBtn" title="打开产品库目录" aria-label="打开产品库目录">
                    <svg viewBox="0 0 24 24"><path d="M3 7h5l2 2h11v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><path d="M3 7V5a2 2 0 0 1 2-2h4l2 2h5a2 2 0 0 1 2 2v2"></path></svg>
                  </button>
                </div>
              </div>
              <div class="libraryList" id="libraryList">
                <div class="libraryEmpty">暂无产品信息</div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section class="panel">
        <div class="panelHeader">
          <h2 class="panelTitle">目标用户</h2>
          <div class="panelMeta" id="fieldMeta">0/__FIELD_COUNT__</div>
        </div>
        <div class="panelBody">
          <div class="targetTools">
            <button class="btn primary" id="targetBtn" title="生成目标用户与核心痛点">
              <svg viewBox="0 0 24 24"><path d="M12 3v4"></path><path d="M12 17v4"></path><path d="M3 12h4"></path><path d="M17 12h4"></path><path d="m5.6 5.6 2.8 2.8"></path><path d="m15.6 15.6 2.8 2.8"></path><path d="m18.4 5.6-2.8 2.8"></path><path d="m8.4 15.6-2.8 2.8"></path></svg>
              生成目标用户
            </button>
            <span class="hint" id="targetMeta">0 组</span>
          </div>
          <textarea id="targetText" spellcheck="false" placeholder="目标客户 | 核心痛点"></textarea>
          <div class="stats">
            <div class="stat"><b id="filledStat">0</b><span>已填写</span></div>
            <div class="stat"><b id="totalStat">__FIELD_COUNT__</b><span>字段</span></div>
          </div>
          <div class="fieldList" id="fieldList"></div>
        </div>
      </section>

      <section class="panel previewPanel">
        <div class="panelHeader">
          <h2 class="panelTitle">Markdown</h2>
          <button class="btn iconOnly" id="copyBtn" title="复制 Markdown" aria-label="复制 Markdown">
            <svg viewBox="0 0 24 24"><rect x="9" y="9" width="13" height="13" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
          </button>
        </div>
        <div class="panelBody">
          <textarea id="markdownPreview" readonly spellcheck="false"></textarea>
        </div>
        <div class="statusBar">
          <span id="statusText">待预览</span>
          <span class="path" id="outputPath"></span>
        </div>
      </section>
    </main>
  </div>
  <div class="toast" id="toast"></div>

  <script>
    const INITIAL_FIELDS = __INITIAL_FIELDS__;
    const FIELD_COUNT = __FIELD_COUNT__;
    const $ = (id) => document.getElementById(id);
    const markdownPreview = $("markdownPreview");
    const fieldList = $("fieldList");
    const libraryList = $("libraryList");
    const libraryMeta = $("libraryMeta");
    const outputPath = $("outputPath");
    const statusText = $("statusText");
    const toast = $("toast");
    let selectedLibraryPath = "";
    let toastTimer = 0;

    function showToast(message, isError = false) {
      toast.textContent = message;
      toast.className = "toast show" + (isError ? " error" : "");
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => toast.className = "toast", 2600);
    }

    async function api(path, body) {
      const response = await fetch(path, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body)
      });
      const data = await response.json();
      if (!response.ok || data.ok === false) {
        throw new Error(data.error || "请求失败");
      }
      return data;
    }

    function splitRows(text) {
      return String(text || "")
        .split(/\n+/)
        .map((line) => line.trim())
        .filter(Boolean);
    }

    function splitNameValue(line) {
      const pipeParts = line.split(/\s*[|｜]\s*/).filter((part) => part.trim());
      if (pipeParts.length >= 2) return [pipeParts[0].trim(), pipeParts.slice(1).join(" | ").trim()];
      const match = line.match(/^(.{1,40}?)[：:=]\s*(.+)$/);
      if (match) return [match[1].trim(), match[2].trim()];
      return [line.trim(), ""];
    }

    function splitValues(value) {
      return String(value || "")
        .split(/\s*[\/／]\s*/)
        .map((item) => item.trim())
        .filter(Boolean);
    }

    function parseNameValueText(text, options = {}) {
      const rows = [];
      for (const line of splitRows(text)) {
        const [name, value] = splitNameValue(line);
        if (!name && !value) continue;
        const values = options.splitValues ? splitValues(value || name) : [value];
        for (const item of values) {
          rows.push({name, value: item || value || name});
        }
      }
      return rows;
    }

    function parseSellingPoints(text) {
      return splitRows(text).map((line) => {
        const [title, description] = splitNameValue(line);
        return {title, description: description || title};
      }).filter((item) => item.title || item.description);
    }

    function parseTargets(text) {
      return splitRows(text).map((line) => {
        const parts = line.split(/\s*[|｜]\s*/);
        if (parts.length >= 2) {
          return {targetAudience: parts[0].trim(), corePainPoints: parts.slice(1).join(" | ").trim()};
        }
        const [targetAudience, corePainPoints] = splitNameValue(line);
        return {targetAudience, corePainPoints};
      }).filter((item) => item.targetAudience || item.corePainPoints);
    }

    function parseAttributes(combo) {
      const attributes = {};
      const segments = String(combo || "").split(/\s*[;；,+，、]\s*/).filter(Boolean);
      for (const segment of segments) {
        const match = segment.match(/^(.{1,24}?)[：:=]\s*(.+)$/);
        if (match) attributes[match[1].trim()] = match[2].trim();
      }
      if (!Object.keys(attributes).length && combo) attributes["规格组合"] = combo;
      return attributes;
    }

    function parseSkus(text) {
      return splitRows(text).map((line) => {
        const parts = line.split(/\s*[|｜]\s*/).map((item) => item.trim());
        return {
          skuId: parts[0] || "",
          attributes: parseAttributes(parts[1] || ""),
          price: {
            originalPrice: parts[2] || "",
            promotionalPrice: parts[3] || ""
          }
        };
      }).filter((item) => item.skuId || Object.keys(item.attributes).length || item.price.originalPrice || item.price.promotionalPrice);
    }

    function formatNameValueRows(rows) {
      return (rows || []).map((row) => `${row.name || ""}: ${row.value || ""}`.trim()).join("\n");
    }

    function formatSellingPoints(rows) {
      return (rows || []).map((row) => `${row.title || ""}: ${row.description || ""}`.trim()).join("\n");
    }

    function formatTargets(rows) {
      return (rows || []).map((row) => `${row.targetAudience || ""} | ${row.corePainPoints || ""}`.trim()).join("\n");
    }

    function formatAttributes(attributes) {
      const entries = Object.entries(attributes || {});
      if (!entries.length) return "";
      return entries.map(([key, value]) => `${key}=${value}`).join("; ");
    }

    function formatSkus(rows) {
      return (rows || []).map((row) => {
        const price = row.price || {};
        return [row.skuId || "", formatAttributes(row.attributes), price.originalPrice || "", price.promotionalPrice || ""].join(" | ");
      }).join("\n");
    }

    function formData() {
      return {
        productNameZh: $("productNameZh").value.trim(),
        productNameLocal: $("productNameLocal").value.trim(),
        country: $("country").value.trim(),
        categories: $("categories").value.split(/\s*[,，、\/]\s*/).map((item) => item.trim()).filter(Boolean),
        price: {
          originalPrice: $("originalPrice").value.trim(),
          promotionalPrice: $("promotionalPrice").value.trim()
        },
        specifications: parseNameValueText($("specificationsText").value, {splitValues: true}),
        extendedAttributes: parseNameValueText($("extendedAttributesText").value),
        keySellingPoints: parseSellingPoints($("keySellingPointsText").value),
        targetAudienceAndPainPoints: parseTargets($("targetText").value),
        skus: parseSkus($("skusText").value)
      };
    }

    function fillForm(data = {}) {
      $("productNameZh").value = data.productNameZh || "";
      $("productNameLocal").value = data.productNameLocal || "";
      $("country").value = data.country || "";
      $("categories").value = (data.categories || []).join(", ");
      const price = data.price || {};
      $("originalPrice").value = price.originalPrice || "";
      $("promotionalPrice").value = price.promotionalPrice || "";
      $("specificationsText").value = formatNameValueRows(data.specifications || []);
      $("extendedAttributesText").value = formatNameValueRows(data.extendedAttributes || []);
      $("keySellingPointsText").value = formatSellingPoints(data.keySellingPoints || []);
      $("targetText").value = formatTargets(data.targetAudienceAndPainPoints || []);
      $("skusText").value = formatSkus(data.skus || []);
      updateTargetMeta();
      statusText.textContent = "待预览";
    }

    function payload() {
      return {
        product_data: formData(),
        filename: "manual_product_input.txt",
        project_slug: "",
        overwrite_path: selectedLibraryPath || "",
        compact: false
      };
    }

    function renderFields(fields = []) {
      fieldList.innerHTML = "";
      for (const field of fields) {
        const item = document.createElement("div");
        item.className = "fieldItem" + (field.filled ? " filled" : "");
        const dot = document.createElement("span");
        dot.className = "dot";
        const name = document.createElement("div");
        name.className = "fieldName";
        name.textContent = field.label;
        const value = document.createElement("div");
        value.className = "fieldValue";
        value.textContent = field.value || "未填写";
        item.append(dot, name, value);
        fieldList.appendChild(item);
      }
    }

    function renderLibrary(items = [], activePath = selectedLibraryPath) {
      selectedLibraryPath = activePath || selectedLibraryPath;
      libraryList.innerHTML = "";
      libraryMeta.textContent = `${items.length} 个`;
      if (!items.length) {
        const empty = document.createElement("div");
        empty.className = "libraryEmpty";
        empty.textContent = "暂无产品信息";
        libraryList.appendChild(empty);
        return;
      }
      for (const item of items) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "libraryItem" + (item.path === selectedLibraryPath ? " active" : "");
        button.title = item.path || item.name || "";
        const name = document.createElement("span");
        name.className = "libraryName";
        name.textContent = item.title || item.name || "未命名产品";
        const time = document.createElement("span");
        time.className = "libraryTime";
        time.textContent = item.updated || "";
        button.append(name, time);
        button.addEventListener("click", () => openLibraryItem(item.path));
        libraryList.appendChild(button);
      }
    }

    function updateTargetMeta() {
      const count = parseTargets($("targetText").value).length;
      $("targetMeta").textContent = `${count} 组`;
    }

    function applyResult(data) {
      if (data.product_data && data.product_data.targetAudienceAndPainPoints) {
        $("targetText").value = formatTargets(data.product_data.targetAudienceAndPainPoints || []);
        updateTargetMeta();
      }
      markdownPreview.value = data.markdown || "";
      renderFields(data.fields || []);
      $("filledStat").textContent = data.filled_count || 0;
      $("totalStat").textContent = data.field_count || FIELD_COUNT;
      $("fieldMeta").textContent = `${data.filled_count || 0}/${data.field_count || FIELD_COUNT}`;
      outputPath.textContent = data.display_path || "";
      statusText.textContent = data.written ? "已生成" : "已预览";
    }

    function setActionBusy(isBusy) {
      $("submitBtn").disabled = isBusy;
      $("generateBtn").disabled = isBusy;
      $("previewBtn").disabled = isBusy;
      $("targetBtn").disabled = isBusy;
    }

    async function preview() {
      try {
        setActionBusy(true);
        const data = await api("/api/preview", payload());
        applyResult(data);
      } catch (error) {
        showToast(error.message, true);
      } finally {
        setActionBusy(false);
      }
    }

    async function ensureTargets(force = false) {
      if (!force && parseTargets($("targetText").value).length > 0) return;
      const data = await api("/api/targets", {product_data: {...formData(), targetAudienceAndPainPoints: []}});
      $("targetText").value = formatTargets(data.rows || []);
      updateTargetMeta();
    }

    async function generate() {
      try {
        setActionBusy(true);
        const overwriting = !!selectedLibraryPath;
        await ensureTargets(false);
        const data = await api("/api/generate", payload());
        applyResult(data);
        selectedLibraryPath = data.display_path || selectedLibraryPath;
        await loadLibrary(data.display_path);
        showToast(overwriting ? "已提交并覆盖" : "已提交并存储");
      } catch (error) {
        showToast(error.message, true);
      } finally {
        setActionBusy(false);
      }
    }

    async function generateTargets() {
      try {
        setActionBusy(true);
        await ensureTargets(true);
        await preview();
      } catch (error) {
        showToast(error.message, true);
      } finally {
        setActionBusy(false);
      }
    }

    async function loadState() {
      try {
        const response = await fetch("/api/state");
        const data = await response.json();
        if (response.ok && data.archive_root) {
          $("archiveRoot").textContent = data.archive_root;
        }
      } catch (error) {
        $("archiveRoot").textContent = "当前智能体 / product";
      }
    }

    async function loadLibrary(activePath = selectedLibraryPath) {
      try {
        const response = await fetch("/api/library");
        const data = await response.json();
        if (!response.ok || data.ok === false) throw new Error(data.error || "产品库读取失败");
        renderLibrary(data.items || [], activePath);
      } catch (error) {
        libraryMeta.textContent = "读取失败";
      }
    }

    async function openLibraryItem(path) {
      try {
        if (!path) return;
        selectedLibraryPath = path;
        const data = await api("/api/library/read", {path});
        if (data.product_data) {
          fillForm(data.product_data);
          renderFields(data.fields || []);
          $("filledStat").textContent = data.filled_count || 0;
          $("totalStat").textContent = data.field_count || FIELD_COUNT;
          $("fieldMeta").textContent = `${data.filled_count || 0}/${data.field_count || FIELD_COUNT}`;
        }
        markdownPreview.value = data.markdown || "";
        outputPath.textContent = data.display_path || path;
        statusText.textContent = "已载入，可修改后覆盖";
        await loadLibrary(path);
      } catch (error) {
        showToast(error.message, true);
      }
    }

    async function openLibraryDirectory() {
      try {
        const data = await api("/api/library/open", {});
        showToast(`已打开 ${data.display_path || "产品库目录"}`);
      } catch (error) {
        showToast(error.message, true);
      }
    }

    $("submitBtn").addEventListener("click", generate);
    $("previewBtn").addEventListener("click", preview);
    $("generateBtn").addEventListener("click", generate);
    $("targetBtn").addEventListener("click", generateTargets);
    $("openLibraryDirBtn").addEventListener("click", openLibraryDirectory);
    $("copyBtn").addEventListener("click", async () => {
      if (!markdownPreview.value) {
        showToast("当前没有 Markdown", true);
        return;
      }
      await navigator.clipboard.writeText(markdownPreview.value);
      showToast("已复制");
    });
    for (const element of document.querySelectorAll(".productInput, #targetText")) {
      element.addEventListener("input", () => {
        statusText.textContent = "待预览";
        if (element.id === "targetText") updateTargetMeta();
      });
    }

    loadState();
    loadLibrary();
    renderFields(INITIAL_FIELDS);
    updateTargetMeta();
  </script>
</body>
</html>
"""


def app_html() -> str:
    initial_fields = json.dumps(
        [{"label": spec.label, "value": "", "filled": False} for spec in OUTPUT_FIELD_SPECS],
        ensure_ascii=False,
    )
    return (
        HTML_TEMPLATE.replace("__FIELD_COUNT__", str(len(OUTPUT_FIELD_SPECS))).replace(
            "__INITIAL_FIELDS__",
            initial_fields,
        )
    )


class ProductInfoWebHandler(BaseHTTPRequestHandler):
    server_version = "ProductInfoAgentWeb/1.1"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        try:
            route = urlparse(self.path).path
            if route == "/":
                text_response(self, 200, app_html())
                return
            if route == "/api/state":
                json_response(
                    self,
                    200,
                    {
                        "ok": True,
                        "root": str(ROOT),
                        "archive_root": f"当前智能体 / {display_path(archive_root_path())}",
                        "sample_available": SAMPLE_PATH.exists(),
                        "sample_path": display_path(SAMPLE_PATH),
                    },
                )
                return
            if route == "/api/library":
                json_response(
                    self,
                    200,
                    {
                        "ok": True,
                        "items": product_library_items(),
                        "archive_root": display_path(archive_root_path()),
                    },
                )
                return
            if route == "/api/sample":
                if not SAMPLE_PATH.exists():
                    json_response(self, 404, {"ok": False, "error": "示例文件不存在"})
                    return
                json_response(
                    self,
                    200,
                    {
                        "ok": True,
                        "filename": SAMPLE_PATH.name,
                        "text": SAMPLE_PATH.read_text(encoding="utf-8"),
                    },
                )
                return
            if route == "/api/sample-data":
                if not SAMPLE_PATH.exists():
                    json_response(self, 404, {"ok": False, "error": "示例文件不存在"})
                    return
                data, mode_used = product_data_from_text(SAMPLE_PATH.read_text(encoding="utf-8"), SAMPLE_PATH.name)
                json_response(
                    self,
                    200,
                    {
                        "ok": True,
                        "filename": SAMPLE_PATH.name,
                        "mode": mode_used,
                        "product_data": data,
                    },
                )
                return
            text_response(self, 404, "Not Found", "text/plain; charset=utf-8")
        except Exception as exc:
            json_response(self, 500, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:
        try:
            payload = read_request_json(self)
            route = urlparse(self.path).path
            if route == "/api/preview":
                json_response(self, 200, analyze_payload(payload, write_output=False))
                return
            if route == "/api/generate":
                json_response(self, 200, analyze_payload(payload, write_output=True))
                return
            if route == "/api/targets":
                data = normalize_product_data(payload.get("product_data", {}))
                rows = generate_target_audience_and_pain_points(data)
                json_response(self, 200, {"ok": True, "rows": rows})
                return
            if route == "/api/library/read":
                path = resolve_library_file(str(payload.get("path") or ""))
                markdown = path.read_text(encoding="utf-8", errors="ignore")
                data = product_data_from_markdown(markdown)
                fields = output_field_values_from_data(data)
                json_response(
                    self,
                    200,
                    {
                        "ok": True,
                        "markdown": markdown,
                        "product_data": data,
                        "fields": fields,
                        "filled_count": sum(1 for item in fields if item["filled"]),
                        "field_count": len(OUTPUT_FIELD_SPECS),
                        "display_path": display_path(path),
                    },
                )
                return
            if route == "/api/library/open":
                root = archive_root_path()
                root.mkdir(parents=True, exist_ok=True)
                subprocess.run(["open", str(root)], check=True)
                json_response(
                    self,
                    200,
                    {
                        "ok": True,
                        "path": str(root),
                        "display_path": display_path(root),
                    },
                )
                return
            if route == "/api/parse-text":
                raw_text = str(payload.get("text") or "").strip()
                if not raw_text:
                    raise ValueError("导入内容为空。")
                filename = Path(str(payload.get("filename") or "web_input.txt")).name
                data, mode_used = product_data_from_text(raw_text, filename)
                json_response(self, 200, {"ok": True, "mode": mode_used, "product_data": data})
                return
            json_response(self, 404, {"ok": False, "error": "接口不存在"})
        except Exception as exc:
            json_response(self, 400, {"ok": False, "error": str(exc)})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="产品信息收集智能体 Web 界面。")
    parser.add_argument("--host", default=HOST, help=f"监听地址，默认 {HOST}")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"监听端口，默认 {DEFAULT_PORT}")
    parser.add_argument("--open", action="store_true", help="启动后打开浏览器")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), ProductInfoWebHandler)
    url = f"http://{args.host}:{args.port}"
    print(f"产品信息收集 Web 界面: {url}", flush=True)
    if args.open:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("已停止。", flush=True)
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
