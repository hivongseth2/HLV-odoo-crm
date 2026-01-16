# -*- coding: utf-8 -*-
from odoo import fields, models

class StockPicking(models.Model):
    _inherit = "stock.picking"

    jt_bill_code = fields.Char(string="J&T Bill Code", copy=False)
    jt_sort_line = fields.Char(string="J&T Sort Line", copy=False)
    jt_order_status = fields.Char(string="Trạng thái J&T", copy=False)
    jt_cod_fee = fields.Float(string="Phí COD J&T", copy=False)
    jt_insurance_fee = fields.Float(string="Phí bảo hiểm J&T", copy=False)
    jt_total_fee = fields.Float(string="Tổng phí J&T", copy=False)

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
