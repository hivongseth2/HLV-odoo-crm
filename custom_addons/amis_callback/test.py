import hmac
import hashlib
import json
import urllib.request

# 1. Cấu hình (Bạn PHẢI thay đổi App ID cho khớp với Odoo)
url = "https://hoanglongvu-stagin-v1-30846915.dev.odoo.com/api/oauth/actopensupport/call_back_data_demo"
app_id = "cfd435c9-b5c9-484f-b86d-ddbba36dc0f4"  # Odoo đang dùng App ID làm Secret Key

# 2. Dữ liệu chi tiết trả về từ MISA (phần lõi)
data_list = [
    {
        "org_refid": "63084_TEST_Python",
        "success": True,
        "voucher_type": 18,
        "session_id": "session_001_abc"
    }
]

# Odoo yêu cầu trường 'data' là một chuỗi (string), nên phải dump mảng này ra chuỗi
data_string = json.dumps(data_list, ensure_ascii=False, separators=(',', ':'))

# 3. Tính toán Signature
# Hash đúng cái data_string bằng app_id
signature = hmac.new(
    app_id.encode('utf-8'),
    msg=data_string.encode('utf-8'),
    digestmod=hashlib.sha256
).hexdigest()

# 4. Gói tất cả vào Payload gửi lên Odoo
final_payload = {
    "app_id": app_id,
    "org_company_code": "HOANGLONGVU",
    "data_type": 20, 
    "success": True,
    "data": data_string, # Truyền cái chuỗi vừa bị hash vào đây
    "signature": signature # Truyền chữ ký để Odoo verify
}

final_body = json.dumps(final_payload)
print("--- Payload đang gửi đi ---")
print(final_body)

# 5. Thực hiện gửi Request
headers = {'Content-Type': 'application/json'}
req = urllib.request.Request(url, data=final_body.encode('utf-8'), headers=headers, method='POST')

try:
    with urllib.request.urlopen(req) as response:
        print("\n--- KẾT QUẢ TỪ ODOO ---")
        print("Status:", response.status)
        print("Response:", response.read().decode())
except urllib.error.HTTPError as e:
    print("\n--- LỖI HTTP ---")
    print("Status:", e.code)
    print("Response:", e.read().decode())