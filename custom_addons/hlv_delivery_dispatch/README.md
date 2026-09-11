# hlv_delivery_dispatch

Điều phối chuyến giao hàng. Sale xem kế hoạch đã công bố tại `/delivery_plan` và đăng ký
chuyến cho đơn của mình.

Thiết kế đầy đủ: `plan/ke-hoach-module-dieu-phoi.md` ở gốc repo.

## Phụ thuộc cần cài thêm

Hai module **core Odoo** chưa được cài trên hệ này:

| Module | Dùng để làm gì |
|---|---|
| `fleet` | Quản lý xe. Module này thêm tải trọng / kích thước khoang / số kiện vào `fleet.vehicle`. |
| `base_geolocalize` | Chỉ dùng service `base.geocoder` để tra toạ độ điểm giao. Không dùng `partner_latitude/longitude` của nó. |

Cài `fleet` sẽ thêm app menu "Đội xe" — chỉ cấp quyền Fleet cho người cần, quyền
đọc/ghi `fleet.vehicle` cho điều phối đã được module này cấp sẵn qua `ir.model.access`.

## Thứ tự bật lần đầu

1. Cài module. Vào **Kho → Cấu hình → Kho hàng → Bến Cam**, bật **Bật điều phối chuyến**
   và kiểm tra các tham số: tự nhận đăng ký, giờ chốt, xem chéo giữa sale, số chuyến/ngày.
2. **Điều phối → Dữ liệu nền → Cụm tuyến**: khai 5 cụm và định mức
   (kho → điểm đầu theo từng cụm, trần điểm mỗi chuyến).
3. **Điều phối → Công cụ → Nhập dữ liệu bản đồ**: nạp `map2.json` rồi `cust.json`
   từ `plan/dieu-phoi-ben-cam/`. Chạy lại được nhiều lần.
4. Đọc báo cáo chất lượng dữ liệu ở cuối wizard, rồi xử lý backlog:
   **Duyệt toạ độ** (cron tra tự động 30 phút/lần), gán cụm cho điểm còn trống.
5. **Điều phối → Dữ liệu nền → Xe điều phối**: bật `x_dispatch_enabled` cho Kim Long,
   EC Van, xe tải 3t5, Suzuki và điền tải trọng / kích thước / số kiện.
6. Tài khoản tài xế dùng chung ("Tài xế khác"): bật **Tài khoản tài xế dùng chung**
   trong form người dùng. Chuyến gán vào tài khoản đó sẽ bắt buộc ghi tên tài xế thật.
7. Cấp group **Điều phối — Quản lý** cho điều phối, **Điều phối — Sale** cho sale.

## Những chỗ dễ hiểu nhầm

- **Đơn vị đếm là ĐIỂM, không phải đơn.** `hlv.delivery.point` gom nhiều mã khách Odoo
  về một địa điểm vật lý. Trần 8 điểm/chuyến chỉ đúng khi khách đã được gắn điểm.
- **Trần điểm là trần mềm** — vượt trần chỉ hiện cảnh báo.
- **Tên tài xế lấy từ `res.users.shipper_name`**, không lấy `res.users.name`.
- **`fleet.vehicle.driver_id` là `res.partner`**, còn chuyến gán tài xế bằng `res.users`
  để khớp với phiếu tài xế quét. Lệch nhau chỉ cảnh báo, không chặn.
- **Sale đăng ký được cả đơn chưa có hàng** — đơn nằm ở "chờ hàng" của chuyến, cron
  `cron_promote_waiting_goods` đẩy vào chuyến khi snapshot báo đủ hàng. Nếu lúc đó chuyến
  đã khoá thì đăng ký tự chuyển sang "dời lại".
- **Lọc xem chéo giữa sale nằm ở controller**, không nằm trong record rule — quy tắc phụ
  thuộc cấu hình từng kho và phải so chuỗi nhiều mã sale MISA.
- **Thủ tục trước khi giao KHÔNG nằm trong bảng thói quen khách.** Khách nào cần thủ tục
  do `hlv.delivery.procedure.partner` (module `hlv_sale_delivery_planning`) quản, còn
  xong hay chưa là ô tick `sale.order.x_plan_procedure_done` của **từng đơn** — cùng một
  khách, đơn này sale đã làm xong thủ tục, đơn kia chưa. `sale.order.x_delivery_blocked`
  và `trip.stop.has_pending_procedure` đều tính từ đó, và đều **không store** vì danh
  sách khách cần thủ tục đọc qua ormcache, store sẽ khiến cờ chặn sai âm thầm khi danh
  sách đổi.

## Liên hệ với `hlv_sale_delivery_planning`

Module này **không sửa** module đó, trừ đúng một comment neo `<!-- HLV_NAV_EXT -->`
trong navbar của trang `/sale_plan` để chèn link "Kế hoạch giao". Không có neo thì link
không hiện, mọi thứ khác vẫn chạy.

Dùng lại (import, không copy): `_send_sale_plan_webpush`, model đăng ký web push,
`hlv.delivery.planner.service._get_current_user_misa_codes` / `_get_mine_only_domain`,
`hlv.delivery.planner.snapshot`, hai kênh bus `delivery_planner_channel` và
`sale_plan_public_channel`.

## Vòng đời việc điền thói quen khách (P3)

```
cron suy sale phụ trách  →  cron sinh việc (hạn 7 ngày)  →  push cho sale
        ↓                                                        ↓
profile.responsible_sale_user_id            /delivery_plan tab "Khách tôi phụ trách"
(source=auto, gán tay thì không bị đè)                           ↓
                                            sale điền + "Lưu và xác nhận đã đúng"
                                                                 ↓
                                            task = submitted, profile = confirmed
                                                                 ↓
                                            điều phối duyệt → review_due_date = +180 ngày
                                                                 ↓
                                            quá hạn → profile = expired → sinh việc lại
```

Sale chỉ sửa được khách mình phụ trách (record rule + whitelist field ở controller).
Cột **Độ đầy (%)** và **Còn thiếu** cho biết còn thiếu gì trong 10 cột thói quen.

## Chưa làm

- **P4** — đối chiếu kế hoạch với thực tế. Field đã có sẵn: `trip.stop.actual_arrival`,
  `actual_depart`, `stock.picking.x_trip_id`.
- Màn xếp chuyến kéo-thả. Hiện điều phối xếp đơn vào chuyến bằng form/list chuẩn Odoo.
- Trang sale làm tươi bằng poll 60 giây; bus event đã bắn nhưng trang chưa nghe.
