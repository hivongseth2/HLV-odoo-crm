from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class GoogleAdsAdGroup(models.Model):
    _name = 'google.ads.ad.group'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Nhóm Quảng Cáo Google Ads'

    name = fields.Char(string='Tên Nhóm', required=True)
    campaign_id = fields.Many2one('google.ads.campaign', string='Chiến Dịch', required=True, ondelete='cascade')
    google_ad_group_id = fields.Char(string='Google Ad Group ID', readonly=True)
    state = fields.Selection([
        ('draft', 'Nháp (Local)'),
        ('synced', 'Đã đồng bộ Google'),
    ], string='Trạng thái bộ máy', default='draft', required=True, tracking=True)

    type_id = fields.Many2one('google.ads.ad.group.type', string='Loại Nhóm Quảng Cáo', required=True, help='Loại nhóm quảng cáo phù hợp với chiến dịch (Tìm kiếm, Hiển thị, Video...)')
    type = fields.Selection(related='type_id.code', string='Mã Loại Nhóm', readonly=True)

    is_campaign_dsa = fields.Boolean(related='campaign_id.is_dsa', string='Chiến dịch DSA', readonly=True)

    status = fields.Selection([
        ('unspecified', 'Chưa xác định'),
        ('unknown', 'Không rõ'),
        ('enabled', 'Đang hoạt động'),
        ('paused', 'Tạm dừng'),
        ('removed', 'Đã xóa'),
    ], string='Trạng Thái', default='enabled', tracking=True)

    # Metrics
    clicks = fields.Integer(string='Lượt Nhấp', default=0, readonly=True)
    impressions = fields.Integer(string='Lượt Hiển Thị', default=0, readonly=True)
    cost = fields.Float(string='Chi Phí', default=0.0, readonly=True)
    conversions = fields.Float(string='Lượt Chuyển Đổi', default=0.0, readonly=True)

    # Computed Metrics for UI
    conversion_rate = fields.Float(
        string='Tỷ Lệ Chuyển Đổi (%)', 
        compute='_compute_performance_metrics', store=False
    )
    roas = fields.Float(
        string='ROAS', 
        compute='_compute_performance_metrics', store=False,
    )
    
    @api.depends('clicks', 'conversions', 'cost')
    def _compute_performance_metrics(self):
        for rec in self:
            # Conversion Rate
            if rec.clicks > 0:
                rec.conversion_rate = (rec.conversions / rec.clicks) * 100
            else:
                rec.conversion_rate = 0.0
                
            # ROAS 
            if rec.cost > 0:
                # Giả định doanh thu 500k cho demo
                rec.roas = (rec.conversions * 500000) / rec.cost
            else:
                rec.roas = 0.0

    @api.onchange('campaign_id')
    def _onchange_campaign_id_clear_type(self):
        """Khi đổi chiến dịch, nếu loại nhóm hiện tại không còn phù hợp thì xóa trắng để chọn lại"""
        if self.campaign_id and self.type_id:
            channel_type = self.campaign_id.channel_type
            if channel_type not in (self.type_id.compatible_channel_types or ''):
                self.type_id = False
                # Không đưa thông báo Warning tự động sửa để tôn trọng ý người dùng, chỉ xóa trắng để họ chọn lại
                
    def action_sync_to_google(self):
        """Đồng bộ Nhóm quảng cáo lên Google Ads"""
        self.ensure_one()
        if self.state == 'synced': return True
        if self.campaign_id.state == 'draft':
            raise UserError(_("Vui lòng đồng bộ Chiến dịch cha trước."))

        if self.campaign_id.channel_type in ['PERFORMANCE_MAX', 'SMART', 'MULTI_CHANNEL']:
            raise UserError(_("Chiến dịch '%s' (loại: %s) không sử dụng 'Nhóm quảng cáo' truyền thống. "
                              "Loại chiến dịch này quản lý quảng cáo và mục tiêu tự động hoặc qua Nhóm thành phần (Asset Group). "
                              "Vui lòng chọn Chiến dịch Tìm kiếm, Hiển thị hoặc Video chuẩn.") % (self.campaign_id.name, self.campaign_id.channel_type))
        
        if self.campaign_id.account_id.is_demo:
            self.google_ad_group_id = f"DEMO_AG_SYNC_{self.id}"
            self.state = 'synced'
            self.message_post(body=_("[DEMO] Nhóm quảng cáo đã được giả lập đồng bộ thành công."))
            return True

        client = self.campaign_id.account_id._get_google_ads_client()
        customer_id = self.campaign_id.account_id.operating_customer_id
        
        if not self.type_id:
            raise UserError(_("Vui lòng chọn 'Loại Nhóm Quảng Cáo' phù hợp với Chiến dịch trước khi đồng bộ."))

        vals = {
            'name': self.name,
            'status': self.status,
            'type': self.type,
        }
        from ..services.google_ads_mutate import GoogleAdsMutateService
        ok, result = GoogleAdsMutateService.create_ad_group(
            client, customer_id, self.campaign_id.google_campaign_id, vals
        )
        
        if ok:
            self.write({'google_ad_group_id': result.split('/')[-1], 'state': 'synced'})
            self.message_post(body=_("Nhóm quảng cáo đã được tạo trên Google Ads. ID: %s") % self.google_ad_group_id)
            return True
        else:
            error_msg = result
            if 'CANNOT_ADD_ADGROUP_OF_TYPE_DSA_TO_CAMPAIGN_WITHOUT_DSA_SETTING' in result:
                error_msg = _("Loại nhóm 'Tìm kiếm động (DSA)' chỉ dùng được với các Chiến dịch đã bật cấu hình DSA. Vui lòng chọn loại 'Tìm kiếm chuẩn' hoặc đổi Chiến dịch.")
            elif 'DUPLICATE_ADGROUP_NAME' in result:
                error_msg = _("Tên nhóm quảng cáo này bị trùng trong chiến dịch. Vui lòng đổi tên khác.")
            elif 'OPERATION_NOT_PERMITTED_FOR_CONTEXT' in result:
                error_msg = _("Loại nhóm quảng cáo này không được hỗ trợ cho Chiến dịch hiện tại (ví dụ: Chiến dịch PMax/Video không dùng Nhóm Tìm kiếm chuẩn).")

            raise UserError(_("Đồng bộ Nhóm thất bại: %s") % error_msg)

    def action_pause_on_google(self):
        self.ensure_one()
        if not self.google_ad_group_id: return
        client = self.campaign_id.account_id._get_google_ads_client()
        customer_id = self.campaign_id.account_id.operating_customer_id
        from ..services.google_ads_mutate import GoogleAdsMutateService
        ok, res = GoogleAdsMutateService.pause_ad_group(client, customer_id, self.google_ad_group_id)
        if ok:
            self.status = 'paused'
            return True
        raise UserError(_("Không thể tạm dừng Nhóm trên Google Ads: %s") % res)

    def action_enable_on_google(self):
        self.ensure_one()
        if not self.google_ad_group_id: return
        client = self.campaign_id.account_id._get_google_ads_client()
        customer_id = self.campaign_id.account_id.operating_customer_id
        from ..services.google_ads_mutate import GoogleAdsMutateService
        ok, res = GoogleAdsMutateService.enable_ad_group(client, customer_id, self.google_ad_group_id)
        if ok:
            self.status = 'enabled'
            return True
        raise UserError(_("Không thể kích hoạt Nhóm trên Google Ads: %s") % res)

    def action_remove_from_google_only(self):
        """Xóa trên Google Ads nhưng giữ lại bản ghi Odoo dưới dạng Nháp"""
        self.ensure_one()
        if not self.google_ad_group_id: return
        client = self.campaign_id.account_id._get_google_ads_client()
        customer_id = self.campaign_id.account_id.operating_customer_id
        from ..services.google_ads_mutate import GoogleAdsMutateService
        ok, res = GoogleAdsMutateService.remove_ad_group(client, customer_id, self.google_ad_group_id)
        if ok:
            self.write({
                'google_ad_group_id': False,
                'state': 'draft',
                'status': 'removed'
            })
            self.message_post(body=_("Đã xóa Nhóm trên Google Ads. Bản ghi Odoo đã chuyển về trạng thái Nháp."))
            return True
        raise UserError(_("Không thể xóa Nhóm trên Google Ads: %s") % res)

    def unlink(self):
        """Khi xóa Nhóm trên Odoo, xóa tương ứng trên Google Ads nếu đã đồng bộ"""
        for rec in self:
            if rec.google_ad_group_id and rec.campaign_id.account_id.state == 'authenticated':
                try:
                    client = rec.campaign_id.account_id.get_google_ads_client()
                    customer_id = rec.campaign_id.account_id.google_customer_id
                    from ..services.google_ads_mutate import GoogleAdsMutateService
                    ok, result = GoogleAdsMutateService.remove_ad_group(client, customer_id, rec.google_ad_group_id)
                    if ok:
                        _logger.info("Deleted ad group %s from Google Ads.", rec.google_ad_group_id)
                    else:
                        _logger.warning("Could not delete ad group %s: %s", rec.google_ad_group_id, result)
                except Exception as e:
                    _logger.error("Error during ad group unlink sync: %s", str(e))
        return super().unlink()

    _sql_constraints = [
        ('google_ad_group_id_uniq', 'unique(google_ad_group_id)', 'Google Ad Group ID phải là duy nhất!'),
    ]
