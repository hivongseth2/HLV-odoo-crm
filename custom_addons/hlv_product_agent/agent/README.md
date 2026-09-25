# Agent trợ lý tạo mã hàng — cài trên máy có Claude Code

Sale chat trong khung "Tạo mã hàng" ở `/search_stock`. Odoo giữ tin trong hàng chờ;
agent này hỏi Odoo vài giây một lần, chạy Claude cho từng cuộc hội thoại, rồi gửi câu
trả lời về.

```
trình duyệt sale ──> Odoo (hàng chờ) <── agent trên máy này ──> claude -p
                          ^                                        │
                          └──── tool MISA (misa_mcp_server.py) <───┘
```

- Agent **chỉ gọi ra** Odoo. Máy này không mở cổng nào.
- Tài khoản MISA vẫn nằm trên Odoo. Claude gọi tool qua Odoo, không cầm token MISA.
- Claude chạy khoá chặt: không shell, không sửa file, chỉ đọc được ảnh trong thư mục
  của đúng cuộc hội thoại, chỉ có tool MISA + WebSearch. Máy tắt thì sale vẫn gửi được
  tin, khung chat báo "máy trợ lý đang tắt" và tin được trả lời khi máy bật lại.

## File trong thư mục này

| File | Việc |
|---|---|
| `hlv_product_agent.py` | vòng lặp poll Odoo, chạy Claude, gửi trả lời |
| `misa_mcp_server.py` | MCP server Claude khởi động mỗi lượt; chuyển lệnh gọi tool lên Odoo |
| `misa_tools.py` | schema các tool MISA |
| `prompt/system_prompt.md` | luật lõi của trợ lý |
| `prompt/product_naming_rules.md` | TÀI LIỆU A — quy tắc đặt tên và mã |
| `prompt/product_category_rules.md` | TÀI LIỆU B — quy tắc phân nhóm, bảng ID nhóm |
| `setup.ps1` | script cài một lệnh |

Các file này **Odoo phục vụ cho máy tải về** (`/product_agent/download/...`). Sửa agent
hay tài liệu quy tắc thì sửa trong repo, deploy Odoo, rồi chạy lại lệnh cài trên máy —
không chép tay. Cuộc hội thoại đang dở vẫn dùng quy tắc cũ (Claude ghi prompt lại lúc
mở phiên); sale bấm nút "Cuộc mới" là nhận bản mới.

## Cài — một lệnh

1. Trong Odoo cài module `hlv_product_agent`, mở **Tồn kho → Cấu hình → Trợ lý tạo mã
   hàng → Máy chạy Claude**, tạo một dòng rồi bấm **Tạo mã cài đặt**.
2. Trên máy chạy Claude, mở **PowerShell thường** (KHÔNG "Run as administrator") và dán
   lệnh hiện trên form (có nút copy).
3. Khi script hỏi, gõ mã cài đặt dạng `XXXX-XXXX`.

Script tự làm hết, không cần quyền admin:

- tìm Claude Code (PATH → `~/.local/bin` → bản đi kèm extension VS Code); chưa có thì
  hỏi rồi cài bằng trình cài chính thức của Anthropic; chỉ có bản VS Code thì hỏi có
  cài thêm bản riêng không (gỡ VS Code là mất Claude);
- kiểm Claude **đã đăng nhập** (`claude auth status`), chưa thì mở trang đăng nhập;
- dùng Python 3.10+ có sẵn, không dùng được thì tải Python nhúng vào
  `C:\hlv_product_agent\python` — không cài gì vào máy;
- tải agent + tài liệu quy tắc từ Odoo vào `C:\hlv_product_agent\agent`;
- đổi mã cài đặt lấy token, ghi `C:\hlv_product_agent\agent.yaml`;
- chạy `--check` và hỏi thử Claude một câu, hỏng ở đâu báo ở đó;
- đăng ký tác vụ **HLV Product Agent** chạy khi đăng nhập Windows, không bung cửa sổ,
  tự bật lại trong vòng 5 phút nếu bị tắt; rồi khởi động agent.

Mã cài đặt **dùng một lần, hết hạn sau 30 phút**.

Tác vụ chạy dưới **chính tài khoản Windows đang cài**, không chạy dưới SYSTEM như agent
ghi hình: đăng nhập Claude nằm trong hồ sơ của tài khoản đó, SYSTEM không có. Hệ quả:
máy phải bật **và** tài khoản đó phải đang đăng nhập Windows thì sale mới được trả lời.

### Cập nhật / cài lại

Chạy lại đúng lệnh đó. Script dừng agent, tải bản mới, **dùng lại token cũ** nếu còn
hiệu lực (không cần mã), giữ nguyên `model` đã chọn, rồi khởi động lại. Lượt chat đang
chạy dở lúc cập nhật sẽ bị ngắt; Odoo tự báo sale gửi lại.

### Đổi model

Sửa dòng `model:` trong `C:\hlv_product_agent\agent.yaml` (`sonnet` nhanh, `opus` kỹ hơn),
rồi `Stop-ScheduledTask -TaskName "HLV Product Agent"; Start-ScheduledTask -TaskName "HLV Product Agent"`.

## Cài thủ công

Dùng khi muốn chạy agent ngay trong repo để sửa code.

1. `pip install requests pyyaml`
2. Chép `agent.example.yaml` thành `agent.yaml`, điền `odoo_url` và `token` (copy trên
   form "Máy chạy Claude").
3. `python hlv_product_agent.py --config agent.yaml --check` — phải in đường dẫn Claude
   và `Odoo: OK`.
4. `python hlv_product_agent.py --config agent.yaml` (Ctrl+C để dừng — agent đợi các
   lượt đang chạy xong rồi mới thoát).

Log: `agent.log` trong `work_dir` (mặc định `C:\hlv_product_agent\agent.log`).

## Quyền

- Mọi nhân viên nội bộ mở được `/search_stock` đều thấy khung chat; mỗi người chỉ thấy
  hội thoại của mình.
- Nhóm **Trợ lý tạo mã hàng: Quản lý**: xem mọi hội thoại, và Claude coi là QUẢN LÝ —
  tạo theo ý họ kể cả khi thiếu thông tin. Nhóm này không tự gán cho admin; cấp có chủ
  đích.
- Mỗi lần Claude tạo/sửa trên MISA, Odoo tự ghi một dòng "Đã tạo trên MISA: ..." vào
  hội thoại — không phụ thuộc lời Claude kể. Lọc "Có tạo/sửa MISA" trong danh sách hội
  thoại để rà.

## Sự cố

| Triệu chứng | Xem |
|---|---|
| Khung chat báo "máy trợ lý đang tắt" | agent không chạy, hoặc token sai (`agent.log` có "Odoo từ chối agent") |
| "Máy trợ lý gặp lỗi ... quá thời gian chờ" | agent chết giữa lượt; Odoo tự thả sau 12 phút. Tool có thể đã chạy — xem dòng "Đã tạo trên MISA" trước khi cho sale gửi lại |
| "Claude dừng giữa chừng" | Claude hết hạn mức / mất đăng nhập: chạy `claude` bằng tay trên máy này xem báo gì |
| Không tìm thấy Claude Code | khai `claude_path` trong `agent.yaml` |
