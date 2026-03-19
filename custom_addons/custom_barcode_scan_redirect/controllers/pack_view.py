# -*- coding: utf-8 -*-
"""Pack view page route (/custom_barcode_scan/pack_view/<id>)."""
from odoo import http
from odoo.http import request
import logging

from ._shared import get_ml_demand

_logger = logging.getLogger(__name__)


class PackViewController(http.Controller):

    @http.route('/custom_barcode_scan/pack_view/<int:picking_id>', type='http', auth='user')
    def view_pack_products(self, picking_id):
        _logger.info(f"🔍 Đang vào pack_view với ID: {picking_id}")

        picking = request.env['stock.picking'].sudo().browse(picking_id)
        if not picking.exists():
            _logger.error("❌ Không tìm thấy phiếu pack!")
            return request.not_found()

        # Auto-assign: Nếu phiếu PACK chưa được assign, tự động gọi action_assign
        if picking.state in ['confirmed', 'waiting']:
            try:
                _logger.info(f"[PACK_VIEW] Auto-assigning picking {picking.name} (state: {picking.state})")
                picking.action_assign()
                picking = request.env['stock.picking'].sudo().browse(picking_id)
                _logger.info(f"[PACK_VIEW] After assign: state={picking.state}, move_lines={len(picking.move_line_ids)}")
            except Exception as e:
                _logger.warning(f"[PACK_VIEW] Auto-assign failed: {e}")

        lines = picking.move_ids_without_package.filtered(lambda m: m.product_id)

        # Tìm PICK gốc để hiển thị
        origin_pick = request.env['stock.picking'].sudo().search([
            ('group_id', '=', picking.group_id.id),
            ('picking_type_id.sequence_code', 'like', 'PICK'),
            ('id', '!=', picking.id)
        ], limit=1)

        drive_connected = bool(request.env['ir.config_parameter'].sudo().get_param('gdrive.user_credentials_json'))

        # Lấy tất cả PACK còn xử lý được để show panel chọn nhanh
        siblings = request.env['stock.picking'].sudo().search([
            ('group_id', '=', picking.group_id.id),
            ('picking_type_id.sequence_code', 'like', 'PACK'),
            ('id', '!=', picking.id),
            ('state', 'in', ['confirmed', 'assigned', 'waiting', 'in_progress']),
        ])

        def _priority(p):
            s = (p.state or '')
            if s == 'assigned': return (0, p.id)
            if s == 'in_progress': return (1, p.id)
            return (2, p.id)

        siblings_sorted = sorted(siblings, key=_priority)

        state_label = {
            'draft': 'Nháp',
            'waiting': 'Chờ',
            'confirmed': 'Xác nhận',
            'assigned': 'Sẵn sàng',
            'in_progress': 'Đang làm',
            'done': 'Hoàn tất',
            'cancel': 'Hủy',
        }

        sibling_packs = [{
            'id': s.id,
            'name': s.name,
            'state': s.state,
            'state_label': state_label.get(s.state, s.state),
        } for s in siblings_sorted]

        # Lấy danh sách packages
        picking_packages = self._build_package_list(picking, origin_pick)

        # Check nếu có move_line nào đang có package → hiện nút "Bỏ đóng gói"
        has_packed_lines = bool(picking.move_line_ids.filtered(
            lambda l: l.package_id or l.result_package_id
        ))

        return request.render("custom_barcode_scan_redirect.pack_scan_template", {
            'picking': picking,
            'lines': lines,
            'origin_pick_name': origin_pick.name if origin_pick else '',
            'drive_connected': drive_connected,
            'sibling_packs': sibling_packs,
            'picking_packages': picking_packages,
            'has_packed_lines': has_packed_lines,
        })

    def _build_package_list(self, picking, origin_pick):
        """Collect packages from current picking + origin PICK."""
        picking_packages = []

        # 1. Packages từ phiếu PACK hiện tại
        all_pkgs = (picking.move_line_ids.mapped('result_package_id') | picking.move_line_ids.mapped('package_id'))

        # 2. Truy vết packages từ phiếu PICK gốc qua move_orig_ids
        origin_pkgs = request.env['stock.quant.package'].sudo()
        origin_pkg_mls_map = {}

        for move in picking.move_ids:
            for orig_move in move.move_orig_ids:
                for orig_ml in orig_move.move_line_ids:
                    if orig_ml.result_package_id:
                        origin_pkgs |= orig_ml.result_package_id
                        pkg_id = orig_ml.result_package_id.id
                        if pkg_id not in origin_pkg_mls_map:
                            origin_pkg_mls_map[pkg_id] = request.env['stock.move.line'].sudo()
                        origin_pkg_mls_map[pkg_id] |= orig_ml

        # 3. Gộp tất cả packages
        all_pkgs = all_pkgs | origin_pkgs

        _logger.info(f"[PACK_VIEW] Picking {picking.name}: Found {len(all_pkgs)} packages (local + origin)")

        if not all_pkgs:
            return picking_packages

        for pkg in all_pkgs:
            pkg_mls = picking.move_line_ids.filtered(
                lambda ml: ml.result_package_id.id == pkg.id or ml.package_id.id == pkg.id
            )

            is_from_origin = False
            if not pkg_mls and pkg.id in origin_pkg_mls_map:
                pkg_mls = origin_pkg_mls_map[pkg.id]
                is_from_origin = True
                _logger.info(f"[PACK_VIEW] Package {pkg.name} loaded from origin PICK with {len(pkg_mls)} lines")

            if not pkg_mls:
                continue

            if is_from_origin:
                total_demand = sum(getattr(ml, 'quantity', 0) or getattr(ml, 'qty_done', 0) or 0 for ml in pkg_mls)
                total_done = total_demand
                package_lines = [{
                    'product_name': ml.product_id.display_name,
                    'done_qty': getattr(ml, 'quantity', 0) or getattr(ml, 'qty_done', 0) or 0,
                    'demand_qty': getattr(ml, 'quantity', 0) or getattr(ml, 'qty_done', 0) or 0,
                    'product_uom': ml.product_uom_id.name,
                } for ml in pkg_mls]
            else:
                total_done = sum(ml.qty_done for ml in pkg_mls)
                total_demand = sum(get_ml_demand(ml) for ml in pkg_mls)
                package_lines = [{
                    'product_name': ml.product_id.display_name,
                    'done_qty': ml.qty_done,
                    'demand_qty': get_ml_demand(ml),
                    'product_uom': ml.product_uom_id.name,
                } for ml in pkg_mls]

            picking_packages.append({
                'id': pkg.id,
                'name': pkg.name,
                'done_qty': total_done,
                'demand_qty': total_demand,
                'package_lines': package_lines,
                'is_from_origin': is_from_origin,
            })

        return picking_packages
