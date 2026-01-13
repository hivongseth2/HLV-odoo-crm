# Hướng dẫn cài đặt HLV Barcode Shipper

## Yêu cầu hệ thống
- Odoo 18.0 trở lên
- Module `stock` (Inventory) đã được cài đặt
- Module `barcodes` đã được cài đặt
- Trình duyệt hỗ trợ HTML5 (cho mobile interface)

## Bước 1: Cài đặt Module

1. **Copy module vào thư mục addons:**
   ```bash
   cp -r hlv_barcode_shipper /path/to/odoo/custom_addons/
   ```

2. **Restart Odoo server:**
   ```bash
   sudo systemctl restart odoo
   ```

3. **Cập nhật danh sách module:**
   - Vào Settings > Apps
   - Nhấn "Update Apps List"

4. **Cài đặt module:**
   - Tìm "HLV Barcode Shipper"
   - Nhấn "Install"

## Bước 2: Cấu hình quyền người dùng

### Tạo nhóm Shipper
1. Vào Settings > Users & Companies > Groups
2. Tìm nhóm "Shipper" (đã được tạo tự động)
3. Thêm người dùng vào nhóm này

### Tạo nhóm Shipper Manager
1. Tìm nhóm "Shipper Manager"
2. Thêm người quản lý vào nhóm này

### Cấu hình người dùng Shipper
```python
# Ví dụ tạo user shipper qua Python
user = env['res.users'].create({
    'name': 'Shipper 01',
    'login': 'shipper01',
    'password': 'shipper123',
    'groups_id': [(4, env.ref('hlv_barcode_shipper.group_shipper').id)]
})
```

## Bước 3: Cấu hình Stock

### Đảm bảo Picking Types
- Kiểm tra có Picking Type "Delivery Orders" (code='outgoing')
- Kiểm tra có Picking Type "Internal Transfers" (code='internal')

### Cấu hình Packages (nếu sử dụng)
1. Vào Inventory > Configuration > Package Types
2. Tạo package types nếu cần
3. Đảm bảo packages có barcode/name duy nhất

## Bước 4: Test Module

### Test cơ bản
1. Tạo Sale Order
2. Confirm để tạo Delivery Order
3. Tạo Internal Transfer (PICK)
4. Liên kết PICK với Delivery Order

### Test giao diện Shipper
1. Login với user shipper
2. Vào menu "Shipper Scanner" > "📱 Mobile Scanner"
3. Test quét mã PICK
4. Test quét packages/products
5. Test hoàn tất delivery

## Bước 5: Cấu hình nâng cao

### Tùy chỉnh tìm kiếm OUT từ PICK
Sửa method `find_out_picking_by_pick_name` trong `stock_picking.py` nếu cần logic khác:

```python
def find_out_picking_by_pick_name(self, pick_name):
    # Custom logic here
    pass
```

### Tùy chỉnh barcode format
Sửa validation trong controller nếu cần format barcode khác:

```python
def scan_pick_order(self, **kwargs):
    barcode = data.get('barcode', '').strip()
    # Add custom validation here
```

### Cấu hình logging
Thêm vào config file:
```ini
[logger_hlv_barcode_shipper]
level = INFO
handlers = hand01
qualname = hlv_barcode_shipper
```

## Troubleshooting

### Lỗi "Access Denied"
- Kiểm tra user có trong nhóm "Shipper"
- Kiểm tra record rules trong security.xml

### Lỗi "PICK order not found"
- Kiểm tra tên PICK order có đúng format
- Kiểm tra picking type code
- Kiểm tra method `find_out_picking_by_pick_name`

### Lỗi "Package not found"
- Kiểm tra package có tồn tại trong picking
- Kiểm tra barcode/name của package
- Kiểm tra method `scan_package_or_product`

### Giao diện mobile không load
- Kiểm tra static files được serve đúng
- Kiểm tra browser console có lỗi JS
- Kiểm tra network requests

### API không hoạt động
- Kiểm tra CSRF token
- Kiểm tra authentication
- Kiểm tra request format (JSON)

## Backup và Restore

### Backup module data
```bash
pg_dump -h localhost -U odoo -t barcode_scan_log odoo_db > barcode_logs.sql
```

### Restore module data
```bash
psql -h localhost -U odoo -d odoo_db < barcode_logs.sql
```

## Performance Optimization

### Database indexes
```sql
CREATE INDEX idx_barcode_scan_log_picking_id ON barcode_scan_log(picking_id);
CREATE INDEX idx_barcode_scan_log_user_time ON barcode_scan_log(user_id, scan_time);
```

### Caching
- Enable Odoo caching
- Use CDN for static files
- Optimize database queries

## Security Checklist

- [ ] Record rules hoạt động đúng
- [ ] API endpoints có authentication
- [ ] CSRF protection enabled
- [ ] Input validation implemented
- [ ] Logging enabled cho audit trail
- [ ] User permissions configured correctly

## Monitoring

### Log files to monitor
- `/var/log/odoo/odoo.log` - General Odoo logs
- Database slow query log
- Web server access logs

### Key metrics
- Number of scans per day
- Average scan time
- Error rate
- User activity

## Support

Nếu gặp vấn đề, vui lòng:
1. Kiểm tra log files
2. Test với user admin
3. Kiểm tra database integrity
4. Liên hệ support team

Email: support@hoanglongvu.com
Phone: +84 xxx xxx xxx