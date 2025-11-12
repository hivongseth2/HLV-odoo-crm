# Hướng dẫn cài đặt và sử dụng HLV AI Sales Support

## 1. Cài đặt Module

### Bước 1: Cài đặt dependencies
```bash
# Cài đặt Python packages cần thiết
pip install openai requests
```

### Bước 2: Cài đặt module trong Odoo
1. Đảm bảo module `hlv_zalo_zns` đã được cài đặt trước
2. Vào **Apps** trong Odoo
3. Tìm kiếm "HLV AI Sales Support"
4. Click **Install**

### Bước 3: Cấu hình ban đầu

#### Cấu hình AI
1. Vào **AI Sales Support > Configuration > AI Configuration**
2. Nhập thông tin:
   - **OpenAI API Key**: API key từ OpenAI
   - **OpenAI Model**: `gpt-3.5-turbo` (khuyến nghị)
   - **Max Tokens**: 1000
   - **Temperature**: 0.3
3. Click **Test OpenAI Connection** để kiểm tra

#### Cấu hình Nhà cung cấp
1. Vào **AI Sales Support > Configuration > Supplier Contacts**
2. Tạo nhà cung cấp mới:
   - **Name**: Tên nhà cung cấp
   - **Zalo User ID**: ID người dùng Zalo của nhà cung cấp
   - **Contact Person**: Tên người liên hệ
   - **Product Categories**: Danh mục sản phẩm
   - **Response Time Hours**: Thời gian phản hồi dự kiến (giờ)

#### Cấu hình Zalo Webhook
1. Vào **Settings > Technical > System Parameters**
2. Tìm parameter `hlv_ai_sales.zalo_verify_token`
3. Đặt giá trị verify token cho webhook
4. Cấu hình webhook URL trong Zalo OA: `https://your-domain.com/webhook/zalo/ai_sales`

## 2. Sử dụng API

### Endpoint chính

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

**Response:**
```json
{
    "success": true,
    "request_id": "SR00001",
    "status": "draft",
    "message": "Sales request created and processing started"
}
```

#### Kiểm tra trạng thái
```bash
GET /api/ai_sales/status/SR00001
```

**Response:**
```json
{
    "success": true,
    "request_id": "SR00001",
    "status": "completed",
    "sales_person": "Anh Quang",
    "customer_name": "Khách hàng ABC",
    "final_response": "Báo giá sản phẩm...",
    "product": {
        "name": "Ốc vít M6x20mm inox 304",
        "stock_available": 150,
        "unit_price": 5000,
        "total_price": 500000
    }
}
```

#### Liệt kê yêu cầu
```bash
GET /api/ai_sales/requests?sales_person=Quang&limit=10
```

#### Health check
```bash
GET /api/ai_sales/health
```

### Test API với Python
```python
import requests

# Tạo yêu cầu
response = requests.post('http://localhost:8069/api/ai_sales/request', json={
    "sales_person": "Anh Quang",
    "product_request": "Cần 50 cái bu lông M8x30"
})

if response.json()['success']:
    request_id = response.json()['request_id']
    print(f"Created request: {request_id}")
    
    # Kiểm tra trạng thái
    status = requests.get(f'http://localhost:8069/api/ai_sales/status/{request_id}')
    print(f"Status: {status.json()}")
```

## 3. Quy trình hoạt động

### Quy trình tự động
1. **Nhận yêu cầu**: Sales gửi thông tin sản phẩm qua API
2. **Phân tích AI**: ChatGPT phân tích và trích xuất thông tin sản phẩm
3. **Tìm sản phẩm**: Hệ thống tìm sản phẩm phù hợp trong database
4. **Kiểm tra tồn kho**: Kiểm tra số lượng có sẵn
5. **Xử lý theo tình huống**:
   - **Đủ hàng**: Tạo báo giá ngay lập tức
   - **Thiếu hàng**: Gửi yêu cầu hỏi giá đến nhà cung cấp qua Zalo
6. **Nhận phản hồi**: Xử lý phản hồi từ nhà cung cấp (qua webhook)
7. **Tạo báo giá**: Tổng hợp thông tin và gửi báo giá cho sales

