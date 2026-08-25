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
        phiếu, chỉ nhả reservation. Ảnh hưởng tới 2 nhóm phiếu cần cảnh báo cho sale:
        1. Phiếu giữ hàng (is_stock_hold_picking) — tác dụng khóa hàng của yêu cầu giữ hàng
           tương ứng coi như đã mất, dù trạng thái vẫn hiển thị "Đang giữ".
        2. Phiếu Lấy hàng (PICK) của 1 đơn bán thật (kho đang cấu hình chỉ cho phép Hủy dự trữ ở
           bước PICK trong quy trình xuất kho 3 bước) — hàng của đơn khách bị nhả ra.

        Dùng context cờ _skip_hold_unreserve_notify khi gọi super() để chặn StockMoveLine.unlink()
        (bị super().do_unreserve() gọi tới bên trong) tự bắn thêm 1 lần thông báo trùng lặp cho
        đúng các phiếu này — phần thông báo do CHÍNH method này đảm nhiệm là đủ.
        """
        hold_pickings = self.filtered("is_stock_hold_picking")
        sale_pick_pickings = self.filtered(
            lambda p: not p.is_stock_hold_picking
            and p.picking_type_id.sequence_code == "PICK"
            and p.sale_id
        )
        res = super(StockPicking, self.with_context(_skip_hold_unreserve_notify=True)).do_unreserve()
        # LƯU Ý: hành động "Hủy dự trữ" trong menu Actions (⋮) của phiếu kho đã bị tùy biến
        # (Studio) để gọi rec.do_unreserve() bên trong 1 khối try/except: pass — TỨC LÀ bất kỳ
        # exception nào xảy ra ở bất cứ đâu trong method này (kể cả không liên quan gì tới phần
        # dưới đây) sẽ bị nuốt hoàn toàn, im lặng, không log, không báo lỗi. Do đó mọi bước quan
        # trọng bên dưới đều tự bọc try/except riêng, không để 1 lỗi làm mất luôn các bước khác.
        if hold_pickings:
            hold_pickings._sync_and_notify_hold_pickings_unreserved(reason="unreserve")
        if sale_pick_pickings:
            sale_pick_pickings._notify_sale_pick_unreserved(reason="unreserve")
        return res

    def _sync_and_notify_hold_pickings_unreserved(self, reason="unreserve"):
        """self: các phiếu giữ hàng (is_stock_hold_picking) vừa mất reservation — do bấm "Hủy dự
        trữ" (reason='unreserve') hoặc bị xóa dòng move line thủ công (reason='delete_move_line').
        Đồng bộ trạng thái stock.hold.request liên quan sang "Đã hủy" (việc QUAN TRỌNG NHẤT, làm
        TRƯỚC và không phụ thuộc log/Zalo phía sau) + cảnh báo qua chatter và Zalo cho sale."""
        holds = self.env["stock.hold.request"].sudo().search([
            ("hold_picking_id", "in", self.ids),
            ("state", "=", "approved"),
        ])
        if not holds:
            return
        holds.write({"state": "cancelled"})

        action_label = (
            "xóa dòng dự trữ thủ công (Move Line)" if reason == "delete_move_line"
            else "bấm \"Hủy dự trữ\" (Unreserve)"
        )
        actor = self.env.user.name
        now_str = fields.Datetime.now()
        for hold in holds:
            try:
                hold.message_post(body=_(
                    "⚠️ CẢNH BÁO: Nhân viên kho (%(user)s) đã %(action)s trên phiếu giữ hàng "
                    "%(picking)s lúc %(time)s — hàng đã được nhả ra, có thể đã dùng cho mục đích "
                    "khác. Yêu cầu giữ hàng này KHÔNG còn hiệu lực nữa, hệ thống đã tự chuyển sang "
                    "trạng thái \"Đã hủy\". Nếu vẫn cần giữ chỗ, vui lòng tạo lại yêu cầu giữ hàng mới."
                ) % {
                    "user": actor,
                    "action": action_label,
                    "picking": hold.hold_picking_id.name,
                    "time": now_str,
                })
            except Exception:
                _logger.exception(
                    "Không log được chatter cho yêu cầu giữ hàng %s sau khi %s.",
                    hold.name, action_label,
                )
            try:
                hold._notify_sale_zalo(_(
                    "⚠️ HÀNG ĐANG GIỮ ĐÃ BỊ NHẢ (kho thao tác: %(action)s)\n"
                    "--------------------\n"
                    "Mã yêu cầu: %(name)s\n"
                    "Sản phẩm: %(product)s\n"
                    "Kho: %(wh)s\n"
                    "Số lượng: %(qty)s\n"
                    "--------------------\n"
                    "Kho vừa thao tác nhả phiếu giữ hàng liên quan (có thể cần dùng hàng cho việc "
                    "khác). Yêu cầu giữ hàng này KHÔNG còn hiệu lực nữa. Vui lòng liên hệ kho hoặc "
                    "tạo lại yêu cầu giữ hàng mới nếu vẫn cần giữ chỗ."
                ) % {
                    "action": action_label,
                    "name": hold.name,
                    "product": hold.product_id.display_name,
                    "wh": hold.warehouse_id.display_name,
                    "qty": "{:,.0f}".format(hold.quantity),
                })
            except Exception:
                _logger.exception(
                    "Không gửi được Zalo cho yêu cầu giữ hàng %s sau khi %s.",
                    hold.name, action_label,
                )
        for picking in self:
            try:
                picking.message_post(body=_(
                    "Phiếu này là phiếu giữ chỗ cho yêu cầu giữ hàng — đã %s nên yêu cầu giữ "
                    "hàng tương ứng cũng đã được tự động chuyển sang \"Đã hủy\"."
                ) % action_label)
            except Exception:
                _logger.exception(
                    "Không log được chatter cho phiếu giữ hàng %s sau khi %s.",
                    picking.name, action_label,
                )

    def _notify_sale_pick_unreserved(self, reason="unreserve"):
        """self: các phiếu Lấy hàng (PICK) của đơn bán thật vừa mất reservation — do "Hủy dự
        trữ" (reason='unreserve') hoặc bị xóa dòng move line thủ công (reason='delete_move_line').
        Báo Zalo cho đúng sale đứng đơn (theo Sale Order.x_studio_misa_saler_code), dùng chung
        mapping hold_unreserve_saler_mapping_text với thông báo giữ hàng."""
        config = self.env["hlv.zalo.stock.notification"].sudo()._get_active_config()
        if not config:
            _logger.info(
                "Không có cấu hình Zalo Stock Notification đang active, bỏ qua báo PICK unreserve cho: %s",
                ", ".join(self.mapped("name")),
            )
            return
        action_label = (
            "xóa dòng dự trữ thủ công (Move Line)" if reason == "delete_move_line"
            else "\"Hủy dự trữ\" (Unreserve)"
        )
        for picking in self:
            saler_code = getattr(picking.sale_id, "x_studio_misa_saler_code", False)
            if not saler_code:
                _logger.info(
                    "Phiếu %s (đơn %s) không có x_studio_misa_saler_code, bỏ qua báo PICK unreserve.",
                    picking.name, picking.sale_id.name,
                )
                continue
            if not config.get_hold_unreserve_saler_user_ids_from_mapping(saler_code):
                _logger.info(
                    "Không tìm thấy Zalo user_id cho saler_code=%s (phiếu %s, đơn %s) trong "
                    "hold_unreserve_saler_mapping_text, bỏ qua.",
                    saler_code, picking.name, picking.sale_id.name,
                )
                continue
            products = ", ".join(sorted(set(
                picking.move_ids.mapped("product_id.display_name")
            ))) or "(không rõ)"
            message = _(
                "⚠️ MẤT HÀNG DỰ TRỮ - PHIẾU LẤY HÀNG\n"
                "--------------------\n"
                "Đơn bán: %(so)s\n"
                "Phiếu lấy hàng: %(picking)s\n"
                "Sản phẩm: %(products)s\n"
                "--------------------\n"
                "Kho vừa thực hiện %(action)s trên phiếu lấy hàng của đơn hàng này — hàng đã "
                "được nhả ra, có thể cần chuẩn bị lại trước khi giao. Vui lòng kiểm tra lại đơn hàng."
            ) % {
                "so": picking.sale_id.name,
                "picking": picking.name,
                "products": products,
                "action": action_label,
            }
            try:
                config.send_hold_unreserve_notification(saler_code, message)
            except Exception:
                _logger.exception(
                    "Lỗi gửi Zalo (PICK unreserve) cho phiếu %s (đơn %s).",
                    picking.name, picking.sale_id.name,
                )

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
