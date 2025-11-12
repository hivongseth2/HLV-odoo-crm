# AI Sales Support Module for Odoo 18

🤖 **AI-powered sales support with inventory check and supplier communication via Zalo**

## Overview

This module provides intelligent sales support functionality that helps sales teams process customer inquiries automatically using AI, check inventory availability, and communicate with suppliers via Zalo OA when stock is insufficient.

## Features

### 🧠 AI-Powered Analysis
- **ChatGPT Integration**: Uses OpenAI's ChatGPT to analyze sales inquiries and extract product information
- **Intelligent Parsing**: Automatically identifies products, quantities, and customer requirements from natural language
- **Multi-language Support**: Works with Vietnamese and English inquiries

### 📦 Inventory Management
- **Real-time Stock Check**: Automatically checks inventory levels across multiple warehouses
- **Pricing Verification**: Retrieves current product prices from Odoo database
- **Availability Analysis**: Determines if sufficient stock is available for each product

### 📱 Zalo Integration
- **Supplier Communication**: Automatically contacts suppliers via Zalo OA when stock is insufficient
- **Response Tracking**: Monitors supplier responses and processing times
- **Performance Analytics**: Tracks supplier response rates and reliability

### 📋 Quotation Generation
- **Automated Quotations**: Generates professional quotations based on AI analysis
- **Dynamic Pricing**: Applies markup percentages and special pricing rules
- **Customer Integration**: Links quotations to existing customers in Odoo

## Installation

1. **Copy Module**: Place the `ai_sales_support_18` folder in your Odoo addons directory
2. **Update Apps List**: Go to Apps → Update Apps List
3. **Install Module**: Search for "AI Sales Support" and click Install
4. **Configure Settings**: Go to Settings → AI Sales Support to configure API keys

## Configuration

### ChatGPT Setup
1. Go to **Settings → AI Sales Support**
2. Enable AI Sales Support
3. Enter your OpenAI API key
4. Configure model settings (default: gpt-3.5-turbo)

### Zalo OA Setup
1. Get Zalo OA access token from Zalo Developer Console
2. Enter Zalo OA credentials in settings
3. Add supplier contacts with their Zalo user IDs

### Supplier Contacts
1. Go to **AI Sales Support → Supplier Contacts**
2. Create contacts for each supplier
3. Add their Zalo user IDs and phone numbers
4. Set priority levels and product categories

## Usage

### For Sales Team

#### Method 1: Web Interface
1. Go to **AI Sales Support → Sales Inquiries**
2. Click "Create" to add new inquiry
3. Enter customer inquiry text
4. Click "Start Processing" to begin AI analysis

#### Method 2: API Integration
```python
import requests

response = requests.post('http://your-odoo-server/ai_sales/inquiry', json={
    "jsonrpc": "2.0",
    "method": "call",
    "params": {
        "inquiry_text": "I need 5 laptops and 10 mice for my office",
        "customer_id": 123
    }
})
```

### Workflow Process

1. **Inquiry Submission**: Sales team submits customer inquiry
2. **AI Analysis**: ChatGPT analyzes and extracts product information
3. **Inventory Check**: System checks stock levels and pricing
4. **Supplier Contact**: If insufficient stock, contacts suppliers via Zalo
5. **Response Processing**: AI processes supplier responses
6. **Quotation Generation**: Creates final quotation for customer

## API Endpoints

### POST /ai_sales/inquiry
Process a new sales inquiry
```json
{
    "inquiry_text": "Customer inquiry text",
    "customer_id": 123
}
```

### POST /ai_sales/status
Check AI system status
```json
{}
```

### POST /ai_sales/inquiry_status
Check inquiry processing status
```json
{
    "inquiry_id": "ASI00001"
}
```

### POST /ai_sales/create_quotation
Create quotation from inquiry
```json
{
    "inquiry_id": "ASI00001",
    "customer_id": 123
}
```

## Models

### ai.sales.inquiry
Main inquiry tracking model
- **inquiry_reference**: Unique reference (ASI00001, ASI00002, etc.)
- **state**: Processing state (draft, processing, completed, etc.)
- **inquiry_text**: Original customer inquiry
- **ai_analysis**: AI processing results
- **total_amount**: Calculated total amount

### ai.sales.supplier.contact
Supplier contact information for Zalo communication
- **supplier_id**: Link to res.partner
- **zalo_user_id**: Zalo user ID for messaging
- **success_rate**: Communication success percentage
- **response_time_avg**: Average response time

### ai.sales.communication.log
Communication history with suppliers
- **message_type**: outgoing/incoming
- **status**: sent/delivered/read/replied/failed
- **response_time**: Time taken for response

## Testing

### Unit Tests
Run the included unit tests:
```bash
python -m pytest ai_sales_support_18/tests/
```

### Demo Script
Test the module functionality:
```bash
python ai_sales_support_18/demo_test.py --url http://localhost:8069
```

## Requirements

### Python Dependencies
- `openai` - OpenAI API client
- `requests` - HTTP requests
- `python-dateutil` - Date parsing

### External Services
- **OpenAI API**: ChatGPT API key required
- **Zalo OA**: Official Account with API access
- **Internet Connection**: For API communications

### Odoo Dependencies
- `base` - Core Odoo functionality
- `sale` - Sales management
- `stock` - Inventory management
- `product` - Product catalog
- `website` - Web interface
- `contacts` - Customer/supplier management

## Configuration Examples

### Sample Inquiry Text
```
Tôi cần báo giá cho khách hàng:
- Laptop Dell XPS 13: 5 chiếc
- Mouse Logitech MX Master: 10 chiếc
- Bàn phím cơ Keychron K2: 3 chiếc

Khách hàng cần giao hàng trong tuần này.
```

### AI System Prompt
```
You are a sales assistant for a Vietnamese technology company. 
Analyze customer inquiries and extract product information including:
- Product names and codes
- Quantities needed
- Any special requirements
- Delivery timeline

Respond in Vietnamese and be professional.
```

## Troubleshooting

### Common Issues

1. **AI not responding**
   - Check OpenAI API key validity
   - Verify internet connection
   - Check API usage limits

2. **Zalo messages not sending**
   - Verify Zalo OA access token
   - Check supplier Zalo user IDs
   - Ensure OA has permission to message users

3. **Inventory not found**
   - Check product codes in database
   - Verify warehouse configurations
   - Update product information

### Debug Mode
Enable debug logging in Odoo configuration:
```ini
[options]
log_level = debug
log_handler = :DEBUG
```

## Support

For support and questions:
- **Email**: support@hoanglongvu.com
- **Documentation**: Check module description and code comments
- **Issues**: Report bugs via your preferred issue tracking system

## License

This module is licensed under LGPL-3.

## Changelog

### Version 18.0.1.0.0
- Initial release for Odoo 18
- ChatGPT integration for inquiry analysis
- Zalo OA integration for supplier communication
- Automated inventory checking
- Quotation generation
- Performance tracking and analytics

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests for new functionality
5. Submit a pull request

## Credits

Developed by **HLV Team** for intelligent sales automation in Odoo 18.