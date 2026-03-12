# QUICK START - HLV Picking Print Sequence

## 🚀 Cài đặt Nhanh

### 1. Copy Module
```bash
# Copy thư mục hlv_picking_print_sequence vào custom_addons/
cp -r hlv_picking_print_sequence /path/to/odoo/custom_addons/
```

### 2. Cài đặt trong Odoo
```
Settings > Apps > Update Apps List
→ Tìm "HLV Stock Picking Print Sequence"
→ Click "Install"
```

### 3. Restart Odoo
```bash
# Nếu cần restart Odoo service
sudo systemctl restart odoo
```

---

## 💡 Cách Dùng Cơ Bản

### Cách 1️⃣: Sắp xếp Thủ công (Đơn giản nhất)

**Menu:** `Inventory > Sắp xếp thứ tự in > Xuất kho`

1. Tìm phiếu cần sắp xếp
2. Click vào phiếu để mở chi tiết
3. Nhập số thứ tự trong trường **"Thứ tự in"**
   - Số 1 = In trước 
   - Số 2 = In thứ hai
   - Số 5 = In thứ ba
4. Lưu

```
VD:
Phiếu A: Thứ tự in = 3
Phiếu B: Thứ tự in = 1  ← In trước
Phiếu C: Thứ tự in = 2  ← In thứ hai
```

---

### Cách 2️⃣: Tự động Sắp xếp (Nhanh nhất)

**Menu:** `Inventory > Sắp xếp thứ tự in > Xuất kho`

1. **Chọn nhiều phiếu** (checkbox ☑️ bên trái)
2. Click menu "⋮" (3 chấm) 
3. Chọn **"Đánh số thứ tự tự động"**
4. ✅ Done! Hệ thống tự động đánh số từ 1, 2, 3...

> **Quy tắc:** Phiếu cũ hơn sẽ in trước (theo ngày tạo)

---

### Cách 3️⃣: Dùng Wizard (Nâng cao)

**Menu:** `Inventory > Sắp xếp thứ tự in > Wizard Sắp xếp`

Cửa sổ wizard cho phép:

```
📋 Chọn loại phiếu:      Xuất kho / Nhập kho / Chuyển nội bộ
⚙️  Cách sắp xếp:       
    ✓ Theo ngày tạo (cũ trước)
    ✓ Theo ngày giao dịch
    ✓ Theo kho / vị trí  
    ✓ Theo khách hàng (A-Z)
    ✓ Theo mức ưu tiên
🔍 Trạng thái:          Tất cả / Chờ / Xác nhận / Hoàn tất
```

**Steps:**
1. Chọn cách sắp xếp
2. Click "Xem trước" → Kiểm tra kết quả
3. Click "Áp dụng sắp xếp" → Lưu

---

## 📖 Các Tình Huống Sử Dụng

### ❌ Vấn đề: Cần in 50 phiếu theo thứ tự ngày

**Giải pháp:**
1. Filter: State = Done
2. Select All (Chọn tất cả)
3. Đánh số tự động
4. Bấm "In theo thứ tự"

### ❌ Vấn đề: Khách hàng A cần giao sớm hơn B

**Giải pháp:**
1. Mở phiếu của A
2. Nhập "Thứ tự in" = **1**
3. Mở phiếu của B
4. Nhập "Thứ tự in" = **2**
5. Save → In theo thứ tự

### ❌ Vấn đề: Cần sắp xếp lại (sắp xếp sai)

**Giải pháp:**
1. Chọn các phiếu bị sai
2. Click "⋮" > "Xóa thứ tự in"  
3. Sắp xếp lại từ đầu

---

## 👀 Các Field / Trường Mới

| Trường | Mô tả | VD |
|--------|-------|-----|
| **Thứ tự in** | Số thứ tự (nhỏ in trước) | 1, 2, 3, 5, 10 |
| **Ghi chú sắp xếp** | Ghi chú tại sao sắp xếp | "Khách VIP", "Cần dạo" |

---

## 🔍 Các Filter / Bộ Lọc

**Menu:** `Inventory > Sắp xếp thứ tự in`

