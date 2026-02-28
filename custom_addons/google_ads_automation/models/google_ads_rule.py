from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class GoogleAdsRule(models.Model):
    _name = 'google.ads.rule'
    _description = 'Quy Tắc Tự Động Hóa Google Ads'
    _inherit = ['mail.thread', 'mail.activity.mixin']

    name = fields.Char(string='Tên Quy Tắc', required=True)
    active = fields.Boolean(string='Kích Hoạt', default=True)
    
    account_id = fields.Many2one('google.ads.account', string='Tài Khoản Áp Dụng', required=True)
    
    target_type = fields.Selection([
        ('campaign', 'Chiến Dịch'),
        ('ad_group', 'Nhóm Quảng Cáo'),
        ('ad', 'Quảng Cáo')
    ], string='Đốí Tượng Áp Dụng', required=True, default='campaign')
    
    # Điều kiện kích hoạt: Ví dụ (chi phí > 500k VÀ CPA > 100k)
    condition_field = fields.Selection([
        ('cost', 'Chi Phí'),
        ('clicks', 'Lượt Nhấp'),
        ('impressions', 'Lượt Hiển Thị'),
        ('conversions', 'Lượt Chuyển Đổi'),
        ('cpa', 'CPA (Chi Phí / Chuyển Đổi)'),
    ], string='Trường Điều Kiện', required=True)
    
    condition_operator = fields.Selection([
        ('>', 'Lớn hơn'),
        ('<', 'Nhỏ hơn'),
        ('=', 'Bằng')
    ], string='Toán Tử', required=True, default='>')
    
    condition_value = fields.Float(string='Giá Trị', required=True)

    # Hành động thực thi
    action_type = fields.Selection([
        ('pause', 'Tạm Dừng (Pause)'),
        ('enable', 'Bật Lại (Enable)'),
        ('notify', 'Chỉ Thông Báo')
    ], string='Hành Động', required=True, default='notify')

    log_ids = fields.One2many('google.ads.rule.log', 'rule_id', string='Lịch Sử Chạy')

    def run_rule(self):
        """Hàm thực thi logic kiểm tra và áp dụng quy tắc"""
        for rule in self:
            if not rule.active:
                continue
                
            _logger.info("Executing rule: %s", rule.name)
            
            # 1. Tìm tập dữ liệu hiện tại trong hệ thống (đã được lấy về qua cron update_account)
            domain = []
            if rule.target_type == 'campaign':
                model = self.env['google.ads.campaign']
                domain = [('account_id', '=', rule.account_id.id), ('status', '=', 'enabled')]
            elif rule.target_type == 'ad_group':
                model = self.env['google.ads.ad.group']
                domain = [('campaign_id.account_id', '=', rule.account_id.id), ('status', '=', 'enabled')]
            elif rule.target_type == 'ad':
                model = self.env['google.ads.ad']
                domain = [('ad_group_id.campaign_id.account_id', '=', rule.account_id.id), ('status', '=', 'enabled')]
            
            records = model.search(domain)
            
            applicable_records = []
            for rec in records:
                # 2. Kiểm tra điều kiện
                val = getattr(rec, rule.condition_field) if rule.condition_field != 'cpa' else 0.0
                if rule.condition_field == 'cpa':
                    if rec.conversions > 0:
                        val = rec.cost / rec.conversions
                    else:
                        val = rec.cost # Không có chuyển đổi mà tốn tiền thì coi CPA bằng cost
                
                is_matched = False
                if rule.condition_operator == '>':
                    is_matched = val > rule.condition_value
                elif rule.condition_operator == '<':
                    is_matched = val < rule.condition_value
                elif rule.condition_operator == '=':
                    is_matched = val == rule.condition_value
                    
                if is_matched:
                    applicable_records.append((rec, val))
            
            # 3. Ghi log và gọi Google API (Nâng cao)
            if not applicable_records:
                self.env['google.ads.rule.log'].create({
                    'rule_id': rule.id,
                    'status': 'success',
                    'message': 'Chạy thành công nhưng không có đối tượng nào thoả mãn.',
                })
                continue

            for (rec, val) in applicable_records:
                log_message = f"Đối tượng '{rec.name}' thoả mãn điều kiện {rule.condition_field} {rule.condition_operator} {rule.condition_value} (Thực tế: {val}). Hành động: {rule.action_type}"
                self.env['google.ads.rule.log'].create({
                    'rule_id': rule.id,
                    'target_name': rec.name,
                    'status': 'action_taken',
                    'message': log_message,
                })
                
                # Tại đây sẽ có code gọi mutate function của google-ads-api để dừng Ads
                # (Ví dụ update status thành PAUSED) -> Vì đây là POC nên hiện mình chỉ Update DB & Log
                if rule.action_type == 'pause':
                    rec.status = 'paused'
                    # Call API here to update Google Ads in production
                    
    @api.model
    def cron_evaluate_all_rules(self):
        """Hàm cron chạy tự động cho tất cả các rule (Schedule Action)"""
        # 1. Trước tiên bắt account tự đồng bộ lấy metrics mới nhất về
        accounts = self.env['google.ads.account'].search([('state', '=', 'connected'), ('active', '=', True)])
        for acc in accounts:
            try:
                acc.action_sync_all_data()
            except Exception as e:
                _logger.error("Cron sync account %s failed: %s", acc.name, str(e))

        # 2. Sau đó chạy tất cả các rule
        rules = self.search([('active', '=', True)])
        rules.run_rule()
