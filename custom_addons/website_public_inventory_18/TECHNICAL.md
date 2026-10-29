# website_public_inventory_18 — Technical

## 1. Mục đích
Trang tra tồn `/search_stock` cho nhân viên (tồn / giữ / sẵn sàng / dự báo theo kho, giữ hàng), cùng các trang tra đơn, tra PO MISA. Mọi route chỉ cho nhân viên nội bộ (`controllers/access.py` → `internal_only`): `auth="user"` thôi thì tài khoản portal tự đăng ký cũng vào được.

## 2. Cấu trúc
```
website_public_inventory_18/
├── controllers/
│   ├── main.py                ← /search_stock và các endpoint JSON (breakdown, forecast_details, location_details, hold/*)
│   ├── order_lookup.py        ← tra đơn hàng
│   ├── misa_purchase_lookup.py← tra PO MISA
│   └── access.py              ← internal_only: chặn tài khoản không phải nhân viên nội bộ
├── models/                    ← stock.hold.request (giữ hàng), kế thừa quant/picking/warehouse
├── views/templates.xml        ← QWeb trang + JS (jQuery inline) render bảng kho khi bấm mở rộng
└── data/, security/, migrations/
```

## 3. File nào giữ logic nào
| Logic | Nơi duy nhất |
|---|---|
| Số dự báo + Nhập/Xuất ĐMH, ĐBH, chuyển kho (CK) | `controllers/main.py` `forecast_details` |
| Dòng theo kho khi mở rộng sản phẩm (tồn, giữ, sẵn sàng, dự báo, chuyển kho `qty_transfer_in/out`) | `controllers/main.py` `product_breakdown` — lấy số CK từ `forecast_details`, không tự tính lại |
| Render bảng kho (desktop + mobile), cột "Chuyển kho", dòng tóm tắt dưới Dự báo (`MH/BH/CK` từ `qty_po/qty_so/qty_transfer_*`) | `views/templates.xml` JS: `buildTransferCell`, `buildHeldNote`, `buildForecastNote` |

## 4. Luồng chính
1. Bấm mở rộng sản phẩm → POST `/search_stock/product_breakdown` → mỗi kho gọi `forecast_details` → trả rows.
2. JS render bảng: Tồn | Chuyển kho (`+nhận / −chuyển đi`) | Giữ | Sẵn sàng | Dự báo (bấm mở popup `forecast_details`).
3. Chuyển kho chỉ tính phiếu nội bộ chưa xong có nguồn/đích khác kho; bước 1 (Tồn kho → CHUYENKHO cùng kho) không tính.

## 5. Mở rộng
- Thêm cột theo kho: thêm key ở `product_breakdown`, render ở JS CASE 2 trong `templates.xml`.
- Khối QWeb `bk = r.get('breakdown')` trong `templates.xml` hiện không được controller set (không dùng).
