# HLV Barcode Realtime Inventory Sync

## Mô tả

Module này giải quyết các vấn đề khi sử dụng `stock_barcode` để kiểm kê:

- **Data loss**: Mất dữ liệu khi browser crash/refresh trước khi xác nhận
- **Multi-user conflict**: Nhiều người cùng 1 account quét đồng thời bị conflict

## Cách hoạt động

### Real-time Sync
- Mỗi lần quét barcode → gửi ngay về server (không đợi "Xác nhận")
- Dữ liệu được lưu trong model `inventory.scan.session`
- Khi nhấn "Xác nhận" → merge tất cả sessions vào stock.quant

### Device Fingerprint
- Mỗi thiết bị có ID riêng (lưu trong `localStorage`)
- Nhiều người dùng cùng account có thể quét đồng thời
- Sessions được merge tự động khi confirm

### UI Indicator
- Badge hiển thị ở góc phải trên màn hình
- Hiển thị số lượng scans đã được sync real-time
- Thông báo khi sync thành công/thất bại

## Cài đặt

```bash
# 1. Module đã được tạo trong custom_addons
cd custom_addons/hlv_barcode_realtime_inventory

# 2. Upgrade module
python odoo-bin -c odoo.conf -u hlv_barcode_realtime_inventory -d hlv_db

# 3. Hoặc upgrade qua UI
Settings → Apps → Update Apps List → Install
```

## Sử dụng

1. Vào **Inventory → Operations → Inventory Adjustments**
2. Tạo hoặc mở 1 Inventory Adjustment
3. Nhấn **Barcode Scanner** (action 364)
4. Quét barcode sản phẩm:
   - Thấy badge hiển thị "Real-time sync ACTIVE"
   - Mỗi lần quét → badge update số lượng scans
5. Nhấn **Validate** → tất cả sessions được merge

## Technical Details

### Models

**inventory.scan.session**
- Session ID (UUID từ frontend)
- Device ID (fingerprint)
- Location, User
- State: active/confirmed/cancelled

**inventory.scan.line**
- Product, Quantity
- Scan time
- Belong to session

### API Endpoints

```python
# Register một lần quét
inventory.scan.session.register_scan(
    session_id, device_id, location_id, product_id, qty
)

# Lấy summary của session
inventory.scan.session.get_session_summary(session_id)

# Merge sessions vào stock.quant
stock.quant.apply_realtime_inventory_sessions(location_id)
```

## Cleanup

Sessions cũ hơn 24h và đã confirmed sẽ được tự động xóa (cron job).

## License

LGPL-3
