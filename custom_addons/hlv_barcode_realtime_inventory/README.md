# HLV Inventory Scanner

## Mô tả

Module kiểm kê tồn kho độc lập sử dụng barcode với khả năng:

- **Real-time sync**: Mỗi lần quét được lưu ngay vào database
- **Khôi phục session**: Reload trang không mất dữ liệu đã quét
- **Hiển thị chênh lệch**: So sánh số lượng thực tế vs lý thuyết

## Workflow

1. **Quét mã vị trí kho** → Module nhận diện location
2. **Quét sản phẩm** → Mỗi lần quét tự động cộng +1 và sync lên server
3. **Xem danh sách** → Hiển thị: `scanned_qty / theoretical_qty` + chênh lệch
4. **Áp dụng** → Cập nhật `stock.quant` với số lượng đã quét

## Tính năng chính

### Không mất dữ liệu khi reload
- Session được lưu trên server với `device_id` unique
- Khi mở lại → tự động khôi phục session active trước đó
- Tất cả sản phẩm đã quét vẫn còn nguyên

### Thao tác nhanh
- **+1, +10**: Tăng nhanh số lượng
- **Xóa**: Bỏ sản phẩm khỏi danh sách
- **Thêm sản phẩm**: Form thêm thủ công với số lượng tùy chọn

### Hiển thị trực quan
- **Badge "MỚI"**: Sản phẩm chưa có trong kho (theoretical = 0)
- **Chênh lệch màu**: Xanh (+) / Đỏ (-)

## Cài đặt

```bash
# Upgrade module
python odoo-bin -c odoo.conf -u hlv_barcode_realtime_inventory -d <database>
```

## Sử dụng

1. Vào **Inventory → Operations → Quét Kiểm Kê**
2. Quét barcode vị trí kho (hoặc chọn từ dropdown)
3. Quét barcode sản phẩm (quan sát số lượng tăng lên)
4. Nhấn **Áp dụng** để cập nhật vào kho

## Technical Details

### Models

**inventory.scan.session**
- `name`: Session ID tự động
- `device_id`: Fingerprint của thiết bị/browser
- `location_id`: Vị trí kho đang kiểm
- `state`: active / confirmed / cancelled
- `line_ids`: Các sản phẩm đã quét

**inventory.scan.line**
- `product_id`: Sản phẩm
- `scanned_qty`: Số lượng đã quét (tổng cộng)
- `theoretical_qty`: Số lượng lý thuyết từ stock.quant
- `difference`: Chênh lệch = scanned - theoretical

### API Methods

```python
# Khôi phục hoặc tạo session mới
session_data = env['inventory.scan.session'].get_or_create_active_session(device_id, location_id)

# Đăng ký 1 lần quét
result = env['inventory.scan.session'].register_scan(session_id, product_id, location_id, qty)

# Cập nhật số lượng line
result = session.update_line_qty(line_id, new_qty)

# Xác nhận và áp dụng vào kho
result = session.confirm_session()
```

## License

LGPL-3
