#!/usr/bin/env python3
import sys
import json
import urllib.request
import urllib.error

# --- CẤU HÌNH ---
# Thay đổi URL này thành địa chỉ Odoo thực tế của bạn
ODOO_URL = "http://hoanglongvu.odoo.com"
ENDPOINT = "/api/misa/product/search"


def search_product(keyword: str) -> None:
    url = f"{ODOO_URL}{ENDPOINT}"

    # Chuẩn bị payload theo chuẩn JSON-RPC của Odoo (type='json')
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": {
            "name": keyword,
            "limit": 5,  # Tìm 5 cái thôi cho gọn
        },
        "id": 1,
    }

    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=body, headers=headers, method="POST")

        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="replace")

        # Odoo có thể trả về 200 OK kể cả khi lỗi logic, cần check 'error' trong body
        data = json.loads(raw)

        if "error" in data:
            print(json.dumps({"status": "error", "message": data["error"]}, ensure_ascii=False))
        elif "result" in data:
            # Controller của bạn trả về data nằm trong key 'result'
            print(json.dumps(data["result"], ensure_ascii=False))
        else:
            print(json.dumps(data, ensure_ascii=False))

    except urllib.error.HTTPError as e:
        try:
            raw = e.read().decode("utf-8", errors="replace")
            detail = json.loads(raw)
        except Exception:
            detail = raw if "raw" in locals() else str(e)

        print(json.dumps({"status": "error", "message": "HTTPError", "detail": detail}, ensure_ascii=False))

    except urllib.error.URLError as e:
        print(json.dumps({"status": "error", "message": "URLError", "detail": str(e)}, ensure_ascii=False))

    except Exception as e:
        print(json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False))


if __name__ == "__main__":
    # Lấy tham số từ dòng lệnh
    if len(sys.argv) < 2:
        print(json.dumps({"error": "Vui lòng nhập tên sản phẩm"}, ensure_ascii=False))
        sys.exit(1)

    # Ghép các từ khóa lại (ví dụ: Khoan FPD3)
    keyword = " ".join(sys.argv[1:])
    search_product(keyword)
