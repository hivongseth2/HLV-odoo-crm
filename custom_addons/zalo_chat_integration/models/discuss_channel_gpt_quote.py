from odoo import models, api, _, tools
from odoo.exceptions import UserError
import logging
import json
from markupsafe import Markup

_logger = logging.getLogger(__name__)


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    # -------------------------------------------------------------------------
    # GPT INTEGRATION (QUOTES)
    # -------------------------------------------------------------------------

    def _execute_command_baogia(self, **kwargs):
        """
        Slash command /baogia to trigger GPT Quote Creation
        """
        self.action_gpt_create_quote()
        return True

    def _execute_command_baogialai(self, **kwargs):
        """
        Slash command /baogialai to trigger GPT Quote Update
        """
        self.action_gpt_update_quote()
        return True

    def action_gpt_create_quote(self):
        """
        Parse chat and create Draft Quotation (Sale Order)
        """
        self.ensure_one()
        
        config = self.env['zalo.oa.config'].sudo().search([('livechat_channel_id', '=', self.livechat_channel_id.id)], limit=1)
        if not config or not config.gpt_api_key:
             raise UserError(_("Vui lòng cấu hình GPT API Key."))
             
        # Fetch messages (Text + Images)
        gpt_messages = self._extract_chat_content_with_images(limit=50)
        
        system_prompt = {
            "role": "system", 
            "content": """Bạn là trợ lý ảo tạo đơn hàng (Sale Order Creator). 
Nhiệm vụ: Trích xuất sản phẩm khách muốn mua TỪ CÁC TIN NHẮN MỚI NHẤT chưa được xử lý.

QUY TẮC XỬ LÝ LỊCH SỬ (QUAN TRỌNG):
1. Dựa vào thời gian (Timestamp) trong tin nhắn. Tìm mốc "System: Đã tạo báo giá..." hoặc "AI Tạo Báo Giá" gần nhất.
2. CHỈ TRÍCH XUẤT yêu cầu MỚI sau mốc đó.
3. Nếu khách gửi ẢNH, hãy phân tích ảnh để xác định sản phẩm họ muốn mua.

QUY TẮC GIÁ & SẢN PHẨM:
1. Trích xuất chính xác Tên sản phẩm, Số lượng.
2. QUAN TRỌNG: Nếu trong hội thoại có NHẮC ĐẾN GIÁ (ví dụ: "giá 50k nhé", "chốt 3tr", "bán cho em giá cũ 120k"), BẮT BUỘC phải lấy giá đó vào `price_unit`.
3. Nếu không nhắc giá hoặc chỉ hỏi giá -> để `price_unit` = 0 (để hệ thống tự lấy bảng giá).

CẤU TRÚC JSON TRẢ VỀ:
{
  "products": [
    {"name": "tên sản phẩm", "quantity": 1, "price_unit": 0, "note": ""}
  ],
  "note": "Ghi chú chung (đặc biệt là về giá nếu có deal)"
}
Nếu không có yêu cầu mới: {"products": []}
"""
        }
        
        # Combine system prompt with chat history
        prompt = [system_prompt] + gpt_messages
        
        try:
            response_content = config._get_gpt_response(prompt, json_mode=True)
            
            data = json.loads(response_content)
            products_data = data.get('products', [])
            
            if not products_data:
                # Post a ephemeral notification or just log
                self.message_post(body="🤖 AI: Không tìm thấy yêu cầu mua hàng mới nào cần tạo báo giá (Các yêu cầu cũ đã được xử lý).", message_type='notification', subtype_xmlid='mail.mt_note')
                return
                
            customer = False
            for partner in self.channel_partner_ids:
                if partner.id != self.env.user.partner_id.id and not partner.user_ids: # Likely the customer
                    customer = partner
                    break
            
            if not customer:
                 partners = self.channel_partner_ids.filtered(lambda p: p.id != self.env.user.partner_id.id)
                 if partners:
                     customer = partners[0]
                 else:
                     raise UserError(_("Không xác định được khách hàng trong kênh chat."))
            
            order_lines = []
            Product = self.env['product.product']
            not_found_products = []
            
            # Need strict string for smart search, but here we used `_extract_chat_content_with_images`.
            # `_find_product_by_name_smart` expects `chat_context` as a string for disambiguation prompt.
            # We can reconstruct a simple string context from `gpt_messages` if needed, or pass the complex structure if `_find_product_by_name_smart` handled it.
            # But `_find_product_by_name_smart` currently does:
            # `{"role": "user", "content": f"... Chat Context: '''{chat_context}''' ..."}`
            # It expects a string.
            # I should provide a string representation of the chat for disambiguation context.
            chat_context_str = ""
            for m in gpt_messages:
                 role = m['role']
                 content = m['content']
                 if isinstance(content, list):
                     text_parts = [c['text'] for c in content if c['type'] == 'text']
                     chat_context_str += f"{role}: {' '.join(text_parts)}\n"
                 else:
                     chat_context_str += f"{role}: {content}\n"

            for item in products_data:
                p_name = item.get('name')
                qty = item.get('quantity', 1)
                note = item.get('note', '')
                price_unit = item.get('price_unit', 0)
                
                # Use Smart Search
                product = self._find_product_by_name_smart(p_name, chat_context_str, config)
                
                if product:
                    line_vals = {
                        'product_id': product.id,
                        'product_uom_qty': qty,
                        'name': product.name + (f" ({note})" if note else ""),
                    }
                    # Apply custom price if detected
                    if price_unit > 0:
                        line_vals['price_unit'] = price_unit
                        
                    order_lines.append((0, 0, line_vals))
                else:
                    not_found_products.append(p_name)
                    order_lines.append((0, 0, {
                        'display_type': 'line_note',
                        'name': f"Sản phẩm chưa tìm thấy mã: {p_name} (SL: {qty}) - Giá: {price_unit if price_unit > 0 else 'Theo bảng giá'}",
                    }))

            vals = {
                'partner_id': customer.id,
                'order_line': order_lines,
                'note': f"Được tạo tự động từ Zalo Chat. Ghi chú: {data.get('note', '')}",
                'origin': f"Zalo Chat {self.name}",
            }
            
            sale_order = self.env['sale.order'].create(vals)
            
            # Post as plain notification
            link = Markup(f'<a href="#" data-oe-model="sale.order" data-oe-id="{sale_order.id}">{sale_order.name}</a>')
            self.message_post(
                body=Markup(f"✅ Đã tạo báo giá: {link}<br/>(Ghi chú: {data.get('note', 'Không')})"),
                message_type='notification',
                subtype_xmlid='mail.mt_note'
            )
            
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'sale.order',
                'res_id': sale_order.id,
                'view_mode': 'form',
                'target': 'current',
            }
            
        except json.JSONDecodeError:
            raise UserError(_("Lỗi phân tích dữ liệu từ GPT. (Invalid JSON)"))
        except Exception as e:
            _logger.exception("GPT Create Quote Failed")
            raise UserError(_(f"Lỗi tạo báo giá: {str(e)}"))

    def action_gpt_update_quote(self):
        """
        Update the LATEST Draft Quotation based on chat
        """
        self.ensure_one()
        
        # 1. Find Customer
        customer = False
        for partner in self.channel_partner_ids:
            if partner.id != self.env.user.partner_id.id and not partner.user_ids:
                customer = partner
                break
        
        if not customer:
             partners = self.channel_partner_ids.filtered(lambda p: p.id != self.env.user.partner_id.id)
             if partners: customer = partners[0]
             
        if not customer:
             raise UserError(_("Không xác định được khách hàng."))

        # 2. Find Latest Draft Order
        last_order = self.env['sale.order'].search([
            ('partner_id', '=', customer.id),
            ('state', 'in', ['draft', 'sent']),
            ('company_id', '=', self.env.company.id)
        ], order='date_order desc', limit=1)
        
        if not last_order:
            # Fallback to create new
            self.message_post(body="🤖 AI: Không tìm thấy báo giá nháp nào để cập nhật. Đang tạo mới...", message_type='notification', subtype_xmlid='mail.mt_note')
            self.action_gpt_create_quote()
            return

        config = self.env['zalo.oa.config'].sudo().search([('livechat_channel_id', '=', self.livechat_channel_id.id)], limit=1)
        if not config or not config.gpt_api_key:
             raise UserError(_("Vui lòng cấu hình GPT API Key."))

        # 3. Fetch Chat History (With Images)
        gpt_messages = self._extract_chat_content_with_images(limit=20)
        
        # 4. Construct System Prompt
        current_order_info = f"Current Quotation #{last_order.name}:\n"
        for line in last_order.order_line:
            current_order_info += f"- {line.product_id.name} (Qty: {line.product_uom_qty}, Price: {line.price_unit})\n"
            
        system_prompt = {
            "role": "system", 
            "content": f"""Bạn là trợ lý cập nhật đơn hàng.
Nhiệm vụ: Dựa vào lịch sử chat VÀ thông tin đơn hàng hiện tại, hãy xác định các thay đổi cần thực hiện.

ĐƠN HÀNG HIỆN TẠI:
{current_order_info}

QUY TẮC:
1. Xác định khách muốn THÊM, SỬA (số lượng/giá), hay XÓA sản phẩm nào.
2. Nếu khách gửi ẢNH, hãy phân tích ảnh để xác định sản phẩm họ muốn thêm/đổi.
3. Nếu không có yêu cầu thay đổi rõ ràng, trả về danh sách rỗng.

OUTPUT JSON FORMAT:
{{
  "actions": [
    {{
      "action": "add" | "update" | "remove",
      "product_name": "tên sản phẩm (tìm kiếm)",
      "quantity": 1,
      "price_unit": 0, # 0 nếu giữ nguyên hoặc lấy theo bảng giá
      "note": "lý do hoặc ghi chú"
    }}
  ],
  "message": "Nội dung trả lời khách hàng ngắn gọn về việc đã làm"
}}
"""
        }
        
        # Insert system prompt at the beginning
        gpt_messages.insert(0, system_prompt)
        
        try:
            response_content = config._get_gpt_response(gpt_messages, json_mode=True)
            data = json.loads(response_content)
            actions = data.get('actions', [])
            reply_msg = data.get('message', '')
            
            if not actions:
                self.message_post(body=f"🤖 AI: Không phát hiện yêu cầu thay đổi nào. ({reply_msg})", message_type='notification', subtype_xmlid='mail.mt_note')
                return
            
            Product = self.env['product.product']
            changes_log = []
            
            # Context string for disambiguation
            chat_context_str = ""
            for m in gpt_messages:
                 if m['role'] == 'system': continue
                 content = m['content']
                 if isinstance(content, list):
                     text_parts = [c['text'] for c in content if c['type'] == 'text']
                     chat_context_str += f"{m['role']}: {' '.join(text_parts)}\n"
                 else:
                     chat_context_str += f"{m['role']}: {content}\n"

            for act in actions:
                action_type = act.get('action')
                p_query = act.get('product_name')
                qty = act.get('quantity', 1)
                price = act.get('price_unit', 0)
                
                # Identify Product
                product = self._find_product_by_name_smart(p_query, chat_context_str, config)
                
                if not product and action_type in ['add', 'update']:
                    changes_log.append(f"⚠️ Không tìm thấy SP '{p_query}' để {action_type}")
                    continue
                    
                if action_type == 'add':
                    existing_line = last_order.order_line.filtered(lambda l: l.product_id.id == product.id)
                    if existing_line:
                        existing_line.product_uom_qty += qty
                        changes_log.append(f"Cộng thêm {qty} {product.name}")
                    else:
                        vals = {
                            'order_id': last_order.id,
                            'product_id': product.id,
                            'product_uom_qty': qty,
                        }
                        if price > 0: vals['price_unit'] = price
                        self.env['sale.order.line'].create(vals)
                        changes_log.append(f"Thêm mới {qty} {product.name}")
                        
                elif action_type == 'update':
                    line = last_order.order_line.filtered(lambda l: l.product_id.id == product.id)
                    if line:
                        line.product_uom_qty = qty
                        if price > 0: line.price_unit = price
                        changes_log.append(f"Cập nhật {product.name}: SL={qty}, Giá={price}")
                    else:
                        changes_log.append(f"⚠️ Không tìm thấy {product.name} trong đơn để cập nhật")
                        
                elif action_type == 'remove':
                    line = last_order.order_line.filtered(lambda l: l.product_id.id == product.id)
                    if line:
                        line.unlink()
                        changes_log.append(f"Đã xóa {product.name}")
            
            if changes_log:
                link = Markup(f'<a href="#" data-oe-model="sale.order" data-oe-id="{last_order.id}">{last_order.name}</a>')
                log_html = f"✅ Đã cập nhật báo giá {link}:<br/>" + "<br/>".join(changes_log)
                self.message_post(body=Markup(log_html), message_type='notification', subtype_xmlid='mail.mt_note')
            
        except Exception as e:
            _logger.exception("GPT Update Quote Failed")
            self.message_post(body=f"⚠️ Lỗi cập nhật báo giá: {str(e)}", message_type='notification', subtype_xmlid='mail.mt_note')
