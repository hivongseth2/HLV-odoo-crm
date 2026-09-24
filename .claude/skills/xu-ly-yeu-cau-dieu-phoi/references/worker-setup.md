# Cài worker trên máy điều phối

Worker là một script Python nằm chờ Odoo gọi. Odoo **không** gọi vào máy này; máy này mở
một websocket ra Odoo và giữ, đúng cách hộp Odoo IoT làm. Vì vậy **không phải mở port nào**
trên router.

## 1. Trong Odoo (làm một lần)

1. **Cài đặt > Người dùng**: tạo một người dùng riêng, ví dụ `ai.worker@hoanglongvu.com`.
   - Cho nhóm **Xem bản đồ đội xe** (`group_vtracking_user`).
   - Đặt mật khẩu mạnh. Đừng dùng tài khoản của người thật: mật khẩu này nằm trên máy tính.
2. **V-Tracking > Cấu hình > Kết nối vTracking**: chọn tài khoản đó ở ô **Tài khoản worker AI**.
   Bỏ trống thì Odoo không gọi ai cả, phiếu nằm chờ tới khi có người bấm *Gửi lại cho AI*.
3. **V-Tracking > Cấu hình > Khoá API**: tạo một khoá, **bật "Cho phép ghi"** — worker phải
   ghi được câu trả lời vào phiếu.

## 2. Trên máy chạy worker

```powershell
py -m pip install websockets

[Environment]::SetEnvironmentVariable('VTRACKING_BASE_URL', 'https://<odoo>', 'User')
[Environment]::SetEnvironmentVariable('VTRACKING_API_KEY', '<khoá vừa tạo>', 'User')
[Environment]::SetEnvironmentVariable('VTRACKING_DB', '<tên database>', 'User')
[Environment]::SetEnvironmentVariable('VTRACKING_WORKER_LOGIN', 'ai.worker@hoanglongvu.com', 'User')
[Environment]::SetEnvironmentVariable('VTRACKING_WORKER_PASSWORD', '<mật khẩu>', 'User')
```

Mở PowerShell **mới** (biến môi trường chỉ có hiệu lực ở cửa sổ mới) rồi thử:

```powershell
py .claude\skills\dieu-phoi-giao-hang\scripts\ai_worker.py --once
```

`--once` xử lý hết phiếu đang chờ rồi thoát — dùng để kiểm tra trước khi chạy nền. Tạo một
phiếu thử trong Odoo rồi chạy lệnh này; phiếu phải chuyển sang *AI đã trả lời*.

Chạy thật (nằm chờ, tức thì):

```powershell
py .claude\skills\dieu-phoi-giao-hang\scripts\ai_worker.py
```

## 3. Tự chạy khi đăng nhập Windows

```powershell
schtasks /Create /TN "HLV AI Worker" /SC ONLOGON /RL LIMITED `
  /TR "pyw C:\HLV\HLV-odoo-crm\.claude\skills\dieu-phoi-giao-hang\scripts\ai_worker.py"
```

`pyw` chạy không hiện cửa sổ. Nhật ký nằm ở `%LOCALAPPDATA%\hlv_ai_worker\worker.log`.

Gỡ: `schtasks /Delete /TN "HLV AI Worker" /F`.

## Khi nào worker không chạy

- **Máy tắt, ngủ, hoặc mất mạng** → phiếu nằm chờ, không mất. Máy bật lại là worker vét hết
  phiếu còn chờ ngay khi nối được.
- Phiếu chờ quá 10 phút mà chưa ai nhận thì trên Odoo hiện cảnh báo **"AI chưa nhận"**, để
  người điều phối biết mà xử lý tay.
- Cron trong Odoo gọi lại các phiếu còn chờ mỗi 10 phút, phòng khi tin bus gửi trượt.

## Giới hạn và an toàn

- Worker chạy Claude bằng **tài khoản đang đăng nhập trên máy đó** — trừ vào gói Claude,
  không tốn tiền API riêng.
- Claude chạy với quyền bị bó: chỉ được đọc repo và gọi `vt.py`. **Không** được Write/Edit,
  không chạy lệnh khác.
- Hai máy cùng chạy worker vẫn an toàn: phiếu phải `claim` được mới xử lý, máy chậm chân
  nhận `claimed: false` và bỏ qua.
- Mật khẩu và khoá API chỉ nằm trong biến môi trường của người dùng Windows, không nằm
  trong repo.

## Chưa kiểm được trên máy này

Websocket của Odoo 18 kiểm cookie phiên và header `Origin`. Script gửi cả hai, nhưng phải
chạy thử với Odoo thật mới chắc odoo.sh không chặn. Nếu bị chặn, đổi sang hỏi định kỳ bằng
cách chạy `--once` theo lịch mỗi phút — chỉ phải sửa cách gọi, không phải sửa Odoo.