- **"Có thứ tự in"** → Chỉ hiển thị phiếu đã sắp xếp (sequence > 0)
- **"Chưa sắp xếp"** → Chỉ hiển thị phiếu chưa gán thứ tự (sequence = 0)

---

## 🖱️ Các Nút / Button

| Nút | Chức năng |
|-----|-----------|
| **In theo thứ tự** | In các phiếu đã sắp xếp theo thứ tự |
| **Sắp xếp in** | Mở wizard sắp xếp |
| **Đánh số tự động** | Tự động gán thứ tự (hàng loạt) |
| **Xóa thứ tự in** | Reset lại thứ tự (xóa sequence) |

---

## ⚡ Mẹo & Thủ Thuật

### ✅ Mẹo 1: In PDF theo Thứ tự

```
1. Danh sách phiếu > Chọn phiếu cần in
2. Click "In theo thứ tự"
3. Hệ thống sẽ tự động in từ sequence nhỏ nhất
```

### ✅ Mẹo 2: Reset & Sắp xếp Lại

```
Nếu sắp xếp sai:
1. Chọn các phiếu
2. Click "⋮" > "Xóa thứ tự in" (Reset)
3. Sắp xếp lại
```

### ✅ Mẹo 3: Batch Processing (Hàng Loạt)

```
Sắp xếp 100+ phiếu:
1. Filter: State = Done
2. Select All
3. Wizard > Tự động sắp xếp > Áp dụng
```

### ✅ Mẹo 4: Export Danh Sách

```
1. Danh sách > Filter "Có thứ tự in"
2. Click "⋮" > "Export"
3. Chọn sheet > Download CSV/Excel
```

---

## 📱 Workflow Tiêu Biểu

### Workflow 1: Sắp xếp Xuất kho Hàng Ngày

```
SÁNG:
├─ Mở Inventory > Picking > Filter "Waiting"
├─ Chọn tất cả
├─ Đánh số tự động
└─ Done!

CHIỀU:
├─ Inventory > Sắp xếp thứ tự in > Xuất kho
├─ Filter "Có thứ tự in"
├─ Select All
└─ In theo thứ tự

📤 Result: PDF theo thứ tự 1, 2, 3...
```

### Workflow 2: Sắp xếp Theo Khách hàng

```
1. Mở Wizard: "Sắp xếp thứ tự in"
2. Chọn:
   ├─ Picking type: Xuất kho
   ├─ Trạng thái: Hoàn tất
   └─ Cách sắp xếp: Theo khách hàng (A-Z)
3. Click "Xem trước" → OK
4. Click "Áp dụng sắp xếp"
5. In theo thứ tự
```

---

## 🐛 Troubleshooting

### ❓ Q: Nó không hiển thị cột "Thứ tự in"?
**A:** 
- Cột được ẩn mặc định
- Click dropdown "▼" (Columns) 
- Check "Thứ tự in"

### ❓ Q: Bấm "In theo thứ tự" nhưng không có gì xảy ra?
**A:**
- Chắc là không có phiếu nào có sequence > 0
- Sắp xếp lại phiếu trước
- Hoặc filter "Có thứ tự in"

### ❓ Q: Muốn xóa sequence và sắp xếp lại?
**A:**
- Select phiếu → Click "⋮" → "Xóa thứ tự in"
- Rồi sắp xếp lại

### ❓ Q: Có thể sắp xếp theo múa custom không?
**A:**
- Hiện tại: theo ngày, khách hàng, kho, ưu tiên
- Muốn thêm: liên hệ IT để custom code

---

## 📞 Liên Hệ & Support

- **Bug Report:** Mô tả chi tiết + Screenshot vào Slack/Email
- **Feature Request:** Đề xuất tính năng mới
- **Training:** Yêu cầu training cho team

---

## 📝 Version History

| Version | Ngày | Ghi chú |
|---------|------|---------|
| **1.0.0** | Jan 2024 | Release đầu tiên |
| **1.0.1** | (TBD) | Thêm tính năng... |

---

**Happy Printing! 🖨️**
