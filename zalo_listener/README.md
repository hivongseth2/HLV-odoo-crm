# Máy nghe Zalo nhóm NCC

Tài khoản Zalo **riêng** (SIM riêng, không phải số chính) được mời vào các nhóm có NCC. Chương trình này đăng nhập
tài khoản đó như Zalo Web, nghe tin nhóm (chữ, ảnh, file, thả cảm xúc), ghi vào SQLite trên máy rồi đẩy về Odoo
(module `hlv_vendor_zalo`). **Chỉ đọc — không có chỗ nào gửi tin Zalo.**

> zca-js là thư viện KHÔNG chính thức, trái chính sách Zalo — tài khoản nghe có thể bị khoá. Không bao giờ dùng số
> chính. Không tự ý đổi bản zca-js (đang ghim 2.2.0): `src/normalize.js` viết theo kiểu dữ liệu của đúng bản này.

```
Nhóm Zalo ──WebSocket──▶ zca-js ─▶ SQLite (data/zalo.db) ──mỗi 15 giây──▶ Odoo /api/zalo-listener/events
                                 └─ ảnh / file: tải NGAY về data/media (link Zalo hết hạn) ──▶ Odoo /api/zalo-listener/media
```

## Cài đặt

1. Máy chạy 24/7, Node.js 20+ (khuyên 22 LTS). Mac cần Xcode Command Line Tools (để cài `better-sqlite3`).
2. Đặt thư mục ở **ổ máy** (vd `~/zalo_listener`) — **KHÔNG** trong Google Drive / Dropbox: SQLite đang ghi mà bị
   đồng bộ là hỏng DB.
3. `npm ci` (npm báo chặn script cài đặt của `better-sqlite3` thì cho phép: `npm approve-scripts better-sqlite3`
   rồi `npm rebuild better-sqlite3`).
4. Odoo: Cài đặt → Mua hàng → Hỏi giá NCC → **Khoá máy nghe Zalo** → Tạo khoá mới. Chép `.env.example` thành `.env`,
   điền `ODOO_URL`, `ODOO_KEY`.
5. `npm test` — phải ra `ALL OK`.
6. **Lần đầu chạy trong Terminal**: `npm start`. Log báo "CẦN QUÉT QR" → mở `data/qr.png`, quét bằng app Zalo của
   **số máy nghe**. Cookie lưu ở `data/credentials.json`, các lần sau tự đăng nhập. Thấy "Listener đã kết nối" thì
   nhắn thử vào một nhóm.
7. Odoo: menu Yêu cầu mua hàng → Báo giá NCC → Zalo nhóm NCC → **Nhóm Zalo**: nhóm vừa có tin hiện ra (chưa ghi tin).
   Chọn NCC của nhóm, bật **Ghi tin**. Menu **Thành viên**: đánh dấu ai là người của NCC, ai là nhân viên mình.
8. **Tắt bản Terminal (Ctrl+C) rồi mới** chạy nền: `pm2 start ecosystem.config.cjs` (đúng một bản). Hai bản cùng chạy
   (hoặc mở Zalo Web / PC bằng số máy nghe) là hai bên đá nhau liên tục (mã 3000).
9. Sao lưu `data/` mỗi đêm. Bản đẩy lên mạng bắt buộc mã hoá (`age`), khoá riêng cất **ngoài** máy.

## Vận hành

- Odoo → Zalo nhóm NCC → **Máy nghe**: trạng thái, lần cuối báo về (đỏ = quá 10 phút không thấy), số lần rớt hôm
  nay, mã rớt gần nhất, số tin còn chờ gửi.
- Mã rớt: **1006** Zalo tự cắt (bình thường, tự nối lại, mỗi lần nối lại xin Zalo gửi lại tin nhóm gần nhất để vá
  các phút "điếc"); **3000** tài khoản đang mở chỗ khác (chờ 5 phút mới nối); **3003** bị đá ra do đổi mật khẩu /
  đăng nhập thiết bị mới — máy nghe **dừng, cần người xem**, không tự đăng nhập lại.
- Đăng nhập giãn cách 30 giây → 1 → 3 → 10 → 30 phút; mất mạng thì chỉ chờ và thử lại bằng cookie, không hiện QR;
  QR tối đa 3 lần / giờ. Nối lại sau rớt: 5 giây → 15 giây → 60 giây → 5 phút; kết nối đứng vững 60 giây mới xoá
  bộ đếm; rớt 10 lần liên tiếp mới đăng nhập lại.
- Tắt nhanh việc xin tin cũ sau mỗi lần nối lại: tạo file `data/NO_BACKFILL`.
- Odoo lỗi / mất mạng: tin nằm chờ trong `data/zalo.db`, lượt sau tự gửi. Ghi DB lỗi hai lần: tin được đẩy ra
  `data/failed.jsonl`, không mất.
- Log ở `data/logs/` — không ghi nội dung tin nhắn.

## Bảo mật

- `data/` quyền 700; cookie, DB, log quyền 600 (ép lại mỗi lần chạy). Ảnh QR xoá ngay sau khi đăng nhập.
- Ai cầm được máy là đọc được cookie + tin nhắn: đặt máy ở chỗ khoá, bật tường lửa, khoá màn hình.
- Báo cho NCC trong nhóm biết có máy ghi lại tin nhắn.
