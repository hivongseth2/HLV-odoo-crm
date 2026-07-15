# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..services import shopee_api


_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    shopee_tracking_button_visible = fields.Boolean(
        compute='_compute_shopee_tracking_button_visible',
    )

    @api.depends(
        'picking_type_id.sequence_code',
        'state',
        'sale_id',
        'sale_id.shopee_order_ref',
        'sale_id.shopee_shop_id',
    )
    def _compute_shopee_tracking_button_visible(self):
        for picking in self:
            sale = picking.sale_id
            sequence_code = (picking.picking_type_id.sequence_code or '').upper()
            picking.shopee_tracking_button_visible = bool(
                'PICK' in sequence_code
                and picking.state not in ('done', 'cancel')
                and sale
                and sale.shopee_order_ref
                and sale.shopee_shop_id
            )

    def action_fetch_shopee_tracking_number(self):
        """Fetch Shopee tracking number and use it as this picking's reference."""
        self.ensure_one()
        sale = self.sale_id
        sequence_code = (self.picking_type_id.sequence_code or '').upper()
        if 'PICK' not in sequence_code:
            raise UserError(_("Chỉ hỗ trợ lấy mã vận đơn cho phiếu PICK."))
        if not sale or not sale.shopee_order_ref:
            raise UserError(_("Phiếu này không liên kết với đơn hàng Shopee."))
        if not sale.shopee_shop_id:
            raise UserError(_("Đơn Shopee chưa được liên kết với cửa hàng Shopee."))

        status_code, body, _params, _creds = (
            shopee_api.call_tracking_number_with_token_refresh(
                sale.shopee_shop_id,
                sale.shopee_order_ref,
            )
        )
        if status_code != 200 or body.get('error'):
            raise UserError(
                _("Shopee không thể trả mã vận đơn cho đơn %(order)s:\n%(error)s - %(message)s")
                % {
                    'order': sale.shopee_order_ref,
                    'error': body.get('error') or 'HTTP %s' % status_code,
                    'message': body.get('message') or '',
                }
            )

        tracking_number = str(
            body.get('response', {}).get('tracking_number') or ''
        ).strip()
        if not tracking_number:
            hint = body.get('response', {}).get('hint') or ''
            raise UserError(
                _(
                    "Shopee chưa trả mã vận đơn cho đơn %(order)s. "
                    "Theo tài liệu Shopee, hãy thử lại sau 5 phút.%(hint)s"
                )
                % {
                    'order': sale.shopee_order_ref,
                    'hint': ('\n%s' % hint) if hint else '',
                }
            )

        duplicate = self.sudo().search([
            ('id', '!=', self.id),
            ('company_id', '=', self.company_id.id),
            ('name', '=', tracking_number),
        ], limit=1)
        if duplicate:
            raise UserError(
                _("Mã vận đơn %(tracking)s đang được dùng bởi phiếu %(picking)s.")
                % {'tracking': tracking_number, 'picking': duplicate.display_name}
            )

        old_name = self.name
        self.write({
            'carrier_tracking_ref': tracking_number,
            'name': tracking_number,
        })
        _logger.info(
            "Shopee tracking fetched: order=%s picking=%s -> %s",
            sale.shopee_order_ref,
            old_name,
            tracking_number,
        )
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Đã lấy mã vận đơn Shopee"),
                'message': _("Phiếu %(old)s đã đổi thành %(tracking)s.") % {
                    'old': old_name,
                    'tracking': tracking_number,
                },
                'type': 'success',
                'sticky': False,
            },
        }
