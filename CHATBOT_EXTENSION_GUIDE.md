# AI Chatbot Extension for Website Public Inventory

## Tổng quan

Extension này mở rộng module `website_public_inventory_18` với tính năng chatbot AI sử dụng ChatGPT để hỗ trợ khách hàng tìm kiếm sản phẩm và thông tin tồn kho.

## Tính năng chính

### 🤖 AI Chatbot
- **Tích hợp ChatGPT**: Sử dụng OpenAI API để xử lý câu hỏi của khách hàng
- **Tìm kiếm thông minh**: Tự động tìm kiếm sản phẩm trong database Odoo
- **Web search**: Tìm kiếm trên web khi không có sản phẩm trong kho
- **Giao diện thân thiện**: Widget chatbot hiện đại với CSS responsive

### 📦 Tìm kiếm tồn kho
- **Tìm kiếm đa tiêu chí**: Theo tên, mã sản phẩm, barcode
- **Thông tin chi tiết**: Tồn kho, giá bán, giá thương mại
- **Trạng thái kho**: Hiển thị tình trạng còn hàng/sắp hết/hết hàng
- **Multi-warehouse**: Hỗ trợ nhiều kho

### 🌐 Web Search
- **Tìm kiếm bên ngoài**: Khi không tìm thấy trong kho
- **Gợi ý thông minh**: Link đến các trang thương mại điện tử
- **Thông tin giá**: Giá tham khảo từ các nguồn bên ngoài

## Cài đặt và Cấu hình

### 1. Cài đặt Dependencies

```bash
pip install openai
```

### 2. Cấu hình trong Odoo

1. **Truy cập Settings**:
   - Đi đến `Settings > Website > Public Inventory`

2. **Cấu hình AI Chatbot**:
   - ✅ Bật "Enable AI Chatbot"
   - 🔑 Nhập "OpenAI API Key" (sk-...)
   - 🤖 Chọn "OpenAI Model" (gpt-3.5-turbo, gpt-4, gpt-4-turbo)
   - ⚙️ Điều chỉnh "Max Tokens" (mặc định: 500)
   - 🎛️ Điều chỉnh "Temperature" (mặc định: 0.3)
   - 🌐 Bật "Enable Web Search" nếu muốn tìm kiếm web

3. **Test kết nối**:
   - Nhấn nút "Test Connection" để kiểm tra API key

### 3. Cấu hình Warehouse

- Chọn các kho muốn hiển thị công khai trong "Public Warehouses"

## Sử dụng

### 1. Truy cập Chatbot

- Chatbot sẽ xuất hiện tự động trên trang `/search_stock`
- Biểu tượng chatbot ở góc dưới bên phải màn hình
- Click để mở/đóng chatbot

### 2. Tương tác với Chatbot

**Ví dụ câu hỏi:**
- "Tôi muốn tìm laptop Dell"
- "Có điện thoại iPhone không?"
- "Giá sản phẩm ABC123 bao nhiêu?"
- "Tồn kho máy tính còn bao nhiêu?"

**Chatbot sẽ:**
- Tìm kiếm trong database Odoo
- Hiển thị thông tin tồn kho và giá
- Nếu không tìm thấy, sẽ search web và đưa ra gợi ý

## API Endpoints

### 1. Chatbot Message
```
POST /chatbot/message
Content-Type: application/json

{
    "jsonrpc": "2.0",
    "method": "call",
    "params": {
        "message": "Tìm laptop Dell"
    },
    "id": 1
}
```

**Response:**
```json
{
    "jsonrpc": "2.0",
    "id": 1,
    "result": {
        "success": true,
        "response": "AI response text",
        "inventory_results": [...],
        "web_results": [...]
    }
}
```

### 2. Chatbot Status
```
GET /chatbot/status
```

**Response:**
```json
{
    "enabled": true,
    "configured": true,
    "web_search_enabled": true
}
```

## Cấu trúc File

```
website_public_inventory_18/
├── controllers/
│   ├── chatbot.py              # Chatbot API controller
│   └── __init__.py             # Updated imports
├── models/
│   └── res_config_settings.py  # Extended with chatbot config
├── static/
│   ├── css/
│   │   └── chatbot.css         # Chatbot styling
│   └── js/
│       └── chatbot.js          # Chatbot frontend logic
├── views/
│   ├── chatbot_templates.xml   # Chatbot widget template
│   └── res_config_settings_views.xml  # Updated config views
└── __manifest__.py             # Updated manifest
```

## Tính năng AI

### 1. Context-Aware Responses
- AI hiểu ngữ cảnh câu hỏi về sản phẩm
- Phân tích ý định tìm kiếm của khách hàng
- Đưa ra phản hồi phù hợp và hữu ích

### 2. Smart Product Matching
- Tìm kiếm mờ (fuzzy search) theo tên sản phẩm
- Hỗ trợ tìm kiếm theo mã sản phẩm và barcode
- Gợi ý sản phẩm tương tự

### 3. Inventory Intelligence
- Phân tích tình trạng tồn kho
- Cảnh báo sản phẩm sắp hết hàng
- Thông tin giá cả chi tiết

## Testing

### 1. Manual Testing
- Sử dụng chatbot trực tiếp trên website
- Test các loại câu hỏi khác nhau
- Kiểm tra phản hồi AI

### 2. API Testing
```bash
python3 chatbot_demo_test.py
```

### 3. Configuration Testing
- Test OpenAI API connection trong Settings
- Kiểm tra các tham số cấu hình

## Troubleshooting

### 1. Chatbot không hiển thị
- ✅ Kiểm tra "Enable AI Chatbot" đã được bật
- 🔑 Kiểm tra OpenAI API key đã được nhập
- 🌐 Kiểm tra kết nối internet

### 2. AI không phản hồi
- 🔑 Kiểm tra API key hợp lệ
- 💰 Kiểm tra credit OpenAI account
- 📊 Kiểm tra logs Odoo

### 3. Không tìm thấy sản phẩm
- 📦 Kiểm tra sản phẩm có tồn tại trong kho được cấu hình
- 🏢 Kiểm tra quyền truy cập warehouse
- 🔍 Thử tìm kiếm với từ khóa khác

## Customization

### 1. Thay đổi AI Prompt
Chỉnh sửa method `_generate_ai_response()` trong `controllers/chatbot.py`

### 2. Tùy chỉnh Web Search
Chỉnh sửa method `_search_web()` để tích hợp API search khác

### 3. Styling Chatbot
Chỉnh sửa file `static/css/chatbot.css`

### 4. Thêm tính năng
Extend ChatbotController để thêm endpoints mới

## Security Notes

- 🔐 API key được lưu trữ an toàn trong system parameters
- 🚫 Không log sensitive data
- ✅ Validate input từ người dùng
- 🛡️ Rate limiting có thể được thêm vào

## Performance

- ⚡ Cache kết quả tìm kiếm inventory
- 🎯 Limit số lượng kết quả trả về
- 📊 Monitor API usage OpenAI
- 🔄 Async processing cho web search

## Support

Để được hỗ trợ:
1. Kiểm tra logs Odoo
2. Test API endpoints trực tiếp
3. Verify cấu hình OpenAI
4. Liên hệ team phát triển

---

**Version**: 1.0.0  
**Compatible**: Odoo 18.0  
**Dependencies**: OpenAI Python library  
**License**: LGPL-3