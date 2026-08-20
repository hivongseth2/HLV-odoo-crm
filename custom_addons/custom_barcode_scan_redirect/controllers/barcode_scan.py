# -*- coding: utf-8 -*-
"""Barcode scan UI entry-point routes (/custom_barcode_scan/*)."""
from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)


class BarcodeScanController(http.Controller):

    @http.route(['/custom_barcode_scan/ui'], type='http', auth='user')
    def scan_ui(self):
        return request.render("custom_barcode_scan_redirect.scan_ui_template")

    @http.route('/custom_barcode_scan/ui/scan', type='json', auth='user', csrf=False)
    def scan_ui_api(self, **kwargs):
        barcode = kwargs.get("barcode")

        Picking = request.env['stock.picking'].sudo()
        picking = Picking.search([('name', '=', barcode)], limit=1)

        if not picking:
            return {'type': 'ir.actions.client','tag': 'display_notification','params': {
                'message': f"Không tìm thấy phiếu với mã: {barcode}", 'type': 'danger','sticky': False}}

        if picking.state == 'done' and picking.group_id:

            # Lấy tất cả PACK còn xử lý được
            packs = Picking.search([
                ('group_id', '=', picking.group_id.id),
                ('id', '!=', picking.id),
                ('picking_type_id.sequence_code', 'like', 'PACK'),
                ('state', 'in', ['confirmed', 'assigned', 'waiting', 'in_progress']),
            ])

            # Ưu tiên 'assigned' trước
            def _priority(p):
                s = (p.state or '')
                if s == 'assigned': return (0, p.id)
                if s == 'in_progress': return (1, p.id)
                return (2, p.id)

            packs_sorted = sorted(packs, key=_priority)

            # Nếu có nhiều phiếu -> Trả về danh sách để user chọn
            if len(packs_sorted) > 1:
                return {
                    'type': 'custom_pack_selection',
                    'title': f"Tìm thấy {len(packs_sorted)} phiếu PACK cho {picking.name}",
                    'items': [{
                        'id': p.id,
                        'name': p.name,
                        'state': dict(p._fields['state'].selection).get(p.state, p.state),
                        'date': p.scheduled_date and p.scheduled_date.strftime('%d/%m') or ''
                    } for p in packs_sorted]
                }

            next_picking = packs_sorted and packs_sorted[0] or False

            if next_picking:
                if next_picking.picking_type_id.code == 'outgoing':
                    return {
                        'type': 'ir.actions.client','tag': 'display_notification','params': {
                            'message': f"✅ Phiếu {picking.name} đã hoàn tất! Đang chờ xuất kho...",
                            'type': 'info','sticky': False
                        }
                    }
                else:
                    return {
                        'type': 'ir.actions.act_url',
                        'url': f"/custom_barcode_scan/pack_view/{next_picking.id}",
                        'target': 'self'
                    }

            return {
                'type': 'ir.actions.client','tag': 'display_notification','params': {
                    'message': "Không tìm thấy phiếu PACK phù hợp để xử lý!",
                    'type': 'warning','sticky': False
                }
            }

        return self._get_barcode_action(picking.id)

    def _get_barcode_action(self, picking_id):
        Picking = request.env['stock.picking'].sudo()
        picking = Picking.browse(picking_id)

        if not picking.exists():
            return {'type': 'ir.actions.client','tag': 'display_notification','params': {
                'message': f"Phiếu #{picking_id} không tồn tại.",'type': 'danger','sticky': False}}

        if not picking.picking_type_id:
            return {'type': 'ir.actions.client','tag': 'display_notification','params': {
                'message': "Phiếu không có loại chuyển kho, không thể mở giao diện barcode.",'type': 'danger','sticky': False}}

        if picking.picking_type_id.code not in ['out', 'pick']:
            return {'type': 'ir.actions.client','tag': 'display_notification','params': {
                'message': f"Phiếu {picking.name} không thuộc loại Pick hoặc Out. Không thể mở giao diện barcode.",'type': 'warning','sticky': False}}

        action = request.env.ref('stock_barcode.stock_barcode_picking_client_action').sudo().read()[0]
        action.update({'context': {'active_id': picking.id,'default_picking_type_id': picking.picking_type_id.id,
                                   'res_model': 'stock.picking','res_id': picking.id}})
        return action
