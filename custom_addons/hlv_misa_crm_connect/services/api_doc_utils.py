# -*- coding: utf-8 -*-
"""Dựng phần hướng dẫn của một endpoint: bảng tham số, JSON đẹp, lệnh curl.

Util thuần: vào chuỗi, ra chuỗi / list. Không đụng ``self.env``.
"""
import json


def pretty_json(text):
    """JSON thụt lề 2 để đọc. Nhận: chuỗi JSON (hoặc rỗng). Trả: chuỗi.

    Rỗng -> "". Không phải JSON hợp lệ -> trả nguyên văn (người viết mẫu tự chịu).
    """
    if not (text or "").strip():
        return ""
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except ValueError:
        return text


def compact_json(text):
    """JSON một dòng (để nhét vào curl). Rỗng -> "{}". Không hợp lệ -> nguyên văn bỏ xuống dòng."""
    if not (text or "").strip():
        return "{}"
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, separators=(",", ":"))
    except ValueError:
        return " ".join(text.split())


def build_curl(url, api_key, payload):
    """Lệnh curl (bash / Git Bash) gọi ``url`` với key và payload mẫu.

    Nhận: URL đầy đủ, key (rỗng -> "<API_KEY>"), chuỗi JSON mẫu (rỗng -> {}).
    Trả: chuỗi nhiều dòng. Dấu ' trong JSON được thoát kiểu bash ('\\'').
    """
    body = compact_json(payload).replace("'", "'\\''")
    return (
        "curl -sS -X POST '%s' \\\n"
        "  -H 'X-API-Key: %s' \\\n"
        "  -H 'Content-Type: application/json' \\\n"
        "  -d '%s'"
    ) % (url, api_key or "<API_KEY>", body)


def parse_params(text):
    """Bảng tham số viết dạng mỗi dòng ``tên | kiểu | bắt buộc | mô tả``.

    Nhận: chuỗi nhiều dòng. Trả: [{"name", "type", "required", "description"}].
    Dòng trống bị bỏ; dòng thiếu cột -> cột thiếu rỗng; "x" / "có" ở cột 3 = bắt buộc.
    """
    rows = []
    for line in (text or "").splitlines():
        if not line.strip():
            continue
        cells = [cell.strip() for cell in line.split("|", 3)] + ["", "", ""]
        rows.append({
            "name": cells[0], "type": cells[1],
            "required": cells[2].lower() in ("x", "có", "co", "yes", "true"),
            "description": cells[3],
        })
    return rows
