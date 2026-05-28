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

        try:
            picking.with_user(request.env.user).mark_pack_actual_started(user=request.env.user)
        except Exception as e:
            _logger.warning("[PACK_VIEW] Access blocked for %s: %s", picking.name, e)
            return request.make_response(
                "<div style='font-family:Segoe UI,Arial;padding:24px'>"
                "<h3>Không thể vào phiếu đóng gói</h3>"
                f"<p>{str(e)}</p>"
                "<a href='/custom_barcode_scan/ui'>Quay lại màn quét</a>"
                "</div>",
                headers=[('Content-Type', 'text/html; charset=utf-8')],
            )

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

        # Auto-clean: Xử lý hàng từ kiện cũ (pass-through lines)
        if picking.state in ['assigned', 'confirmed', 'in_progress']:
            if self._auto_clean_source_packages(picking):
                return request.redirect(f'/custom_barcode_scan/pack_view/{picking_id}')

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

        response = request.render("custom_barcode_scan_redirect.pack_scan_template", {
            'picking': picking,
            'lines': lines,
            'origin_pick_name': origin_pick.name if origin_pick else '',
            'drive_connected': drive_connected,
            'sibling_packs': sibling_packs,
            'picking_packages': picking_packages,
            'has_packed_lines': has_packed_lines,
            'is_repack': is_repack,
        })
        response.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        return response

    def _auto_clean_source_packages(self, picking):
        """Auto-clean pass-through package lines for re-pack scenarios.

        When goods are reserved from packages, Odoo creates move lines with
        package_id=X AND result_package_id=X (pass-through). These phantom lines
        cause double-counting in our scanning flow. This cleanup:
        1. Unreserves to remove phantom lines (qty_done=0)
        2. Moves quants out of source packages to loose
        3. Re-reserves to create clean loose lines
        """
        pass_through = picking.move_line_ids.filtered(
            lambda l: l.package_id and l.result_package_id
                      and l.package_id.id == l.result_package_id.id
        )
        if not pass_through:
            return False

        source_packages = pass_through.mapped('package_id')
        location = picking.location_id

        _logger.info(
            "[AUTO-CLEAN] %s: %d pass-through lines, packages: %s",
            picking.name, len(pass_through), source_packages.mapped('name')
        )

        try:
            # Step 1: Unreserve — removes pass-through lines (qty_done=0), keeps packed lines
            picking.do_unreserve()

            # Step 2: Move quants out of source packages to loose
            Quant = request.env['stock.quant'].sudo()
            for pkg in source_packages:
                pkg_quants = Quant.search([
                    ('package_id', '=', pkg.id),
                    ('location_id', '=', location.id),
                    ('quantity', '!=', 0),
                ])
                for q in pkg_quants:
                    existing = Quant.search([
                        ('product_id', '=', q.product_id.id),
                        ('location_id', '=', q.location_id.id),
                        ('lot_id', '=', q.lot_id.id if q.lot_id else False),
                        ('package_id', '=', False),
                        ('owner_id', '=', q.owner_id.id if q.owner_id else False),
                    ], limit=1)
                    if existing:
                        existing.quantity += q.quantity
                    else:
                        Quant.create({
                            'product_id': q.product_id.id,
                            'location_id': q.location_id.id,
                            'lot_id': q.lot_id.id if q.lot_id else False,
                            'package_id': False,
                            'owner_id': q.owner_id.id if q.owner_id else False,
                            'quantity': q.quantity,
                        })
                    q.quantity = 0
                _logger.info("[AUTO-CLEAN] Moved quants out of %s", pkg.name)

            # Step 3: Re-reserve with clean loose quants
            picking.action_assign()
            _logger.info("[AUTO-CLEAN] %s: cleanup complete", picking.name)
            return True

        except Exception as e:
            _logger.exception("[AUTO-CLEAN] Error cleaning %s: %s", picking.name, e)
            return False

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
