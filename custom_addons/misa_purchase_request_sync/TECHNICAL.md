# TECHNICAL.md - misa_purchase_request_sync

## Mục đích
Module cung cấp 2 RESTful API endpoints cho **Browser Extension MISA CRM (Chrome MV3)** đẩy Yêu Cầu Mua Hàng (YCMH / Purchase Request) từ MISA CRM về Odoo, kèm một nút bấm stub trên form `purchase.request` cho hướng đẩy ngược (Odoo → MISA) - hiện đang TODO.

## Cấu trúc thư mục
```
misa_purchase_request_sync/
├── __init__.py
├── __manifest__.py
├── data/
│   └── ir_config_parameter.xml       # System Parameter 'misa_extension_token'
├── security/
│   └── ir.model.access.csv           # ACL cho purchase.request & line
├── models/
│   ├── __init__.py
│   └── purchase_request.py           # _inherit purchase.request: button + _prepare_misa_user
├── views/
│   └── purchase_request_view.xml     # Thêm nút "Đẩy sang MISA CRM" vào header form
├── controllers/
│   ├── __init__.py
│   └── extension_api.py             # 2 endpoints: check + create
└── TECHNICAL.md
```

## Quy tắc kiểm soát (Ownership)

| Chức năng | File sở hữu |
|---|---|
| Nút "Đẩy sang MISA CRM" trên form | `models/purchase_request.py` → `action_send_to_misa_crm()` |
| Logic map `OwnerIDText` → `res.users` | `models/purchase_request.py` → `_prepare_misa_user()` |
| Auth token (Bearer / X-MISA-Token) | `controllers/extension_api.py` → `_authenticate()` |
| GET kiểm tra PR đã tồn tại | `controllers/extension_api.py` → `api_extension_pr_check()` |
| POST tạo PR mới từ CRM | `controllers/extension_api.py` → `api_extension_pr_create()` |
| Token mặc định | `data/ir_config_parameter.xml` |

## RESTful API

### 1. `GET /api/extension/pr/check?name=<name>`
- **Mục đích**: Extension gọi để biết YCMH đã tồn tại trên Odoo hay chưa → quyết định inject nút "Tạo YCMH Odoo" hay inject cột "Trạng thái Odoo".
- **Auth**: Header `X-MISA-Token: <token>` hoặc query `?token=<token>`.
- **Response 200**:
  ```json
  {
    "ok": true,
    "exists": true,
    "id": 5,
    "name": "PR00001",
    "status": "draft",
    "status_label": "Mới"
  }
  ```

### 2. `POST /api/extension/pr/create`
- **Mục đích**: Tạo YCMH mới từ payload CRM.
- **Auth**: Header `X-MISA-Token` hoặc `{"token": "..."}` trong body.
- **Body JSON**:
  ```json
  {
    "PurchaseRequestName": "PR00001",
    "OwnerIDText": "MAI VĂN NAM (MAIVANNAM1)",
    "description": "YCMH từ CRM MISA",
    "lines": [
      {"product_code": "SP001", "name": "Sản phẩm A", "qty": 10, "uom": "Cái"}
    ]
  }
  ```
- **Response 200**:
  ```json
  {
    "ok": true,
    "id": 7,
    "name": "PR00001",
    "state": "draft",
    "lines_created": 1,
    "owner_warning": null
  }
  ```

## Xác thực
- Token lưu trong `ir.config_parameter` key `misa_extension_token`.
- Mặc định: `secret_token_123` (CHỈ dùng cho DEV/STAGING - đổi trên Production).
- So sánh: strip zero-width chars (`​-‍﻿`) trước khi so sánh để tránh lỗi copy/paste.
- Pattern tham chiếu: `misa_fetch_po_button/controllers/misa_api.py` (dùng `X-MISA-Token`).

## Luồng xử lý chính
```
Browser Extension (CRM MISA)
       │
       │ 1) xhr_interceptor.js bắt /api/business/PurchaseRequest/FormDataNew/...
       │ 2) postMessage(MISA_PR_DATA) → content_script.js
       │ 3) content_script gọi background.js → GET /api/extension/pr/check
       │
       ▼
Odoo (MisaExtensionController)
       │
       ├─ exists=false → content_script inject nút "Tạo YCMH Odoo"
       │     └─ click → background.js → POST /api/extension/pr/create
       │           └─ MisaExtensionController._prepare_misa_user()
       │           └─ pr.create() + pr.line_ids.create()
       │
       └─ exists=true → content_script inject cột "Trạng thái Odoo"
             └─ chỉ là DOM, KHÔNG ghi DB
```

## Mở rộng
- **Thêm field khác cho PR**: sửa `_prepare_misa_user` không liên quan - thêm fields vào `pr_vals` trong `api_extension_pr_create()`.
- **Thêm endpoint mới**: thêm method trong `MisaExtensionController`, route mới phải dùng `_authenticate()` ở đầu method.
- **Đổi token**: Settings > Technical > System Parameters > `misa_extension_token`.

## Lưu ý kỹ thuật
- Tuân thủ Odoo 18 rules: dùng `sudo()` trên recordset, không trên env; dùng `Command` cho O2M; dùng `<list>` thay `<tree>`.
- Tất cả write/create chạy dưới quyền `base.user_admin` để tránh block bởi record rules.
- `_prepare_misa_user` trả về `(user_id, message)`: nếu user không tìm thấy sẽ fallback về Admin và message sẽ post vào Chatter để truy vết sau.
