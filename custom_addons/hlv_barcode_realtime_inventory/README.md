# HLV Inventory Scanner - Mobile App

## 🎯 Standalone Mobile App cho Kiểm Kê Kho

App quét barcode độc lập với:
- ✅ **Camera Scanning** - Quét bằng camera điện thoại
- ✅ **Keyboard Input** - Hỗ trợ máy quét barcode  
- ✅ **Dark Theme** - Giao diện tối, dễ nhìn
- ✅ **Mobile-First** - Tối ưu cho điện thoại
- ✅ **Offline-Ready** - Không mất dữ liệu khi reload

---

## 📱 Cách sử dụng

### Truy cập Direct URL (không cần vào menu)

```
https://your-odoo-domain.com/web#action=hlv_barcode_realtime_inventory.action_inventory_scanner
```

Hoặc shortlink:
```
https://your-odoo-domain.com/inventory-scan
```

### Thêm vào Home Screen (PWA)

**Android/iPhone:**
1. Mở link trên
2. Menu → "Add to Home Screen"
3. Dùng như app native

---

## 🎬 Workflow

1. **Mở app** → Camera tự động bật
2. **Quét vị trí kho** → App nhận diện location
3. **Quét sản phẩm** → Mỗi lần quét +1, lưu ngay vào server
4. **Xem danh sách** → Số lượng quét / Số lượng lý thuyết
5. **Nhấn "Áp dụng"** → Cập nhật vào stock.quant

---

## 🎨 Tính năng

### Camera Scanning
- Sử dụng **BarcodeDetector API** (native browser)
- Hỗ trợ: Code128, Code39, EAN13, EAN8, QR Code
- Auto-detect trong 300ms

### Keyboard Mode
- Chuyển đổi ngay trong app
- Dành cho máy quét barcode USB/Bluetooth

### Real-time Sync
- Mỗi lần quét → Lưu ngay database
- Reload trang → Tự động khôi phục session

### Offline-Friendly
- Session & device fingerprint
- Restore data khi mất mạng/reload

---

## 🔧 Technical

### Browser Support

| Browser | Camera | Keyboard |
|---------|--------|----------|
| Chrome Mobile (Android) | ✅ | ✅ |
| Safari Mobile (iOS) | ⚠️ Cần enable | ✅ |
| Chrome Desktop | ✅ | ✅ |
| Firefox | ❌ Fallback keyboard | ✅ |

### API Used
- `navigator.mediaDevices.getUserMedia()` - Camera access
- `BarcodeDetector` - Native barcode scanning
- `navigator.vibrate()` - Haptic feedback

---

## 🚀 Installation

```bash
python odoo-bin -c odoo.conf -u hlv_barcode_realtime_inventory -d <database>
```

---

## 🎨 Dark Theme

Màu sắc đậm, tối ưu cho môi trường kho:
- **Background**: #0A0E27 (Dark Navy)
- **Cards**: #141B3C (Deep Blue)
- **Accent**: #3B82F6 (Vibrant Blue)
- **Text**: #F8FAFC (Almost White)

---

## 📊 Backend Models

### inventory.scan.session
- `device_id` - Fingerprint thiết bị
- `location_id` - Vị trí đang quét
- `state` - active / confirmed

### inventory.scan.line  
- `scanned_qty` - Số lượng đã quét
- `theoretical_qty` - Số lượng lý thuyết
- `difference` - Chênh lệch

---

## License

LGPL-3
