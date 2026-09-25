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
| `setup.ps1` | script cài một lệnh |

Các file này **Odoo phục vụ cho máy tải về** (`/product_agent/download/...`). Sửa agent
thì sửa trong repo, deploy Odoo, rồi chạy lại lệnh cài trên máy — không chép tay.

## Sửa prompt và quy tắc đặt tên — trên Odoo

Không nằm trên máy agent nữa. Trong **Tồn kho → Cấu hình → Trợ lý tạo mã hàng**:

- **Prompt trợ lý** — ba phần: Luật lõi, Tài liệu A (đặt tên và mã), Tài liệu B (phân
  nhóm). Mỗi lần lưu, bản cũ vào tab **Lịch sử** (có nút khôi phục); nút **Khôi phục
  mặc định** đưa về bản đi kèm module (`data/prompt_defaults/*.md`). Tab **Prompt hoàn
  chỉnh** cho xem đúng thứ Claude nhận.
- **Quy tắc riêng theo dòng hàng** — ngoại lệ đặt tên / mã cho từng dòng (KARCHER giữ
  nguyên part number, MILWAUKEE không nối hậu tố hãng...). Mỗi dòng: áp dụng khi nào,
  quy tắc tên, quy tắc mã, ví dụ đúng. Được ghép ngay sau tài liệu A và thắng tài liệu A
  ở điểm nó nói tới; bật / tắt từng dòng được. Thêm ngoại lệ ở đây, đừng sửa tài liệu A.

Agent so vân tay prompt mỗi lần poll, đổi thì tự tải trong vài giây — không cần chạy lại
lệnh cài. Bản mới vào **cuộc chat mới**; cuộc đang dở vẫn dùng bản cũ (Claude ghi prompt
lại lúc mở phiên) cho tới khi sale bấm "Cuộc mới", hoặc quản lý bấm **Áp dụng ngay cho
cuộc chat đang mở** trên form prompt (Claude mở phiên mới và đọc lại các tin gần nhất).

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
- tải agent từ Odoo vào `C:\hlv_product_agent\agent` (prompt thì agent tự tải lúc chạy);
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
- Mỗi lần Claude tạo/sửa trên MISA, Odoo tự ghi (không phụ thuộc lời Claude kể):
  - một dòng "Đã tạo trên MISA: ..." trong hội thoại;
  - một dòng trong **Trợ lý tạo mã hàng → Hàng đã tạo / sửa**: ai (tên + mã sale MISA),
    lúc nào, mã, tên, nhóm, MISA ID. Lọc theo ngày / "Chưa về Odoo", nhóm theo nhân
    viên, xuất Excel bằng nút xuất của danh sách.

## Tài khoản dùng chung nhiều sale

Tài khoản khai nhiều người trong hai field sẵn có (đọc theo cùng thứ tự):

- **Mã sale MISA** (`x_misa_saler_codes`): `MAIVANNAM1,HUYNHTHIMYPHUONG,LUUTHICONG1`
- **Sale Plan mention aliases** (`x_sale_plan_mention_names`): `Nam ĐN,Phương ĐN,Công ĐN`

thì khung chat hỏi "Anh/chị là ai?" một lần trên mỗi máy (trình duyệt nhớ), có nút
**Đổi người**. Mỗi người một cuộc chat riêng: không thấy tin của nhau, "Cuộc mới" chỉ
đóng cuộc của mình, chạy song song được, và nhật ký ghi đúng người tạo. Thêm / bớt sale
chỉ cần sửa hai field đó — giữ **đúng thứ tự**, lệch vị trí là gán nhầm tên.

Chọn tên là dựa vào lòng tin (dùng chung mật khẩu thì không cách nào xác minh được ai
đang ngồi máy).

## Nhiều người gửi cùng lúc

- Agent chạy song song `max_parallel` cuộc (mặc định 2), còn lại xếp hàng theo thứ tự
  gửi; khung chat báo "trước anh/chị còn N cuộc". Tăng trong `agent.yaml` nếu máy đủ
  RAM và hạn mức Claude cho phép.
- Chống tạo trùng: mọi lệnh tạo đi qua một khoá chung trên Odoo, và ngay trước khi tạo
  Odoo kiểm lại (hàng vừa tạo trong 30 phút qua theo nhật ký + khớp đúng mã / tên trên
  MISA). Trùng thì trả `duplicate`, Claude báo sale chứ không tạo.

## Sự cố

| Triệu chứng | Xem |
|---|---|
| Khung chat báo "máy trợ lý đang tắt" | agent không chạy, hoặc token sai (`agent.log` có "Odoo từ chối agent") |
| "Máy trợ lý gặp lỗi ... quá thời gian chờ" | agent chết giữa lượt; Odoo tự thả sau 12 phút. Tool có thể đã chạy — xem dòng "Đã tạo trên MISA" trước khi cho sale gửi lại |
| "Claude dừng giữa chừng" | Claude hết hạn mức / mất đăng nhập: chạy `claude` bằng tay trên máy này xem báo gì |
| Không tìm thấy Claude Code | khai `claude_path` trong `agent.yaml` |
