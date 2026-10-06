# Cài báo cáo đối soát MISA hằng ngày (19h)

Chạy trên cùng máy với worker điều phối V-Tracking (dùng chung Claude đang đăng nhập trên máy và
cách dò `claude.exe`). Odoo không gọi vào máy này; máy tự gọi API Odoo theo lịch.

## 1. Trong Odoo (làm một lần)

1. Nâng cấp module **misa_invoice_status_report** (bản 1.15 — thêm model báo cáo AI).
2. Tài khoản worker (VD `ai.worker@hoanglongvu.com`, dùng lại tài khoản worker điều phối được) phải
   thuộc nhóm **Đối soát XHD MISA / Đối soát XHD**. Không có nhóm này thì mọi lệnh báo
   "Tài khoản worker phải thuộc nhóm 'Đối soát XHD'".
3. Báo cáo hiện ở menu **Đối soát XHD MISA > Báo cáo đối soát (AI)**.

## 2. Trên máy worker

Nếu máy đã chạy worker điều phối thì các biến `VTRACKING_BASE_URL / VTRACKING_DB /
VTRACKING_WORKER_LOGIN / VTRACKING_WORKER_PASSWORD` đã có và `misa_ai.py` tự dùng. Muốn tài khoản
riêng thì đặt:

```powershell
[Environment]::SetEnvironmentVariable('MISA_AI_BASE_URL', 'https://<odoo>', 'User')
[Environment]::SetEnvironmentVariable('MISA_AI_DB', '<tên database>', 'User')
[Environment]::SetEnvironmentVariable('MISA_AI_LOGIN', '<tài khoản>', 'User')
[Environment]::SetEnvironmentVariable('MISA_AI_PASSWORD', '<mật khẩu>', 'User')
```

Mở PowerShell MỚI rồi thử:

```powershell
py .claude\skills\doi-soat-misa\scripts\misa_ai.py last_report
py .claude\skills\doi-soat-misa\scripts\misa_report_worker.py --dry-run   # gom số liệu, không gọi Claude
py .claude\skills\doi-soat-misa\scripts\misa_report_worker.py             # chạy thật 1 lần
```

`--dry-run` in đường dẫn file số liệu (`%LOCALAPPDATA%\hlv_misa_ai\doi_soat_<ngày>.jsonl`). Gom số
liệu mất vài phút (mỗi đơn 1–3 lệnh gọi MISA). Nhật ký: `%LOCALAPPDATA%\hlv_misa_ai\worker.log`.

## 3. Lịch 19h mỗi ngày

```powershell
schtasks /Create /TN "HLV Doi soat MISA" /SC DAILY /ST 19:00 /RL LIMITED `
  /TR "pyw C:\HLV\HLV-odoo-crm\.claude\skills\doi-soat-misa\scripts\misa_report_worker.py"
```

Gỡ: `schtasks /Delete /TN "HLV Doi soat MISA" /F`.

## Khi có sự cố

- **Máy tắt lúc 19h** → hôm đó không có báo cáo; lần chạy sau vẫn gom đủ số liệu mới nhất.
- **Claude lỗi / không gửi báo cáo** → worker tự gửi báo cáo ngắn "AI chưa viết được báo cáo hôm
  nay: <lý do>" kèm tổng số đơn lệch, để người đọc biết mà xem khung "Vì sao còn lệch".
- Claude chỉ được đọc repo / file số liệu và gọi `misa_ai.py`; được soát lại theo đơn, KHÔNG gắn
  mã đề nghị (chỉ đề xuất, người bấm "Gắn" trên Odoo).
