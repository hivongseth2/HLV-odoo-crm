from odoo import fields, models

class GoogleAdsRuleLog(models.Model):
    _name = 'google.ads.rule.log'
    _description = 'Lịch Sử Chạy Quy Tắc'
    _order = 'create_date desc'

    rule_id = fields.Many2one('google.ads.rule', string='Quy Tắc', required=True, ondelete='cascade')
    run_date = fields.Datetime(string='Thời Gian Chạy', default=fields.Datetime.now)
    target_name = fields.Char(string='Đối Tượng Bị Tác Động')
    
    status = fields.Selection([
        ('success', 'Bình Thường (Không có tác động)'),
        ('action_taken', 'Đã Xử Lý (Bị Tác Động)'),
        ('error', 'Lỗi')
    ], string='Trạng Thái')
    
    message = fields.Text(string='Ghi Chú Chi Tiết')
