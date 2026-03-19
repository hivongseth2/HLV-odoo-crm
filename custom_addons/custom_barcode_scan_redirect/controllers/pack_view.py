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

        # Block truy cập phiếu đã hoàn tất hoặc đã hủy
        if picking.state in ('done', 'cancel'):
            _logger.warning(f"[PACK_VIEW] Blocked: picking {picking.name} is {picking.state}")
            return request.redirect('/custom_barcode_scan/ui')

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

        # Check nếu có move_line nào đang có result_package → hiện nút "Bỏ đóng gói"
        has_packed_lines = bool(picking.move_line_ids.filtered(
            lambda l: l.result_package_id
        ))

        # Detect re-pack: có source package (package_id) nhưng chưa có destination package
        # → hàng nằm trong kiện cũ, cần đóng gói lại
        has_source_packages = bool(picking.move_line_ids.filtered(
            lambda l: l.package_id and not l.result_package_id
        ))
        is_repack = has_source_packages and not has_packed_lines

        return request.render("custom_barcode_scan_redirect.pack_scan_template", {
            'picking': picking,
            'lines': lines,
            'origin_pick_name': origin_pick.name if origin_pick else '',
            'drive_connected': drive_connected,
            'sibling_packs': sibling_packs,
            'picking_packages': picking_packages,
            'has_packed_lines': has_packed_lines,
            'is_repack': is_repack,
        })

    def _build_package_list(self, picking, origin_pick):
        """Collect DESTINATION packages from current picking.
        Only shows packages being created (result_package_id),
        NOT source packages (package_id) to avoid confusion in re-pack scenarios.
        """
        picking_packages = []

        # Chỉ lấy packages ĐÍCH (result_package_id) — kiện đang được tạo/đóng gói
        all_pkgs = picking.move_line_ids.mapped('result_package_id')

        _logger.info(f"[PACK_VIEW] Picking {picking.name}: Found {len(all_pkgs)} destination packages")

        if not all_pkgs:
            return picking_packages

        for pkg in all_pkgs:
            pkg_mls = picking.move_line_ids.filtered(
                lambda ml: ml.result_package_id.id == pkg.id
            )

            if not pkg_mls:
                continue

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
            })

        return picking_packages
