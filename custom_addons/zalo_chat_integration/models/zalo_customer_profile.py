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
    summary_cumulative = fields.Html(string='Tóm tắt tổng hợp (AI)', 
        help="AI sẽ tự động cập nhật nội dung này dựa trên các phiên đánh giá mới nhất.",
        sanitize=False) # Disable sanitize to allow custom classes/styles if needed
    
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
            {"role": "system", "content": """Bạn là trợ lý AI quản lý hồ sơ khách hàng (CRM). 
Nhiệm vụ: Cập nhật \"Tóm tắt tổng hợp\" và \"Thẻ phân loại\" cho khách hàng.

OUTPUT FORMAT: JSON
{
    "updated_summary_html": "HTML Code",
    "tags": ["Tag1", "Tag2"]
}

QUY TẮC GẮN TAG:
- Luôn xác định vai trò: \"Khách hàng\" hoặc \"NCC\" (nhà cung cấp).
- Nếu khách đang chào bán/đề xuất cung ứng/hỏi mua vào từ phía mình → gắn tag \"NCC\".
- Nếu khách hỏi giá/mua hàng/đặt hàng → gắn tag \"Khách hàng\".
- Có thể gắn thêm tag theo hãng (Bosch/Makita/Milwaukee...) và nhu cầu (Hỏi giá/Mua hàng/...)

YÊU CẦU VỀ HTML TIMELINE:
- Trả về 1 danh sách `ul` với class=\"zalo-timeline\".
- Mỗi sự kiện là 1 `li` với class=\"zalo-timeline-item\".
- Bên trong `li` có:
  - `span.time`: Thời gian (VD: 10/10 14:00)
  - `span.content`: Nội dung tóm tắt
  - `span.status`: Trạng thái (VD: Chờ xử lý, Đã xong) - dùng class badge nếu cần.
- Sắp xếp thời gian từ MỚI NHẤT lên đầu.
- Giữ lại các sự kiện cũ quan trọng, merge với sự kiện mới.

VÍ DỤ HTML:
<ul class=\"zalo-timeline\">
  <li class=\"zalo-timeline-item\">
    <span class=\"time\">Hôm nay 10:00</span>
    <span class=\"content\">Khách hỏi mua FPD3</span>
    <span class=\"status badge badge-warning\">Đang chờ</span>
  </li>
  <li class=\"zalo-timeline-item\">
    <span class=\"time\">Hôm qua 15:30</span>
    <span class=\"content\">Đã chốt đơn hàng cũ</span>
    <span class=\"status badge badge-success\">Hoàn thành</span>
  </li>
</ul>
"""},
            {"role": "user", "content": f"""
HỒ SƠ HIỆN TẠI (HTML cũ):
{existing_summary}

TAGS CŨ: [{existing_tags}]

THÔNG TIN MỚI (Vừa chat xong):
"{new_evaluation_content}"

Hãy cập nhật timeline và tags.
"""}
        ]

        try:
            response = config._get_gpt_response(prompt, json_mode=True)
            import json
            data = json.loads(response)
            
            updated_summary = data.get('updated_summary_html') or data.get('updated_summary')
            new_tags_list = data.get('tags', [])
            
            # Update Summary
            if updated_summary:
                self.summary_cumulative = updated_summary
                
            # Update Tags
            TagModel = self.env['zalo.customer.tag']
            tag_ids = []
            for tag_name in new_tags_list:
                if not tag_name:
                    continue

                # Normalize role tags
                tag_name_norm = tag_name.strip()
                if tag_name_norm.lower() in ['nhà cung cấp', 'ncc']:
                    tag_name_norm = 'NCC'
                elif tag_name_norm.lower() in ['khách lẻ', 'khách hàng']:
                    tag_name_norm = 'Khách hàng'

                # Find or Create Tag (Case insensitive search)
                tag = TagModel.search([('name', '=ilike', tag_name_norm)], limit=1)
                if not tag:
                    # AI might infer category, but for now default to 'other' or simple logic
                    category = 'other'
                    if tag_name_norm in ['Khách lẻ', 'Khách hàng', 'NCC', 'Nhà cung cấp', 'Đại lý', 'CTV']:
                        category = 'role'
                    elif any(brand in tag_name_norm for brand in ['Bosch', 'Makita', 'Milwaukee']):
                        category = 'brand'
                    elif tag_name_norm in ['Mua hàng', 'Bảo hành', 'Hỏi giá', 'Khiếu nại']:
                        category = 'need'
                        
                    tag = TagModel.create({'name': tag_name_norm, 'category': category})
                tag_ids.append(tag.id)
            
            if tag_ids:
                self.tag_ids = [(6, 0, tag_ids)]
                
            _logger.info(f"Updated Profile for Partner {self.partner_id.name}: Summary len={len(updated_summary)}, Tags={new_tags_list}")
            
        except Exception as e:
            _logger.error(f"Failed to update Customer Profile AI: {e}")
