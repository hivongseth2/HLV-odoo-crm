import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Field do Studio tạo trên bản cài này, không có trong mã nguồn Odoo. Đọc qua ``_fields``
# để module vẫn cài được ở nơi chưa tạo các field đó.
STUDIO_ADDRESS_FIELD = 'x_studio_a_ch_giao_hng'
STUDIO_AMOUNT_FIELD = 'x_studio_tng_tin_sau_thu'


class StockPicking(models.Model):
    """Phiếu giao — đơn vị được xếp lên xe trong kế hoạch giao hàng."""

    _inherit = 'stock.picking'

    plan_line_ids = fields.One2many(
        'hlv.vtracking.plan.line', 'picking_id', string='Dòng kế hoạch giao',
    )
    plan_id = fields.Many2one(
        'hlv.vtracking.plan', string='Kế hoạch giao', compute='_compute_plan_id', store=True,
        help='Kế hoạch đang chứa phiếu này. Một phiếu chỉ nằm trong một kế hoạch.',
    )

    @api.depends('plan_line_ids', 'plan_line_ids.plan_id')
    def _compute_plan_id(self):
        for picking in self:
            picking.plan_id = picking.plan_line_ids[:1].plan_id

    # ------------------------------------------------------------------
    # Đọc dữ liệu Studio
    # ------------------------------------------------------------------
    def _vtracking_delivery_address(self):
        """Địa chỉ dùng để tra toạ độ cho phiếu này.

        Ưu tiên ô địa chỉ giao gõ tay trên phiếu: đó là nơi kho ghi địa chỉ THẬT của
        chuyến này, có thể khác địa chỉ mặc định của khách. Không có thì lùi về địa chỉ
        liên hệ của đối tác.
        """
        self.ensure_one()
        studio_value = ''
        if STUDIO_ADDRESS_FIELD in self._fields:
            studio_value = (self[STUDIO_ADDRESS_FIELD] or '').strip()
        if studio_value:
            return studio_value
        return (self.partner_id.contact_address or '').replace('\n', ', ').strip(' ,')

    def _vtracking_amount(self):
        """Tiền hàng của phiếu — lấy thẳng ô "Tổng tiền sau thuế" trên phiếu.

        KHÔNG tự cộng lại từ dòng hàng: ô đó là con số kho và kế toán đang nhìn, tự tính
        lại chỉ tạo ra một con số thứ hai lệch với nó.

        Trả về 0.0 khi bản cài chưa có field đó, NHƯNG ghi log cảnh báo: gõ sai tên field
        Studio thì mọi dòng kế hoạch đều hiện 0 đ mà không có dấu hiệu gì là đang hỏng —
        đúng một lỗi như vậy đã xảy ra rồi.
        """
        self.ensure_one()
        if STUDIO_AMOUNT_FIELD not in self._fields:
            _logger.warning(
                'V-Tracking: stock.picking không có field "%s" nên tiền hàng của mọi dòng '
                'kế hoạch sẽ là 0. Kiểm lại tên field Studio trong models/stock_picking.py.',
                STUDIO_AMOUNT_FIELD,
            )
            return 0.0
        return self[STUDIO_AMOUNT_FIELD] or 0.0

    def _vtracking_source_name(self):
        """Tên đơn bán gắn với phiếu, để hiện kèm mã phiếu.

        Người điều phối gọi nhau bằng số đơn bán chứ không bằng mã phiếu xuất kho, nên
        chỉ hiện mã phiếu là họ phải tra ngược. Không có đơn bán thì lùi về ``origin``
        (phiếu chuyển kho, phiếu trả hàng...).
        """
        self.ensure_one()
        if 'sale_id' in self._fields and self.sale_id:
            return self.sale_id.name or ''
        return self.origin or ''
