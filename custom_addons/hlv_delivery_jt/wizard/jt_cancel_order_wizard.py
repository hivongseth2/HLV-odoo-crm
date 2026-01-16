# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
from odoo.exceptions import UserError
from ..utils.jt_api_utils import JTApiUtils
import logging

_logger = logging.getLogger(__name__)

class JTCancelOrderWizard(models.TransientModel):
    _name = 'jt.cancel.order.wizard'
    _description = 'Hủy đơn J&T Express'

    picking_id = fields.Many2one('stock.picking', string='Phiếu xuất kho', required=True)
    jt_bill_code = fields.Char(related='picking_id.jt_bill_code', string='Mã vận đơn J&T')
    reason = fields.Selection([
        ('Khách đổi ý', 'Khách đổi ý'),
        ('Sai thông tin', 'Sai thông tin'),
        ('Hết hàng', 'Hết hàng'),
        ('Khác', 'Khác'),
    ], string='Lý do hủy', required=True, default='Khách đổi ý')
    other_reason = fields.Text(string='Lý do khác')

    def action_cancel_jt_order(self):
        self.ensure_one()
        picking = self.picking_id
        company = picking.company_id

        # Get credentials from System Parameters (consistent with order creation)
        get_param = self.env['ir.config_parameter'].sudo().get_param
        api_account = get_param('jnt_apiAccount')
        private_key = get_param('jnt_privateKey')
        jnt_customer_code = get_param('jnt_customerCode')
        jnt_password = get_param('jnt_password')

        if not api_account or not private_key or not jnt_customer_code or not jnt_password:
            raise UserError(_("Chưa cấu hình thông tin J&T trong System Parameters (jnt_apiAccount, jnt_privateKey, jnt_customerCode, jnt_password)."))

        client = JTApiUtils(
            api_account=api_account,
            private_key=private_key,
            environment=company.jt_environment
        )

        reason_text = self.other_reason if self.reason == 'Khác' else self.reason
        
        # User confirmed txlogisticId is the picking name (OUT code)
        biz_params = {
            "customerCode": jnt_customer_code,
            "password": jnt_password.upper(),
            "txlogisticId": picking.name.replace("/", "-"),
            "billCode": picking.jt_bill_code or "",
            "reason": reason_text
        }

        _logger.info("J&T Cancelling Order for %s | Reason: %s", picking.name, reason_text)
        result = client.cancel_order(biz_params)

        if result.get('code') == '1':
            picking.write({
                'jt_order_status': 'Cancelled'
            })
            picking.message_post(body=f"Đã hủy đơn J&T thành công. Lý do: {reason_text}")
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Thành công',
                    'message': 'Đã hủy đơn J&T thành công!',
                    'type': 'success',
                }
            }
        else:
            msg = result.get('msg', 'Lỗi không xác định từ J&T')
            raise UserError(_("Không thể hủy đơn J&T: %s") % msg)
