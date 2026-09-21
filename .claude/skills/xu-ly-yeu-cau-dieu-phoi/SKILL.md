---
name: xu-ly-yeu-cau-dieu-phoi
description: Trả lời một phiếu yêu cầu nhân viên gửi cho AI trong V-Tracking — xin giao sớm, dời ngày, xếp vào chuyến, gỡ khỏi chuyến, hỏi ý kiến. Kiểm hàng, thủ tục, chỗ trống trên xe rồi trả lời được / được nếu / không được, và sửa kế hoạch NHÁP nếu làm được. Dùng khi được giao xử lý "yêu cầu điều phối #<id>" (worker tự gọi), hoặc khi người dùng bảo xem phiếu yêu cầu nào đó.
---

# Xử lý một yêu cầu điều phối

Bạn trả lời **một** phiếu, rồi dừng. Người gửi là nhân viên bán hàng đang chờ câu trả lời
trên màn hình của họ.

## Ranh giới cứng

- **Mỗi phiếu kết thúc bằng đúng một lời gọi** `requests/<id>/answer`, hoặc
  `requests/<id>/fail` nếu bí. Không trả lời là người ta ngồi chờ một cái máy im lặng.
- **Không bao giờ** gọi `plans/<id>/state`. Không chốt, không đánh dấu xong, không huỷ.
- **Kế hoạch đã chốt (`plan_state = "confirmed"`) thì KHÔNG sửa.** Chỉ mô tả phương án
  trong câu trả lời và để `applied: false` — người điều phối bấm *Duyệt* thì phiếu quay lại
  với `approved: true` và kế hoạch lúc đó đã ở trạng thái nháp, khi ấy mới sửa.
- **Không hứa giờ cho khách.** Km là đường chim bay nhân hệ số; luôn nói "ước khoảng".
- Không sửa đơn hàng, phiếu kho, thói quen khách, định mức.

## Các bước

### 1. Đọc phiếu và bối cảnh

```
py .claude/skills/dieu-phoi-giao-hang/scripts/vt.py get requests/<id>
py .claude/skills/dieu-phoi-giao-hang/scripts/vt.py get context
```

`context` cho cụm tuyến, **định mức hiện tại**, xe. Đừng nhớ định mức từ lần trước.

### 2. Hiểu yêu cầu nói về cái gì

| Có gì trên phiếu | Đọc tiếp |
|---|---|
| `sale_order_id` | `get orders/<id>` — khối `dispatch`, `supply`, `fulfillment`, `revisit_risk` |
| `picking_id` | `get pickings/<id>` |
| `plan_id` | `get plans/<id>` |

Đọc luôn `get orders/<id>/chatter` khi lý do nghe có vẻ đã bàn với khách.

### 3. Lọc trước khi tính

Dùng đúng luật của skill `dieu-phoi-giao-hang` (đọc mục *Lọc bằng `dispatch`* ở đó):

- `blocked: true` → **không được**, nêu rõ vướng thủ tục gì. Đây là câu trả lời hoàn chỉnh,
  không phải lý do để bỏ cuộc.
- `needs_truck: false` → khách tự lấy / CPN / Grab, xe công ty không đi.
- `supply_state: waiting` → hàng chưa về đủ; so `expected_arrival_date` với ngày khách xin.
- `zone: null` hoặc `zone.uncertain` → nói rõ là đang đoán cụm.

### 4. Tìm chỗ

```
py ... vt.py get "fleet?date=<ngày mong muốn>"
```

Xem `free_sessions` và `day_load` của từng xe, `stop_count` so với trần điểm của cụm.

Thứ tự ưu tiên khi tìm chỗ:
1. Chuyến **nháp** cùng ngày, cùng cụm, chưa vượt trần điểm → chèn vào, rẻ nhất.
2. Chuyến nháp cùng ngày khác cụm → chỉ khi thêm được mà không phá trần và không kéo dài
   quá đáng; nói rõ phần tăng thêm.
3. Buổi còn trống của một xe → chuyến mới, nhưng nhớ ngưỡng "đáng chạy": 1–2 điểm thì thà
   đừng chạy.
4. Không còn chỗ → **không được**, kèm phương án gần nhất (ngày khác, hoặc CPN).

Thử bằng `post estimate` (không ghi gì) trước khi đụng vào kế hoạch thật. So km và tổng
thời gian giữa các phương án.

### 5. Làm hoặc đề xuất

**Kế hoạch nháp** (hoặc phiếu có `approved: true`):

```
py ... vt.py post plans/<id>/documents   '{"sale_order_ids": [812]}'
py ... vt.py post plans/<id>/remove-lines '{"line_ids": [55]}'
py ... vt.py post plans/<id>/resequence   '{"strategy": "nearest"}'
py ... vt.py post plans/<id>/notes        '{"reasoning": "Chèn DH... theo yêu cầu #<id> của ..."}'
```

Sửa xong **luôn ghi `notes`**: kế hoạch bị đổi mà không nói vì sao thì người điều phối mở
ra không hiểu ai đổi. Rồi `answer` với `applied: true`.

**Kế hoạch đã chốt**: không đụng, `applied: false`, mô tả rõ phải đổi gì.

### 6. Trả lời

```
py ... vt.py post requests/<id>/answer '{"verdict": "feasible", "applied": true, "answer": "..."}'
```

`verdict`: `feasible` được · `conditional` được nếu… · `not_feasible` không được ·
`info` chỉ trả lời câu hỏi.

Viết `answer` cho **người bán hàng đọc**, không phải cho kỹ sư:

```
ĐƯỢC:
Đã chèn DH125524949235614 vào chuyến chiều nay của xe 60D-00750 (Nhơn Trạch),
ghé thứ 3 trong 5 điểm. Ước tới nơi khoảng 14:30 — là ước, không phải giờ hẹn.

VÌ SAO ĐƯỢC:
Hàng đã đóng gói xong, khách không vướng thủ tục, chuyến còn 3 chỗ dưới trần cụm.
Thêm điểm này chuyến dài thêm khoảng 12 phút.

TÔI CHƯA CHẮC:
Cụm của điểm này máy phải đoán (cách điểm đã biết 3,4 km), nên giờ có thể lệch.
```

Quy ước hiển thị: dòng VIẾT HOA kết thúc bằng `:` thành tiêu đề đậm; dòng trống ngắt đoạn.

**Luôn có mục "TÔI CHƯA CHẮC"** khi có chỗ phải đoán. Không có gì phải đoán thì bỏ.

### 7. Bí thì báo bí

```
py ... vt.py post requests/<id>/fail '{"error": "Yêu cầu nói về đơn khác kho, chưa rõ xe nào"}'
```

Trả lời bừa tệ hơn nhận là mình không làm được: người điều phối thấy phiếu lỗi sẽ xử lý tay.

## Bẫy

1. **Sửa kế hoạch đã chốt** — tài xế có thể đã cầm tờ in đi rồi. Chỉ đề xuất.
2. **Quên `notes`** — kế hoạch đổi mà không ai biết vì sao.
3. **Trả lời hai lần** — `answer` chỉ gọi một lần; gọi khi phiếu không còn ở trạng thái
   "AI đang xem" sẽ bị API từ chối, và đó là chủ ý.
4. **Nhận lời khi hàng chưa về** — xem `supply.expected_arrival_date`, đừng chỉ nhìn
   `fulfillment`.
5. **Xếp thêm điểm làm vỡ trần cụm** — đọc `zone_warning` sau khi sửa; còn cảnh báo thì
   nêu trong câu trả lời.
6. **Quên khách hai nhà máy** — gom theo `dispatch.place_id`, đừng gom theo tên.
