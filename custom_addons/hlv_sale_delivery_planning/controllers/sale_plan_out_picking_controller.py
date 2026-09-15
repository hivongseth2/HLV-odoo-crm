# -*- coding: utf-8 -*-
"""API chỉ-đọc cho nút "Xem phiếu xuất kho" trong drawer trang /sale_plan.

Tính năng này cố ý tách rời để sau này gỡ bỏ không ảnh hưởng phần còn lại:

    - Backend: chỉ file này.
    - UI: chỉ static/src/sale_plan_out_picking/sale_plan_out_picking.js.
    - Móc vào code cũ đúng 3 chỗ (đều có comment "XEM PHIẾU XUẤT KHO"):
        controllers/__init__.py          → 1 dòng import
        controllers/sale_plan_controller.py → 1 dòng CustomEvent cuối openDrawer
                                           → 1 thẻ <script src> trước </body>

Gỡ tính năng = xoá 2 file + 3 dòng trên, không đụng model/payload nào khác.

Chỉ đọc: không có route nào ghi dữ liệu. Phiếu luôn được lấy qua sale order
(so.picking_ids) nên người dùng không thể đọc phiếu của đơn khác bằng cách
đoán picking_id.
"""

import logging
from collections import OrderedDict

from odoo import http, tools
from odoo.http import request

from ..services.kit_qty_utils import kit_qty_from_components
from ..services.sale_line_amount_utils import compute_line_amounts
from .picking_export_helper import (
    PICKING_STATE_LABELS,
    _format_date_done,
    _get_tz,
)

_logger = logging.getLogger(__name__)

# Chỉ phiếu giao cho khách. PICK/PACK nội bộ đã có màn hình riêng trên /sale_plan.
_OUT_PICKING_CODE = 'outgoing'


def _picking_sort_key(picking):
    """Mới nhất lên đầu: ưu tiên ngày hoàn tất, chưa xong thì theo ngày dự kiến."""
    return (picking.date_done or picking.scheduled_date or picking.create_date, picking.id)


