# -*- coding: utf-8 -*-
from odoo import models, fields, api, _

class DeliveryStatusReportWizard(models.TransientModel):
    _name = 'delivery.status.report.wizard'
    _description = 'Wizard Báo cáo Tình trạng Giao hàng'

    date_to = fields.Date('Tính đến ngày', default=fields.Date.context_today, required=True)

    def action_view_report(self):
        # Clear old report lines for this user
        self.env['delivery.status.report.line'].search([('create_uid', '=', self.env.uid)]).unlink()

        domain = [
            ('commitment_date', '<=', self.date_to),
            ('state', 'in', ['sale', 'done'])
        ]
        orders = self.env['sale.order'].search(domain)
        pending_orders = orders.filtered(lambda o: not all(l.qty_delivered >= l.product_uom_qty for l in o.order_line if l.product_id.type == 'product'))

        lines_to_create = []
        for order in pending_orders:
            is_ready = True
            is_waiting = False
            for line in order.order_line:
                if line.product_id.type == 'product':
                    if line.product_id.qty_available < (line.product_uom_qty - line.qty_delivered):
                        is_ready = False
                        if line.product_id.incoming_qty > 0:
                            is_waiting = True

            stock_status = 'ready'
            if not is_ready:
                if is_waiting:
                    stock_status = 'waiting'
                else:
                    stock_status = 'shortage'

            strategy = 'Không rõ'
            htgh_val = ''
            if hasattr(order, 'x_studio_htgh') and order.x_studio_htgh:
                htgh_val = order.x_studio_htgh
                if order._fields['x_studio_htgh'].type == 'selection':
                    strategy = dict(order._fields['x_studio_htgh'].selection).get(order.x_studio_htgh, order.x_studio_htgh)
                else:
                    strategy = order.x_studio_htgh
            elif not hasattr(order, 'x_studio_htgh'):
                strategy = 'Không ưu tiên'

            origin_val = order.origin or ''

            lines_to_create.append({
                'order_id': order.id,
                'partner_id': order.partner_id.id,
                'commitment_date': order.commitment_date,
                'stock_status': stock_status,
                'strategy_note': f"HTGH: {strategy} | Ghi chú: {origin_val}"
            })

        if lines_to_create:
            self.env['delivery.status.report.line'].create(lines_to_create)

        return {
            'name': _('Báo cáo Tình trạng đơn hàng tính đến %s') % self.date_to,
            'type': 'ir.actions.act_window',
            'res_model': 'delivery.status.report.line',
            'view_mode': 'list',
            'domain': [('create_uid', '=', self.env.uid)],
            'context': {'create': False, 'edit': False, 'delete': False}
        }

class DeliveryStatusReportLine(models.TransientModel):
    _name = 'delivery.status.report.line'
    _description = 'Dòng Báo cáo Tình trạng Giao hàng'

    order_id = fields.Many2one('sale.order', string='Đơn hàng')
    partner_id = fields.Many2one('res.partner', string='Khách hàng')
    commitment_date = fields.Datetime('Ngày hẹn giao')
    stock_status = fields.Selection([
        ('ready', 'Đủ hàng (Sẵn sàng)'),
        ('waiting', 'Chờ hàng về (Sáng mai)'),
        ('shortage', 'Thiếu hàng (Tạm hoãn)')
    ], string='Tình trạng kho')
    strategy_note = fields.Char('Ghi chú / Chiến lược')
