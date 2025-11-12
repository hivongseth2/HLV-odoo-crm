# HLV AI Sales Support

## Mô tả

Module AI Sales Support tích hợp trí tuệ nhân tạo để hỗ trợ đội ngũ bán hàng trong việc xử lý yêu cầu sản phẩm từ khách hàng. Module sử dụng ChatGPT để phân tích yêu cầu, kiểm tra tồn kho tự động, và liên hệ nhà cung cấp qua Zalo khi cần thiết.

## Tính năng chính

### 1. Phân tích yêu cầu bằng AI
- Sử dụng ChatGPT để phân tích thông tin sản phẩm từ mô tả tự nhiên
- Trích xuất tên sản phẩm, số lượng, đơn vị, và từ khóa tìm kiếm
- Chuẩn hóa thông tin sản phẩm

### 2. Kiểm tra tồn kho tự động
- Tìm kiếm sản phẩm trong hệ thống dựa trên kết quả phân tích AI
- Kiểm tra số lượng tồn kho có đủ đáp ứng yêu cầu
- Hỗ trợ kiểm tra đa kho hoặc kho chính

### 3. Liên hệ nhà cung cấp qua Zalo
- Tự động gửi tin nhắn hỏi giá đến nhà cung cấp qua Zalo OA
- Quản lý danh sách nhà cung cấp với thông tin liên hệ Zalo
- Theo dõi phản hồi và phân tích giá từ nhà cung cấp

### 4. Tạo báo giá tự động
- Tự động tạo báo giá khi có đủ thông tin
- Gửi báo giá cho đội ngũ bán hàng
- Quản lý thời hạn hiệu lực báo giá

## Cài đặt

### Yêu cầu hệ thống
- Odoo 15.0+
- Python packages: `requests`, `openai`
- Module `hlv_zalo_zns` (đã có sẵn trong hệ thống)

### Cài đặt module
1. Copy module vào thư mục `custom_addons`
2. Cập nhật danh sách apps trong Odoo
3. Cài đặt module "HLV AI Sales Support"

### Cấu hình ban đầu

#### 1. Cấu hình AI
- Vào **AI Sales Support > Configuration > AI Configuration**
- Nhập OpenAI API Key
- Chọn model AI phù hợp (khuyến nghị: gpt-3.5-turbo)
- Điều chỉnh các tham số AI nếu cần

#### 2. Cấu hình nhà cung cấp
- Vào **AI Sales Support > Configuration > Supplier Contacts**
- Thêm thông tin nhà cung cấp với Zalo User ID
- Cấu hình danh mục sản phẩm và từ khóa cho mỗi nhà cung cấp

#### 3. Cấu hình Zalo Webhook
- Thiết lập webhook URL: `https://your-domain.com/webhook/zalo/ai_sales`
- Cấu hình verify token trong System Parameters

## Sử dụng

### API Endpoints

#### Tạo yêu cầu bán hàng
```bash
POST /api/ai_sales/request
Content-Type: application/json

{
    "sales_person": "Anh Quang",
    "sales_email": "quang@hlv.com", 
    "customer_name": "Khách hàng ABC",
    "product_request": "Tôi cần 100 cái ốc vít M6x20mm inox 304"
}
```

#### Kiểm tra trạng thái yêu cầu
```bash
GET /api/ai_sales/status/{request_id}
```

#### Liệt kê yêu cầu
```bash
GET /api/ai_sales/requests?sales_person=Quang&limit=10
```

### Quy trình xử lý

1. **Nhận yêu cầu**: Sales gửi thông tin sản phẩm qua API
2. **Phân tích AI**: ChatGPT phân tích và chuẩn hóa thông tin
3. **Tìm sản phẩm**: Hệ thống tìm sản phẩm phù hợp trong kho
4. **Kiểm tra tồn kho**: Kiểm tra số lượng có sẵn
5. **Xử lý theo tình huống**:
   - **Đủ hàng**: Tạo báo giá ngay lập tức
   - **Thiếu hàng**: Liên hệ nhà cung cấp qua Zalo
6. **Nhận phản hồi**: Xử lý phản hồi từ nhà cung cấp
7. **Tạo báo giá**: Tổng hợp thông tin và gửi báo giá cho sales

## Cấu trúc dữ liệu

### Models chính

- **hlv.ai.sales.config**: Cấu hình AI và hệ thống
- **hlv.ai.supplier.contact**: Thông tin nhà cung cấp
- **hlv.ai.sales.request**: Yêu cầu từ đội ngũ bán hàng
- **hlv.ai.product.inquiry**: Yêu cầu hỏi giá nhà cung cấp
- **hlv.ai.sales.response**: Phản hồi cho đội ngũ bán hàng

### Trạng thái xử lý

#### Sales Request States
- `draft`: Mới tạo
- `analyzing`: Đang phân tích bằng AI
- `checking_stock`: Đang kiểm tra tồn kho
- `contacting_suppliers`: Đang liên hệ nhà cung cấp
- `waiting_response`: Chờ phản hồi nhà cung cấp
- `preparing_quote`: Đang chuẩn bị báo giá
- `completed`: Hoàn thành
- `cancelled`: Đã hủy
- `error`: Lỗi

#### Product Inquiry States
- `draft`: Mới tạo
- `sent`: Đã gửi cho nhà cung cấp
- `responded`: Nhà cung cấp đã phản hồi
- `timeout`: Quá thời gian chờ
- `error`: Lỗi

## Tùy chỉnh

### Prompt Templates
Có thể tùy chỉnh các template prompt trong cấu hình AI:
- **Product Analysis Prompt**: Template phân tích sản phẩm
- **Supplier Inquiry Prompt**: Template tin nhắn hỏi giá

### Webhook Customization
Có thể mở rộng xử lý webhook để hỗ trợ thêm các loại tin nhắn từ Zalo.

## Troubleshooting

### Lỗi thường gặp

1. **OpenAI API Error**: Kiểm tra API key và quota
2. **Zalo Connection Error**: Kiểm tra cấu hình Zalo ZNS
3. **Product Not Found**: Kiểm tra dữ liệu sản phẩm và từ khóa
4. **Supplier Not Responding**: Kiểm tra Zalo User ID và trạng thái hoạt động

### Logs
Kiểm tra logs trong Odoo để debug:
```bash
grep "hlv_ai_sales" /var/log/odoo/odoo.log
```

## Phát triển

### Mở rộng tính năng
- Tích hợp thêm AI models khác
- Hỗ trợ thêm kênh liên lạc (SMS, Email)
- Dashboard và báo cáo chi tiết
- Tích hợp với CRM và Sales Order

### API Documentation
Chi tiết API có thể xem tại `/api/ai_sales/health` để kiểm tra trạng thái hệ thống.

## Hỗ trợ

Liên hệ team phát triển để được hỗ trợ kỹ thuật và tùy chỉnh theo nhu cầu cụ thể.