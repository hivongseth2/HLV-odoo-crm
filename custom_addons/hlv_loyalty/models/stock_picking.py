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
        # (Tính 1 lần cho cả đơn — nếu có nhiều tài khoản, điểm này được
        # CHIA theo tỷ lệ số tiền cộng điểm ở _split_loyalty_points_by_account,
        # không tính lại riêng cho từng tài khoản để tránh mất điểm do làm
        # tròn/mốc.)
        ranking_points = 0
        if delivered_subtotal > 0 and program.earning_amount > 0:
            ranking_points = int(delivered_subtotal / program.earning_amount) * program.earning_points

        # ── Điểm đổi thưởng: KHÔNG còn dựa vào CK Loyalty %/dòng bán hàng.
        # Mỗi tài khoản trên bảng "Tài khoản cộng điểm Loyalty" của đơn được
        # gán 1 SỐ TIỀN cố định (earning_amount) = tổng tiền tài khoản đó
        # được cộng NẾU đơn giao đủ 100%. Phiếu này giao được bao nhiêu % giá
        # trị của cả đơn thì tài khoản nhận đúng bấy nhiêu % số tiền đó (xem
        # `_split_loyalty_points_by_account`). Không cộng dồn/đối chiếu qua
        # nhiều phiếu — mỗi phiếu tính độc lập trên phần mình giao, giống hệt
        # cách điểm xếp hạng đã làm từ trước.
        order_total_amount = self._get_loyalty_order_total_amount(sale_order)
        delivery_ratio = 0.0
        if order_total_amount > 0:
            delivery_ratio = min(delivered_subtotal / order_total_amount, 1.0)

        # Luôn tích vào công ty gốc (đi lên hết chuỗi parent_id)
        root_partner = partner._get_loyalty_root()

        allocations = self._get_loyalty_account_allocations(sale_order, root_partner)
        if not allocations:
            return
        if ranking_points <= 0 and not any(amount for _, amount in allocations):
            return

        shares = self._split_loyalty_points_by_account(
            allocations, delivered_subtotal, order_total_amount, delivery_ratio, program, ranking_points,
        )

        base_vals = {
            'partner_id': root_partner.id,
            'transaction_type': 'earn',
            'picking_id': self.id,
            'sale_order_id': sale_order.id,
            'company_id': self.company_id.id,
            'sale_company_id': sale_order.company_id.id,
            'delivery_company_id': self.company_id.id,
        }

        total_ranking_recorded = 0
        total_exchange_recorded = 0
        for share in shares:
            account = share['account']
            acc_ranking = share['ranking_points']
            acc_exchange = share['exchange_points']
            if acc_ranking <= 0 and acc_exchange <= 0:
                continue

            # Kiểm tra xem tài khoản này đã tích điểm cho phiếu này chưa
            # (tránh duplicate khi validate lại / recalculate).
            existing = self.env['hlv.loyalty.history'].sudo().search([
                ('picking_id', '=', self.id),
                ('transaction_type', '=', 'earn'),
                ('account_id', '=', account.id),
            ])
            if existing:
                ranking_hist = existing.filtered(lambda h: h.point_type == 'ranking')[:1]
                exchange_hist = existing.filtered(lambda h: h.point_type == 'exchange')[:1]
                if ranking_hist:
                    # Luôn confirmed ngay khi tạo (đã vào số dư) → chỉ cập
                    # nhật công thức để đối chiếu, không tự sửa điểm đã chốt.
                    ranking_hist.write({
                        'point_formula': share['ranking_formula'],
                        'point_formula_html': share['ranking_formula_html'],
                    })
                elif acc_ranking > 0:
                    # Bù bản ghi ranking còn thiếu (hiếm khi xảy ra, nhưng
                    # xử lý đối xứng với nhánh exchange bên dưới).
                    self.env['hlv.loyalty.history'].sudo().create({
                        **base_vals,
                        'account_id': account.id,
                        'point_amount': acc_ranking,
                        'point_type': 'ranking',
                        'state': 'confirmed',
                        'description': (
                            f'Tích điểm xếp hạng (bù) {sale_order.name} - Phiếu {self.name}'
                            f' - TK {account.display_name}'
                        ),
                        'point_formula': share['ranking_formula'],
                        'point_formula_html': share['ranking_formula_html'],
                    })
                    total_ranking_recorded += acc_ranking

                if exchange_hist and exchange_hist.state == 'pending':
                    exchange_hist.write({
                        'point_amount': acc_exchange,
                        'point_formula': share['exchange_formula'],
                        'point_formula_html': share['exchange_formula_html'],
                    })
                elif exchange_hist:
                    exchange_hist.write({
                        'point_formula': share['exchange_formula'],
                        'point_formula_html': share['exchange_formula_html'],
                    })
                elif acc_exchange > 0:
                    # Bù bản ghi điểm đổi thưởng còn thiếu: trước đây phiếu
                    # này chỉ tạo được điểm ranking (lúc validate, bảng
                    # "Tài khoản cộng điểm Loyalty"/số tiền chưa được cấu
                    # hình, hoặc được nhập/sửa SAU khi đã giao) — trước đây
                    # nhánh `if existing: ... continue` bỏ qua vĩnh viễn,
                    # không bao giờ tạo bổ sung. Giờ chạy lại (validate lại /
                    # wizard tính lại / nút "Tạo bù điểm đổi thưởng" trên
                    # đơn hàng) sẽ tạo bổ sung bản ghi còn thiếu này.
                    self.env['hlv.loyalty.history'].sudo().create({
                        **base_vals,
                        'account_id': account.id,
                        'point_amount': acc_exchange,
                        'point_type': 'exchange',
                        'state': 'pending',
                        'description': (
                            f'Tích điểm đổi thưởng (bù) {sale_order.name} - Phiếu {self.name}'
                            f' - TK {account.display_name}'
                        ),
                        'point_formula': share['exchange_formula'],
                        'point_formula_html': share['exchange_formula_html'],
                    })
                    total_exchange_recorded += acc_exchange
                continue

            if acc_ranking > 0:
                self.env['hlv.loyalty.history'].sudo().create({
                    **base_vals,
                    'account_id': account.id,
                    'point_amount': acc_ranking,
                    'point_type': 'ranking',
                    'state': 'confirmed',
                    'description': (
                        f'Tích điểm xếp hạng {sale_order.name} - Phiếu {self.name}'
                        f' - TK {account.display_name}'
                    ),
                    'point_formula': share['ranking_formula'],
                    'point_formula_html': share['ranking_formula_html'],
                })
                total_ranking_recorded += acc_ranking

            if acc_exchange > 0:
                self.env['hlv.loyalty.history'].sudo().create({
                    **base_vals,
                    'account_id': account.id,
                    'point_amount': acc_exchange,
                    'point_type': 'exchange',
                    'state': 'pending',
                    'description': (
                        f'Tích điểm đổi thưởng {sale_order.name} - Phiếu {self.name}'
                        f' - TK {account.display_name}'
                    ),
                    'point_formula': share['exchange_formula'],
                    'point_formula_html': share['exchange_formula_html'],
                })
                total_exchange_recorded += acc_exchange

        self.loyalty_points_earned = ranking_points
        _logger.info(
            'Loyalty: Tích ranking=%d exchange=%d cho %s từ phiếu %s (SO: %s) qua %d tài khoản',
            total_ranking_recorded, total_exchange_recorded, partner.name, self.name,
            sale_order.name, len(shares),
        )

    def _get_loyalty_account_allocations(self, sale_order, root_partner):
        """Trả về danh sách [(account, earning_amount)] để chia điểm của đơn này.

        - Nếu đơn có cấu hình bảng "Tài khoản cộng điểm Loyalty"
          (`loyalty_account_line_ids`), dùng đúng danh sách tài khoản +
          `earning_amount` (số tiền cộng điểm nếu đơn giao đủ 100%) đã nhập
          trên từng dòng.
        - Nếu không (đơn không chọn tài khoản nào), fallback về tài khoản
          mặc định (`is_default=True`, hoặc tài khoản đầu tiên) của công ty,
          với earning_amount=None nghĩa là "nhận 100% điểm xếp hạng, KHÔNG có
          điểm đổi thưởng" (không còn fallback theo CK Loyalty %/dòng bán
          hàng nữa — muốn có điểm đổi thưởng bắt buộc phải cấu hình bảng
          tài khoản + số tiền cho đơn).
        """
        self.ensure_one()
        lines = sale_order.loyalty_account_line_ids.filtered(
            lambda l: l.account_id and l.account_id.active
        )
        if lines:
            return [(line.account_id, line.earning_amount or 0.0) for line in lines]

        accounts = self.env['hlv.loyalty.portal.account'].sudo().search([
            ('partner_id', '=', root_partner.id),
            ('active', '=', True),
        ])
        if not accounts:
            return []
        default_account = accounts.filtered('is_default')[:1] or accounts[:1]
        return [(default_account, None)]

    def _get_loyalty_order_total_amount(self, sale_order):
        """Tổng giá trị đơn hàng (dùng làm mẫu số để suy ra % đã giao của
        phiếu này so với cả đơn). Tính từ price_unit x số lượng ĐẶT HÀNG của
        các dòng sản phẩm thật (bỏ qua dòng section/note VÀ dòng thưởng
        Voucher Loyalty - is_loyalty_reward_line), KHÔNG dùng amount_untaxed
        để tránh lẫn dòng giảm giá Voucher/phí ship làm lệch tỷ lệ."""
        return sum(
            (line.price_unit or 0.0) * (line.product_uom_qty or 0.0)
            for line in sale_order.order_line
            if not line.display_type and not line.is_loyalty_reward_line
        )

    def _split_loyalty_points_by_account(
        self, allocations, delivered_subtotal, order_total_amount, delivery_ratio, program, ranking_points,
    ):
        """Chia điểm ranking + đổi thưởng của cả phiếu cho từng tài khoản.

        Điểm đổi thưởng KHÔNG còn dựa vào CK Loyalty %/dòng bán hàng. Mỗi
        tài khoản trên bảng "Tài khoản cộng điểm Loyalty" của đơn được gán
        1 SỐ TIỀN cố định (`earning_amount`) = tổng tiền tài khoản đó được
        cộng NẾU đơn giao đủ 100%. Phiếu này giao được bao nhiêu % giá trị
        của cả đơn (`delivery_ratio` = doanh số giao phiếu này / tổng giá
        trị đơn) thì tài khoản nhận đúng bấy nhiêu % số tiền đó, quy đổi
        điểm theo `discount_per_point`. Mỗi phiếu tính ĐỘC LẬP trên phần
        mình giao (không cộng dồn/đối chiếu qua nhiều phiếu), giống hệt
        cách điểm xếp hạng đã làm từ trước.

        - Chỉ 1 allocation với earning_amount=None (fallback, đơn không cấu
          hình bảng phân bổ): tài khoản đó nhận 100% điểm xếp hạng, KHÔNG có
          điểm đổi thưởng (không còn fallback theo CK Loyalty % nữa — muốn
          có điểm đổi thưởng bắt buộc phải cấu hình bảng + số tiền).
        - Có bảng phân bổ (N dòng, mỗi dòng 1 số tiền): `ranking_points` của
          cả đơn được chia theo tỷ lệ `earning_amount / tổng earning_amount`
          (chuẩn hóa theo tổng số tiền đã liệt kê trong bảng — tương tự cách
          chia % cũ, chỉ đổi từ % sang số tiền làm trọng số). Tài khoản cuối
          cùng luôn nhận phần dư do làm tròn để tổng luôn khớp đúng
          `ranking_points` của cả đơn.
        """
        self.ensure_one()

        if len(allocations) == 1 and allocations[0][1] is None:
            account = allocations[0][0]
            exchange_points = 0
            exchange_formula = (
                'Điểm đổi thưởng: đơn chưa cấu hình bảng "Tài khoản cộng điểm Loyalty" '
                'kèm số tiền cho tài khoản này → không tính điểm đổi thưởng, chỉ tính điểm xếp hạng.'
            )
            exchange_formula_html = f'<p>{escape(exchange_formula)}</p>'
            ranking_formula = self._format_loyalty_point_formula(
                'Điểm xếp hạng', delivered_subtotal, program.earning_amount, program.earning_points,
                ranking_points, multiplier_label='điểm/mốc',
            )
            ranking_formula_html = self._format_loyalty_point_formula_html(
                'Điểm xếp hạng', delivered_subtotal, program.earning_amount, program.earning_points,
                ranking_points, multiplier_label='điểm/mốc',
            )
            return [{
                'account': account,
                'ranking_points': ranking_points,
                'exchange_points': exchange_points,
                'ranking_formula': ranking_formula,
                'ranking_formula_html': ranking_formula_html,
                'exchange_formula': exchange_formula,
                'exchange_formula_html': exchange_formula_html,
            }]

        # ── Có bảng phân bổ nhiều tài khoản ──────────────────────────────
        total_amount = sum((amount or 0.0) for _, amount in allocations) or 1.0

        reference_note = (
            f'Tổng giá trị cả đơn: {order_total_amount:,.0f}đ. Phiếu này giao '
            f'{delivered_subtotal:,.0f}đ = {delivery_ratio:.2%} giá trị đơn.'
        )

        shares = []
        ranking_running_total = 0
        for idx, (account, amount) in enumerate(allocations):
            amount = amount or 0.0
            is_last = idx == len(allocations) - 1

            if is_last:
                account_ranking_points = ranking_points - ranking_running_total
            else:
                account_ranking_points = round(ranking_points * amount / total_amount)
            ranking_running_total += account_ranking_points

            account_money_this_delivery = amount * delivery_ratio
            account_exchange_points = 0
            if account_money_this_delivery > 0 and program.discount_per_point > 0:
                account_exchange_points = int(account_money_this_delivery / program.discount_per_point)

            source_label = (
                f'{reference_note} Tài khoản "{account.display_name}" được gán '
                f'{amount:,.0f}đ nếu đơn giao đủ 100% → lần này nhận '
                f'{amount:,.0f}đ x {delivery_ratio:.2%} = {account_money_this_delivery:,.0f}đ.'
            )

            exchange_formula = self._format_loyalty_point_formula(
                'Điểm đổi thưởng', account_money_this_delivery, program.discount_per_point, 1,
                account_exchange_points, source_label=source_label,
            )
            exchange_formula_html = self._format_loyalty_point_formula_html(
                'Điểm đổi thưởng', account_money_this_delivery, program.discount_per_point, 1,
                account_exchange_points, source_label=source_label,
            )
            ranking_formula = (
                f'Điểm xếp hạng tài khoản "{account.display_name}": tổng điểm xếp hạng cả đơn '
                f'{ranking_points:,} điểm (tính từ doanh số giao {delivered_subtotal:,.0f}đ), '
                f'chia theo tỷ lệ số tiền cộng điểm được phân bổ trên đơn = '
                f'round({ranking_points:,} x {amount:,.0f}đ / {total_amount:,.0f}đ) = {account_ranking_points:,} điểm.'
            )
            ranking_formula_html = f'<p><strong>{escape(ranking_formula)}</strong></p>'

            shares.append({
                'account': account,
                'ranking_points': account_ranking_points,
                'exchange_points': account_exchange_points,
                'ranking_formula': ranking_formula,
                'ranking_formula_html': ranking_formula_html,
                'exchange_formula': exchange_formula,
                'exchange_formula_html': exchange_formula_html,
            })
        return shares

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

        # Lấy TOÀN BỘ dòng earn của phiếu gốc — có thể nhiều dòng (mỗi tài
        # khoản Loyalty được chọn trên đơn 1 dòng ranking + 1 dòng exchange),
        # không còn dựa vào field loyalty_points_earned (chỉ 1 số duy nhất,
        # không đủ để thu hồi đúng theo từng tài khoản).
        origin_earn_hist = self.env['hlv.loyalty.history'].sudo().search([
            ('picking_id', '=', origin_picking.id),
            ('transaction_type', '=', 'earn'),
        ])
        if not origin_earn_hist:
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

        total_ranking_deducted = 0
        total_exchange_deducted = 0

        # ── Điểm xếp hạng (luôn auto-confirmed) → tạo bản ghi âm cho từng
        #    tài khoản đã nhận điểm ranking ở phiếu gốc ──────────────────────
        for ranking_hist in origin_earn_hist.filtered(lambda h: h.point_type == 'ranking'):
            ranking_to_deduct = round(ranking_hist.point_amount * ratio)
            if ranking_to_deduct <= 0:
                continue
            self.env['hlv.loyalty.history'].sudo().create({
                **base_vals,
                'account_id': ranking_hist.account_id.id,
                'point_amount': -ranking_to_deduct,
                'point_type': 'ranking',
                'state': 'confirmed',
                'description': (
                    f'Thu hồi điểm xếp hạng do hoàn hàng {self.name}'
                    f' (gốc: {origin_picking.name}){pct_label}'
                ),
            })
            total_ranking_deducted += ranking_to_deduct

        # ── Điểm đổi thưởng — xử lý riêng cho từng tài khoản/dòng ───────────
        for exchange_hist in origin_earn_hist.filtered(
            lambda h: h.point_type == 'exchange' and h.state in ('pending', 'confirmed')
        ):
            exchange_original = exchange_hist.point_amount
            exchange_to_deduct = round(exchange_original * ratio)

            if exchange_hist.state == 'pending':
                # Chưa xác nhận → chưa vào số dư khách hàng
                # → chỉ điều chỉnh bản ghi pending, KHÔNG tạo record âm
                if is_full_return:
                    # Hoàn toàn bộ: hủy bản ghi pending gốc
                    exchange_hist.write({
                        'state': 'cancelled',
                        'description': (
                            exchange_hist.description
                            + f' [Hủy do hoàn hàng {self.name}]'
                        ),
                    })
                else:
                    # Hoàn một phần: giảm điểm pending còn lại
                    # (khi nhân viên xác nhận sau, chỉ cộng phần chưa hoàn)
                    remaining = max(0, exchange_original - exchange_to_deduct)
                    exchange_hist.write({
                        'point_amount': remaining,
                        'description': (
                            exchange_hist.description
                            + f' [Đã giảm {exchange_to_deduct}đ do hoàn {self.name}]'
                        ),
                    })
                total_exchange_deducted += exchange_to_deduct

            elif exchange_hist.state == 'confirmed':
                # Đã xác nhận → đã vào số dư → tạo bản ghi âm để khấu trừ
                if exchange_to_deduct > 0:
                    self.env['hlv.loyalty.history'].sudo().create({
                        **base_vals,
                        'account_id': exchange_hist.account_id.id,
                        'point_amount': -exchange_to_deduct,
                        'point_type': 'exchange',
                        'state': 'confirmed',
                        'description': (
                            f'Thu hồi điểm đổi thưởng (đã XN) do hoàn hàng {self.name}'
                            f' (gốc: {origin_picking.name}){pct_label}'
                        ),
                    })
                    total_exchange_deducted += exchange_to_deduct

        _logger.info(
            'Loyalty: Thu hồi ranking=%d exchange=%d (ratio=%.0f%%) từ %s'
            ' do hoàn hàng %s (gốc: %s)',
            total_ranking_deducted, total_exchange_deducted, ratio * 100,
            partner.name, self.name, origin_picking.name,
        )
