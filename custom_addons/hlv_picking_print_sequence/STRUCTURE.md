# 📂 Module Structure - File Directory

## Module: hlv_picking_print_sequence

```
hlv_picking_print_sequence/
│
├── 📄 __manifest__.py                    (Module metadata & dependencies)
├── 📄 __init__.py                        (Python package initializer)
├── 📄 README.md                          (Chi tiết & tính năng)
├── 📄 QUICK_START.md                     (Hướng dẫn nhanh cho users)
├── 📄 INSTALLATION_GUIDE.md              (Chi tiết cài đặt & troubleshooting)
├── 📄 utilities_and_examples.py          (Code examples & helper functions)
│
├── 📁 models/                            (Python models/business logic)
│   ├── __init__.py                       (Import models)
│   ├── stock_picking.py                  (Extend stock.picking + actions)
│   └── wizard.py                         (Wizard untuk UI interaktif)
│
├── 📁 views/                             (XML views/forms/lists)
│   ├── stock_picking_views.xml           (Extend picking form & list view)
│   └── wizard_views.xml                  (Wizard form & menus)
│
└── 📁 security/                          (Access control)
    └── ir.model.access.csv               (Group permissions)
```

---

## 📋 File-by-File Breakdown

### **__manifest__.py**
```
- Nama module: 'HLV Stock Picking Print Sequence'
- Version: 18.0.1.0.0 (Odoo 18)
- Dependencies: ['stock', 'web']
- Mendeklarasikan:
  ✅ Persyaratan modul
  ✅ File data yang perlu load (views, security)
  ✅ Installable = True
```

### **__init__.py**
```
from . import models
→ Import package models dari folder models/
```

---

### **models/__init__.py**
```
from . import stock_picking    → Import stock_picking model
from . import wizard           → Import wizard model
```

### **models/stock_picking.py**
```
Class: StockPicking (inherited from stock.picking)

Fields ditambah:
├─ print_sequence: Integer (thứ tự in)
└─ print_sequence_note: Char (ghi chú)

Methods ditambah:
├─ action_auto_sequence()         (Tự động đánh số)
├─ action_reset_sequence()        (Xóa thứ tự)
├─ action_print_by_sequence()     (In theo thứ tự)
├─ action_print_delivery_note()   (In biên bản giao)
├─ get_sorted_pickings_for_print() (Lấy danh sách sắp xếp)
└─ _assign_print_sequence_by_date() (Gán sequence theo ngày)
```

**File bao gồm:**
- Extend model stock.picking
- Thêm fields print_sequence & print_sequence_note
- Thêm 6+ action methods
- Có docstring chi tiết

### **models/wizard.py**
```
Class 1: PickingPrintSequenceWizard (transient model)
├── Fields:
│   ├─ sequence_method (Selection: manual, by_date, by_warehouse, etc)
│   ├─ picking_ids (Many2many - chọn phiếu cụ thể)
│   ├─ picking_type (Outgoing/Incoming/Internal)
│   ├─ state_filter (All/Waiting/Confirmed/Done)
│   ├─ reset_before (Boolean - xóa sequence cũ)
│   ├─ start_sequence (Integer - bắt đầu từ số)
│   └─ dry_run (xem trước mà không lưu)
│
└── Methods:
    ├─ action_preview()      (Xem trước kết quả)
    ├─ action_apply()        (Áp dụng sắp xếp)
    ├─ _get_target_pickings() (Lấy phiếu cần sắp xếp)
    └─ _sort_pickings()      (Logic sắp xếp)

Class 2: StockPickingAction
└─ action_open_print_sequence_wizard()  (Mở wizard từ picking form)
```

**File bao gồm:**
- Wizard form interaktif
- 6 cách sắp xếp (by_date, by_due_date, by_warehouse, etc)
- Preview trước khi apply
- Batch processing support

---

### **views/stock_picking_views.xml**
```
Records XML:
1. stock_picking_form_inherit_print_sequence
   └─ Thêm fields vào picking form

2. stock_picking_tree_inherit_print_sequence
   └─ Thêm cột vào list view

3. stock_picking_search_inherit_print_sequence
   └─ Thêm filters ("Có thứ tự in", "Chưa sắp xếp")

4. action_stock_picking_sortable_outgoing
   └─ Action untuk menu "Sắp xếp xuất kho"

5. action_stock_picking_sortable_internal
   └─ Action untuk menu "Sắp xếp chuyển nội bộ"

6. menu_picking_print_sequence
   └─ Menu item di Inventory

7. stock_picking_form_inherit_buttons
   └─ Tombol "In theo thứ tự"

8. action_stock_picking_auto_sequence
   └─ Server action "Đánh số tự động" (bulk)

9. action_stock_picking_reset_sequence
   └─ Server action "Xóa thứ tự in" (bulk)
```

**File bao gồm:**
- Extend picking form dengan fields baru
- Extend list view dengan cột sequence
- Thêm search filters
- Thêm menu items
- Thêm buttons & server actions

---

### **views/wizard_views.xml**
```
Records XML:
1. picking_print_sequence_wizard_form
   └─ Form view untuk wizard (fields + buttons)

2. action_picking_print_sequence_wizard
   └─ Window action untuk wizard

3. menu_wizard_print_sequence
   └─ Menu "Wizard Sắp xếp" di submenu

4. stock_picking_form_button_wizard
   └─ Tombol "Sắp xếp in" di picking form
```

**File bao gồm:**
- Wizard form layout
- Footer buttons (Xem trước, Áp dụng, Hủy)
- Menu item untuk wizard
- Button entry point di picking form

---

