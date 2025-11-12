# -*- coding: utf-8 -*-

import json
import requests
import logging
from datetime import datetime, timedelta
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class AISalesService(models.Model):
    _name = 'ai.sales.service'
    _description = 'AI Sales Service'

    @api.model
    def process_sales_inquiry(self, inquiry_text, sales_person_id=None, customer_id=None):
        """
        Main method to process sales inquiry
        """
        try:
            # Create inquiry record
            inquiry = self.env['ai.sales.inquiry'].create({
                'inquiry_text': inquiry_text,
                'sales_person_id': sales_person_id or self.env.user.id,
                'customer_id': customer_id,
                'state': 'draft'
            })
            
            inquiry.start_processing()
            
            # Step 1: Analyze inquiry with AI
            analysis_result = self._analyze_inquiry_with_ai(inquiry_text)
            inquiry.write({
                'ai_analysis': analysis_result.get('analysis', ''),
                'processed_inquiry': analysis_result.get('processed_text', inquiry_text)
            })
            
            # Step 2: Extract product information
            products_info = self._extract_products_from_analysis(analysis_result)
            
            # Step 3: Create inquiry lines
            self._create_inquiry_lines(inquiry, products_info)
            
            # Step 4: Check inventory
            inquiry.state = 'inventory_check'
            inventory_sufficient = self._check_inventory(inquiry)
            
            if inventory_sufficient:
                # Step 5a: Generate quotation directly
                response = self._generate_quotation_response(inquiry)
                inquiry.write({
                    'ai_response': response,
                    'state': 'quotation_ready'
                })
            else:
                # Step 5b: Contact suppliers
                inquiry.state = 'supplier_contact'
                self._contact_suppliers(inquiry)
                response = "Đang liên hệ với nhà cung cấp để kiểm tra giá và tồn kho. Tôi sẽ phản hồi trong thời gian sớm nhất."
                inquiry.ai_response = response
            
            inquiry.complete_processing()
            
            return {
                'success': True,
                'inquiry_id': inquiry.id,
                'response': response,
                'state': inquiry.state
            }
            
        except Exception as e:
            _logger.error(f"Error processing sales inquiry: {str(e)}")
            if 'inquiry' in locals():
                inquiry.fail_processing(str(e))
            return {
                'success': False,
                'error': str(e),
                'response': 'Xin lỗi, đã có lỗi xảy ra khi xử lý yêu cầu của bạn.'
            }

    def _analyze_inquiry_with_ai(self, inquiry_text):
        """
        Analyze inquiry using ChatGPT
        """
        config = self.env['ir.config_parameter'].sudo()
        api_key = config.get_param('ai_sales_support.chatgpt_api_key')
        model = config.get_param('ai_sales_support.chatgpt_model', 'gpt-3.5-turbo')
        system_prompt = config.get_param('ai_sales_support.ai_system_prompt', '')
        
        if not api_key:
            raise UserError(_("ChatGPT API key is not configured"))
        
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        prompt = f"""
        Phân tích yêu cầu bán hàng sau và trích xuất thông tin sản phẩm:
        
        "{inquiry_text}"
        
        Vui lòng trả về thông tin dưới dạng JSON với format:
        {{
            "analysis": "Phân tích chi tiết về yêu cầu",
            "products": [
                {{
                    "name": "Tên sản phẩm",
                    "code": "Mã sản phẩm (nếu có)",
                    "description": "Mô tả sản phẩm",
                    "quantity": số_lượng,
                    "unit": "đơn vị tính"
                }}
            ],
            "customer_info": "Thông tin khách hàng (nếu có)",
            "urgency": "mức độ khẩn cấp (low/medium/high)",
            "processed_text": "Văn bản đã được xử lý và chuẩn hóa"
        }}
        """
        
        data = {
            'model': model,
            'messages': [
                {'role': 'system', 'content': system_prompt},
                {'role': 'user', 'content': prompt}
            ],
            'max_tokens': int(config.get_param('ai_sales_support.chatgpt_max_tokens', 1000)),
            'temperature': float(config.get_param('ai_sales_support.chatgpt_temperature', 0.7))
        }
        
        try:
            response = requests.post(
                'https://api.openai.com/v1/chat/completions',
                headers=headers,
                json=data,
                timeout=30
            )
            response.raise_for_status()
            
            result = response.json()
            ai_response = result['choices'][0]['message']['content']
            
            # Try to parse JSON response
            try:
                return json.loads(ai_response)
            except json.JSONDecodeError:
                # If not JSON, return as analysis text
                return {
                    'analysis': ai_response,
                    'products': [],
                    'processed_text': inquiry_text
                }
                
        except requests.exceptions.RequestException as e:
            _logger.error(f"ChatGPT API error: {str(e)}")
            raise UserError(_("Error connecting to ChatGPT API: %s") % str(e))

    def _extract_products_from_analysis(self, analysis_result):
        """
        Extract and validate product information from AI analysis
        """
        products = analysis_result.get('products', [])
        validated_products = []
        
        for product_info in products:
            # Try to find product in database
            product = None
            
            # Search by code first
            if product_info.get('code'):
                product = self.env['product.product'].search([
                    ('default_code', '=', product_info['code'])
                ], limit=1)
            
            # Search by name if not found by code
            if not product and product_info.get('name'):
                product = self.env['product.product'].search([
                    ('name', 'ilike', product_info['name'])
                ], limit=1)
            
            validated_products.append({
                'product_id': product.id if product else False,
                'product_code': product_info.get('code', ''),
                'product_name': product_info.get('name', ''),
                'description': product_info.get('description', ''),
                'quantity': product_info.get('quantity', 1.0),
                'unit': product_info.get('unit', ''),
            })
        
        return validated_products

    def _create_inquiry_lines(self, inquiry, products_info):
        """
        Create inquiry lines from product information
        """
        for i, product_info in enumerate(products_info):
            self.env['ai.sales.inquiry.line'].create({
                'inquiry_id': inquiry.id,
                'sequence': (i + 1) * 10,
                'product_id': product_info.get('product_id'),
                'product_code': product_info.get('product_code'),
                'product_name': product_info.get('product_name'),
                'description': product_info.get('description'),
                'quantity': product_info.get('quantity', 1.0),
            })

    def _check_inventory(self, inquiry):
        """
        Check inventory for all products in inquiry
        """
        all_sufficient = True
        inventory_details = []
        
        for line in inquiry.product_lines:
            if line.product_id:
                # Check inventory
                sufficient = line.check_inventory()
                line.get_product_price()
                
                if not sufficient:
                    all_sufficient = False
                
                inventory_details.append({
                    'product': line.product_name or line.product_id.name,
                    'requested': line.quantity,
                    'available': line.available_qty,
                    'sufficient': sufficient
                })
            else:
                # Product not found in system
                all_sufficient = False
                inventory_details.append({
                    'product': line.product_name or line.product_code,
                    'requested': line.quantity,
                    'available': 0,
                    'sufficient': False,
                    'note': 'Sản phẩm không tìm thấy trong hệ thống'
                })
        
        inquiry.write({
            'inventory_sufficient': all_sufficient,
            'inventory_check_details': json.dumps(inventory_details, ensure_ascii=False)
        })
        
        return all_sufficient

    def _contact_suppliers(self, inquiry):
        """
        Contact suppliers for insufficient products
        """
        config = self.env['ir.config_parameter'].sudo()
        auto_contact = config.get_param('ai_sales_support.auto_contact_suppliers', 'True') == 'True'
        
        if not auto_contact:
            return
        
        suppliers_to_contact = set()
        
        # Find suppliers for insufficient products
        for line in inquiry.product_lines:
            if not line.is_sufficient:
                if line.product_id:
                    # Get suppliers for this product
                    suppliers = self.env['ai.sales.supplier.contact'].get_suppliers_for_product(line.product_id.id)
                    suppliers_to_contact.update(suppliers.ids)
                else:
                    # Get all active suppliers for unknown products
                    suppliers = self.env['ai.sales.supplier.contact'].search([('is_active', '=', True)])
                    suppliers_to_contact.update(suppliers.ids)
        
        # Contact suppliers via Zalo
        contacted_suppliers = []
        for supplier_id in suppliers_to_contact:
            supplier = self.env['ai.sales.supplier.contact'].browse(supplier_id)
            success = self._send_zalo_message(supplier, inquiry)
            if success:
                contacted_suppliers.append(supplier_id)
        
        inquiry.suppliers_contacted = [(6, 0, contacted_suppliers)]

    def _send_zalo_message(self, supplier, inquiry):
        """
        Send message to supplier via Zalo OA
        """
        config = self.env['ir.config_parameter'].sudo()
        access_token = config.get_param('ai_sales_support.zalo_oa_access_token')
        
        if not access_token:
            _logger.warning("Zalo OA access token not configured")
            return False
        
        # Prepare message content
        products_text = ""
        for line in inquiry.product_lines:
            if not line.is_sufficient:
                products_text += f"- {line.product_name or line.product_code}: {line.quantity} {line.uom_id.name if line.uom_id else 'đơn vị'}\n"
        
        message = f"""
Xin chào {supplier.contact_person or supplier.supplier_name},

Chúng tôi cần báo giá cho các sản phẩm sau:

{products_text}

Vui lòng phản hồi giá và thời gian giao hàng.

Trân trọng,
{inquiry.sales_person_id.name}
Mã yêu cầu: {inquiry.inquiry_reference}
        """.strip()
        
        headers = {
            'access_token': access_token,
            'Content-Type': 'application/json'
        }
        
        data = {
            'recipient': {
                'user_id': supplier.zalo_user_id
            },
            'message': {
                'text': message
            }
        }
        
        try:
            response = requests.post(
                'https://openapi.zalo.me/v2.0/oa/message',
                headers=headers,
                json=data,
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                if result.get('error') == 0:
                    # Log successful communication
                    self.env['ai.sales.communication.log'].create({
                        'supplier_contact_id': supplier.id,
                        'inquiry_id': inquiry.id,
                        'message_type': 'outgoing',
                        'message_content': message,
                        'zalo_message_id': result.get('data', {}).get('message_id'),
                        'status': 'sent'
                    })
                    return True
                else:
                    _logger.error(f"Zalo API error: {result}")
                    return False
            else:
                _logger.error(f"Zalo API HTTP error: {response.status_code}")
                return False
                
        except requests.exceptions.RequestException as e:
            _logger.error(f"Error sending Zalo message: {str(e)}")
            return False

    def _generate_quotation_response(self, inquiry):
        """
        Generate quotation response using AI
        """
        # Prepare inventory information
        inventory_info = ""
        total_amount = 0
        
        for line in inquiry.product_lines:
            if line.product_id:
                subtotal = line.quantity * line.unit_price
                total_amount += subtotal
                inventory_info += f"""
- {line.product_id.name}
  Số lượng: {line.quantity} {line.uom_id.name if line.uom_id else 'đơn vị'}
  Đơn giá: {line.unit_price:,.0f} VND
  Thành tiền: {subtotal:,.0f} VND
  Tồn kho: {line.available_qty} {line.uom_id.name if line.uom_id else 'đơn vị'}
"""
        
        inquiry.total_amount = total_amount
        
        # Generate AI response
        config = self.env['ir.config_parameter'].sudo()
        api_key = config.get_param('ai_sales_support.chatgpt_api_key')
        
        if not api_key:
            # Generate simple response without AI
            return f"""
Báo giá cho yêu cầu #{inquiry.inquiry_reference}

{inventory_info}

Tổng cộng: {total_amount:,.0f} VND

Tất cả sản phẩm đều có sẵn trong kho. Chúng tôi có thể giao hàng ngay.

Báo giá có hiệu lực trong 7 ngày.
            """.strip()
        
        # Use AI to generate professional quotation
        prompt = f"""
Tạo báo giá chuyên nghiệp cho khách hàng với thông tin sau:

Yêu cầu gốc: {inquiry.inquiry_text}
Mã yêu cầu: {inquiry.inquiry_reference}
Nhân viên bán hàng: {inquiry.sales_person_id.name}

Chi tiết sản phẩm:
{inventory_info}

Tổng cộng: {total_amount:,.0f} VND

Vui lòng tạo báo giá chuyên nghiệp, thân thiện và đầy đủ thông tin.
        """
        
        try:
            headers = {
                'Authorization': f'Bearer {api_key}',
                'Content-Type': 'application/json'
            }
            
            data = {
                'model': config.get_param('ai_sales_support.chatgpt_model', 'gpt-3.5-turbo'),
                'messages': [
                    {'role': 'system', 'content': config.get_param('ai_sales_support.ai_system_prompt', '')},
                    {'role': 'user', 'content': prompt}
                ],
                'max_tokens': int(config.get_param('ai_sales_support.chatgpt_max_tokens', 1000)),
                'temperature': float(config.get_param('ai_sales_support.chatgpt_temperature', 0.7))
            }
            
            response = requests.post(
                'https://api.openai.com/v1/chat/completions',
                headers=headers,
                json=data,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                return result['choices'][0]['message']['content']
            else:
                _logger.error(f"ChatGPT API error: {response.status_code}")
                
        except Exception as e:
            _logger.error(f"Error generating AI quotation: {str(e)}")
        
        # Fallback to simple response
        return f"""
Báo giá cho yêu cầu #{inquiry.inquiry_reference}

{inventory_info}

Tổng cộng: {total_amount:,.0f} VND

Tất cả sản phẩm đều có sẵn trong kho.
        """.strip()

    @api.model
    def handle_supplier_response(self, supplier_user_id, message_content):
        """
        Handle response from supplier via Zalo webhook
        """
        # Find supplier by Zalo user ID
        supplier = self.env['ai.sales.supplier.contact'].search([
            ('zalo_user_id', '=', supplier_user_id),
            ('is_active', '=', True)
        ], limit=1)
        
        if not supplier:
            _logger.warning(f"Supplier not found for Zalo user ID: {supplier_user_id}")
            return False
        
        # Find recent inquiries waiting for this supplier
        recent_inquiries = self.env['ai.sales.inquiry'].search([
            ('state', '=', 'supplier_contact'),
            ('suppliers_contacted', 'in', supplier.id),
            ('create_date', '>=', fields.Datetime.now() - timedelta(hours=24))
        ])
        
        if not recent_inquiries:
            _logger.warning(f"No recent inquiries found for supplier: {supplier.supplier_name}")
            return False
        
        # Log the response
        for inquiry in recent_inquiries:
            self.env['ai.sales.communication.log'].create({
                'supplier_contact_id': supplier.id,
                'inquiry_id': inquiry.id,
                'message_type': 'incoming',
                'message_content': message_content,
                'status': 'received'
            })
        
        # Process the response with AI to extract pricing information
        self._process_supplier_response(recent_inquiries[0], supplier, message_content)
        
        return True

    def _process_supplier_response(self, inquiry, supplier, response_content):
        """
        Process supplier response and update inquiry
        """
        # Update supplier response
        current_responses = inquiry.supplier_responses or ""
        inquiry.supplier_responses = f"{current_responses}\n\n{supplier.supplier_name}: {response_content}"
        
        # Try to extract pricing with AI
        config = self.env['ir.config_parameter'].sudo()
        api_key = config.get_param('ai_sales_support.chatgpt_api_key')
        
        if api_key:
            try:
                # Use AI to extract pricing information
                pricing_info = self._extract_pricing_with_ai(response_content)
                
                # Update inquiry lines with supplier pricing
                for line in inquiry.product_lines:
                    if not line.is_sufficient:
                        # Try to match product and update pricing
                        for product_price in pricing_info.get('products', []):
                            if (line.product_name and product_price.get('name', '').lower() in line.product_name.lower()) or \
                               (line.product_code and product_price.get('code', '') == line.product_code):
                                line.write({
                                    'supplier_id': supplier.supplier_id.id,
                                    'supplier_price': product_price.get('price', 0),
                                    'markup_percentage': config.get_param('ai_sales_support.default_markup_percentage', 20.0)
                                })
                                line.get_product_price()
                                break
                
                # Generate final quotation
                response = self._generate_quotation_response(inquiry)
                inquiry.write({
                    'ai_response': response,
                    'state': 'quotation_ready'
                })
                
            except Exception as e:
                _logger.error(f"Error processing supplier response with AI: {str(e)}")
        
        # Update supplier statistics
        supplier.update_communication_stats(success=True)

    def _extract_pricing_with_ai(self, response_content):
        """
        Extract pricing information from supplier response using AI
        """
        config = self.env['ir.config_parameter'].sudo()
        api_key = config.get_param('ai_sales_support.chatgpt_api_key')
        
        prompt = f"""
Trích xuất thông tin giá từ phản hồi của nhà cung cấp sau:

"{response_content}"

Vui lòng trả về thông tin dưới dạng JSON:
{{
    "products": [
        {{
            "name": "Tên sản phẩm",
            "code": "Mã sản phẩm",
            "price": giá_số,
            "unit": "đơn vị",
            "delivery_time": "thời gian giao hàng",
            "notes": "ghi chú"
        }}
    ],
    "general_notes": "ghi chú chung"
}}
        """
        
        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        }
        
        data = {
            'model': config.get_param('ai_sales_support.chatgpt_model', 'gpt-3.5-turbo'),
            'messages': [
                {'role': 'user', 'content': prompt}
            ],
            'max_tokens': 500,
            'temperature': 0.3
        }
        
        response = requests.post(
            'https://api.openai.com/v1/chat/completions',
            headers=headers,
            json=data,
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()
            ai_response = result['choices'][0]['message']['content']
            try:
                return json.loads(ai_response)
            except json.JSONDecodeError:
                return {'products': [], 'general_notes': ai_response}
        
        return {'products': [], 'general_notes': response_content}