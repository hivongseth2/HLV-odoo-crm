# -*- coding: utf-8 -*-
from odoo import models, api, fields
import logging

_logger = logging.getLogger(__name__)


class PosOrder(models.Model):
    _inherit = 'pos.order'

    def _create_order_picking(self):
        res = super()._create_order_picking()
        self._fix_multi_location_returns()
        return res

    # ------------------------------------------------------------------
    # Multi-location return: tách move lines theo đúng kệ gốc
    # ------------------------------------------------------------------
    def _fix_multi_location_returns(self):
        """Sau khi picking được tạo & validate, kiểm tra nếu đơn gốc xuất
        từ nhiều vị trí thì tách move lines của phiếu hoàn cho đúng."""
        for order in self:
            refund_lines = order.lines.filtered(
                lambda l: l.qty < 0 and l.refunded_orderline_id
            )
            if not refund_lines:
                continue

            # Phiếu hoàn: src = Customer
            return_pickings = order.picking_ids.filtered(
                lambda p: p.state == 'done' and p.location_id.usage == 'customer'
            )

            for picking in return_pickings:
                for move in picking.move_ids:
                    self._process_return_move(move, refund_lines)

    def _process_return_move(self, return_move, refund_lines):
        """Kiểm tra 1 stock.move hoàn có cần tách multi-location không."""
        matching_refund = refund_lines.filtered(
            lambda l: l.product_id == return_move.product_id
        )
        if not matching_refund or not matching_refund[0].refunded_orderline_id:
            return

        orig_order = matching_refund[0].refunded_orderline_id.order_id

        # Tìm move lines xuất gốc cho sản phẩm này
        orig_mls = orig_order.sudo().picking_ids.move_line_ids.filtered(
            lambda ml: ml.product_id == return_move.product_id
            and ml.quantity > 0
            and ml.location_dest_id.usage == 'customer'
        )
        if not orig_mls:
            orig_mls = orig_order.sudo().picking_ids.move_line_ids.filtered(
                lambda ml: ml.product_id == return_move.product_id and ml.quantity > 0
            )

        # Group theo vị trí nguồn (= vị trí cần hoàn về)
        loc_qty = {}
        for ml in orig_mls:
            loc = ml.location_id
            loc_qty[loc] = loc_qty.get(loc, 0) + ml.quantity

        if len(loc_qty) <= 1:
            return  # 1 vị trí → _prepare_stock_move_vals đã xử lý đúng

        self._redistribute_return_move(return_move, loc_qty)

    def _redistribute_return_move(self, return_move, orig_loc_qty):
        """Tách move lines của phiếu hoàn để mỗi kệ nhận đúng SL gốc.

        Luồng:
        1. Tính phân bổ SL hoàn cho từng vị trí
        2. Snapshot quant TRƯỚC thay đổi
        3. Sửa move lines (write + copy)
        4. Snapshot quant SAU thay đổi → fix delta
        """
        total_return = return_move.quantity
        if total_return <= 0:
            return

        # --- Tính phân bổ ---
        remaining = total_return
        distribution = []
        for loc, orig_qty in orig_loc_qty.items():
            alloc = min(orig_qty, remaining)
            if alloc > 0:
                distribution.append((loc, alloc))
                remaining -= alloc
            if remaining <= 0:
                break

        # Phần dư (hoàn nhiều hơn gốc) → dồn vào vị trí đầu
        if remaining > 0 and distribution:
            distribution[0] = (distribution[0][0], distribution[0][1] + remaining)

        if len(distribution) <= 1:
            return

        current_mls = return_move.move_line_ids
        if not current_mls:
            return

        product = return_move.product_id
        first_ml = current_mls[0]
        wrong_dest = first_ml.location_dest_id

        # Thông tin lot/package/owner để match quant chính xác
        lot = first_ml.lot_id
        pkg = first_ml.result_package_id
        owner = first_ml.owner_id

        Quant = self.env['stock.quant'].sudo()

        # Tập hợp tất cả locations bị ảnh hưởng
        affected_locs = {wrong_dest}
        for loc, _qty in distribution:
            affected_locs.add(loc)

        # --- Snapshot quant TRƯỚC ---
        before_quants = {}
        for loc in affected_locs:
            before_quants[loc.id] = self._get_quant_qty(Quant, product, loc, lot, pkg, owner)

        try:
            # === Sửa Move Lines ===
            first_loc, first_qty = distribution[0]
            first_ml.sudo().write({
                'quantity': first_qty,
                'location_dest_id': first_loc.id,
            })

            for loc, qty in distribution[1:]:
                first_ml.sudo().copy(default={
                    'quantity': qty,
                    'location_dest_id': loc.id,
                })

            # === Reconcile Quants ===
            # Trạng thái mong muốn:
            #   wrong_dest: before - total_return + (phần thuộc wrong_dest nếu có)
            #   other locs: before + phần phân bổ
            expected_quants = dict(before_quants)
            expected_quants[wrong_dest.id] -= total_return  # undo sai
            for loc, qty in distribution:
                expected_quants[loc.id] = expected_quants.get(loc.id, 0) + qty

            # So sánh actual vs expected → fix delta
            for loc in affected_locs:
                actual = self._get_quant_qty(Quant, product, loc, lot, pkg, owner)
                expected = expected_quants.get(loc.id, 0)
                diff = expected - actual

                if abs(diff) > 0.001:
                    Quant._update_available_quantity(
                        product, loc, diff,
                        lot_id=lot or None,
                        package_id=pkg or None,
                        owner_id=owner or None,
                    )
                    _logger.info(
                        "[HLV POS RETURN] Quant fix: %s @ %s: %+.2f",
                        product.name, loc.complete_name, diff,
                    )

            _logger.info(
                "[HLV POS RETURN] Split return %s → %s",
                product.name,
                ' | '.join(f"{loc.complete_name}: {qty}" for loc, qty in distribution),
            )

        except Exception as e:
            _logger.error("[HLV POS RETURN] Error in _redistribute_return_move: %s", str(e))

    @staticmethod
    def _get_quant_qty(Quant, product, location, lot, pkg, owner):
        """Trả về on-hand quantity cho product tại location (exact match)."""
        domain = [
            ('product_id', '=', product.id),
            ('location_id', '=', location.id),
            ('lot_id', '=', lot.id if lot else False),
            ('package_id', '=', pkg.id if pkg else False),
            ('owner_id', '=', owner.id if owner else False),
        ]
        quants = Quant.search(domain)
        return sum(quants.mapped('quantity'))

class PosOrderLine(models.Model):
    _inherit = 'pos.order.line'

    hlv_source_location_id = fields.Many2one(
        'stock.location',
        string='POS Source Location',
        help='Stock source location selected from the POS interface for this line.',
    )
    hlv_source_location_allocations = fields.Text(
        string='POS Source Location Allocations',
        help='JSON allocation of POS line quantity by source stock location.',
    )

    @api.model
    def _load_pos_data_fields(self, config_id):
        fields_list = super()._load_pos_data_fields(config_id)
        if 'hlv_source_location_id' not in fields_list:
            fields_list.append('hlv_source_location_id')
        if 'hlv_source_location_allocations' not in fields_list:
            fields_list.append('hlv_source_location_allocations')
        return fields_list
