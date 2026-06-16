# -*- coding: utf-8 -*-
import logging
from html import escape
from odoo import models, fields, api

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    loyalty_points_earned = fields.Integer(
        string='Điểm tích lũy', readonly=True, copy=False,
        help='Số điểm loyalty được tích cho khách hàng từ phiếu giao này',
    )

    def button_validate(self):
        """Override để tích điểm khi giao hàng / thu hồi điểm khi trả hàng."""
        res = super().button_validate()
        for picking in self:
            if picking.state == 'done':
                picking._loyalty_earn_points()
                picking._loyalty_return_points()
        return res

    def _loyalty_earn_points(self):
        """Tích điểm loyalty khi phiếu xuất kho hoàn tất giao hàng."""
        self.ensure_one()

        # Chỉ áp dụng cho phiếu xuất kho giao hàng cho khách
        if self.picking_type_code != 'outgoing':
            return
        if not self.sale_id:
            return

        sale_order = self.sale_id
        partner = sale_order.partner_id
        if not partner:
            return

        root_partner = partner._get_loyalty_root()
        has_active_portal_account = self.env['hlv.loyalty.portal.account'].sudo().search_count([
            ('partner_id', '=', root_partner.id),
            ('active', '=', True),
        ])
        if not has_active_portal_account:
            return

        # Tìm chương trình loyalty đang active
        program = self.env['hlv.loyalty.program'].sudo().search([
            ('active', '=', True),
        ], limit=1)
        if not program:
            return

        # Tính tổng tiền hàng thực giao trong phiếu này (cho điểm xếp hạng)
        delivered_subtotal = sum(
            (move.sale_line_id.price_unit if move.sale_line_id
             else move.product_id.lst_price) * move.quantity
            for move in self.move_ids
            if move.state == 'done'
        )

        # ── Điểm xếp hạng: mỗi earning_amount tiền hàng = earning_points điểm ──
        ranking_points = 0
        if delivered_subtotal > 0 and program.earning_amount > 0:
            ranking_points = int(delivered_subtotal / program.earning_amount) * program.earning_points
        ranking_formula = self._format_loyalty_point_formula(
            'Điểm xếp hạng',
            delivered_subtotal,
            program.earning_amount,
            program.earning_points,
            ranking_points,
            multiplier_label='điểm/mốc',
        )
        ranking_formula_html = self._format_loyalty_point_formula_html(
            'Điểm xếp hạng',
            delivered_subtotal,
            program.earning_amount,
            program.earning_points,
            ranking_points,
            multiplier_label='điểm/mốc',
        )

        # ── Điểm đổi thưởng: dựa trên tiền chiết khấu ──
        discount_details = [
            self._get_loyalty_discount_detail_for_move(move)
            for move in self.move_ids
            if move.state == 'done' and move.sale_line_id
        ]
        discount_amount = sum(item['discount_amount'] for item in discount_details)
        discount_formula_source = 'Tổng chiết khấu loyalty theo dòng giao'
        # Fallback: không có dòng nào có amount/% loyalty → dùng % mặc định của contact
        if discount_amount <= 0:
            root_partner_lookup = partner._get_loyalty_root()
            # loyalty_default_discount lưu dạng 0-1 (Odoo convention: 0.05 = 5%)
            fallback_pct = root_partner_lookup.loyalty_default_discount or 0.0
            discount_amount = delivered_subtotal * fallback_pct
            discount_details = [
                self._get_loyalty_discount_detail_for_move(move, fallback_pct=fallback_pct)
                for move in self.move_ids
                if move.state == 'done'
            ]
            discount_formula_source = (
                'Doanh số giao x % chiết khấu mặc định KH '
                f'({fallback_pct:.2%})'
            )

        exchange_points = 0
        if discount_amount > 0 and program.discount_per_point > 0:
            exchange_points = int(discount_amount / program.discount_per_point)
        exchange_formula = self._format_loyalty_point_formula(
            'Điểm đổi thưởng',
            discount_amount,
            program.discount_per_point,
            1,
            exchange_points,
            source_label=discount_formula_source,
            detail_lines=discount_details,
        )
        exchange_formula_html = self._format_loyalty_point_formula_html(
            'Điểm đổi thưởng',
            discount_amount,
            program.discount_per_point,
            1,
            exchange_points,
            source_label=discount_formula_source,
            detail_lines=discount_details,
        )

        if ranking_points <= 0 and exchange_points <= 0:
            return

        # Kiểm tra xem phiếu này đã tích điểm chưa (tránh duplicate)
        existing = self.env['hlv.loyalty.history'].sudo().search([
            ('picking_id', '=', self.id),
            ('transaction_type', '=', 'earn'),
        ])
        if existing:
            ranking_hist = existing.filtered(lambda hist: hist.point_type == 'ranking')[:1]
            exchange_hist = existing.filtered(lambda hist: hist.point_type == 'exchange')[:1]
            if ranking_hist:
                ranking_hist.write({
                    'point_formula': ranking_formula,
                    'point_formula_html': ranking_formula_html,
                })
            if exchange_hist:
                exchange_hist.write({
                    'point_formula': exchange_formula,
                    'point_formula_html': exchange_formula_html,
                })
            return

        # Luôn tích vào công ty gốc (đi lên hết chuỗi parent_id)
        root_partner = partner._get_loyalty_root()

        base_vals = {
            'partner_id': root_partner.id,
            'transaction_type': 'earn',
            'picking_id': self.id,
            'sale_order_id': sale_order.id,
            'company_id': self.company_id.id,
            'sale_company_id': sale_order.company_id.id,
            'delivery_company_id': self.company_id.id,
        }

        # 1. Điểm xếp hạng – tự động xác nhận
        if ranking_points > 0:
            self.env['hlv.loyalty.history'].sudo().create({
                **base_vals,
                'point_amount': ranking_points,
                'point_type': 'ranking',
                'state': 'confirmed',
                'description': f'Tích điểm xếp hạng {sale_order.name} - Phiếu {self.name}',
                'point_formula': ranking_formula,
                'point_formula_html': ranking_formula_html,
            })

        # 2. Điểm đổi thưởng – chờ nhân viên xác nhận
        if exchange_points > 0:
            self.env['hlv.loyalty.history'].sudo().create({
                **base_vals,
                'point_amount': exchange_points,
                'point_type': 'exchange',
                'state': 'pending',
                'description': f'Tích điểm đổi thưởng {sale_order.name} - Phiếu {self.name}',
                'point_formula': exchange_formula,
                'point_formula_html': exchange_formula_html,
            })

        self.loyalty_points_earned = ranking_points
        _logger.info(
            'Loyalty: Tích ranking=%d exchange=%d cho %s từ phiếu %s (SO: %s)',
            ranking_points, exchange_points, partner.name, self.name, sale_order.name,
        )

    def _get_loyalty_discount_amount_for_move(self, move):
        """Return loyalty discount amount for one delivered move."""
        return self._get_loyalty_discount_detail_for_move(move)['discount_amount']

    def _get_loyalty_discount_detail_for_move(self, move, fallback_pct=None):
        """Return loyalty discount detail for one delivered move."""
        sale_line = move.sale_line_id
        product_name = move.product_id.display_name or ''
        qty = move.quantity or 0.0
        price_unit = sale_line.price_unit if sale_line else move.product_id.lst_price
        subtotal = price_unit * qty
        detail = {
            'product': product_name,
            'qty': qty,
            'price_unit': price_unit,
            'subtotal': subtotal,
            'source': 'Không tính điểm đổi thưởng',
            'discount_rate': 0.0,
            'discount_amount': 0.0,
        }

        if fallback_pct is not None:
            detail.update({
                'source': 'Fallback % mặc định khách hàng',
                'discount_rate': fallback_pct,
                'discount_amount': subtotal * fallback_pct,
            })
            return detail

        if not sale_line:
            return detail

        direct_amount = getattr(sale_line, 'x_studio_loyalty_discount_amount', 0.0) or 0.0
        if direct_amount > 0:
            ordered_qty = sale_line.product_uom_qty or 0.0
            if ordered_qty > 0:
                prorated_amount = direct_amount * min(qty / ordered_qty, 1.0)
            else:
                prorated_amount = direct_amount
            detail.update({
                'source': 'Số tiền CK loyalty trực tiếp trên dòng',
                'discount_rate': (prorated_amount / subtotal) if subtotal else 0.0,
                'discount_amount': prorated_amount,
                'direct_amount': direct_amount,
                'ordered_qty': ordered_qty,
            })
            return detail

        discount_pct = sale_line.loyalty_discount_pct or 0.0
        if discount_pct <= 0:
            return detail

        discount_rate = discount_pct if discount_pct <= 1.0 else discount_pct / 100.0
        detail.update({
            'source': 'CK loyalty % trên dòng bán hàng',
            'discount_rate': discount_rate,
            'discount_amount': subtotal * discount_rate,
        })
        return detail

    def _format_loyalty_point_formula(
        self, label, numerator, divisor, multiplier, points,
        source_label='', multiplier_label='', detail_lines=None,
    ):
        """Build a human-readable formula snapshot for QC."""
        self.ensure_one()
        if divisor <= 0:
            return f'{label}: không tính được vì cấu hình mẫu số <= 0.'

        base = (
            f'{label} = floor({numerator:,.0f} / {divisor:,.0f})'
        )
        if multiplier != 1:
            suffix = f' {multiplier_label}' if multiplier_label else ''
            base += f' x {multiplier:g}{suffix}'
        base += f' = {points:,} điểm'
        if source_label:
            base += f'\nNguồn tiền quy đổi: {source_label}.'
        if detail_lines:
            base += '\nChi tiết dòng giao:'
            for item in detail_lines:
                base += (
                    '\n- {product}: SL giao {qty:g} x đơn giá {price:,.0f}'
                    ' = {subtotal:,.0f}; {source}; tỷ lệ {rate:.2%};'
                    ' tiền quy đổi {discount:,.0f}'
                ).format(
                    product=item.get('product') or '',
                    qty=item.get('qty') or 0.0,
                    price=item.get('price_unit') or 0.0,
                    subtotal=item.get('subtotal') or 0.0,
                    source=item.get('source') or '',
                    rate=item.get('discount_rate') or 0.0,
                    discount=item.get('discount_amount') or 0.0,
                )
        return base

    def _format_loyalty_point_formula_html(
        self, label, numerator, divisor, multiplier, points,
        source_label='', multiplier_label='', detail_lines=None,
    ):
        """Build an HTML formula snapshot with line details in a table."""
        self.ensure_one()
        if divisor <= 0:
            return f'<p>{escape(label)}: không tính được vì cấu hình mẫu số &lt;= 0.</p>'

        formula = f'{label} = floor({numerator:,.0f} / {divisor:,.0f})'
        if multiplier != 1:
            suffix = f' {multiplier_label}' if multiplier_label else ''
            formula += f' x {multiplier:g}{suffix}'
        formula += f' = {points:,} điểm'

        parts = [
            '<div class="o_hlv_loyalty_formula">',
            f'<p><strong>{escape(formula)}</strong></p>',
        ]
        if source_label:
            parts.append(f'<p>Nguồn tiền quy đổi: {escape(source_label)}.</p>')

        if detail_lines:
            rows = []
            for item in detail_lines:
                rows.append(
                    '<tr>'
                    f'<td>{escape(item.get("product") or "")}</td>'
                    f'<td class="text-end">{item.get("qty") or 0.0:g}</td>'
                    f'<td class="text-end">{item.get("price_unit") or 0.0:,.0f}</td>'
                    f'<td class="text-end">{item.get("subtotal") or 0.0:,.0f}</td>'
                    f'<td>{escape(item.get("source") or "")}</td>'
                    f'<td class="text-end">{item.get("discount_rate") or 0.0:.2%}</td>'
                    f'<td class="text-end">{item.get("discount_amount") or 0.0:,.0f}</td>'
                    '</tr>'
                )
            parts.extend([
                '<div class="table-responsive">',
                '<table class="table table-sm table-bordered mb-0">',
                '<thead><tr>'
                '<th>Dòng hàng</th>'
                '<th class="text-end">SL giao</th>'
                '<th class="text-end">Đơn giá</th>'
                '<th class="text-end">Thành tiền</th>'
                '<th>Nguồn CK</th>'
                '<th class="text-end">Tỷ lệ</th>'
                '<th class="text-end">Tiền quy đổi</th>'
                '</tr></thead>',
                '<tbody>',
                ''.join(rows),
                '</tbody></table>',
                '</div>',
            ])
        parts.append('</div>')
        return ''.join(parts)

    def _loyalty_return_points(self):
        """Thu hồi điểm khi trả hàng.

        Hỗ trợ:
        - Hoàn toàn bộ và hoàn một phần (tính theo tỷ lệ qty)
        - Điểm đổi thưởng chưa xác nhận (pending): hủy/giảm bản ghi pending gốc,
          không tạo record âm vì điểm pending chưa vào số dư
        - Điểm đổi thưởng đã xác nhận (confirmed): tạo bản ghi âm để trừ số dư
        - Điểm xếp hạng (luôn confirmed): tạo bản ghi âm
        """
        self.ensure_one()

        # Nhận diện phiếu hoàn hàng bằng cách kiểm tra move có origin_returned_move_id
        # (đáng tin cậy hơn picking_type_code và tránh nhầm với PO receipt)
        returned_moves = self.move_ids.filtered(
            lambda m: m.state == 'done' and m.origin_returned_move_id
        )
        if not returned_moves:
            return

        # Tìm phiếu xuất kho gốc từ move đầu tiên (Odoo lưu link trực tiếp)
        origin_picking = returned_moves[0].origin_returned_move_id.picking_id
        if not origin_picking:
            return
        if origin_picking.picking_type_code != 'outgoing' or not origin_picking.sale_id:
            return
        if origin_picking.state != 'done':
            return

        partner = origin_picking.sale_id.partner_id
        if not partner:
            return

        # Kiểm tra đã xử lý chưa (tránh duplicate khi validate lại)
        existing = self.env['hlv.loyalty.history'].sudo().search([
            ('picking_id', '=', self.id),
            ('transaction_type', '=', 'return'),
        ], limit=1)
        if existing:
            return

        # ── Tính tỷ lệ hoàn hàng để khấu trừ đúng phần (hoàn một phần) ──────
        original_qty = sum(
            m.quantity for m in origin_picking.move_ids if m.state == 'done'
        )
        return_qty = sum(m.quantity for m in returned_moves)
        ratio = min(return_qty / original_qty, 1.0) if original_qty > 0 else 1.0
        is_full_return = ratio >= 0.999  # float tolerance

        ranking_to_deduct = round(origin_picking.loyalty_points_earned * ratio)

        # Tìm bản ghi điểm đổi thưởng của phiếu gốc (pending hoặc confirmed)
        origin_exchange_hist = self.env['hlv.loyalty.history'].sudo().search([
            ('picking_id', '=', origin_picking.id),
            ('point_type', '=', 'exchange'),
            ('transaction_type', '=', 'earn'),
            ('state', 'in', ['pending', 'confirmed']),
        ], limit=1)

        if ranking_to_deduct <= 0 and not origin_exchange_hist:
            return

        root_partner = partner._get_loyalty_root()
        pct_label = '' if is_full_return else f' ({int(ratio * 100)}%)'

        base_vals = {
            'partner_id': root_partner.id,
            'transaction_type': 'return',
            'picking_id': self.id,
            'sale_order_id': origin_picking.sale_id.id,
            'company_id': self.company_id.id,
            'sale_company_id': origin_picking.sale_id.company_id.id,
            'delivery_company_id': self.company_id.id,
        }

        # ── Điểm xếp hạng (luôn auto-confirmed) → tạo bản ghi âm ────────────
        if ranking_to_deduct > 0:
            self.env['hlv.loyalty.history'].sudo().create({
                **base_vals,
                'point_amount': -ranking_to_deduct,
                'point_type': 'ranking',
                'state': 'confirmed',
                'description': (
                    f'Thu hồi điểm xếp hạng do hoàn hàng {self.name}'
                    f' (gốc: {origin_picking.name}){pct_label}'
                ),
            })

        # ── Điểm đổi thưởng ──────────────────────────────────────────────────
        exchange_log = 0
        if origin_exchange_hist:
            exchange_original = origin_exchange_hist.point_amount
            exchange_to_deduct = round(exchange_original * ratio)
            exchange_log = exchange_to_deduct

            if origin_exchange_hist.state == 'pending':
                # Chưa xác nhận → chưa vào số dư khách hàng
                # → chỉ điều chỉnh bản ghi pending, KHÔNG tạo record âm
                if is_full_return:
                    # Hoàn toàn bộ: hủy bản ghi pending gốc
                    origin_exchange_hist.write({
                        'state': 'cancelled',
                        'description': (
                            origin_exchange_hist.description
                            + f' [Hủy do hoàn hàng {self.name}]'
                        ),
                    })
                else:
                    # Hoàn một phần: giảm điểm pending còn lại
                    # (khi nhân viên xác nhận sau, chỉ cộng phần chưa hoàn)
                    remaining = max(0, exchange_original - exchange_to_deduct)
                    origin_exchange_hist.write({
                        'point_amount': remaining,
                        'description': (
                            origin_exchange_hist.description
                            + f' [Đã giảm {exchange_to_deduct}đ do hoàn {self.name}]'
                        ),
                    })

            elif origin_exchange_hist.state == 'confirmed':
                # Đã xác nhận → đã vào số dư → tạo bản ghi âm để khấu trừ
                if exchange_to_deduct > 0:
                    self.env['hlv.loyalty.history'].sudo().create({
                        **base_vals,
                        'point_amount': -exchange_to_deduct,
                        'point_type': 'exchange',
                        'state': 'confirmed',
                        'description': (
                            f'Thu hồi điểm đổi thưởng (đã XN) do hoàn hàng {self.name}'
                            f' (gốc: {origin_picking.name}){pct_label}'
                        ),
                    })

        _logger.info(
            'Loyalty: Thu hồi ranking=%d exchange=%d (ratio=%.0f%%) từ %s'
            ' do hoàn hàng %s (gốc: %s)',
            ranking_to_deduct, exchange_log, ratio * 100,
            partner.name, self.name, origin_picking.name,
        )
