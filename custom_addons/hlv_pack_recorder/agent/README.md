# Agent ghi hình đóng gói — cài trên máy tại kho

Ghi thẳng luồng RTSP của từng camera thành file riêng bằng `ffmpeg -c copy`:
không giải mã, không nén lại, chất lượng đúng bằng luồng gốc, CPU gần như 0.

Agent **chỉ gọi ra** Odoo, không mở cổng nào. Không cần chỉnh firewall, không
dính chuyện mixed content của trình duyệt, không trang web lạ nào gọi vào được.

## Hai loại camera, hai cách xử lý

| | Camera IP (RTSP) | Webcam USB |
|---|---|---|
| ffmpeg làm gì | `-c copy` — chép thẳng luồng đã nén | `libx264` — bắt buộc nén lại |
| Chất lượng | đúng bằng bản gốc | phụ thuộc bitrate khai trong config |
| CPU | gần như 0 | tốn thật, ~1 lõi cho 1080p24 |
| Dấu giờ trên hình | camera tự đóng sẵn | agent vẽ vào, vì webcam không tự làm |
| Khai trong config | chuỗi URL RTSP | dict có `type: usb` và `device` |

Webcam hầu như không bao giờ xuất H.264, nên không thể chép thẳng như camera IP.
Nhiều webcam trên một máy sẽ cộng dồn CPU — cân nhắc trước khi khai quá hai cái.

### Xem camera làm được gì

**Webcam USB** — hỏi "nó làm được những gì", rồi chọn một chế độ trong danh sách:

```
python hlv_pack_agent.py --config agent.yaml --list-cameras
```

In ra tên thiết bị, mọi độ phân giải/fps nó hỗ trợ, kèm khối YAML điền sẵn để
chép thẳng vào `agent.yaml`. Khai chế độ ngoài danh sách là ffmpeg báo lỗi.

**Camera IP** — hỏi "nó đang phát cái gì". Không chọn được, vì `-c copy` chép
nguyên luồng; muốn đổi thì vào web cấu hình camera, mục Video/Encode → Main Stream.

```
ffprobe.exe -rtsp_transport tcp -i "rtsp://user:matkhau@192.168.1.10:554/cam/realmonitor?channel=1&subtype=0"
```

Dòng `Stream #0:0: Video: h264 ... 1920x1080, 25 fps, 4096 kb/s` chính là thứ sẽ
nằm trong file quay ra. Thấy 704x576 hay 640x480 là đang dính luồng phụ — đổi
`subtype=1` thành `subtype=0`.

## Trước khi cài

1. Cài **ffmpeg**. Hai cách:
   - Tải bản static rồi để `ffmpeg.exe` ngay cạnh agent, khai `ffmpeg_path`
     trong `agent.yaml` — khỏi đụng vào PATH. Bản đã kiểm:
     https://github.com/BtbN/FFmpeg-Builds/releases (file `win64-gpl`).
   - Hoặc thêm thư mục `bin` của ffmpeg vào PATH rồi bỏ trống `ffmpeg_path`.
2. Cài **Python 3.10+**, rồi `pip install requests pyyaml`.
3. Trong Odoo: **Tồn kho → Cấu hình → Video đóng gói → Bàn đóng gói & camera**.
   Tạo một bàn, khai các camera của bàn đó. **Mã camera** ở đây phải trùng khoá
   trong `agent.yaml` bên dưới.

## Cài nhanh — một lệnh (nên dùng)

1. Trong Odoo mở **Tồn kho → Cấu hình → Video đóng gói → Bàn đóng gói**, chọn
   đúng bàn, khai camera của nó, rồi bấm **Tạo mã cài đặt**.
2. Trên máy đóng gói, mở **PowerShell** và dán lệnh hiện trên form (có nút copy).
3. Khi script hỏi, gõ mã cài đặt dạng `XXXX-XXXX`, rồi dán URL RTSP cho từng
   camera — hoặc gõ `usb` nếu là webcam, script sẽ liệt kê webcam cho chọn.

Script tự làm hết: cài Python nếu thiếu, tải agent và ffmpeg, ghi `agent.yaml`,
đăng ký chạy cùng Windows, khởi động agent. Không cần quyền admin.

Mã cài đặt **dùng một lần và hết hạn sau 30 phút**. URL với mật khẩu camera chỉ
được hỏi tại chỗ rồi ghi xuống máy đó — Odoo không bao giờ thấy.

Cài xong còn một bước trên trình duyệt của máy đó: mở
`/pack_recorder/set_station` và chọn bàn. Script sẽ hỏi có mở luôn không.

### Cài lại / cập nhật agent

Chạy lại đúng lệnh đó. Script tải bản agent mới nhất từ Odoo, giữ nguyên ffmpeg
đã tải, và ghi đè cấu hình — nên phải tạo mã cài đặt mới mỗi lần.

## Cài thủ công

Dùng khi máy không ra được internet, hoặc muốn kiểm từng bước.

```
copy hlv_pack_agent.py       C:\hlv_agent\
copy agent.example.yaml      C:\hlv_agent\agent.yaml
```

Sửa `agent.yaml`: điền `station_key` và `token` lấy từ màn hình bàn đóng gói,
rồi điền URL RTSP từng camera.

> URL RTSP chỉ nằm trong file này, Odoo không bao giờ thấy. Token Odoo có rò ra
> ngoài cũng không lộ được mật khẩu camera.

Chạy thử bằng tay trước:

```
python hlv_pack_agent.py --config agent.yaml --verbose
```

Mở một phiếu đóng gói trên máy đó. Log phải hiện `ffmpeg start rec=... cam=...`.
Bấm Hoàn tất, log phải hiện `gửi rec=... MB` rồi `gửi xong`.

## Khai báo máy một lần

Trên trình duyệt của máy đóng gói, mở `/pack_recorder/set_station` rồi bấm chọn
đúng bàn. Mã bàn được lưu vào localStorage; từ đó mỗi lần mở phiếu trang tự gửi
kèm. Làm một lần cho mỗi máy.

## Chạy như service

Dùng [NSSM](https://nssm.cc/):

```
nssm install HLVPackAgent "C:\Python312\python.exe" "D:\hlv_agent\hlv_pack_agent.py --config D:\hlv_agent\agent.yaml"
nssm set HLVPackAgent AppDirectory D:\hlv_agent
nssm set HLVPackAgent Start SERVICE_AUTO_START
nssm set HLVPackAgent AppExit Default Restart
nssm start HLVPackAgent
```

`AppExit Default Restart` là phần quan trọng: agent chết vì lý do gì thì Windows
tự bật lại. Đây là thứ thay cho việc bắt nhân viên nhớ mở OBS.

## Kiểm tra khi có sự cố

| Triệu chứng | Xem ở đâu |
|---|---|
| Phiếu không có video | Odoo → Nhật ký ghi hình, lọc theo phiếu |
| Không rõ agent còn sống không | Màn hình bàn đóng gói, ô **Agent gọi lần cuối** |
| ffmpeg lỗi | Cột **error_note** trong Nhật ký ghi hình |
| Video mờ | Kiểm `subtype=0` trong URL RTSP — `subtype=1` là luồng phụ, mờ |

## Dung lượng

1080p H.264 sao chép nguyên luồng khoảng **30 MB/phút/camera**. Hai camera, đơn
5 phút ≈ 300 MB. `work_dir` chỉ giữ file trong lúc ghi rồi gửi đi; gửi xong là
xoá. File nào gửi không được thì **giữ lại có chủ ý** để lấy tay — đừng xoá thư
mục đó khi chưa kiểm.
