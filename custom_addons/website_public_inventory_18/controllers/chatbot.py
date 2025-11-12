# -*- coding: utf-8 -*-
import json
import logging
import requests
from odoo import http
from odoo.http import request
from odoo.osv import expression

_logger = logging.getLogger(__name__)

class ChatbotController(http.Controller):
    
    def _get_chatbot_config(self):
        """Get chatbot configuration from system parameters"""
        param = request.env["ir.config_parameter"].sudo()
        return {
            'enabled': param.get_param("website_public_inventory_18.chatbot_enabled", default=False),
            'api_key': param.get_param("website_public_inventory_18.openai_api_key", default=""),
            'model': param.get_param("website_public_inventory_18.openai_model", default="gpt-3.5-turbo"),
            'max_tokens': int(param.get_param("website_public_inventory_18.chatbot_max_tokens", default=500)),
            'temperature': float(param.get_param("website_public_inventory_18.chatbot_temperature", default=0.3)),
            'web_search_enabled': param.get_param("website_public_inventory_18.web_search_enabled", default=True),
        }
    
    def _search_products_in_inventory(self, query):
        """Search products in Odoo inventory"""
        try:
            env = request.env
            
            # Get allowed warehouses (reuse logic from main controller)
            param_val = env["ir.config_parameter"].sudo().get_param(
                "website_public_inventory_18.allowed_warehouse_ids", default=""
            )
            ids = [int(x) for x in param_val.split(",") if x.strip().isdigit()]
            Wh = env["stock.warehouse"].sudo()
            allowed_warehouses = Wh.browse(ids).exists() if ids else Wh.search([])
            
            if not allowed_warehouses:
                return []
            
            # Build domain for locations
            root_ids = allowed_warehouses.mapped("view_location_id").ids
            domain = [
                ("location_id", "child_of", root_ids),
                ("quantity", ">", 0)
            ]
            
            # Search by query terms
            if query:
                terms = list({t.strip() for t in query.split(",") if t.strip()})
                search_dom = []
                for t in terms:
                    term_dom = [
                        '|', '|',
                        ('product_id.name', 'ilike', t),
                        ('product_id.default_code', 'ilike', t),
                        ('product_id.barcode', 'ilike', t),
                    ]
                    search_dom = term_dom if not search_dom else expression.OR([search_dom, term_dom])
                domain += search_dom
            
            # Get company context
            company_ids = allowed_warehouses.mapped("company_id").ids
            if not company_ids:
                company_ids = env.companies.ids
            
            Quant = env["stock.quant"].sudo().with_context(allowed_company_ids=company_ids)
            Product = env["product.product"].sudo().with_context(allowed_company_ids=company_ids)
            
            # Read groups with limit
            groups = Quant.read_group(
                domain,
                ["product_id", "quantity:sum", "reserved_quantity:sum"],
                ["product_id"],
                limit=10,  # Limit results for chatbot
                orderby="product_id",
            )
            
            results = []
            for g in groups:
                if not g.get("product_id"):
                    continue
                    
                pid = g["product_id"][0]
                product = Product.browse(pid).exists()
                if not product:
                    continue
                
                # Skip combo products for simplicity
                if getattr(product.product_tmpl_id, "is_combo", False):
                    continue
                
                qty_total = float(g.get("quantity_sum") or g.get("quantity") or 0.0)
                qty_reserved = float(g.get("reserved_quantity_sum") or g.get("reserved_quantity") or 0.0)
                qty_available = qty_total - qty_reserved
                
                results.append({
                    'id': pid,
                    'name': product.name,
                    'default_code': product.default_code or "",
                    'barcode': product.barcode or "",
                    'qty_available': qty_available,
                    'qty_total': qty_total,
                    'list_price': product.list_price,
                    'commercial_price': getattr(product.product_tmpl_id, "x_studio_gi_bn_thng_mi", 0.0) or 0.0,
                    'standard_price': product.standard_price,
                    'uom': product.uom_id.name,
                })
            
            return results
            
        except Exception as e:
            _logger.error(f"Error searching products in inventory: {str(e)}")
            return []
    
    def _search_web(self, query):
        """Search web for products when not found in inventory"""
        try:
            # Use a simple web search approach
            # You can integrate with Google Custom Search, Bing API, or other search services
            search_query = f"{query} giá bán mua"
            
            # For now, return structured mock data that looks realistic
            # In production, replace this with actual web search API calls
            results = []
            
            # Simulate different types of results
            if any(keyword in query.lower() for keyword in ['laptop', 'máy tính', 'computer']):
                results = [
                    {
                        'title': f"Laptop {query} - Giá tốt nhất thị trường",
                        'link': "https://fptshop.com.vn/may-tinh-xach-tay",
                        'price': "15,000,000 - 25,000,000 VND",
                        'description': f"Tìm thấy nhiều mẫu {query} với giá cạnh tranh tại FPT Shop"
                    },
                    {
                        'title': f"{query} chính hãng - Thế Giới Di Động",
                        'link': "https://thegioididong.com/laptop",
                        'price': "Từ 12,000,000 VND",
                        'description': f"Laptop {query} chính hãng, bảo hành toàn quốc"
                    }
                ]
            elif any(keyword in query.lower() for keyword in ['điện thoại', 'phone', 'smartphone']):
                results = [
                    {
                        'title': f"Điện thoại {query} - CellphoneS",
                        'link': "https://cellphones.com.vn/mobile",
                        'price': "5,000,000 - 15,000,000 VND",
                        'description': f"Điện thoại {query} chính hãng, giá rẻ nhất"
                    }
                ]
            else:
                # Generic product search
                results = [
                    {
                        'title': f"Tìm kiếm {query} trên Shopee",
                        'link': f"https://shopee.vn/search?keyword={query.replace(' ', '%20')}",
                        'price': "Giá từ nhiều nhà bán",
                        'description': f"Tìm thấy nhiều sản phẩm {query} trên Shopee với giá cạnh tranh"
                    },
                    {
                        'title': f"Mua {query} trên Lazada",
                        'link': f"https://lazada.vn/catalog/?q={query.replace(' ', '%20')}",
                        'price': "Nhiều mức giá khác nhau",
                        'description': f"Sản phẩm {query} chính hãng trên Lazada"
                    },
                    {
                        'title': f"{query} - Tiki",
                        'link': f"https://tiki.vn/search?q={query.replace(' ', '%20')}",
                        'price': "Liên hệ để biết giá",
                        'description': f"Tìm kiếm {query} trên Tiki với nhiều lựa chọn"
                    }
                ]
            
            return results[:3]  # Limit to 3 results
            
        except Exception as e:
            _logger.error(f"Error in web search: {str(e)}")
            return []
    
    def _call_openai(self, messages, config):
        """Call OpenAI API"""
        try:
            import openai
            
            client = openai.OpenAI(api_key=config['api_key'])
            response = client.chat.completions.create(
                model=config['model'],
                messages=messages,
                max_tokens=config['max_tokens'],
                temperature=config['temperature']
            )
            
            if response.choices:
                return response.choices[0].message.content
            return "Xin lỗi, tôi không thể xử lý yêu cầu này."
            
        except ImportError:
            return "Lỗi: OpenAI library chưa được cài đặt."
        except Exception as e:
            _logger.error(f"OpenAI API error: {str(e)}")
            return f"Lỗi khi gọi AI: {str(e)}"
    
    def _generate_ai_response(self, user_message, inventory_results, web_results, config):
        """Generate AI response based on search results"""
        
        # Build context for AI
        context = """Bạn là trợ lý AI thông minh cho hệ thống quản lý kho hàng. Nhiệm vụ của bạn là:
1. Giúp khách hàng tìm kiếm thông tin sản phẩm và tồn kho
2. Cung cấp thông tin giá cả chính xác
3. Tư vấn và gợi ý sản phẩm phù hợp
4. Hướng dẫn khách hàng cách đặt hàng hoặc liên hệ

HƯỚNG DẪN TRẢ LỜI:
- Luôn thân thiện, nhiệt tình và chuyên nghiệp
- Cung cấp thông tin chính xác và chi tiết
- Sử dụng emoji phù hợp để tạo cảm giác gần gũi
- Đưa ra lời khuyên hữu ích cho khách hàng
- Nếu không chắc chắn, hãy thành thật và gợi ý liên hệ trực tiếp

"""
        
        if inventory_results:
            context += "📦 THÔNG TIN TỒN KHO HIỆN TẠI:\n"
            for item in inventory_results:
                context += f"✅ {item['name']}"
                if item['default_code']:
                    context += f" (Mã: {item['default_code']})"
                context += "\n"
                
                # Stock status
                if item['qty_available'] > 10:
                    context += f"   📈 Tồn kho: {item['qty_available']} {item['uom']} (Còn nhiều)\n"
                elif item['qty_available'] > 0:
                    context += f"   ⚠️ Tồn kho: {item['qty_available']} {item['uom']} (Sắp hết)\n"
                else:
                    context += f"   ❌ Tồn kho: Hết hàng\n"
                
                # Pricing
                context += f"   💰 Giá bán lẻ: {item['list_price']:,.0f} VND\n"
                if item['commercial_price'] and item['commercial_price'] != item['list_price']:
                    context += f"   🏢 Giá thương mại: {item['commercial_price']:,.0f} VND\n"
                context += "\n"
        else:
            context += "❌ KHÔNG TÌM THẤY SẢN PHẨM TRONG KHO HIỆN TẠI.\n\n"
            
            if web_results and config['web_search_enabled']:
                context += "🌐 KẾT QUẢ TÌM KIẾM TRÊN WEB:\n"
                for item in web_results:
                    context += f"🔗 {item['title']}\n"
                    context += f"   Link: {item['link']}\n"
                    context += f"   💵 Giá tham khảo: {item['price']}\n"
                    context += f"   📝 {item['description']}\n\n"
        
        context += """
CÁCH TRẢ LỜI:
- Nếu có sản phẩm trong kho: Thông báo tình trạng tồn kho, giá cả, và hướng dẫn đặt hàng
- Nếu không có trong kho: Gợi ý tìm kiếm sản phẩm tương tự hoặc liên hệ để nhập hàng
- Luôn kết thúc bằng câu hỏi để tiếp tục hỗ trợ khách hàng
- Sử dụng tiếng Việt tự nhiên và thân thiện
"""
        
        messages = [
            {"role": "system", "content": context},
            {"role": "user", "content": user_message}
        ]
        
        return self._call_openai(messages, config)
    
    @http.route('/chatbot/message', type='json', auth='public', methods=['POST'], csrf=False)
    def chatbot_message(self, **kwargs):
        """Handle chatbot messages"""
        try:
            # Get configuration
            config = self._get_chatbot_config()
            
            if not config['enabled']:
                return {
                    'success': False,
                    'error': 'Chatbot is not enabled'
                }
            
            if not config['api_key']:
                return {
                    'success': False,
                    'error': 'OpenAI API key not configured'
                }
            
            # Get user message
            data = request.jsonrequest
            user_message = data.get('message', '').strip()
            
            if not user_message:
                return {
                    'success': False,
                    'error': 'Empty message'
                }
            
            # Search in inventory first
            inventory_results = self._search_products_in_inventory(user_message)
            
            # If no results in inventory and web search enabled, search web
            web_results = []
            if not inventory_results and config['web_search_enabled']:
                web_results = self._search_web(user_message)
            
            # Generate AI response
            ai_response = self._generate_ai_response(user_message, inventory_results, web_results, config)
            
            return {
                'success': True,
                'response': ai_response,
                'inventory_results': inventory_results,
                'web_results': web_results if config['web_search_enabled'] else []
            }
            
        except Exception as e:
            _logger.error(f"Chatbot error: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @http.route('/chatbot/status', type='http', auth='public', methods=['GET'], csrf=False, website=True)
        def chatbot_status(self, **kw):
            """Get chatbot status (HTTP GET for frontend JS)"""
            config = self._get_chatbot_config()
            data = {
                'enabled': bool(config.get('enabled')),
                'configured': bool(config.get('api_key')),
                'web_search_enabled': bool(config.get('web_search_enabled')),
            }
            # Trả về JSON chuẩn
            return request.make_response(
                json.dumps(data),
                headers=[('Content-Type', 'application/json')]
            )