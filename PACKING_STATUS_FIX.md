# Sửa Lỗi Tính Toán Số Lượng Đã Đóng Gói

## Vấn Đề
Đơn hàng có 5 sản phẩm trong kho, chưa đóng gói gì (0 đã đóng) nhưng vẫn hiển thị ở cột "Đã Đóng Gói Đủ" trong Kanban.

## Nguyên Nhân
1. **Đếm cả phiếu trả hàng**: Logic cũ đếm TẤT CẢ picking có package, bao gồm cả phiếu trả hàng (returns), làm tăng số lượng packed sai
2. **Đếm sai khi có nhiều move line**: Logic cũ chỉ lấy qty của move line ĐẦU TIÊN cho mỗi package, bỏ sót các move line sau

## Giải Pháp
File: `services/delivery_planner_stock.py`

### Thay Đổi 1: Lọc chỉ phiếu xuất kho
```python
# CŨ: đếm tất cả picking
('result_package_id', '!=', False),
('state', '!=', 'cancel'),

# MỚI: chỉ đếm phiếu xuất (outgoing), không đếm trả hàng
('picking_id.picking_type_code', '=', 'outgoing'),
('result_package_id', '!=', False),
('state', 'not in', ['cancel', 'draft']),
```

### Thay Đổi 2: Đếm theo sản phẩm thay vì package
```python
# CŨ: đếm theo package, chỉ lấy lần đầu xuất hiện
so_pack_data = {}  # {so_id: {package_id: qty}}
if p_id not in so_pack_data[so_id]:
    so_pack_data[so_id][p_id] = float(ml.quantity)  # Chỉ lần đầu

# MỚI: đếm theo product, cộng dồn TẤT CẢ
so_pack_data = {}  # {so_id: {product_id: total_packed_qty}}
if prod_id not in so_pack_data[so_id]:
    so_pack_data[so_id][prod_id] = 0.0
so_pack_data[so_id][prod_id] += float(ml.quantity)  # Cộng dồn
```

## Cách Áp Dụng
1. Restart Odoo service:
   ```bash
   # Trên server
   sudo systemctl restart odoo
   # Hoặc docker
   docker-compose restart odoo
   ```

2. F5 lại trình duyệt để xóa cache frontend

3. Kiểm tra lại đơn [D-25644] - giờ sẽ hiển thị đúng ở cột "Có Hàng Chưa Đóng Gói"

## Kiểm Tra
- ✅ Đơn có hàng chưa đóng gói → cột "Có Hàng Chưa Đóng Gói"
- ✅ Đơn đã đóng hết phần có thể đóng → cột "Đã Đóng Gói Đủ"
- ✅ Đơn trả hàng KHÔNG ảnh hưởng đến số packed của đơn gốc
- ✅ Package có nhiều sản phẩm → đếm đúng tổng qty
