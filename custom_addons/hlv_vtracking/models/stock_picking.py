import logging

from odoo import api, fields, models

from ..tools.vtracking_channel import delivery_channel
from .sale_order import STUDIO_CHANNEL_FIELD

_logger = logging.getLogger(__name__)

# Field do Studio tạo trên bản cài này, không có trong mã nguồn Odoo. Đọc qua ``_fields``
# để module vẫn cài được ở nơi chưa tạo các field đó.
#
# THỨ TỰ QUAN TRỌNG: `x_studio_a_ch_giao_hng` là field TÍNH TỪ liên hệ của khách nên nó
# gần như luôn có giá trị. Đặt nó trước thì không bao giờ đọc tới địa chỉ giao thật mà kho
# gõ tay ở `x_studio_dia_chi_giao_hang` — và mọi phiếu sẽ geocode nhầm về trụ sở khách.
STUDIO_ADDRESS_FIELDS = ('x_studio_dia_chi_giao_hang', 'x_studio_a_ch_giao_hng')
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

    @api.model_create_multi
    def create(self, vals_list):
        """Nối phiếu xuất mới sinh vào dòng kế hoạch đang chờ phiếu của cùng đơn bán.

        Điều phối chốt "chiều nay giao đơn này" từ sáng, lúc kho chưa soạn hàng nên phiếu
        xuất chưa tồn tại. Không nối tự động ở đây thì người điều phối phải nhớ quay lại
        sửa từng kế hoạch sau khi kho soạn xong — việc không ai nhớ nổi.
        """
        pickings = super().create(vals_list)
        try:
            self.env['hlv.vtracking.plan.line'].attach_new_pickings(pickings)
        except Exception:  # noqa: BLE001
            # Tạo phiếu là việc của kho và không được hỏng vì kế hoạch giao. Nối trượt
            # thì dòng kế hoạch vẫn ở trạng thái "Chờ phiếu xuất", nối tay được.
            _logger.exception('V-Tracking: không nối được phiếu mới vào kế hoạch đang chờ.')
        return pickings

    # ------------------------------------------------------------------
    # Đọc dữ liệu Studio
    # ------------------------------------------------------------------
    def _vtracking_delivery_address(self):
        """Địa chỉ dùng để tra toạ độ cho phiếu này.

        Thử lần lượt các ô ở ``STUDIO_ADDRESS_FIELDS`` rồi mới lùi về địa chỉ liên hệ của
        khách. Ô đầu là địa chỉ giao kho gõ tay — nơi ghi địa chỉ THẬT của chuyến này, có
        thể khác hẳn trụ sở khách.
        """
        self.ensure_one()
        for field_name in STUDIO_ADDRESS_FIELDS:
            if field_name not in self._fields:
                continue
            value = (self[field_name] or '').strip()
            if value:
                return value
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

    def _vtracking_delivery_channel(self):
        """Kênh giao của phiếu. Ô trên PHIẾU thắng, không có thì hỏi đơn bán.

        Phiếu thắng vì nó là thứ kho đang cầm: sale chốt "gửi CPN" từ lúc đặt hàng, nhưng
        đến ngày giao khách đổi ý ghé lấy thì người sửa là kho, sửa trên phiếu.
        """
        self.ensure_one()
        if STUDIO_CHANNEL_FIELD in self._fields:
            channel = delivery_channel(self[STUDIO_CHANNEL_FIELD])
            if channel:
                return channel
        if 'sale_id' in self._fields and self.sale_id:
            return self.sale_id._vtracking_delivery_channel()
        return ''
