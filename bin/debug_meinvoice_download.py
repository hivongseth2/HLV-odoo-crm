# Script: debug_meinvoice_download.py
# Mục đích: Thử nhiều payload format khác nhau cho /invoice/download để tìm format đúng
# Chạy: python odoo-bin shell -d <DATABASE> < bin/debug_meinvoice_download.py

import requests, json

TRANSACTION_ID = 'DQF0F517ZB9_'   # ← thay bằng transaction_id hóa đơn đã gửi

config = env['amis.callback.config'].sudo().search([], limit=1, order='id asc')
api_url = (config.meinvoice_api_url or '').rstrip('/')
config._ensure_meinvoice_token()
headers = {
    'Content-Type': 'application/json',
    'Authorization': 'Bearer %s' % config.meinvoice_token,
}

endpoint = api_url + '/invoice/download'

payloads = [
    # Format đã biết 200 — test thêm với PDF/XML
    ('POST list string',          'POST', None, [TRANSACTION_ID]),
    ('POST list dict camelCase',  'POST', None, [{'transactionId': TRANSACTION_ID, 'fileType': 'PDF'}]),
    ('POST list dict PascalCase', 'POST', None, [{'TransactionID': TRANSACTION_ID, 'FileType': 'PDF'}]),
    ('POST list dict XML',        'POST', None, [{'transactionId': TRANSACTION_ID, 'fileType': 'XML'}]),
    ('POST list dict XML Pascal', 'POST', None, [{'TransactionID': TRANSACTION_ID, 'FileType': 'XML'}]),
]

print("=" * 70)
print(f"Testing /invoice/download — transactionId={TRANSACTION_ID}")
print("=" * 70)

for label, method, params, body in payloads:
    try:
        if method == 'POST':
            resp = requests.post(endpoint, json=body, headers=headers, params=params, timeout=15)
        else:
            resp = requests.get(endpoint, headers=headers, params=params, timeout=15)

        try:
            rb = resp.json()
        except Exception:
            rb = resp.text[:300]

        status_mark = '✓' if resp.status_code == 200 else '✗'
        print(f"\n{status_mark} [{label}] → HTTP {resp.status_code}")
        print(f"  body: {json.dumps(rb, ensure_ascii=False, default=str)[:300]}")
    except Exception as e:
        print(f"\n! [{label}] → Exception: {e}")

print("\nDone.")
