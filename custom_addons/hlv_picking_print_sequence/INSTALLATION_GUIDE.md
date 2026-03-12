# INSTALLATION GUIDE - HLV Stock Picking Print Sequence

## 📋 Mục Lục

1. [Yêu cầu hệ thống](#yêu-cầu-hệ-thống)
2. [Cài đặt bước từng bước](#cài-đặt-bước-từng-bước)
3. [Kiểm tra cài đặt](#kiểm-tra-cài-đặt)
4. [Cấu hình Odoo](#cấu-hình-odoo)
5. [Fix lỗi thường gặp](#fix-lỗi-thường-gặp)
6. [Uninstall module](#uninstall-module)

---

## 🔧 Yêu cầu hệ thống

- ✅ **Odoo 18.0** (hoặc tương thích)
- ✅ Module **stock** (Inventory/Warehouse) đã cài đặt
- ✅ Module **web** đã cài đặt  
- ✅ Quyền **Administrator** để cài đặt module

---

## 📦 Cài đặt bước từng bước

### **Bước 1: Copy module vào Odoo**

**Cách 1: Dùng File Manager**

```
1. Mở File Manager
2. Dẫn tới: D:\HLV\HLV-odoo-crm\custom_addons\
3. Copy thư mục: hlv_picking_print_sequence/
   (Trong thư mục này có: models/, views/, security/, __manifest__.py, etc.)
4. Done!
```

**Cách 2: Dùng Terminal/Command Prompt**

```bash
# Windows PowerShell
cd D:\HLV\HLV-odoo-crm\custom_addons\
# (hlv_picking_print_sequence đã ở đây rồi)

# Hoặc copy từ elsewhere:
# Copy-Item -Path ".\hlv_picking_print_sequence" -Destination "odoo_custom_addons\" -Recurse
```

**Cách 3: Dùng Git**

```bash
cd D:\HLV\HLV-odoo-crm
git add custom_addons/hlv_picking_print_sequence/
git commit -m "Add: hlv_picking_print_sequence module"
git push origin stagin
```

---

### **Bước 2: Restart Odoo Service**

**Cách 1: Restart Odoo Service (Linux)**

```bash
sudo systemctl restart odoo
# Hoặc
sudo service odoo restart
```

**Cách 2: Reload Odoo qua Browser**

```
1. Mở Odoo website
2. Vào: Settings > Technical > Actions > Server Actions > Search
3. Hoặc bấm Ctrl+Shift+R để refresh (Hard Refresh)
```

**Cách 3: Restart thủ công (Development)**

```bash
# Nếu chạy bằng command line
# Tắt: Ctrl+C
# Bật lại: python odoo-bin -c odoo.conf
```

---

### **Bước 3: Update Apps List trong Odoo**

```
1. Login vào Odoo với tài khoản Administrator
2. Vào: Settings > Apps > Update Apps List
   (Hoặc click "🔄" ở góc trái)
3. Chờ cho đến khi xong
4. ✅ Module sẽ xuất hiện trong danh sách
```

**Screenshot:**
```
Settings
  └─ Apps
      └─ Update Apps List ← Click vào đây
```

---

### **Bước 4: Tìm & Cài đặt Module**

```
1. Settings > Apps > Apps
2. Search: "HLV Stock Picking Print Sequence"
   Hoặc: "hlv_picking_print_sequence"
3. Click vào module
4. Bấm nút "Install" (xanh)
5. ⏳ Đợi cho đến khi xong (1-2 phút)
6. ✅ Status sẽ đổi thành "Installed"
```

---

### **Bước 5: Kiểm tra Cài đặt Thành Công**

```
✅ Vào menu: Inventory > Sắp xếp thứ tự in
✅ Nếu menu xuất hiện → Cài đặt thành công!
```

---

## 🔍 Kiểm tra cài đặt

### **Check 1: Module đã cài đặt**

```
Settings > Apps > Apps > Filter: Installed
→ Tìm "HLV Stock Picking Print Sequence"
→ Nếu có → ✅ Đã cài
```

### **Check 2: Menu đã xuất hiện**

```
Inventory > Sắp xếp thứ tự in > Xuất kho
→ Nếu menu có → ✅ Đã hoạt động
```

### **Check 3: Fields đã thêm vào**

```
1. Mở một picking bất kỳ
2. Scroll xuống tìm field "Thứ tự in"
3. Nếu có → ✅ Fields đã thêm thành công
```

### **Check 4: Database Log**

```
1. Settings > Technical > Logs
2. Tìm entries với model: "picking.print.sequence.wizard"
3. Nếu có entries → ✅ Module đang hoạt động
```

---

## ⚙️ Cấu hình Odoo

### **1. Enable Developer Mode (Optional)**

```
Developer Mode giúp debug dễ hơn:

1. Login > Settings > Activate the Developer Mode
2. Hoặc: Thêm ?debug=1 vào URL
   https://odoo.example.com/?debug=1
3. Sẽ có menu "Developer" ở footer
```

### **2. Setup Permissions (ACL)**

Module đã có ACL tự động:
- **Stock Users** → Có thể read, write (không delete)
- **Stock Managers** → Full access (read, write, create, delete)

Nếu cần custom:
```
Settings > Technical > Security > Access Control Lists
→ Tìm "picking.print.sequence.wizard"
→ Edit permissions cho group cụ thể
```

### **3. Configure Picking Types**

```
Kiểm tra Picking Types có hỗ trợ:

Inventory > Configuration > Picking Types
→ Tìm types: "Outgoing (Xuất kho)", "Incoming", "Internal"
→ Module hỗ trợ cả 3 loại
```

---

## 🐛 Fix Lỗi Thường Gặp

### **Lỗi 1: Module không xuất hiện sau Update Apps List**

**Triệu chứng:**
```
- Tìm "HLV Stock Picking Print Sequence" không thấy
- Hoặc thấy nhưng grayed out
```

**Giải pháp:**

```bash
# 1. Kiểm tra file __manifest__.py
d:\HLV\HLV-odoo-crm\custom_addons\hlv_picking_print_sequence\__manifest__.py

# 2. Nếu file bị lỗi, fix lại
# - Hãy đảm bảo JSON valid (dùng JSONlint.com)
# - Hãy đảm bảo imports đúng

# 3. Restart Odoo
sudo systemctl restart odoo

# 4. Update Apps List lại
# Settings > Apps > Update Apps List
```

---

### **Lỗi 2: "ModuleNotFoundError" hoặc "No module named wizard"**

**Triệu chứng:**
```
ERROR: [models] no model wizard
ERROR: models.wizard
```

**Giải pháp:**

```bash
# 1. Kiểm tra file models/__init__.py
cat models/__init__.py

# Phải có:
# from . import stock_picking
# from . import wizard

# 2. Nếu không có, edit lại file

# 3. Restart Odoo
sudo systemctl restart odoo
```

---

### **Lỗi 3: Fields không xuất hiện trong form**

**Triệu chứng:**
```
- Mở picking form không thấy "Thứ tự in"
- Cột "Thứ tự in" không có trong danh sách
```

**Giải pháp:**

```
# 1. Kiểm tra XML files
views/stock_picking_views.xml
→ Hãy đảm bảo XML valid (không lỗi syntax)

# 2. Settings > Technical > Views
→ Tìm "stock.picking.form.inherit.print.sequence"
→ Kiểm tra nó đã load

# 3. Nếu cột ẩn mặc định:
→ Click dropdown "▼" > Columns
→ Check "Thứ tự in"

# 4. Nếu vẫn không có, restart Odoo
sudo systemctl restart odoo
```

---

### **Lỗi 4: "Permission denied" hoặc "Access Denied"**

**Triệu chứng:**
```
- Click button nhưng toàn "Access Denied"
- Không thể edit dữ liệu
```

**Giải pháp:**

```
# 1. Kiểm tra user có thuộc group "Stock Users" hoặc "Stock Managers"
Settings > Users & Companies > Users
→ Mở user của bạn
→ Kiểm tra "Groups" có chứa "Inventory / Stock Users"

# 2. Nếu không có, thêm vào group

# 3. Kiểm tra ACL
Settings > Technical > Security > Access Control Lists
→ Tìm model "picking.print.sequence.wizard"
→ Hãy đảm bảo group của bạn có quyền

# 4. Logout & Login lại
```

---

### **Lỗi 5: Wizard không mở hoặc "Form view not found"**

**Triệu chứng:**
```
- Click button "Sắp xếp in" không có gì xảy ra
- Hoặc lỗi "Form view for model 'picking.print.sequence.wizard' could not be found"
```

**Giải pháp:**

```bash
# 1. Kiểm tra wizard_views.xml
cat views/wizard_views.xml

# Hãy đảm bảo:
# - XML không có lỗi syntax
# - Record id="picking_print_sequence_wizard_form" có tồn tại

# 2. Settings > Technical > Views
# → Tìm "picking.print.sequence.wizard.form"
# → Nếu không có, cài đặt lại module

# 3. Nếu vẫn lỗi, restart Odoo
sudo systemctl restart odoo
```

---

### **Lỗi 6: Database Error "Unknown field print_sequence"**

**Triệu chứng:**
```
ERROR: AttributeError: Unknown field 'print_sequence' on model 'stock.picking'
```

**Giải pháp:**

```bash
# 1. Kiểm tra migration/init
# Module sẽ tự động thêm fields vào database khi install

# 2. Nếu lỗi vẫn xảy ra, delete & reinstall module:

# 2a. Uninstall module
Settings > Apps > Apps > Search "HLV Stock Picking Print Sequence"
→ Click "Uninstall"
→ Confirm

# 2b. Delete module folder
rm -rf d:\HLV\HLV-odoo-crm\custom_addons\hlv_picking_print_sequence\

# 2c. Copy lại module
cp -r path/to/hlv_picking_print_sequence d:\HLV\HLV-odoo-crm\custom_addons\

# 2d. Restart & Install lại
```

---

### **Lỗi 7: "No matching database"**

**Triệu chứng:**
```
Database selection screen
Không thấy database
```

**Giải pháp:**

```bash
# Này là issue Odoo chung, không liên quan module

# 1. Kiểm tra Odoo config file
cat /etc/odoo/odoo.conf

# 2. Kiểm tra database server chạy chưa
sudo systemctl status postgresql

# 3. Nếu không chạy, start nó
sudo systemctl start postgresql
sudo systemctl restart odoo
```

---

## 🗑️ Uninstall Module

**Nếu cần gỡ module:**

```
1. Settings > Apps > Apps
2. Search: "HLV Stock Picking Print Sequence"
3. Click vào module
4. Click "Uninstall" (đỏ/đen)
5. Confirm

⚠️ WARNING: Dữ liệu (print_sequence values) sẽ bị xóa!
   Nếu muốn backup, export data trước.
```

**Backup dữ liệu trước khi uninstall:**

```
1. Inventory > Stock Pickings (tất cả)
2. Chọn tất cả
3. Click "⋮" > "Export"
4. Chọn fields: name, print_sequence, print_sequence_note
5. Format: CSV
6. Download
```

---

## 📊 Performance Tuning

Nếu bạn có 10,000+ picking records:

```
# 1. Thêm index cho quick search
# Edit models/stock_picking.py thêm:

print_sequence = fields.Integer(
    ...,
    index=True  # ← Thêm cái này
)

# 2. Batch processing (sắp xếp 1000 records mà không lag)
def action_auto_sequence_batch(self):
    batch_size = 1000
    pickings = self.search(...)
    
    for i in range(0, len(pickings), batch_size):
        batch = pickings[i:i+batch_size]
        for idx, picking in enumerate(batch, i+1):
            picking.print_sequence = idx
        
        self.env.cr.commit()  # Commit sau mỗi batch
```

---

## 🚀 Next Steps

Sau khi cài đặt xong:

1. ✅ **Đọc Quick Start:** `QUICK_START.md`
2. ✅ **Test module:** Tạo test picking & sắp xếp
3. ✅ **Configure:** Tuỳ chỉnh theo workflow của bạn
4. ✅ **Training:** Hướng dẫn team cách dùng
5. ✅ **Automation:** Setup Cron jobs (optional)

---

## 📞 Support

Nếu cần giúp:

1. **Check logs:** Settings > Technical > Logs
2. **Forum:** Hỏi trên diễn đàn Odoo community
3. **Contact:** Email admin@company.com

---

**Good luck! 🎉**
