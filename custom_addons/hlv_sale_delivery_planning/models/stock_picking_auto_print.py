"""Tự động gửi in phiếu lấy hàng (PICK) khi phiếu đã giữ đủ hàng — trigger bằng cron và
bước soát số trên phiếu vs tồn thật trước khi cho vào hàng chờ in IoT.

Tách riêng khỏi stock_picking.py: file đó lo fields + snapshot/realtime của phiếu, còn cả
mảng auto-print là một mối quan tâm khép kín (bật/tắt, phiếu nào đủ điều kiện, soát tồn,
điểm vào của cron). Odoo ORM tự merge 2 file vào cùng một model qua _inherit.
"""

import logging
from collections import defaultdict

from odoo import api, models
from odoo.tools import float_compare

_logger = logging.getLogger(__name__)

# Các cờ lỗi từ auto_confirm_print_pick_slip() mang nghĩa "chặn TẠM THỜI, tự hết được" — gặp
# những cờ này thì KHÔNG đánh dấu x_auto_print_requested, để lượt cron sau còn thử lại.
# stock_mismatch nằm ở đây vì sửa lại số trên phiếu là hết vướng, không phải lỗi vĩnh viễn.
_AUTO_PRINT_TEMPORARY_BLOCKS = (
    'locked', 'queue_full', 'missing_delivery_type', 'no_stock', 'stock_mismatch',
)


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _pick_slip_stock_mismatch(self):
        """Trả về chuỗi mô tả chỗ lệch nếu phiếu này ghi lấy NHIỀU HƠN số thực có tại đúng vị trí
        lấy hàng, hoặc '' nếu phiếu khớp tồn.

        Vì sao phải kiểm dù phiếu đã 'Sẵn sàng': state='assigned' KHÔNG bảo đảm số trên phiếu
        khớp tồn thật. Đã gặp trên PRD (KBC/PICK/12106): dòng lấy hàng ghi 48 Chai RP7-350G từ
        KBC/Tồn kho/PALLET RP7 WD40 trong khi vị trí đó chỉ có 13 Chai và quant còn
        reserved_quantity=0, phiếu vẫn 'Sẵn sàng'. Không xác định được người dùng thao tác gì để
        lọt 48 vào đó nên không chặn được ở nguồn — phải soát lại trước khi in, vì in ra là kho đi
        lấy 35 chai không tồn tại.

        So với TỒN THỰC CÓ (quant.quantity), KHÔNG trừ reserved_quantity: dòng đã giữ hàng đúng
        cách thì chính nó đang nằm trong reserved_quantity, trừ đi sẽ báo lỗi oan hàng loạt. Đổi
        lại, hàm này KHÔNG bắt được ca 2 phiếu cùng tranh một lượng tồn — đó là việc của cơ chế
        reservation của Odoo, ở đây chỉ chặn đúng ca số trên phiếu vượt tồn.
        """
        self.ensure_one()
        demand = defaultdict(float)
        for line in self.move_line_ids:
            # quantity_product_uom: quy về đơn vị của sản phẩm, vì quant luôn tính theo đơn vị đó
            # (dòng phiếu có thể nhập bằng đơn vị khác — Thùng/Lốc).
            qty = line.quantity_product_uom
            if qty <= 0:
                continue
            key = (
                line.location_id.id, line.product_id.id,
                line.lot_id.id, line.package_id.id, line.owner_id.id,
            )
            demand[key] += qty

        Quant = self.env['stock.quant'].sudo()
        problems = []
        for (location_id, product_id, lot_id, package_id, owner_id), qty in demand.items():
            product = self.env['product.product'].browse(product_id)
            quants = Quant.search([
                # child_of chứ không phải '=': nếu dòng phiếu trỏ vào vị trí cha (có vị trí con
                # bên dưới), so với đúng vị trí cha sẽ thấy tồn 0 và báo lỗi oan. Nới rộng thế này
                # vẫn bắt được ca thật (13 < 48), chỉ đánh đổi ở ca hàng nằm ở vị trí con khác
                # nhánh — thà bỏ sót còn hơn chặn nhầm phiếu đúng.
                ('location_id', 'child_of', location_id),
                ('product_id', '=', product_id),
                ('lot_id', '=', lot_id or False),
                ('package_id', '=', package_id or False),
                ('owner_id', '=', owner_id or False),
            ])
            on_hand = sum(quants.mapped('quantity'))
            rounding = product.uom_id.rounding or 0.01
            if float_compare(qty, on_hand, precision_rounding=rounding) > 0:
                location = self.env['stock.location'].browse(location_id)
                problems.append('%s: phiếu ghi lấy %g %s tại %s nhưng thực có %g' % (
                    product.display_name, qty, product.uom_id.name,
                    location.complete_name, on_hand,
                ))
        # Chỉ nêu 3 dòng đầu — thông báo còn phải đọc được trên toast của sale, liệt kê hết 20
        # dòng thì không ai đọc. Số còn lại vẫn nói rõ là còn.
        if len(problems) > 3:
            return '; '.join(problems[:3]) + ' (và %d dòng khác nữa)' % (len(problems) - 3)
        return '; '.join(problems)

    @api.model
    def _auto_print_when_full_enabled(self):
        return self.env['ir.config_parameter'].sudo().get_param(
            'hlv_sale_delivery_planning.auto_print_pick_slip_when_full'
        ) in ('1', 'True', 'true', True)

    @api.model
    def _auto_print_candidate_domain(self):
        """Phiếu đủ điều kiện để hệ thống TỰ gửi in. Từng điều kiện có lý do riêng:
          - state='assigned': mọi move còn active đã reserve ĐỦ (khác 'partially_available' —
            chỉ giữ được một phần, in ra thì kho lấy thiếu).
          - x_printed: phiếu đã in rồi (kho in tay, hoặc lượt tự động trước đã in) thì không
            gửi lại nữa — nếu cần in lại thì dùng "Đưa lại vào hàng chờ" ở hàng chờ in.
          - kho phải ĐÃ gán máy in IoT: kho chưa gán thì yêu cầu chỉ vào hàng chờ để nằm đó rồi
            báo lỗi (xem iot_print_queue._do_print), làm rác hàng chờ của kho khác.
          - HTGH: xem _auto_print_delivery_type_domain()."""
        return [
            ('state', '=', 'assigned'),
            ('picking_type_id.sequence_code', 'ilike', 'PICK'),
            ('return_id', '=', False),
            ('x_auto_print_requested', '=', False),
            ('x_printed', '=', False),
            ('picking_type_id.warehouse_id.x_iot_printer_device_id', '!=', False),
        ] + self._auto_print_delivery_type_domain()

    @api.model
    def _auto_print_delivery_type_domain(self):
        """Điều kiện HTGH: phiếu tự có HTGH, HOẶC đơn của phiếu có HTGH để lấy xuống (xem
        services/delivery_planner_iot_print._backfill_picking_delivery_type). Đo trên PRD: 69/77
        phiếu "Sẵn sàng" bị loại chỉ vì thiếu HTGH ở cấp phiếu dù đơn đã có — lọc cứng theo
        x_pick_delivery_type là auto-print gần như không bao giờ có việc để làm.

        Nhánh sale_id = False là phiếu không liên kết đơn qua procurement group: service còn tự
        truy đơn qua move_ids.sale_line_id nên vẫn có thể in được. KHÔNG đưa đường
        move_ids.sale_line_id.order_id vào domain vì nó thành subquery 3 tầng trên toàn bộ đơn/
        dòng đơn, chạy mỗi phút thì quá nặng — thà để vài phiếu lẻ đó được quét lại mỗi lượt
        (phiếu không có đơn thật sẽ bị đánh dấu ngay lượt đầu và tự rơi khỏi danh sách) còn hơn
        im lặng bỏ sót chúng."""
        field_name = self.env['hlv.delivery.planner.service']._order_delivery_type_field()
        if not field_name:
            return [('x_pick_delivery_type', '!=', False)]
        return [
            '|', ('x_pick_delivery_type', '!=', False),
            '|', ('sale_id.%s' % field_name, '!=', False),
                 ('sale_id', '=', False),
        ]

    @api.model
    def cron_auto_queue_print_when_full(self, limit=50):
        """Quét phiếu PICK đã giữ đủ hàng rồi đẩy vào hàng chờ in IoT (chạy mỗi phút).

        Vì sao là CRON chứ không phải hook bắt lúc phiếu chuyển 'assigned': state của
        stock.picking là field COMPUTE + STORE (_compute_state của core), nên khi move được
        reserve, ORM ghi state mới xuống DB bằng đường flush recompute (_write) — KHÔNG đi qua
        write() công khai. Hook cũ đặt ở write() vì vậy chưa từng chạy lần nào (đo trên PRD:
        88 phiếu đang 'assigned', 0 phiếu được tự động gửi in). Quét theo TRẠNG THÁI CUỐI thay
        vì bắt khoảnh khắc chuyển trạng thái nên phủ được mọi đường giữ hàng (nút Check
        Availability, scheduler, module khác gọi _action_assign) và không im lặng bỏ sót."""
        if not self._auto_print_when_full_enabled():
            return 0
        picks = self.search(self._auto_print_candidate_domain(), order='id', limit=limit)
        if not picks:
            return 0
        picks._auto_queue_print_when_full()
        return len(picks)

    def _auto_queue_print_when_full(self):
        """Gửi yêu cầu in cho những phiếu trong recordset này đã giữ ĐỦ hàng. Điểm vào của vận
        hành thật là cron_auto_queue_print_when_full(); hàm này vẫn tự kiểm lại điều kiện để gọi
        tay trên shell cho 1 phiếu cụ thể cũng an toàn (xem bin/force_auto_print_test.py)."""
        if not self._auto_print_when_full_enabled():
            return
        picks = self.filtered(
            lambda p: p.state == 'assigned'
            and p._is_pick_slip_picking()
            and not p.x_auto_print_requested
            and not p.x_printed
        )
        if not picks:
            return
        Service = self.env['hlv.delivery.planner.service'].sudo()
        for pick in picks:
            result = None
            try:
                result = Service.auto_confirm_print_pick_slip(pick)
            except Exception:
                _logger.exception('Auto print pick slip failed for %s', pick.name)
            # Chỉ đánh dấu "đã gửi" khi kết quả DỨT ĐIỂM — gửi thành công, hoặc lý do tự nó
            # KHÔNG bao giờ hết (không xác định được đơn hàng của phiếu). Các lý do TẠM THỜI ở
            # _AUTO_PRINT_TEMPORARY_BLOCKS thì để nguyên cờ cho lượt cron sau thử lại: thiếu HTGH
            # sale nhập sau là xong, kho đầy hàng chờ thì xử lý vài đơn là hết, khóa tính năng thì
            # admin tắt là hết. Đánh dấu ở những trường hợp đó = phiếu bị loại vĩnh viễn khỏi
            # auto-print dù điều kiện đã hết vướng, đúng kiểu lỗi im lặng.
            if not result:
                continue
            if result.get('stock_mismatch'):
                # Phiếu sai số so với tồn: cron sẽ thử lại mỗi phút nên không được im lặng, phải
                # có dấu vết trong log để truy được phiếu nào sai từ lúc nào (kho/sale không nhìn
                # thấy log, nhưng đây là ca cần người sửa phiếu chứ không tự hết).
                _logger.warning('Auto print bỏ qua %s: %s', pick.name, result.get('message'))
            if result.get('success') or not any(
                result.get(key) for key in _AUTO_PRINT_TEMPORARY_BLOCKS
            ):
                pick.x_auto_print_requested = True
