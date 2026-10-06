---
name: doi-soat-misa
description: Viết báo cáo đối soát MISA hằng ngày — đọc file số liệu đơn đang lệch (tiền xuất kho vs tiền hóa đơn), tự soát lại theo đơn những đơn tự sửa được, chia việc cho kế toán / từng sale, đề xuất gắn mã đề nghị (chờ người xác nhận), rồi gửi báo cáo về Odoo. Dùng khi worker giao "viết báo cáo đối soát MISA ngày <ngày> từ file <đường dẫn>", hoặc khi người dùng bảo xem / viết báo cáo lệch đối soát MISA.
---

# Báo cáo đối soát MISA hằng ngày

Người đọc là quản lý và kế toán, mỗi sáng mở báo cáo ra để chia việc. Họ cần biết: **hôm nay
lệch bao nhiêu, máy đã tự sửa gì, còn lại ai phải làm gì với đơn nào.** Không cần giải thích
cách tính.

## Ranh giới cứng

- Chỉ dùng lệnh `py .claude/skills/doi-soat-misa/scripts/misa_ai.py <route> ...`. Không sửa file.
- **Được** gọi `refresh` (soát lại theo đơn) — chỉ cho đơn có `refresh_fixes: true` hoặc nằm trong
  `pairs`, tối đa 90 đơn/ngày (3 lượt × 30).
- **Không** gắn mã đề nghị. Chỉ đề xuất trong `suggestions` của báo cáo — người bấm "Gắn" trên
  Odoo mới gắn. Gắn sai là tiền HĐ của đơn khác chạy sang phiếu này.
- **Không bịa số.** Mọi số tiền, mã đơn, mã phiếu, số đề nghị lấy từ file số liệu hoặc kết quả
  `refresh`. Không chắc thì ghi vào mục "Cần người xem".
- Kết thúc bằng **đúng một** lời gọi `report`. Gặp lỗi API giữa chừng vẫn phải gửi báo cáo (ngắn,
  nêu lỗi) — không gửi gì là sáng mai không ai biết hôm nay có lệch.

## File số liệu

JSONL, đọc bằng Read (file dài thì đọc từng đoạn bằng offset/limit, đọc HẾT trước khi viết).

- **Dòng 1** — tổng quan: `report_date`, `order_count` / `total_gap` (mọi đơn lệch), `listed_orders`
  (số đơn có trong file, lệch lớn trước), `pairs` = `[[đơn thiếu, đơn thừa, tiền]]` cùng khách lệch
  ngược dấu, `last_report` (báo cáo lần trước: `report_date`, `order_count`, `total_gap`,
  `pending_suggestions`) để so.
- **Mỗi dòng sau** — 1 đơn: `id`, `name`, `partner`, `saler_codes`, `gap` (dương = thiếu HĐ, âm = HĐ
  thừa), `age_days` (ngày từ lúc xuất kho phiếu lệch cũ nhất), `gap_pickings` (phiếu, ngày xuất,
  `net_actual`, `allocated`, `gap`, `state`, `request_refno`, `invoice_no`), `requests` (đề nghị tính
  cho đơn: `refno`, `inv_no` rỗng = chưa phát hành, `amount`, `notes` = dòng ghi nhầm mã đơn đã
  chuyển đi/đến), `customs` (dòng HĐ hải quan CHƯA khớp hết; dòng đã khớp chỉ đếm ở
  `customs_matched_count`), `missing` / `extra` / `tax_diff` / `price_diff`
  (so từng mã hàng, dạng chuỗi đọc được), `duplicates`, `reasons`, `refresh_fixes`, `error`.

Mã `reasons`:

| reasons | Nghĩa | Ai làm | Việc |
|---|---|---|---|
| `no_invoice` | Chưa có đề nghị / HĐ nào | Sale | Lập đề nghị xuất HĐ, ghi đúng số phiếu xuất kho |
| `pending_request` | Có đề nghị, chưa phát hành | Kế toán | Phát hành HĐ cho đề nghị (ghi `refno`) |
| `duplicate_request` | ≥ 2 đề nghị cùng số tiền | Kế toán | Xóa đề nghị trùng, KHÔNG phát hành thêm |
| `missing_items` | HĐ thiếu mã hàng đã giao | Sale | Lập đề nghị bổ sung đúng mã + SL trong `missing` |
| `extra_items` | HĐ có mã / SL nhiều hơn đã giao | Kế toán | Kiểm HĐ: xuất trùng, xuất trước khi giao đủ, hay ghi nhầm mã hàng |
| `tax_diff` / `price_diff` | % thuế / đơn giá đơn bán khác HĐ | Sale | Sửa đơn bán Odoo cho đúng HĐ (hoặc báo kế toán nếu HĐ sai) |
| `customs_unmatched` | Dòng HĐ hải quan chưa khớp phiếu | Kế toán | Khớp tay ở tab Đơn hải quan |
| `mislabeled` / `stale` / `not_checked` | Soát lại theo đơn là tự sửa | Máy | Bước 2 |
| (rỗng) | Mặt hàng khớp mà vẫn lệch | — | "Cần người xem" |

