# ⚡ Quick Setup - Google Drive Upload

## 🎯 Tóm tắt nhanh

Module này tự động upload video đóng gói lên Google Drive theo warehouse, với cấu trúc folder:
```
KHO_HCM/           ← Tên folder dễ đọc
  └── 10_01_2025/  ← Ngày
      └── clip/    ← Video đóng gói
```

---

## 📋 Checklist Setup

### ☑️ Phần 1: Google Console (5 phút)

1. Tạo project tại: https://console.cloud.google.com/
2. Enable **Google Drive API**
3. Tạo **OAuth 2.0 Client ID** (Web application)
4. Lưu lại:
   - ✅ Client ID
   - ✅ Client Secret
5. Thêm Redirect URI:
   ```
   http://localhost:8069/gdrive/oauth2/callback
   ```
6. Thêm email test vào **OAuth Consent Screen > Test users**

### ☑️ Phần 2: Cấu hình Odoo (3 phút)

Vào: **Settings > Technical > System Parameters**, tạo:

```plaintext
gdrive.oauth_client_id           = [YOUR_CLIENT_ID]
gdrive.oauth_client_secret       = [YOUR_CLIENT_SECRET]
gdrive.oauth_redirect_uri        = http://localhost:8069/gdrive/oauth2/callback
gdrive.oauth_scopes             = https://www.googleapis.com/auth/drive.file
gdrive.warehouse_folder_mapping  = TSN:KHO_HCM,KBC:KHO_BENCAM
gdrive.anyone_link              = true
```

### ☑️ Phần 3: Kết nối Drive (1 phút)

1. Truy cập: `http://localhost:8069/gdrive/oauth2/start`
2. Đăng nhập Google (email đã thêm vào Test users)
3. Cho phép quyền truy cập
4. ✅ Done!

---

## 🏢 Thêm kho mới

### Ví dụ: Thêm KHO Hà Nội

1. **Trong Odoo**: Tạo warehouse với code `HN`
2. **Cập nhật mapping**:
   ```
   gdrive.warehouse_folder_mapping = TSN:KHO_HCM,KBC:KHO_BENCAM,HN:KHO_HANOI
   ```
3. **Video sẽ lưu vào**: `KHO_HANOI/DD_MM_YYYY/clip/`

### Format mapping:
```
WAREHOUSE_CODE:FOLDER_NAME,WAREHOUSE_CODE2:FOLDER_NAME2
```

**Lưu ý**: 
- Không có khoảng trắng
- Phân cách bằng dấu phẩy `,`
- Phân cách code và folder bằng dấu hai chấm `:`

---

## 🔧 Test Setup

### Test xem đã kết nối chưa?

1. Vào **System Parameters**
2. Tìm key: `gdrive.user_credentials_json`
3. Có value (JSON) = ✅ Đã kết nối
4. Không có value = ⚠️ Chưa kết nối, quay lại bước 3

### Test upload video

1. Tạo phiếu Pack operations
2. Quét barcode để mở giao diện
3. Bật camera và đóng gói
4. Hoàn tất → kiểm tra Google Drive
5. Video sẽ xuất hiện trong folder tương ứng với warehouse

---

## 🆘 Gặp lỗi?

| Lỗi | Giải pháp |
|-----|-----------|
| "Missing OAuth config" | Kiểm tra đã tạo đủ 3 parameters: client_id, client_secret, redirect_uri |
| "Access blocked" | Kiểm tra email có trong Test users (Google Console) |
| "Invalid redirect_uri" | Đảm bảo redirect_uri trong Odoo = trong Google Console (100%) |
| Video không upload | Xem log: `grep "BG_UPLOAD" odoo.log` |
| Token expired | Disconnect: `/gdrive/oauth2/disconnect` rồi connect lại |
| Folder sai tên | Kiểm tra warehouse code và mapping |

---

## 📖 Tài liệu chi tiết

Xem file `SETUP_GUIDE.md` để biết hướng dẫn chi tiết từng bước với screenshots.

---

**Tip**: Nếu muốn test với Drive cá nhân, chỉ cần:
1. Tạo project riêng trong Google Console
2. Thêm email cá nhân vào Test users
3. Kết nối với email đó
4. Video sẽ lưu vào Drive cá nhân của bạn! ✨

