# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import json
import logging
from markupsafe import Markup

_logger = logging.getLogger(__name__)

class ZaloChatEvaluation(models.Model):
    _name = 'zalo.chat.evaluation'
    _description = 'Đánh giá hội thoại Zalo'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string='Mã phiếu', default='New', readonly=True, copy=False)
    partner_id = fields.Many2one('res.partner', string='Khách hàng', required=True, tracking=True)
    conversation_id = fields.Many2one('zalo.chat.conversation', string='Hội thoại nguồn', readonly=True)
    livechat_channel_id = fields.Many2one('discuss.channel', string='Kênh Chat', readonly=True)
    
    chat_content = fields.Text(string='Nội dung hội thoại', help="Nội dung chat được dùng để phân tích")
    
    # AI Analysis Result
    gpt_summary = fields.Html(string='Tóm tắt nội dung', tracking=True)
    gpt_sentiment = fields.Selection([
        ('positive', '😊 Tích cực'),
        ('neutral', '😐 Trung tính'),
        ('negative', '😡 Tiêu cực'),
    ], string='Thái độ khách hàng', tracking=True)
    
    gpt_issues = fields.Html(string='Nhu cầu / Vấn đề', tracking=True)
    
    gpt_suggestion = fields.Selection([
        ('none', 'Không có'),
        ('create_quote', 'Tạo Báo Giá'),
        ('escalate', 'Chuyển cấp trên (Khiếu nại)'),
        ('follow_up', 'Cần chăm sóc thêm'),
    ], string='Đề xuất hành động', tracking=True)
    
    sale_order_id = fields.Many2one('sale.order', string='Báo giá đã tạo', readonly=True)
    
    state = fields.Selection([
        ('draft', 'Mới'),
        ('analyzed', 'Đã phân tích'),
    ], default='draft', string='Trạng thái', tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('zalo.chat.evaluation') or 'New'
        return super(ZaloChatEvaluation, self).create(vals_list)

    def action_analyze_gpt(self):
        """Analyze chat content using GPT"""
        self.ensure_one()
        
        if not self.chat_content:
             raise UserError(_("Không có nội dung chat để phân tích."))
             
        # Get Config
        config = self.env['zalo.oa.config'].sudo().search([('active', '=', True)], limit=1)
        if not config or not config.gpt_api_key:
             raise UserError(_("Vui lòng cấu hình GPT API Key trong Zalo OA."))
             
        prompt = [
            {"role": "system", "content": """Bạn là chuyên gia QC (Quality Control) chăm sóc khách hàng.
Hãy phân tích đoạn chat dưới đây và trả về kế quả dưới dạng JSON CHUẨN.
Cấu trúc JSON:
{
  "summary": "Tóm tắt ngắn gọn cuộc hội thoại (HTML format)",
  "sentiment": "positive" | "neutral" | "negative",
  "issues": "Liệt kê các nhu cầu hoặc vấn đề của khách hàng (HTML bullets)",
  "suggestion": "create_quote" | "escalate" | "follow_up" | "none"
}
Lưu ý logic suggestion:
- create_quote: Nếu khách hàng hỏi giá, chốt đơn, hoặc muốn mua hàng.
- escalate: Nếu khách hàng phàn nàn, giận dữ.
- follow_up: Nếu khách hàng đang hỏi thông tin nhưng chưa chốt.
- none: Chat xã giao.
"""},
            {"role": "user", "content": self.chat_content}
        ]
        
        try:
            response_content = config._get_gpt_response(prompt)
            # Cleanup Markdown
            if "```json" in response_content:
                response_content = response_content.split("```json")[1].split("```")[0].strip()
            elif "```" in response_content:
                response_content = response_content.split("```")[1].split("```")[0].strip()
                
            data = json.loads(response_content)
            
            self.write({
                'gpt_summary': data.get('summary'),
                'gpt_sentiment': data.get('sentiment'),
                'gpt_issues': data.get('issues'),
                'gpt_suggestion': data.get('suggestion', 'none'),
                'state': 'analyzed'
            })
            
            # Post log
            self.message_post(body="✅ Đã hoàn thành phân tích bởi GPT.")
            
        except Exception as e:
            _logger.exception("GPT Analysis Failed")
            raise UserError(_(f"Lỗi phân tích GPT: {str(e)}"))

    def action_create_quote(self):
        """Create Quote based on analysis"""
        self.ensure_one()
        # This will call the existing Quote Creation logic but we might need to parse chat again 
        # OR we can improve logic to use the analysis result.
        # Ideally, we call action_gpt_create_quote from generic method but passing content.
        # But action_gpt_create_quote relies on message history in 'discuss.channel'.
        
        # If we have livechat_channel_id, we can delegate?
        if self.livechat_channel_id:
            # We call the channel method directly?
            # But the channel method uses self.message_ids.
            # Does this evaluation record update channel messages? No.
            # So we should call the channel's method.
            return self.livechat_channel_id.action_gpt_create_quote()
        else:
             raise UserError(_("Không tìm thấy kênh chat gốc để tạo báo giá."))
