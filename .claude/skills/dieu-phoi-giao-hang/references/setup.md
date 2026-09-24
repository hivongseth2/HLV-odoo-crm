# Cấu hình để skill gọi được API

Làm một lần. Sau đó `scripts/vt.py` chạy được ở bất kỳ phiên nào.

## 0. Skill nằm ở đâu

Skill này nằm **trong repo** (`.claude/skills/dieu-phoi-giao-hang/`) và **có trong git**.
Nghĩa là:

- Mở Claude Code trong thư mục repo → tự tìm thấy, không phải cài gì.
- Đồng nghiệp `git pull` → có ngay, cũng không phải cài gì.
- Repo deploy lên server → skill đi cùng.

Chỉ **khoá API là riêng của từng người** (mục 1–2 bên dưới) — khoá không bao giờ nằm trong
repo.

Muốn dùng skill ở thư mục KHÁC ngoài repo thì copy nó sang `~/.claude/skills/`. Nhưng khi
đó bản copy sẽ không tự cập nhật theo repo, nên chỉ làm khi thật sự cần.

## 1. Tạo khoá API trong Odoo

Odoo → **V-Tracking → Cấu hình → Khoá API → Tạo**.

| Ô | Điền |
|---|---|
| Tên ứng dụng | `Claude Code – <tên máy>`. Ghi rõ để sau còn biết thu hồi cái nào |
| Cho phép ghi | **Tắt** trong vài ngày chạy thử đầu — xem mục 4 |
| Công ty | Pháp nhân sở hữu kho Bến Cam |

Copy giá trị ô **Khoá**. Nó chỉ là một chuỗi ngẫu nhiên, không lấy lại được từ đâu khác
ngoài chính bản ghi đó.

## 2. Đặt biến môi trường

Git Bash / Linux / macOS — thêm vào `~/.bashrc` hoặc `~/.zshrc`:

```bash
export VTRACKING_BASE_URL="https://<tên-instance>.dev.odoo.com"
export VTRACKING_API_KEY="<dán khoá vừa copy>"
```

PowerShell — đặt vĩnh viễn cho user hiện tại:

```powershell
[Environment]::SetEnvironmentVariable('VTRACKING_BASE_URL', 'https://<tên-instance>.dev.odoo.com', 'User')
[Environment]::SetEnvironmentVariable('VTRACKING_API_KEY', '<dán khoá vừa copy>', 'User')
```

**Đừng commit khoá vào git.** Nó nằm trong biến môi trường chính là để không phải nhét vào
file nào trong repo.

## 3. Kiểm tra

```bash
python scripts/vt.py get context
```

| Kết quả | Nghĩa |
|---|---|
| JSON có `zones`, `vehicles` | Xong |
| `LỖI: Chưa đặt VTRACKING_BASE_URL…` | Chưa đặt biến, hoặc terminal chưa mở lại sau khi đặt |
| `UNAUTHORIZED (HTTP 401)` | Khoá sai, hoặc đã bị lưu trữ trong Odoo |
| `LỖI: Không kết nối được…` | Sai URL, hoặc instance đang ngủ — mở Odoo trên trình duyệt cho nó thức dậy |
| `WRITE_NOT_ALLOWED (HTTP 403)` | Khoá đang chỉ đọc mà bạn gọi endpoint ghi. Đúng như thiết kế ở mục 4 |

## 4. Vì sao tắt "Cho phép ghi" lúc đầu

Vài ngày đầu là giai đoạn **chạy tay, đối chiếu tay**: để AI đọc dữ liệu và đề xuất, còn
người tự bấm tạo kế hoạch trong Odoo. Khoá chỉ đọc khiến mọi endpoint ghi trả 403 — một
hàng rào thật, không phải lời hứa.

Khi kết quả đã tin được thì bật ô đó lên, hoặc cấp một khoá thứ hai có quyền ghi.

Khoá đọc và khoá ghi nên là **hai bản ghi riêng**: lộ khoá đọc thì chỉ mất dữ liệu, lộ khoá
ghi thì người lạ sửa được kế hoạch giao hàng.

## 5. Khi chuyển sang chạy trên server

`scripts/vt.py` **không phải đổi gì** — chỉ đổi hai biến môi trường trên máy chủ, và dùng
một khoá riêng (có quyền ghi, tên khác, thu hồi độc lập).

Lúc đó mới phát sinh thêm **khoá Anthropic**: tiến trình chạy không người đăng nhập nên
phải có `ANTHROPIC_API_KEY`, tính tiền theo token. Chạy từ máy cá nhân thì dùng tài khoản
Claude đã đăng nhập, không cần khoá đó.

Hai loại khoá này độc lập nhau:

| Chỗ chạy | Khoá Anthropic | Khoá V-Tracking |
|---|---|---|
| Claude Code trên máy cá nhân | không cần | cần |
| Tiến trình riêng trên server | cần | cần |
| Trong Odoo (server action / cron) | cần | không cần — chạy thẳng ORM |
