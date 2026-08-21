# -*- coding: utf-8 -*-
import logging

from lxml import etree

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class StockPicking(models.Model):
    _inherit = "stock.picking"

    is_stock_hold_picking = fields.Boolean(
        string="Phiếu giữ hàng (Giữ hàng theo Sale)",
        default=False,
        copy=False,
        help=(
            "Phiếu chuyển kho nội bộ này được tạo tự động bởi tính năng Giữ hàng theo Sale "
            "(trang /search_stock) để khóa chỗ hàng — KHÔNG đại diện cho một lần chuyển hàng "
            "thật. Không được xác nhận/hoàn tất (validate) phiếu này."
        ),
    )

    def button_validate(self):
        blocked = self.filtered("is_stock_hold_picking")
        if blocked:
            raise UserError(_(
                "Đây là phiếu giữ chỗ (do tính năng Giữ hàng theo Sale tạo ra), không phải phiếu "
                "chuyển hàng thật — KHÔNG được xác nhận/hoàn tất phiếu này. Nếu hoàn tất, hệ thống "
                "sẽ di chuyển hàng thật sang vị trí ảo 'Giữ hàng chờ đơn', làm mất vị trí tồn kho "
                "thực tế và làm hàng bị giữ mất luôn tác dụng khóa (không còn giảm 'Sẵn sàng' nữa).\n\n"
                "Hãy vào menu Kho hàng > Giữ hàng theo Sale, mở yêu cầu tương ứng (%s) và bấm "
                "'Hoàn thành' (khi đã lên đơn/báo giá xong) hoặc 'Hủy' (khi không cần giữ nữa)."
            ) % ", ".join(blocked.mapped("origin")))
        return super().button_validate()

    def action_cancel(self):
        res = super().action_cancel()
        holds = self.env["stock.hold.request"].sudo().search([
            ("hold_picking_id", "in", self.ids),
            ("state", "=", "approved"),
        ])
        holds.write({"state": "cancelled"})
        return res

    def get_view(self, view_id=None, view_type='form', **options):
        """Ẩn nút 'Xác nhận' (button_validate) trên phiếu giữ hàng (is_stock_hold_picking),
        để tránh người dùng lỡ tay validate làm mất tác dụng khóa hàng (button_validate() đã
        raise UserError chặn cứng ở tầng server rồi, đây chỉ là ẩn bớt cho khỏi bấm nhầm).

        Không đụng vào điều kiện invisible gốc của nút (không biết chắc nó là gì ở mọi version) —
        chỉ OR thêm điều kiện của mình vào, nên phiếu thường (is_stock_hold_picking=False) không
        bị ảnh hưởng gì cả. Bọc try/except để nếu có gì bất thường thì bỏ qua, không làm sập
        màn hình phiếu kho của cả hệ thống.
        """
        res = super().get_view(view_id=view_id, view_type=view_type, **options)
        if view_type != 'form':
            return res
        try:
            doc = etree.fromstring(res['arch'])
            buttons = doc.xpath("//button[@name='button_validate']")
            if not buttons:
                return res
            for node in buttons:
                current = node.get('invisible')
                node.set(
                    'invisible',
                    "is_stock_hold_picking" if not current
                    else "(%s) or is_stock_hold_picking" % current,
                )
            res['arch'] = etree.tostring(doc, encoding='unicode')
            if isinstance(res.get('fields'), dict) and 'is_stock_hold_picking' not in res['fields']:
                res['fields']['is_stock_hold_picking'] = self.fields_get(
                    ['is_stock_hold_picking']
                )['is_stock_hold_picking']
        except Exception:
            _logger.exception(
                "Không thể ẩn nút Xác nhận cho phiếu giữ hàng — bỏ qua, dùng view gốc."
            )
            return super().get_view(view_id=view_id, view_type=view_type, **options)
        return res
