# -*- coding: utf-8 -*-
from odoo import fields, models, api

class StockPicking(models.Model):
    _inherit = "stock.picking"

    jt_bill_code = fields.Char(string="J&T Bill Code", copy=False)
    jt_sort_line = fields.Char(string="J&T Sort Line", copy=False)
    jt_order_status = fields.Char(string="Trạng thái J&T", copy=False)
    jt_cod_fee = fields.Float(string="Phí COD J&T", copy=False)
    jt_insurance_fee = fields.Float(string="Phí bảo hiểm J&T", copy=False)
    jt_total_fee = fields.Float(string="Tổng phí J&T", copy=False)
    
    jt_total_fee = fields.Float(string="Tổng phí J&T", copy=False)
    
    jt_tracking_log_ids = fields.One2many("jt.tracking.log", "picking_id", string="Hành trình J&T")
    jt_tracking_timeline = fields.Html(string="Hành trình đơn hàng", compute="_compute_jt_timeline")

    @api.depends('jt_tracking_log_ids')
    def _compute_jt_timeline(self):
        for record in self:
            html = '<div class="o_jt_timeline" style="margin-left: 10px; border-left: 2px solid #ddd; padding-left: 20px;">'
            if not record.jt_tracking_log_ids:
                html = '<div class="text-muted">Chưa có thông tin hành trình.</div>'
            else:
                import pytz
                user_tz = self.env.user.tz or 'Asia/Ho_Chi_Minh'
                
                logs = record.jt_tracking_log_ids
                for index, log in enumerate(logs):
                    time_str = ""
                    if log.scan_time:
                        try:
                            # J&T usually returns local time already, but good to ensure format
                            # Assuming scan_time in DB is UTC
                            utc = pytz.UTC
                            dest_tz = pytz.timezone(user_tz)
                            local_dt = utc.localize(log.scan_time).astimezone(dest_tz)
                            time_str = local_dt.strftime("%d/%m/%Y %H:%M:%S")
                        except:
                            time_str = log.scan_time.strftime("%d/%m/%Y %H:%M:%S")
                    
                    status_vn = log.scan_type_name or "N/A"
                    desc = log.desc or ""
                    
                    # Color based on status keywords (J&T specific)
                    color = "#0056b3"
                    bg_dot = "#0d6efd" 
                    
                    # 106 Picked up, 113 Delivered, 116 Returning, 117 Returned
                    status_lower = status_vn.lower()
                    if 'ký nhận' in status_lower or 'delivered' in status_lower: 
                        color = "#0f5132"
                        bg_dot = "#198754"
                    elif 'đang chuyển hoàn' in status_lower or 'returning' in status_lower: 
                        color = "#842029"
                        bg_dot = "#dc3545"
                    elif 'đã ký nhận hoàn trả' in status_lower or 'returned' in status_lower:
                        color = "#664d03"
                        bg_dot = "#ffc107"
                    elif 'nhận hàng' in status_lower or 'picked' in status_lower:
                        color = "#0d6efd"
                        bg_dot = "#0d6efd"

                    # Text badge for latest item (first in list)
                    badge_html = ""
                    if index == 0:
                        badge_html = f'<span style="color: #adb5bd; font-size: 0.8em; margin-left: 8px; font-weight: normal; font-style: italic;">(Hiện tại)</span>'

                    html += f'''
                    <div style="position: relative; margin-bottom: 20px;">
                        <div style="position: absolute; left: -26px; top: 0; width: 12px; height: 12px; border-radius: 50%; background: {bg_dot}; border: 2px solid white; box-shadow: 0 0 0 1px {bg_dot};"></div>
                        <div style="font-weight: bold; color: {color}">{status_vn} <span style="font-weight: normal; color: #666; font-size: 0.9em;">- {time_str}</span> {badge_html}</div>
                        <div style="font-size: 0.9em; color: #555; margin-top: 4px;">{desc}</div>
                        <div style="font-size: 0.8em; color: #888; margin-top: 2px;">
                           NV: {log.staff_name or ''} - {log.staff_contact or ''} | {log.scan_network_name or ''}
                        </div>
                    </div>
                    '''
            
            html += '</div>'
            record.jt_tracking_timeline = html

    def action_sync_jt_status(self):
        """Sync tracking status from J&T"""
        self.ensure_one()
        from odoo.exceptions import UserError
        from ..utils.jt_api_utils import JTApiUtils

        if not self.jt_bill_code:
            raise UserError("Đơn hàng chưa có mã vận đơn J&T!")

        # Get credentials
        get_param = self.env['ir.config_parameter'].sudo().get_param
        api_account = get_param('jnt_apiAccount')
        private_key = get_param('jnt_privateKey')
        jnt_customer_code = get_param('jnt_customerCode')
        jnt_password = get_param('jnt_password')
        company = self.company_id or self.env.company

        if not all([api_account, private_key, jnt_customer_code, jnt_password]):
            raise UserError("Chưa cấu hình thông tin J&T trong System Parameters.")

        client = JTApiUtils(
            api_account=api_account,
            private_key=private_key,
            environment=company.jt_environment
        )

        biz_params = {
            "customerCode": jnt_customer_code,
            "password": jnt_password.upper(),
            "billCodes": self.jt_bill_code
        }

        result = client.trace_order(biz_params)
        
        if result.get('code') == '1' and result.get('data'):
            data_list = result['data']
            if isinstance(data_list, list) and len(data_list) > 0:
                data = data_list[0] # We only requested one bill code
                details = data.get('details', [])
                
                # Clear old logs to clean update
                self.jt_tracking_log_ids.unlink()
                
                LogModel = self.env['jt.tracking.log']
                for det in details:
                    LogModel.create({
                        'picking_id': self.id,
                        'scan_time': det.get('scanTime'),
                        'scan_type_name': det.get('scanTypeName'),
                        'desc': det.get('desc'),
                        'scan_network_name': det.get('scanNetworkName'),
                        'staff_name': det.get('staffName'),
                        'staff_contact': det.get('staffContact'),
                    })
                
                return {
                    'type': 'ir.actions.client',
                    'tag': 'display_notification',
                    'params': {
                        'title': 'Thành công',
                        'message': 'Đã cập nhật hành trình đơn hàng J&T!',
                        'type': 'success',
                        'sticky': False,
                    }
                }
            else:
                 raise UserError(f"Không tìm thấy dữ liệu hành trình for {self.jt_bill_code}")
        else:
            msg = result.get('msg', 'Lỗi không xác định từ J&T')
            raise UserError(f"Lỗi cập nhật hành trình: {msg}")

    def action_open_jt_wizard(self):
        self.ensure_one()
        return {
            'name': 'Tạo đơn J&T Express',
            'type': 'ir.actions.act_window',
            'res_model': 'jt.create.order.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_picking_id': self.id}
        }

    def action_open_jt_cancel_wizard(self):
        self.ensure_one()
        return {
            'name': 'Hủy đơn J&T Express',
            'type': 'ir.actions.act_window',
            'res_model': 'jt.cancel.order.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_picking_id': self.id}
        }

    def action_open_carrier_selector(self):
        self.ensure_one()
        return {
            'name': 'Chọn đơn vị vận chuyển',
            'type': 'ir.actions.act_window',
            'res_model': 'choose.delivery.carrier.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_picking_id': self.id}
        }

    def action_print_jt_label(self):
        """Print J&T shipping label"""
        self.ensure_one()
        from odoo.exceptions import UserError
        from ..utils.jt_api_utils import JTApiUtils
        import base64

        if not self.jt_bill_code:
            raise UserError("Đơn hàng chưa có mã vận đơn J&T, không thể in!")

        # Get credentials
        get_param = self.env['ir.config_parameter'].sudo().get_param
        api_account = get_param('jnt_apiAccount')
        private_key = get_param('jnt_privateKey')
        jnt_customer_code = get_param('jnt_customerCode')
        jnt_password = get_param('jnt_password')
        company = self.company_id or self.env.company

        if not all([api_account, private_key, jnt_customer_code, jnt_password]):
            raise UserError("Chưa cấu hình thông tin J&T trong System Parameters.")

        client = JTApiUtils(
            api_account=api_account,
            private_key=private_key,
            environment=company.jt_environment
        )

        biz_params = {
            "customerCode": jnt_customer_code,
            "password": jnt_password.upper(),
            "txlogisticId": self.name.replace("/", "-")
        }

        result = client.print_label(biz_params)
        if result.get('code') == '1' and result.get('data'):
            data = result['data']
            base64_content = data.get('base64EncodeContent')
            
            if not base64_content:
                raise UserError("Không nhận được nội dung tem từ J&T.")

            # Create attachment for the label
            attachment = self.env['ir.attachment'].create({
                'name': f'Tem_JT_{self.jt_bill_code}.pdf',
                'type': 'binary',
                'datas': base64_content,
                'res_model': 'stock.picking',
                'res_id': self.id,
                'mimetype': 'application/pdf',
            })

            # Return client action to trigger silent print from JS
            return {
                'type': 'ir.actions.client',
                'tag': 'jt_print_label',
                'params': {
                    'attachment_id': attachment.id,
                }
            }
        else:
            msg = result.get('msg', 'Lỗi không xác định từ J&T')
            raise UserError(f"Không thể in tem J&T: {msg}")

    def action_jt_bulk_print_labels(self):
        """J&T Bulk Label Print Action"""
        from odoo.exceptions import UserError
        from ..utils.jt_api_utils import JTApiUtils

        pickings = self.filtered(lambda p: p.jt_bill_code)
        if not pickings:
            raise UserError("Vui lòng chọn ít nhất một đơn có mã vận đơn J&T!")

        if len(pickings) > 200:
            raise UserError("J&T chỉ hỗ trợ in tối đa 200 đơn hàng một lần!")

        # Get credentials
        get_param = self.env['ir.config_parameter'].sudo().get_param
        api_account = get_param('jnt_apiAccount')
        private_key = get_param('jnt_privateKey')
        jnt_customer_code = get_param('jnt_customerCode')
        jnt_password = get_param('jnt_password')
        company = pickings[0].company_id or self.env.company

        if not all([api_account, private_key, jnt_customer_code, jnt_password]):
            raise UserError("Chưa cấu hình thông tin J&T trong System Parameters.")

        client = JTApiUtils(
            api_account=api_account,
            private_key=private_key,
            environment=company.jt_environment
        )

        biz_params = {
            "customerCode": jnt_customer_code,
            "password": jnt_password.upper(),
            "txlogisticIds": [p.name.replace("/", "-") for p in pickings]
        }

        result = client.print_bulk_labels(biz_params)
        if result.get('code') == '1' and result.get('data'):
            return {
                'type': 'ir.actions.act_url',
                'url': result['data'],
                'target': 'new',
            }
        else:
            msg = result.get('msg', 'Lỗi không xác định từ J&T')
            raise UserError(f"Không thể in hàng loạt J&T: {msg}")
