# Agent ghi hình đóng gói — cài trên máy tại kho

Ghi thẳng luồng RTSP của từng camera thành file riêng bằng `ffmpeg -c copy`:
không giải mã, không nén lại, chất lượng đúng bằng luồng gốc, CPU gần như 0.

Agent **chỉ gọi ra** Odoo, không mở cổng nào. Không cần chỉnh firewall, không
dính chuyện mixed content của trình duyệt, không trang web lạ nào gọi vào được.

## Trước khi cài

1. Cài **ffmpeg** và đảm bảo `ffmpeg -version` chạy được trong Command Prompt.
   Tải bản Windows ở https://www.gyan.dev/ffmpeg/builds/ rồi thêm thư mục `bin`
   vào PATH.
2. Cài **Python 3.10+**, rồi `pip install requests pyyaml`.
3. Trong Odoo: **Tồn kho → Cấu hình → Video đóng gói → Bàn đóng gói & camera**.
   Tạo một bàn, khai các camera của bàn đó. **Mã camera** ở đây phải trùng khoá
   trong `agent.yaml` bên dưới.

## Cài

```
copy hlv_pack_agent.py       D:\hlv_agent\
copy agent.example.yaml      D:\hlv_agent\agent.yaml
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
