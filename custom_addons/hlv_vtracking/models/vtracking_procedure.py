"""Người bán báo ĐÃ LÀM XONG thủ tục cho một chứng từ.

Vì sao phải có ô này ở đây chứ không chỉ ở dòng kế hoạch: thói quen khách nói "khách này
phải khai hải quan trước khi xe vào", và cờ đó chặn đơn khỏi MỌI kế hoạch. Trong khi ô
"Thủ tục đã xong" lại nằm trên dòng kế hoạch — tức là chỉ tích được sau khi đơn đã vào
chuyến. Đơn bị chặn thì không vào chuyến, không vào chuyến thì không có chỗ tích: vòng
luẩn quẩn, và cách duy nhất thoát ra là người điều phối xếp tay rồi tự tích.

Ô này cắt vòng đó. Người bán làm xong tờ khai thì bấm ngay trên đơn của mình; từ lúc đó
máy coi chứng từ là xếp được, và dòng kế hoạch sinh ra sau cũng đã sẵn "thủ tục đã xong".

Cờ gắn vào CHỨNG TỪ chứ không vào khách: tờ khai hải quan làm cho từng lô hàng, không
phải làm một lần cho cả đời khách.
"""

from odoo import api, fields, models


class SaleOrderProcedure(models.Model):
    _inherit = 'sale.order'

    vtracking_procedure_ready = fields.Boolean(
        string='Thủ tục giao hàng đã xong', tracking=True, copy=False,
        help='Tích khi đã khai hải quan / đã đăng ký người và xe với khách cho ĐƠN NÀY. '
             'Chưa tích thì đơn không được xếp lên xe, vì bảo vệ sẽ không cho xe vào cổng.',
    )

    def action_vtracking_procedure_done(self):
        """Nút "Đã xong thủ tục" trong menu Thao tác của đơn bán."""
        return _mark_done(self, 'đơn bán')


class StockPickingProcedure(models.Model):
    _inherit = 'stock.picking'

    vtracking_procedure_ready = fields.Boolean(
        string='Thủ tục giao hàng đã xong', tracking=True, copy=False,
        compute='_compute_vtracking_procedure_ready', store=True, readonly=False,
        help='Tích khi đã khai hải quan / đã đăng ký người và xe với khách cho LÔ HÀNG '
             'này. Mặc định lấy theo đơn bán, sửa riêng cho phiếu được.',
    )

    @api.depends('sale_id.vtracking_procedure_ready')
    def _compute_vtracking_procedure_ready(self):
        """Theo đơn bán, nhưng chỉ theo chiều BẬT.

        Người bán tích trên đơn là muốn cả lô hàng của đơn đó đi được. Ngược lại, kho đã
        tự tích trên một phiếu rồi thì đừng gỡ ra chỉ vì đơn chưa tích — phiếu là thứ sát
        thực tế hơn.
        """
        for picking in self:
            if picking.sale_id.vtracking_procedure_ready:
                picking.vtracking_procedure_ready = True
            elif not picking.vtracking_procedure_ready:
                picking.vtracking_procedure_ready = False

    def action_vtracking_procedure_done(self):
        """Nút "Đã xong thủ tục" trong menu Thao tác của phiếu giao."""
        return _mark_done(self, 'phiếu giao')


def _mark_done(documents, nhan):
    """Bật cờ và ghi vào chatter. Ghi lại vì đây là việc có hậu quả: nó mở đường cho đơn
    lên xe, nên sau này phải tra được ai bấm và bấm lúc nào."""
    documents.write({'vtracking_procedure_ready': True})
    for document in documents:
        document.message_post(
            body='Đã xác nhận xong thủ tục giao hàng (%s). Chứng từ này xếp lên xe được.'
                 % nhan,
            message_type='notification',
        )
    return True
