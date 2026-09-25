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

Sửa quy tắc: sửa file trong `prompt/`, **khởi động lại agent**. Cuộc hội thoại đang dở
vẫn dùng bản cũ (Claude ghi prompt lại lúc mở phiên); sale bấm nút "Cuộc mới" là nhận
bản mới.

## Cài

1. Máy đã cài **Claude Code** và **đã đăng nhập** bằng đúng tài khoản Windows sẽ chạy
   agent (đăng nhập nằm trong `%USERPROFILE%\.claude`). Extension VS Code là đủ, agent
   tự tìm `claude.exe` đi kèm.
2. **Python 3.10+**, rồi: `pip install requests pyyaml`
3. Trong Odoo cài module `hlv_product_agent`, mở **Tồn kho → Cấu hình → Trợ lý tạo mã
   hàng → Máy chạy Claude**, tạo một dòng, copy **Token agent**.
4. Chép `agent.example.yaml` thành `agent.yaml`, điền `odoo_url` và `token`.
5. Kiểm:

   ```
   python hlv_product_agent.py --config agent.yaml --check
   ```

   Phải in ra đường dẫn Claude và `Odoo: OK`. Trên form "Máy chạy Claude" trạng thái
   chuyển sang **Đang chạy** trong ít giây.
6. Chạy thật: `python hlv_product_agent.py --config agent.yaml` (Ctrl+C để dừng — agent
   đợi các lượt đang chạy xong rồi mới thoát).

## Chạy cùng Windows

Agent phải chạy dưới **chính tài khoản Windows đã đăng nhập Claude**, không chạy dưới
SYSTEM. Tạo tác vụ chạy lúc đăng nhập, không bung cửa sổ:

```powershell
$py  = (Get-Command pythonw.exe).Source
$dir = "C:\HLV\HLV-odoo-crm\custom_addons\hlv_product_agent\agent"
schtasks /Create /F /SC ONLOGON /TN "HLV Product Agent" `
  /TR "`"$py`" `"$dir\hlv_product_agent.py`" --config `"$dir\agent.yaml`""
schtasks /Run /TN "HLV Product Agent"
```

Log: `C:\hlv_product_agent\agent.log` (theo `work_dir`).

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