Một đơn có thể nhiều mã — liệt kê đủ việc, không chọn 1. `missing_items` + `extra_items` cùng
lúc, SL bằng nhau, khác mã → nhiều khả năng HĐ ghi nhầm mã hàng: ghi rõ "HĐ ghi X thay vì Y".

## Các bước

### 1. Đọc file số liệu

Đọc hết. Ghi nhận `order_count`, `total_gap` và `last_report` để so ở phần tóm tắt.

### 2. Soát lại theo đơn những đơn tự sửa được

Lấy `id` của các đơn `refresh_fixes: true` và 2 đơn của mỗi cặp trong `pairs` (tra `id` theo `name`
trong file). Gọi theo lô ≤ 30:

```
py .claude/skills/doi-soat-misa/scripts/misa_ai.py refresh '{"order_ids": [123, 456]}'
```

Kết quả `[{name, gap_before, gap_after}]`. Đơn `|gap_after| ≤ 1.000` là **đã tự sửa** — đưa vào mục
"Đã tự sửa", bỏ khỏi danh sách việc. Đơn còn lệch thì giữ lại với lý do cũ (và số `gap_after`).

### 3. Đề xuất gắn mã đề nghị

Chỉ cho cặp trong `pairs` **vẫn còn lệch sau bước 2**, và chỉ khi có bằng chứng dòng hàng: mã hàng
trong `extra` của đơn thừa trùng mã + SL trong `missing` của đơn thiếu. Đề xuất gắn đề nghị (có
`inv_no`) chứa món đó của đơn thừa cho **phiếu lệch** của đơn thiếu. Thiếu bằng chứng → ghi vào
"Cần người xem", không đề xuất.

### 4. Viết báo cáo (HTML)

Chỉ dùng thẻ `h3 p b ul li table tr th td`. **Không** dùng dấu `"` trong HTML (không cần thuộc
tính) để khỏi phải thoát ký tự trong JSON. Số tiền dạng `1.234.567 đ`. Mỗi dòng việc có mã đơn,
khách, phiếu, số tiền và **việc cụ thể** (mã hàng thiếu, số đề nghị cần phát hành / xóa...).

1. **Tóm tắt** — tổng đơn lệch và tổng tiền (sau khi tự sửa), so với báo cáo trước; số đơn đã tự
   sửa; số đề xuất chờ duyệt.
2. **Đã tự sửa** — bảng: Đơn | lệch trước → sau.
3. **Việc của kế toán** — theo từng loại việc (phát hành đề nghị, xóa đề nghị trùng, kiểm HĐ thừa,
   khớp tay hải quan), bảng: Đơn | Khách | Phiếu | Tiền | Việc.
4. **Việc của sale** — theo từng mã sale trong `saler_codes`, bảng đơn lệch lớn trước với cột
   Tuổi (ngày); đơn > 30 ngày in đậm. Đơn nhiều sale thì ghi ở sale đầu tiên.
5. **Đề xuất gắn mã đề nghị (chờ xác nhận)** — lặp lại đề xuất ở bước 3 kèm lý do.
6. **Cần người xem** — đơn không có lý do rõ, đơn `error`, cặp không đủ bằng chứng.
7. **Nhận xét** — tối đa 3 ý: khách / sale lặp lỗi, đề nghị trùng lặp lại, khoản lệch lớn bất thường.

Lệch ≤ 50.000 đ chỉ vì `price_diff` → gom 1 dòng "lệch nhỏ do làm tròn / giá" ở cuối mục sale.

### 5. Gửi báo cáo

```
py .claude/skills/doi-soat-misa/scripts/misa_ai.py report - <<'EOF'
{"report_date": "<ngày>", "order_count": <đơn còn lệch>, "total_gap": <tổng lệch còn lại>,
 "worker": "claude", "refreshed_log": "DH… lệch 1.555.200 → 0\n...",
 "body": "<h3>Tóm tắt</h3>...",
 "suggestions": [{"picking": "KBC/OUT/13410", "refno": "KBC/OUT/13410", "amount": 1555200,
                  "reason": "HĐ 00005764 ghi YS513RL ×3 cho DH…236901, đúng hàng phiếu này"}]}
EOF
```

`order_count` / `total_gap` = số của file trừ các đơn đã tự sửa. Lỗi "Đề xuất không hợp lệ" nghĩa
là tên phiếu sai — sửa rồi gửi lại, không bỏ đề xuất đi mà không nói.
