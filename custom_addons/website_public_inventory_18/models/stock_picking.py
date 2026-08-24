# -*- coding: utf-8 -*-
import logging

from lxml import etree

from odoo import fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Tên các nút cần ẩn trên phiếu giữ hàng (is_stock_hold_picking=True). Nút "In phiếu lấy hàng"
# là do Odoo Studio tự sinh (name dạng UUID) — đã xác nhận bằng cách dump arch thật qua shell
# (bin/check_stock_picking_hold_buttons.py), không phải đoán. Nếu ai đó sửa lại nút này trong
# Studio (đổi tên/tạo lại), UUID có thể đổi — lúc đó cần dump lại arch để cập nhật.
HIDDEN_BUTTON_NAMES_ON_HOLD_PICKING = [
    "button_validate",
    "action_cancel",
    "action_open_label_wizard",  # "In Tem Nhãn" (module custom_picking_label)
    "studio_customization.hoat_ong_lay_hang_2cee26a0-9494-42ea-ac3a-337c20b5f150",  # "In phiếu lấy hàng" (Odoo Studio)
]


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

    def do_unreserve(self):
        """'Hủy dự trữ' (Unreserve) trong menu Actions — khác action_cancel(): không hủy cả
        phiếu, chỉ nhả reservation. Nếu ai đó dùng nó trên phiếu giữ hàng (vd kho cố tình giành
        lại hàng cho việc khác), tác dụng khóa hàng của yêu cầu giữ hàng tương ứng coi như đã
        mất — dù trạng thái vẫn đang hiển thị "Đang giữ". Nên: cảnh báo (chatter + thông báo cho
        người thao tác) + tự động chuyển yêu cầu giữ hàng sang "Đã hủy" để phản ánh đúng thực tế,
        không để sale tưởng nhầm hàng vẫn còn được giữ.
        """
        hold_pickings = self.filtered("is_stock_hold_picking")
        res = super().do_unreserve()
        if hold_pickings:
            # LƯU Ý: hành động "Hủy dự trữ" trong menu Actions (⋮) của phiếu kho đã bị tùy biến
            # (Studio) để gọi rec.do_unreserve() bên trong 1 khối try/except: pass — TỨC LÀ bất kỳ
            # exception nào xảy ra ở bất cứ đâu trong method này (kể cả không liên quan gì tới
            # phần dưới đây) sẽ bị nuốt hoàn toàn, im lặng, không log, không báo lỗi. Do đó:
            # 1. Đồng bộ trạng thái stock.hold.request (việc QUAN TRỌNG NHẤT) phải làm TRƯỚC
            #    và không được phép bị chặn bởi lỗi ở bước log/Zalo phía sau.
            # 2. message_post()/_notify_sale_zalo() bọc try/except RIÊNG từng cái, để lỗi gửi
            #    Zalo (vd module hlv_zalo_zns chưa cấu hình) không làm mất luôn cả việc ghi log.
            holds = self.env["stock.hold.request"].sudo().search([
                ("hold_picking_id", "in", hold_pickings.ids),
                ("state", "=", "approved"),
            ])
            if holds:
                holds.write({"state": "cancelled"})
                actor = self.env.user.name
                now_str = fields.Datetime.now()
                for hold in holds:
                    try:
                        hold.message_post(body=_(
                            "⚠️ CẢNH BÁO: Nhân viên kho (%(user)s) đã bấm \"Hủy dự trữ\" (Unreserve) "
                            "trên phiếu giữ hàng %(picking)s lúc %(time)s — hàng đã được nhả ra, có "
                            "thể đã dùng cho mục đích khác. Yêu cầu giữ hàng này KHÔNG còn hiệu lực "
                            "nữa, hệ thống đã tự chuyển sang trạng thái \"Đã hủy\". Nếu vẫn cần giữ "
                            "chỗ, vui lòng tạo lại yêu cầu giữ hàng mới."
                        ) % {
                            "user": actor,
                            "picking": hold.hold_picking_id.name,
                            "time": now_str,
                        })
                    except Exception:
                        _logger.exception(
                            "Không log được chatter cho yêu cầu giữ hàng %s sau khi Hủy dự trữ.",
                            hold.name,
                        )
                    try:
                        hold._notify_sale_zalo(_(
                            "⚠️ HÀNG ĐANG GIỮ ĐÃ BỊ NHẢ (kho thao tác)\n"
                            "--------------------\n"
                            "Mã yêu cầu: %(name)s\n"
                            "Sản phẩm: %(product)s\n"
                            "Kho: %(wh)s\n"
                            "Số lượng: %(qty)s\n"
                            "--------------------\n"
                            "Kho vừa \"Hủy dự trữ\" phiếu giữ hàng liên quan (có thể cần dùng hàng "
                            "cho việc khác). Yêu cầu giữ hàng này KHÔNG còn hiệu lực nữa. Vui lòng "
                            "liên hệ kho hoặc tạo lại yêu cầu giữ hàng mới nếu vẫn cần giữ chỗ."
                        ) % {
                            "name": hold.name,
                            "product": hold.product_id.display_name,
                            "wh": hold.warehouse_id.display_name,
                            "qty": "{:,.0f}".format(hold.quantity),
                        })
                    except Exception:
                        _logger.exception(
                            "Không gửi được Zalo cho yêu cầu giữ hàng %s sau khi Hủy dự trữ.",
                            hold.name,
                        )
            for picking in hold_pickings:
                try:
                    picking.message_post(body=_(
                        "Phiếu này là phiếu giữ chỗ cho yêu cầu giữ hàng — đã \"Hủy dự trữ\" nên "
                        "yêu cầu giữ hàng tương ứng cũng đã được tự động chuyển sang \"Đã hủy\"."
                    ))
                except Exception:
                    _logger.exception(
                        "Không log được chatter cho phiếu giữ hàng %s sau khi Hủy dự trữ.",
                        picking.name,
                    )
        return res

    def get_view(self, view_id=None, view_type='form', **options):
        """Ẩn các nút không phù hợp với phiếu giữ hàng (is_stock_hold_picking): 'Xác nhận'
        (button_validate), 'Hủy' (action_cancel), 'In Tem Nhãn' (action_open_label_wizard), 'In
        phiếu lấy hàng' (nút Studio) — buộc phải thao tác qua yêu cầu giữ hàng tương ứng (nút
        "Hoàn thành"/"Hủy" trên stock.hold.request) thay vì đụng thẳng vào phiếu kho, và không in
        ấn gì cho 1 phiếu vốn chỉ để giữ chỗ chứ không giao/nhận hàng thật. Các method này vẫn
        gọi thẳng được từ code nội bộ module (_reserve/_release) — ẩn nút chỉ chặn bấm tay trên UI.

        Không đụng vào điều kiện invisible gốc của các nút (không biết chắc nó là gì ở mọi
        version) — chỉ OR thêm điều kiện của mình vào, nên phiếu thường (is_stock_hold_picking=
        False) không bị ảnh hưởng gì cả. Bọc try/except để nếu có gì bất thường thì bỏ qua,
        không làm sập màn hình phiếu kho của cả hệ thống.
        """
        res = super().get_view(view_id=view_id, view_type=view_type, **options)
        if view_type != 'form':
            return res
        try:
            doc = etree.fromstring(res['arch'])
            xpath_expr = " | ".join(
                "//button[@name='%s']" % name for name in HIDDEN_BUTTON_NAMES_ON_HOLD_PICKING
            )
            buttons = doc.xpath(xpath_expr)
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
                "Không thể ẩn nút Xác nhận/Hủy cho phiếu giữ hàng — bỏ qua, dùng view gốc."
            )
            return super().get_view(view_id=view_id, view_type=view_type, **options)
        return res
