#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""MCP server (stdio) đưa các tool MISA cho Claude, chạy tool bằng cách gọi Odoo.

Claude khởi động một tiến trình này cho MỖI lượt trả lời, nên bộ nhớ của tiến trình
chính là phạm vi "một lượt": cache tool đọc và chặn gọi lặp tool ghi nằm ở đây.

Tự viết giao thức thay vì dùng thư viện `mcp` để agent chỉ cần `requests` như agent
ghi hình — ở đây chỉ cần bốn method: initialize, ping, tools/list, tools/call.

Thông tin kết nối đến qua biến môi trường do agent đặt, không nằm trên dòng lệnh:
    HLV_ODOO_URL, HLV_AGENT_TOKEN, HLV_CLAIM_TOKEN
"""
import json
import os
import sys

import requests

from misa_tools import READ_ONLY_TOOLS, TOOL_NAMES, TOOLS

SERVER_INFO = {"name": "hlv-misa", "version": "1.0.0"}
DEFAULT_PROTOCOL = "2025-06-18"
# MISA chậm nhất ở lúc lấy token lần đầu; để rộng hơn thế một chút.
ODOO_TIMEOUT_SECONDS = 90


def _json(payload):
    return json.dumps(payload, ensure_ascii=False, default=str)


def call_odoo_tool(name, arguments):
    """Gửi một lệnh gọi tool lên Odoo.

    Trả: dict kết quả của tool, luôn có khoá 'status'.
    Biên: lỗi mạng / Odoo lỗi -> {'status': 'error', ...}. Không bao giờ raise, vì
    Claude cần thấy lỗi để nói thật với người dùng thay vì coi như "không tìm thấy".
    """
    url = os.environ.get("HLV_ODOO_URL", "").rstrip("/") + "/product_agent/agent/tool"
    body = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "token": os.environ.get("HLV_AGENT_TOKEN", ""),
            "claim_token": os.environ.get("HLV_CLAIM_TOKEN", ""),
            "name": name,
            "args": arguments,
        },
    }
    try:
        response = requests.post(url, json=body, timeout=ODOO_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except Exception as error:
        return {"status": "error", "message": "Không gọi được Odoo: %s" % error}

    if data.get("error"):
        message = (data["error"].get("data") or {}).get("message") or data["error"].get("message")
        return {"status": "error", "message": "Odoo báo lỗi: %s" % message}
    result = data.get("result")
    if not isinstance(result, dict):
        return {"status": "error", "message": "Odoo trả về dữ liệu lạ."}
    return result


class ToolRunner:
    """Chạy tool cho một lượt, nhớ những gì đã chạy trong lượt đó."""

    def __init__(self, call=call_odoo_tool):
        self._call = call
        self._cache = {}

    def run(self, name, arguments):
        """Trả dict kết quả. Tool ghi gọi lặp cùng tham số -> 'already_executed'."""
        if name not in TOOL_NAMES:
            return {"status": "error", "message": "Tool %s không tồn tại." % name}
        key = (name, json.dumps(arguments, sort_keys=True, ensure_ascii=False, default=str))
        if key in self._cache:
            if name in READ_ONLY_TOOLS:
                return self._cache[key]
            return {
                "status": "already_executed",
                "message": "Lệnh ghi này đã chạy trong lượt hiện tại. Không gọi lại; "
                           "dùng kết quả trước đó để trả lời người dùng.",
            }
        result = self._call(name, arguments)
        # Không cache lỗi: lỗi mạng chớp nhoáng thì lần gọi lại phải được đi thật.
        if result.get("status") != "error":
            self._cache[key] = result
        return result


def handle_request(message, runner):
    """Xử lý một message JSON-RPC. Trả dict response, hoặc None với notification."""
    method = message.get("method")
    msg_id = message.get("id")
    if msg_id is None:
        return None  # notification (vd notifications/initialized): không trả lời

    params = message.get("params") or {}
    if method == "initialize":
        result = {
            "protocolVersion": params.get("protocolVersion") or DEFAULT_PROTOCOL,
            "capabilities": {"tools": {}},
            "serverInfo": SERVER_INFO,
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        tool_result = runner.run(params.get("name"), params.get("arguments") or {})
        result = {
            "content": [{"type": "text", "text": _json(tool_result)}],
            "isError": tool_result.get("status") == "error",
        }
    else:
        return {
            "jsonrpc": "2.0", "id": msg_id,
            "error": {"code": -32601, "message": "Method not found: %s" % method},
        }
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def main():
    runner = ToolRunner()
    # Đọc/ghi bằng byte + utf-8: console Windows mặc định cp1252, in tiếng Việt là vỡ.
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    for raw_line in stdin:
        line = raw_line.decode("utf-8").strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            continue
        response = handle_request(message, runner)
        if response is not None:
            stdout.write((_json(response) + "\n").encode("utf-8"))
            stdout.flush()


if __name__ == "__main__":
    main()