class SalePlanOutPickingController(http.Controller):
    """Danh sách + chi tiết phiếu xuất kho của một đơn bán (chỉ xem)."""

    def _resolve_order(self, order_id):
        """Trả về sale order đã browse, hoặc None nếu id rỗng/không tồn tại."""
        try:
            order = request.env['sale.order'].sudo().browse(int(order_id or 0))
        except (TypeError, ValueError):
            return None
        return order if order.exists() else None

    def _out_pickings(self, order):
        pickings = order.picking_ids.filtered(
            lambda p: p.picking_type_id.code == _OUT_PICKING_CODE
        )
        return sorted(pickings, key=_picking_sort_key, reverse=True)

    def _picking_summary(self, picking, utc_tz, user_tz):
        """Một dòng trong danh sách phiếu xuất kho."""
        moves = picking.move_ids.filtered(lambda m: m.state != 'cancel')
        return {
            'id': picking.id,
            'name': picking.name or '',
            'state': picking.state,
            'state_label': PICKING_STATE_LABELS.get(picking.state, picking.state or ''),
            'scheduled_date': _format_date_done(picking.scheduled_date, utc_tz, user_tz),
            'date_done': _format_date_done(picking.date_done, utc_tz, user_tz),
            'warehouse_name': picking.picking_type_id.warehouse_id.name or '',
            'line_count': len(moves),
            'qty_done': sum(moves.mapped('quantity')),
            'qty_demand': sum(moves.mapped('product_uom_qty')),
            'delivery_type': picking.x_pick_delivery_type or '',
            'backorder_of': picking.backorder_id.name if picking.backorder_id else '',
        }

    def _move_breakdown(self, move):
        """Kiện/lô của một move — chỉ trả dòng nào thực sự có kiện hoặc lô."""
        breakdown = []
        for line in move.move_line_ids:
            package = line.result_package_id.name or ''
            lot = line.lot_id.name or ''
            if not package and not lot:
                continue
            breakdown.append({
                'package': package,
                'lot': lot,
                'qty': line.quantity,
            })
        return breakdown

    def _move_row(self, move):
        """Một move hiển thị thô: sản phẩm, ĐVT, yêu cầu, thực giao, kiện/lô."""
        return {
            'product_name': move.product_id.display_name or '',
            'uom_name': move.product_uom.name or '',
            'qty_demand': move.product_uom_qty,
            'qty_done': move.quantity,
            'breakdown': self._move_breakdown(move),
        }

    def _phantom_bom_by_product(self, products):
        """{product_id: mrp.bom phantom} cho các sản phẩm truyền vào.

        Tìm theo product_tmpl_id rồi ưu tiên BOM gắn đúng biến thể — cùng cách
        nhận diện kit mà dashboard đang dùng (services/delivery_planner_formatter.py).
        """
        if not products or 'mrp.bom' not in request.env:
            return {}
        boms = request.env['mrp.bom'].sudo().search([
            ('product_tmpl_id', 'in', products.product_tmpl_id.ids),
            ('type', '=', 'phantom'),
        ])
        by_product, by_template = {}, {}
        for bom in boms:
            if bom.product_id:
                by_product[bom.product_id.id] = bom
            else:
                by_template.setdefault(bom.product_tmpl_id.id, bom)
        return {
            product.id: by_product.get(product.id) or by_template.get(product.product_tmpl_id.id)
            for product in products
            if by_product.get(product.id) or by_template.get(product.product_tmpl_id.id)
        }

    def _picking_detail_lines(self, picking):
        """Dòng hàng của phiếu, gom theo DÒNG ĐƠN BÁN chứ không theo move.

        Combo (phantom BOM) nổ ra nhiều move thành phần nhưng tất cả cùng trỏ về
        một dòng SO. Tính tiền theo từng move thì mỗi thành phần ăn trọn đơn giá
        của cả combo → tổng tiền phình lên đúng bằng số thành phần. Vì vậy: gom
        move theo sale_line, quy SL thành phần về số BỘ combo, rồi mới tính tiền
        một lần cho cả dòng; các move thành phần chỉ hiển thị làm chi tiết.
        """
        moves = picking.move_ids.filtered(lambda m: m.state != 'cancel')
        groups = OrderedDict()
        extras = []
        for move in moves:
            sale_line = move.sale_line_id
            if not sale_line:
                # Move thêm tay trong phiếu, không gắn dòng SO → không có tiền.
                extras.append(move)
                continue
            groups.setdefault(sale_line.id, {'sale_line': sale_line, 'moves': []})
            groups[sale_line.id]['moves'].append(move)

        sale_products = request.env['product.product'].browse(list({
            group['sale_line'].product_id.id
            for group in groups.values() if group['sale_line'].product_id
        }))
        bom_by_product = self._phantom_bom_by_product(sale_products)

        lines = []
        for group in groups.values():
            sale_line = group['sale_line']
            group_moves = group['moves']
            bom = bom_by_product.get(sale_line.product_id.id)
            # Kit thật sự khi BOM phantom có và move mang sản phẩm thành phần.
            is_kit = bool(bom) and any(
                move.product_id != sale_line.product_id for move in group_moves
            )
            if is_kit:
                done_by_product, demand_by_product = {}, {}
                for move in group_moves:
                    done_by_product[move.product_id.id] = (
                        done_by_product.get(move.product_id.id, 0.0) + move.quantity
                    )
                    demand_by_product[move.product_id.id] = (
                        demand_by_product.get(move.product_id.id, 0.0) + move.product_uom_qty
                    )
                qty_done = kit_qty_from_components(
                    bom, lambda comp: done_by_product.get(comp.id, 0.0)
                )
                qty_demand = kit_qty_from_components(
                    bom, lambda comp: demand_by_product.get(comp.id, 0.0)
                )
                components = [self._move_row(move) for move in group_moves]
                breakdown = []
            else:
                qty_done = sum(move.quantity for move in group_moves)
                qty_demand = sum(move.product_uom_qty for move in group_moves)
                components = []
                breakdown = [
                    item for move in group_moves for item in self._move_breakdown(move)
                ]

            amounts = compute_line_amounts(sale_line, qty_done)
            lines.append({
                'has_amount': True,
                'product_name': sale_line.product_id.display_name or '',
                'uom_name': sale_line.product_uom.name or '',
                'qty_demand': qty_demand,
                'qty_done': qty_done,
                'is_kit': is_kit,
                'components': components,
                'breakdown': breakdown,
                'price_unit': round(amounts['price_unit'], 0),
                'discount': amounts['discount'],
                'delivered_subtotal': round(amounts['subtotal'], 0),
                'delivered_tax': round(amounts['tax'], 0),
                'delivered_total': round(amounts['total'], 0),
            })

        for move in extras:
            row = self._move_row(move)
            # Không gắn dòng SO thì không có đơn giá để tính — FE hiện dấu "—".
            row.update({
                'has_amount': False,
                'is_kit': False,
                'components': [],
                'price_unit': 0.0,
                'discount': 0.0,
                'delivered_subtotal': 0.0,
                'delivered_tax': 0.0,
                'delivered_total': 0.0,
            })
            lines.append(row)
        return lines

    def _picking_detail(self, picking, order, utc_tz, user_tz):
        """Thông tin đầy đủ của một phiếu: giao cái gì, giao khi nào, ai giao."""
        # shipper_* do module giao nhận khác thêm vào — dùng getattr để trang vẫn
        # chạy được khi module đó chưa cài.
        shipper_user = getattr(picking, 'shipper_user_id', False)
        detail = self._picking_summary(picking, utc_tz, user_tz)
        detail.update({
            'type_name': picking.picking_type_id.name or '',
            'order_name': order.name or '',
            # display_name của liên hệ con là "công ty, tên liên hệ" — với khách
            # có contact trùng tên công ty thì ra chuỗi lặp 2 lần. Lấy liên hệ gốc.
            'partner_name': (
                picking.partner_id.commercial_partner_id.name
                or picking.partner_id.name
                or ''
            ),
            'shipping_address': (
                getattr(order, 'misa_shipping_address', '')
                or getattr(picking.partner_id, 'contact_address_complete', '')
                or picking.partner_id.contact_address
                or ''
            ),
            'origin': picking.origin or '',
            'create_date': _format_date_done(picking.create_date, utc_tz, user_tz),
            'responsible': picking.user_id.name or '',
            'shipper_name': (
                getattr(shipper_user, 'shipper_name', None) or shipper_user.name
                if shipper_user else ''
            ),
            'shipper_received': bool(getattr(picking, 'shipper_received', False)),
            'htgh': getattr(order, 'x_studio_htgh', '') or '',
            'note': tools.html2plaintext(picking.note or '') if picking.note else '',
            'lines': self._picking_detail_lines(picking),
        })
        return detail

    @http.route('/api/sale_plan/out_pickings', type='json', auth='user', methods=['POST'])
    def api_sale_plan_out_pickings(self, order_id=None, **kwargs):
        """Danh sách phiếu xuất kho của một đơn bán."""
        try:
            order = self._resolve_order(order_id)
            if not order:
                return {'status': 'error', 'message': 'Không tìm thấy đơn hàng.'}
            utc_tz, user_tz = _get_tz()
            return {
                'status': 'success',
                'order_name': order.name or '',
                'pickings': [
                    self._picking_summary(picking, utc_tz, user_tz)
                    for picking in self._out_pickings(order)
                ],
            }
        except Exception as e:
            _logger.exception('sale_plan out_pickings error')
            return {'status': 'error', 'message': str(e)}

    @http.route('/api/sale_plan/out_picking_detail', type='json', auth='user', methods=['POST'])
    def api_sale_plan_out_picking_detail(self, order_id=None, picking_id=None, **kwargs):
        """Chi tiết một phiếu xuất kho — bắt buộc thuộc đúng đơn được truyền vào."""
        try:
            order = self._resolve_order(order_id)
            if not order:
                return {'status': 'error', 'message': 'Không tìm thấy đơn hàng.'}
            try:
                picking_id = int(picking_id or 0)
            except (TypeError, ValueError):
                picking_id = 0
            picking = next(
                (p for p in self._out_pickings(order) if p.id == picking_id),
                None,
            )
            if picking is None:
                return {'status': 'error', 'message': 'Phiếu không thuộc đơn hàng này.'}
            utc_tz, user_tz = _get_tz()
            return {
                'status': 'success',
                'picking': self._picking_detail(picking, order, utc_tz, user_tz),
            }
        except Exception as e:
            _logger.exception('sale_plan out_picking_detail error')
            return {'status': 'error', 'message': str(e)}