### Trạng thái xử lý
- `draft`: Mới tạo
- `analyzing`: Đang phân tích bằng AI
- `checking_stock`: Đang kiểm tra tồn kho
- `contacting_suppliers`: Đang liên hệ nhà cung cấp
- `waiting_response`: Chờ phản hồi nhà cung cấp
- `preparing_quote`: Đang chuẩn bị báo giá
- `completed`: Hoàn thành
- `error`: Lỗi

## 4. Quản lý trong Odoo

### Theo dõi yêu cầu
- Vào **AI Sales Support > Operations > Sales Requests**
- Xem danh sách tất cả yêu cầu với trạng thái
- Click vào yêu cầu để xem chi tiết

### Quản lý nhà cung cấp
- Vào **AI Sales Support > Configuration > Supplier Contacts**
- Xem thống kê phản hồi của từng nhà cung cấp
- Cập nhật thông tin liên hệ

### Theo dõi yêu cầu hỏi giá
- Vào **AI Sales Support > Operations > Product Inquiries**
- Xem tất cả yêu cầu gửi đến nhà cung cấp
- Theo dõi phản hồi và giá

## 5. Tùy chỉnh

### Tùy chỉnh Prompt AI
1. Vào **AI Sales Support > Configuration > AI Configuration**
2. Tab **AI Prompts**
3. Chỉnh sửa:
   - **Product Analysis Prompt**: Template phân tích sản phẩm
   - **Supplier Inquiry Prompt**: Template tin nhắn hỏi giá

### Ví dụ Product Analysis Prompt:
```
Phân tích yêu cầu sản phẩm sau và trả về JSON:
{product_info}

Trả về format JSON:
{
    "product_name": "tên sản phẩm chuẩn hóa",
    "category": "danh mục sản phẩm", 
    "quantity": số_lượng,
    "unit": "đơn vị",
    "description": "mô tả chi tiết",
    "keywords": ["từ khóa 1", "từ khóa 2"]
}
```

### Ví dụ Supplier Inquiry Prompt:
```
Xin chào,

Chúng tôi cần báo giá cho sản phẩm:
- Tên: {product_name}
- Mô tả: {description}
- Số lượng: {quantity} {unit}

Vui lòng cung cấp:
1. Giá đơn vị
2. Thời gian giao hàng
3. Số lượng tối thiểu (nếu có)

Cảm ơn!
```

## 6. Troubleshooting

### Lỗi thường gặp

#### OpenAI API Error
- Kiểm tra API key có đúng không
- Kiểm tra quota OpenAI
- Thử test connection trong cấu hình

#### Zalo Connection Error  
- Kiểm tra cấu hình Zalo ZNS
- Kiểm tra Zalo User ID của nhà cung cấp
- Kiểm tra webhook URL và verify token

#### Product Not Found
- Kiểm tra dữ liệu sản phẩm trong hệ thống
- Cập nhật từ khóa tìm kiếm
- Kiểm tra prompt phân tích AI

### Logs và Debug
```bash
# Xem logs Odoo
tail -f /var/log/odoo/odoo.log | grep "hlv_ai_sales"

# Hoặc trong Odoo
# Settings > Technical > Logging
```

### Test API
```bash
# Chạy script test
cd /path/to/odoo
python demo_api_test.py
```

## 7. Bảo mật

### API Security
- API endpoints sử dụng `auth='public'` để dễ tích hợp
- Trong production, nên thêm authentication
- Sử dụng HTTPS cho tất cả API calls

### Data Protection
- OpenAI API key được mã hóa trong database
- Logs không chứa thông tin nhạy cảm
- Webhook có verify token để xác thực

## 8. Mở rộng

### Tích hợp thêm AI Models
- Có thể thêm support cho Claude, Gemini
- Chỉnh sửa trong `ai_sales_config.py`

### Thêm kênh liên lạc
- SMS gateway
- Email automation  
- Telegram bot

### Dashboard và Reports
- Tạo dashboard theo dõi hiệu suất
- Báo cáo thống kê sales requests
- Phân tích hiệu quả nhà cung cấp

## Liên hệ hỗ trợ

Nếu gặp vấn đề trong quá trình cài đặt hoặc sử dụng, vui lòng liên hệ team phát triển để được hỗ trợ.