| menu | phân loại | thực hiện | kết quả |
| --- | --- | --- | --- |
| product feed |  | tạo mới product feed, thêm sản phẩm, liên kết tài khoản ads, liên kết chiến dịch  | pass |
| chiến lược tự động |  | tạo mới chiến lược tự động, cấu hình tài khoản ads, sản phẩm | pass |
|  |  | chọn loại chiến lược theo mẫu có sẵn hoặc tùy chỉnh | pass, tự sinh rule cho các sản phẩm được liên kết, chưa kiểm tra kết quả thực tế khi điều kiện thỏa |
| chiến dịch | mua sắm | tạo chiến dịch loại mua sắm, chọn sản phẩm và tài khoản, yêu cầu có tài khoản merchant | pass, tạo và đồng bộ google thành công |
|  | tìm kiếm | tạo chiến dịch loại tìm kiếm, chọn sản phẩm và tài khoản | pass, tạo và đồng bộ google thành công |
|  | tạo nhu cầu | tạo chiến dịch loại "tạo nhu cầu (Demand gen)", chọn sản phẩm và tài khoản | pass, tạo và đồng bộ google thành công |
|  | video | tạo chiến dịch loại video | fail, chưa rõ yêu cầu từ phía google hay api không hỗ trợ |
|  | thông minh | tạo chiến dịch loại thông minh, chọn sản phẩm và tài khoản | pass, tạo và đồng bộ google thành công |
|  | khách sạn | tạo chiến dịch loại khách sạn | fail, tài khoản không hỗ trợ, không cần thiết cho nhu cầu, bỏ qua |
|  | tối đa hiệu suất (Pmax) | tạo chiến dịch loại tối đa hiệu suất, kết nối tài khoản ads, liên kết sản phẩm, cần thiết lập url, tên thương hiệu, ảnh logo vuông, ảnh quảng cáo ngang,đầy đủ tiêu đề và mô tả | pass, tạo và đồng bộ google thành công |
|  | đa kênh (UAC) | tạo chiến dịch loại đa kênh, điền các giá trị cần thiết | fail, cần có ứng dụng đăng ký thành công trên store, không phù hợp nhu cầu hiện tại, bỏ qua |
|  | adsroid | thiết lập liên kết api, có nút phân tích nhanh và mở chat, triển khai code để tự điều chỉnh theo kết quả phân tích | on working, api chưa hoạt động do không có ngân sách |
| nhóm quảng cáo |  | tạo mới nhóm quảng cáo, chọn loại chiến dịch, sản phẩm và loại nhóm quảng cáo phù hợp, đồng bộ lên google ads | pass, đồng bộ thành công nếu không có sai sót trong thiết lập, cần xem lại logic chọn sản phẩm, cần test kỹ hơn |
| quảng cáo | thành phần con của nhóm quảng cáo | tạo mới loại mẫu quảng cáo, chọn đúng nhóm quảng cáo phù hợp và điền các thông tin cần thiết, nhấn đồng bộ google | on working, cần test kĩ các trường hợp do mối quan hệ phức tạp giữa mẫu quảng cáo - nhóm quảng cáo - chiến dịch |
| quy tắc tự động | chứa các rule sinh ra từ menu chiến lược tự động | kiểm tra các rule sinh ra từ chiến lược tự động, có thể điều chỉnh toán tử riêng từng rule, tạo rule chung áp dụng cho toàn chiến dịch hoặc nhóm quảng cáo hoặc mẫu quảng cáo | tạo thành công, quy tắc được kích hoạt, chưa kiểm tra kết quả khi thỏa điều kiện |
| lịch sử quy tắc |  | kiểm tra các lần quy tắc tự động được chạy | pass, các quy tắc khi được kích hoạt thủ công hiển thị đầy đủ, chưa kiểm tra trường hợp kích hoạt tự động từ menu trên |
| lượt chuyển đổi | dữ liệu trả về từ google |  | on working, chưa thể kiểm tra ở tình trạng hiện tại |
| cấu hình tài khoản API | liên kết các loại tài khoản và API | thiết lập credential, kết nối ID các loại tài khoản, kết nối API adsroid | pass, chưa kiểm tra trường hợp sử dụng service account |
| cấu hình GTM | liên kết tài khoản GTM | điền các thông tin kết nối, kiểm tra dữ liệu trả về | pass, giao diện hiển thị đầy đủ dữ liệu trả về từ google analytis, không đồng bộ ngược được do tài khoản không được cấp quyền |
| conversion action |  | thu thập dữ liệu từ các lượt click quảng cáo đã mua hàng để gửi lên google | không thể test ở hiện tại |
