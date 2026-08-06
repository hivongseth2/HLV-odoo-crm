# -*- coding: utf-8 -*-
import logging
from collections import defaultdict
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
        delivered_lines = self._get_loyalty_delivered_lines()
        delivered_subtotal = sum(
            (line['price_unit'] or 0.0) * (line['qty'] or 0.0) for line in delivered_lines
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
        exchange_points, exchange_formula, exchange_formula_html = (
            self._compute_loyalty_exchange_points(program, delivered_lines, delivered_subtotal, partner)
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
                # Điểm xếp hạng luôn tự động confirmed ngay khi tạo (đã vào
                # số dư) → chỉ cập nhật công thức để đối chiếu, không tự
                # sửa point_amount đã chốt.
                ranking_hist.write({
                    'point_formula': ranking_formula,
                    'point_formula_html': ranking_formula_html,
                })
            if exchange_hist and exchange_hist.state == 'pending':
                # Điểm đổi thưởng đang chờ xác nhận: CHƯA vào số dư khách
                # hàng → an toàn để tính lại đúng số điểm mới nhất (VD:
                # sale vừa sửa % CK loyalty trên dòng bán hàng, hoặc dữ
                # liệu combo/kit vừa được tính đúng lại).
                exchange_hist.write({
                    'point_amount': exchange_points,
                    'point_formula': exchange_formula,
                    'point_formula_html': exchange_formula_html,
                })
            elif exchange_hist:
                # Đã xác nhận (đã vào số dư) → chỉ cập nhật công thức để
                # đối chiếu, không tự sửa point_amount đã chốt.
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

    def _get_loyalty_delivered_lines(self):
        """Gom các stock.move đã giao (state=done) của phiếu này thành các
        'dòng giao' logic, mỗi sale.order.line chỉ tính đúng 1 lần.

        Sản phẩm combo/kit (BOM loại Kit - phantom) không có move riêng cho
        chính nó: khi giao hàng, Odoo nổ nhu cầu thành nhiều move theo từng
        thành phần, nhưng TẤT CẢ các move thành phần đó đều trỏ về CÙNG 1
        sale_line_id (dòng combo) - dòng duy nhất có price_unit là giá của
        cả combo. Nếu lấy giá đó gán cho từng move thành phần rồi cộng dồn
        theo move như trước, thành tiền loyalty sẽ bị nhân lên theo số
        lượng thành phần trong combo (VD combo có 3 thành phần → tính tiền
        x3). Vì vậy các move thành phần của cùng 1 dòng combo phải được
        gộp lại và quy đổi về số lượng combo thực giao theo tỷ lệ BOM (xem
        `_get_loyalty_kit_qty_delivered`), rồi chỉ tính price_unit x qty
        combo đúng 1 lần cho cả dòng.
        """
        self.ensure_one()
        done_moves = self.move_ids.filtered(lambda m: m.state == 'done')

        moves_by_line = defaultdict(list)
        loose_moves = []
        for move in done_moves:
            if move.sale_line_id:
                moves_by_line[move.sale_line_id].append(move)
            else:
                loose_moves.append(move)

        kit_tmpl_ids = set()
        if moves_by_line:
            tmpl_ids = [sale_line.product_id.product_tmpl_id.id for sale_line in moves_by_line]
            kit_tmpl_ids = set(self.env['mrp.bom'].sudo().search([
                ('product_tmpl_id', 'in', tmpl_ids),
                ('type', '=', 'phantom'),
            ]).mapped('product_tmpl_id').ids)

        result = []
        for sale_line, moves in moves_by_line.items():
            product = sale_line.product_id
            has_own_product_move = any(m.product_id == product for m in moves)
            if product.product_tmpl_id.id in kit_tmpl_ids and not has_own_product_move:
                qty = self._get_loyalty_kit_qty_delivered(product, moves)
            else:
                qty = sum(m.quantity or 0.0 for m in moves)
            result.append({
                'sale_line': sale_line,
                'product': product,
                'qty': qty,
                'price_unit': sale_line.price_unit,
            })

        for move in loose_moves:
            result.append({
                'sale_line': False,
                'product': move.product_id,
                'qty': move.quantity or 0.0,
                'price_unit': move.product_id.lst_price,
            })
        return result

    def _get_loyalty_kit_qty_delivered(self, kit_product, moves):
        """Suy ra số lượng combo/kit thực giao từ các move thành phần, theo
        đúng tỷ lệ khai báo trên BOM (Kit) của sản phẩm combo.

        Dùng min() trên tất cả thành phần: nếu 1 thành phần giao thiếu so
        với tỷ lệ combo, số combo được tính là chưa giao đủ (tránh đếm dư
        điểm khi combo giao chưa trọn bộ).
        """
        bom = self.env['mrp.bom'].sudo().search([
            ('product_tmpl_id', '=', kit_product.product_tmpl_id.id),
            ('type', '=', 'phantom'),
        ], limit=1)
        if not bom or not bom.bom_line_ids:
            return sum(m.quantity or 0.0 for m in moves)

        bom_qty = bom.product_qty or 1.0
        qty_per_kit_by_product = defaultdict(float)
        for bom_line in bom.bom_line_ids:
            if bom_line.product_id and bom_line.product_qty:
                qty_per_kit_by_product[bom_line.product_id.id] += bom_line.product_qty / bom_qty

        if not qty_per_kit_by_product:
            return sum(m.quantity or 0.0 for m in moves)

        delivered_by_product = defaultdict(float)
        for move in moves:
            delivered_by_product[move.product_id.id] += move.quantity or 0.0

        ratios = [
            delivered_by_product.get(product_id, 0.0) / qty_per_kit
            for product_id, qty_per_kit in qty_per_kit_by_product.items()
            if qty_per_kit > 0
        ]
        return min(ratios) if ratios else 0.0

    def _compute_loyalty_exchange_points(self, program, delivered_lines, delivered_subtotal, partner):
        """Tính điểm đổi thưởng + công thức từ danh sách dòng giao đã gộp
        (xem `_get_loyalty_delivered_lines`). Tách riêng để dùng lại được
        khi tính lại điểm cho 1 bản ghi lịch sử đang chờ xác nhận.

        Trả về (exchange_points, exchange_formula, exchange_formula_html).
        """
        self.ensure_one()
        discount_details = [
            self._get_loyalty_discount_detail_for_line(line)
            for line in delivered_lines
            if line['sale_line']
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
                self._get_loyalty_discount_detail_for_line(line, fallback_pct=fallback_pct)
                for line in delivered_lines
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
        return exchange_points, exchange_formula, exchange_formula_html

    def _get_loyalty_discount_detail_for_line(self, line, fallback_pct=None):
        """Return loyalty discount detail for one delivered line (đã gộp
        theo sale_line, xem `_get_loyalty_delivered_lines`)."""
        sale_line = line['sale_line']
        product_name = line['product'].display_name if line['product'] else ''
        qty = line['qty'] or 0.0
        price_unit = line['price_unit'] or 0.0
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