### **security/ir.model.access.csv**
```
Rows:
1. access_stock_picking_user
   └─ Everyone can read/write picking (not delete)

2. access_stock_picking_manager
   └─ Managers can full access (read/write/create/delete)

3. access_picking_print_sequence_wizard_user
   └─ Normal users can access wizard (read/write/create)

4. access_picking_print_sequence_wizard_manager
   └─ Managers: full access (delete juga)
```

**File bao gồm:**
- Group-based permissions
- Setiap row = satu rule ACL
- Format: CSV (Odoo standard)

---

### **README.md**
```
Dokumentasi lengkap:
├─ Mô tả module
├─ Tính năng chính
├─ Hướng dẫn sử dụng (3 cách)
├─ Các bộ lọc
├─ Python API examples
├─ Menu items
├─ Advanced features (auto-assign, reset)
├─ Troubleshooting
├─ Version history
└─ License & Support
```

---

### **QUICK_START.md**
```
Hướng dẫn nhanh (5 phút):
├─ Cài đặt nhanh
├─ Cách dùng cơ bản (3 cách)
├─ Tình huống sử dụng
├─ Fields mới
├─ Filters
├─ Buttons
├─ Mẹo & Thủ thuật
├─ 2 Workflows tiêu biểu
├─ Troubleshooting nhanh
└─ Version history
```

---

### **INSTALLATION_GUIDE.md**
```
Hướng dẫn cài đặt chi tiết:
├─ Yêu cầu hệ thống
├─ 5 bước cài đặt (copy, restart, update, search, install)
├─ Kiểm tra 4 điểm
├─ Cấu hình Odoo
├─ 7 lỗi phổ biến + cách fix
├─ Uninstall module
├─ Performance tuning
└─ Next steps
```

---

### **utilities_and_examples.py**
```
15 Python examples:
├─ 1. Sắp xếp thủ công
├─ 2. By date (cũ trước)
├─ 3. By due date (sớm trước)
├─ 4. By warehouse/vị trí
├─ 5. By customer (A-Z)
├─ 6. By priority (cao trước)
├─ 7. Filter & print
├─ 8. Batch daily sequence
├─ 9. Location + date combined
├─ 10. Skip blacklist items
├─ 11. Reset & resequence
├─ 12. Report with sequence
├─ 13. Cron job setup
├─ 14. Validate duplicate check
├─ 15. Export to CSV
└─ Migration guide
```

---

## 🗂️ File Organization Rationale

| Folder | Purpose | Contents |
|--------|---------|----------|
| **models/** | Business Logic | Python classes (stock_picking, wizard) |
| **views/** | UI / Forms / Lists | XML views untuk form, list, wizard |
| **security/** | Access Control | ACL groups (siapa punya akses apa) |
| **/root** | Metadata & Docs | .py/__manifest__, README, guides |

---

## 📊 Dependencies Between Files

```
__manifest__.py
│
├─→ models/__init__.py
│   ├─→ models/stock_picking.py (StockPicking class)
│   └─→ models/wizard.py (Wizard + action)
│
├─→ views/stock_picking_views.xml
│   └─ Ref: stock.picking model (inherit)
│
├─→ views/wizard_views.xml
│   └─ Ref: picking.print.sequence.wizard model
│
└─→ security/ir.model.access.csv
    ├─ Ref: stock.picking
    └─ Ref: picking.print.sequence.wizard
```

---

## 📦 Total Lines of Code

```
models/stock_picking.py    ~150 lines
models/wizard.py           ~200 lines
views/stock_picking_views.xml ~200 lines
views/wizard_views.xml     ~100 lines
utilities_and_examples.py  ~500 lines (examples only)
Documents (README, guides) ~1000 lines
───────────────────────────────────
Total: ~2,150 lines (production code only = ~650 lines)
```

---

## 🔄 Data Flow

```
User di UI
    ↓
[Menu: Sắp xếp thứ tự in]
    ↓
[stock_picking_views.xml: action_stock_picking_sortable_outgoing]
    ↓
[List view stock.picking (dengan field print_sequence)]
    ↓
User memilih pickings & click button
    ↓
[models/stock_picking.py: action_auto_sequence() / action_print_by_sequence()]
    ↓
Update field print_sequence di database
    ↓
Print PDF sesuai urutan (print_sequence asc)
```

Atau dengan Wizard:

```
Click Button "Sắp xếp in"
    ↓
[wizard_views.xml: action_open_print_sequence_wizard()]
    ↓
[models/wizard.py: PickingPrintSequenceWizard form]
    ↓
User pilih method (by_date, by_customer, etc)
    ↓
Click "Xem trước" / "Áp dụng"
    ↓
[wizard.py: action_preview() / action_apply()]
    ↓
_get_target_pickings() → _sort_pickings()
    ↓
Write print_sequence ke database
    ↓
Done!
```

---

## ✅ Checklist - Semua File Ada?

- [x] `__manifest__.py` - Module metadata
- [x] `__init__.py` - Package init
- [x] `models/__init__.py` - Models package
- [x] `models/stock_picking.py` - Extended stock.picking
- [x] `models/wizard.py` - Interactive wizard
- [x] `views/stock_picking_views.xml` - Form/list extensions
- [x] `views/wizard_views.xml` - Wizard forms
- [x] `security/ir.model.access.csv` - Permissions
- [x] `README.md` - Full documentation
- [x] `QUICK_START.md` - Quick guide
- [x] `INSTALLATION_GUIDE.md` - Setup guide
- [x] `utilities_and_examples.py` - Code examples

**Total: 12 files** ✅

---

## 🎯 Next: How to Use This Module

1. **First time install?** → Read `INSTALLATION_GUIDE.md`
2. **Want to use now?** → Read `QUICK_START.md`
3. **Need full docs?** → Read `README.md`
4. **Want custom?** → Check `utilities_and_examples.py`
5. **Got errors?** → Back to `INSTALLATION_GUIDE.md` troubleshooting section
