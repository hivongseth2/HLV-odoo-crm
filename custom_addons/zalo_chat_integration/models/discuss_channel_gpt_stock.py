from odoo import models, api, _, tools
from odoo.exceptions import UserError
import logging
from markupsafe import Markup

_logger = logging.getLogger(__name__)


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

    # -------------------------------------------------------------------------
    # GPT INTEGRATION (STOCK & SUMMARY)
    # -------------------------------------------------------------------------

    def action_gpt_summarize(self):
        """
        Summarize the livechat conversation using GPT
        """
        self.ensure_one()
        
        # Only applicable for livechat channels linked to Zalo OA
        if self.channel_type != 'livechat' or not self.livechat_channel_id:
             return
             
        # Find Zalo Config linked to this livechat channel
        config = self.env['zalo.oa.config'].sudo().search([('livechat_channel_id', '=', self.livechat_channel_id.id)], limit=1)
        
        if not config:
             raise UserError(_("Không tìm thấy cấu hình Zalo OA liên kết với kênh này."))
             
        if not config.gpt_api_key:
             raise UserError(_("Vui lòng cấu hình GPT API Key trong cài đặt Zalo OA."))
             
        # Fetch last 50 messages
        messages = self.message_ids.sorted(key=lambda m: m.date)[-50:]
        if not messages:
            raise UserError(_("Hội thoại chưa có tin nhắn nào để tóm tắt."))
            
        content_lines = []
        for msg in messages:
            # Simple sanitization
            body = tools.html2plaintext(msg.body) if msg.body else ''
            if not body: continue
            
            author_name = msg.author_id.name if msg.author_id else "Bot"
            content_lines.append(f"{author_name}: {body}")
        
        chat_content = "\n".join(content_lines)
        
        prompt = [
            {"role": "system", "content": "Bạn là trợ lý AI quản lý khách hàng (CRM). Hãy đọc đoạn hội thoại sau và tóm tắt ngắn gọn các ý chính:\n1. Nhu cầu/Vấn đề của khách hàng\n2. Thái độ khách hàng (Tích cực/Tiêu cực)\n3. Trạng thái hiện tại (Đã chốt/Đang tư vấn/Khiếu nại)\nTrả lời bằng tiếng Việt, ngắn gọn súc tích."},
            {"role": "user", "content": chat_content}
        ]
        
        try:
            summary = config._get_gpt_response(prompt)
            
            self.message_post(
                body=Markup(f"📝 **Tóm tắt nội dung (GPT):**\n{summary.replace(chr(10), '<br/>')}"),
                message_type='notification',
                subtype_xmlid='mail.mt_note'
            )
        except Exception as e:
            raise UserError(_(f"Lỗi khi gọi GPT: {str(e)}"))

    def action_gpt_check_stock(self):
        """
        AI infers product from chat and checks stock
        """
        self.ensure_one()
        
        config = self.env['zalo.oa.config'].sudo().search([('livechat_channel_id', '=', self.livechat_channel_id.id)], limit=1)
        if not config or not config.gpt_api_key:
             raise UserError(_("Vui lòng cấu hình GPT API Key."))
             
        # Fetch messages (Text + Images)
        gpt_messages = self._extract_chat_content_with_images(limit=30)
        
        system_prompt = {
            "role": "system", 
            "content": """Bạn là trợ lý kho hàng. Đọc đoạn hội thoại và xem hình ảnh (nếu có) để xác định sản phẩm khách hàng đang hỏi tồn kho GẦN NHẤT.
Quy tắc:
1. Chỉ trả về TÊN SẢN PHẨM (hoặc Mã) mà khách đang quan tâm nhất.
2. Nếu khách hỏi nhiều món, ưu tiên món hỏi sau cùng.
3. Nếu khách gửi ẢNH, hãy phân tích ảnh để xác định tên sản phẩm hoặc mã sản phẩm trên bao bì/nhãn mác.
4. Nếu không tìm thấy thông tin sản phẩm nào, trả về "NULL".
5. Không giải thích, chỉ trả về tên sản phẩm."""
        }
        
        # Combine system prompt with chat history
        prompt = [system_prompt] + gpt_messages
        
        try:
            product_query = config._get_gpt_response(prompt)
            product_query = product_query.strip().strip('"').strip("'")
            
            if product_query == "NULL" or not product_query:
                self.message_post(body="🤖 AI: Không tìm thấy tên sản phẩm nào trong đoạn chat gần đây để kiểm tra tồn kho.", message_type='notification', subtype_xmlid='mail.mt_note')
                return

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
                
            # Smart search using explicit method
            product = self._find_product_by_name_smart(product_query, chat_context_str, config)
            
            if product:
                # Get Stock Info
                qty_available = product.qty_available
                virtual_available = product.virtual_available
                
                # Format currency
                price = "{:,.0f}".format(product.lst_price)
                
                msg = f"""📦 **Kiểm tra tồn kho: {product.name}**
- Mã: {product.default_code}
- Giá niêm yết: {price} đ
- Tồn thực tế: **{qty_available}**
- Dự kiến (sau khi giữ hàng): {virtual_available}
"""
                self.message_post(body=Markup(msg), message_type='notification', subtype_xmlid='mail.mt_note')
            else:
                 self.message_post(body=f"🤖 AI: Đã tìm kiếm '{product_query}' nhưng không thấy sản phẩm nào khớp trong hệ thống.", message_type='notification', subtype_xmlid='mail.mt_note')

        except Exception as e:
            _logger.error(f"Stock Check Error: {e}")
            self.message_post(body=f"⚠️ Lỗi kiểm tra tồn: {str(e)}", message_type='notification', subtype_xmlid='mail.mt_note')
