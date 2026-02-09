# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
import logging

_logger = logging.getLogger(__name__)

class ZaloCustomerProfile(models.Model):
    _name = 'zalo.customer.profile'
    _description = 'Zalo Customer Profile'
    _rec_name = 'partner_id'

    partner_id = fields.Many2one('res.partner', string='Khách hàng', required=True, index=True)
    
    # Smart Summaries
    summary_cumulative = fields.Text(string='Tóm tắt tổng hợp (AI)', 
        help="AI sẽ tự động cập nhật nội dung này dựa trên các phiên đánh giá mới nhất.")
    
    tag_ids = fields.Many2many('zalo.customer.tag', string='Thẻ phân loại',
        help="Thẻ tự động được gắn bởi AI hoặc thủ công.")

    # Relationships
    evaluation_ids = fields.One2many('zalo.chat.evaluation', 'profile_id', string='Lịch sử đánh giá')
    evaluation_count = fields.Integer(string='Số lượng phiếu', compute='_compute_evaluation_count')
    
    # Display fields for Kanban
    display_tag_ids = fields.Many2many('zalo.customer.tag', compute='_compute_display_tags')

    _sql_constraints = [
        ('partner_unique', 'unique(partner_id)', 'Mỗi khách hàng chỉ được có một Hồ sơ Zalo Profile!'),
    ]

    @api.depends('evaluation_ids')
    def _compute_evaluation_count(self):
        for record in self:
            record.evaluation_count = len(record.evaluation_ids)

    @api.depends('tag_ids')
    def _compute_display_tags(self):
        for record in self:
            record.display_tag_ids = record.tag_ids[:5] # Show top 5 tags

    def action_update_summary_ai(self, new_evaluation_content, config):
        """
        AI Logic: Update cumulative summary and tags based on new evaluation content.
        This method is called from zalo.chat.evaluation when a new analysis completes.
        """
        self.ensure_one()
        
        # Construct Prompt
        existing_summary = self.summary_cumulative or "Chưa có thông tin."
        existing_tags = ", ".join(self.tag_ids.mapped('name'))
        
        prompt = [
            {"role": "system", "content": """Bạn là trợ lý AI quản lý hồ sơ khách hàng (Customer Profile Manager). 
Nhiệm vụ của bạn là cập nhật "Tóm tắt tổng hợp" và "Thẻ phân loại" cho khách hàng dựa trên phiên hội thoại mới nhất.

QUY TẮC CẬP NHẬT TÓM TẮT:
1. Giữ lại các thông tin quan trọng trong quá khứ.
2. Bổ sung thông tin mới từ phiên hội thoại hiện tại.
3. QUAN TRỌNG: Phải trích xuất THỜI GIAN và TRẠNG THÁI xử lý.
   - Ví dụ: "Ngày 10/10 14:00: Khách hỏi giá FPD3 -> 14:15: Nhân viên đã báo giá -> Chờ khách chốt."
   - Ghi rõ những việc ĐANG CHỜ (Pending) để nhân viên follow.
4. Viết ngắn gọn, súc tích, trình bày theo dạng Timeline nếu có nhiều sự kiện.

QUY TẮC CẬP NHẬT THẺ (TAGS):
1. Xác định VAI TRÒ: [Khách lẻ, NCC, Đại lý, CTV].
2. Xác định THƯƠNG HIỆU quan tâm: [Bosch, Makita, Milwaukee, ...].
3. Xác định NHU CẦU hiện tại: [Mua hàng, Bảo hành, Hỏi giá, Khiếu nại].
4. Trả về danh sách thẻ, bao gồm cả thẻ cũ (nếu còn đúng) và thẻ mới.

OUTPUT FORMAT (JSON):
{
    "updated_summary": "...",
    "tags": ["Khách lẻ", "Bosch", "Mua hàng"]
}
"""},
            {"role": "user", "content": f"""
HỒ SƠ HIỆN TẠI:
- Tóm tắt cũ: {existing_summary}
- Thẻ cũ: [{existing_tags}]

THÔNG TIN MỚI (Phiên đánh giá vừa xong):
"{new_evaluation_content}"

Hãy cập nhật hồ sơ khách hàng này."""}
        ]

        try:
            response = config._get_gpt_response(prompt, json_mode=True)
            import json
            data = json.loads(response)
            
            updated_summary = data.get('updated_summary')
            new_tags_list = data.get('tags', [])
            
            # Update Summary
            if updated_summary:
                self.summary_cumulative = updated_summary
                
            # Update Tags
            TagModel = self.env['zalo.customer.tag']
            tag_ids = []
            for tag_name in new_tags_list:
                # Find or Create Tag (Case insensitive search)
                tag = TagModel.search([('name', '=ilike', tag_name)], limit=1)
                if not tag:
                    # AI might infer category, but for now default to 'other' or simple logic
                    category = 'other'
                    if tag_name in ['Khách lẻ', 'NCC', 'Đại lý', 'CTV']:
                        category = 'role'
                    elif any(brand in tag_name for brand in ['Bosch', 'Makita', 'Milwaukee']):
                        category = 'brand'
                    elif tag_name in ['Mua hàng', 'Bảo hành', 'Hỏi giá', 'Khiếu nại']:
                        category = 'need'
                        
                    tag = TagModel.create({'name': tag_name, 'category': category})
                tag_ids.append(tag.id)
            
            if tag_ids:
                self.tag_ids = [(6, 0, tag_ids)]
                
            _logger.info(f"Updated Profile for Partner {self.partner_id.name}: Summary len={len(updated_summary)}, Tags={new_tags_list}")
            
        except Exception as e:
            _logger.error(f"Failed to update Customer Profile AI: {e}")
