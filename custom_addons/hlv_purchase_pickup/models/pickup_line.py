from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

OPEN_RUN_STATES = ('draft', 'assigned', 'departed')
# Đơn coi như còn phải đi nhận tiếp — được phép xếp vào chuyến sau.
UNFINISHED_STATES = ('pending', 'not_ready', 'partial')


class HlvPickupLine(models.Model):
    """Một đơn mua hàng cần lấy tại một điểm.

    Module KHÔNG xác nhận đơn mua thật: không đụng ``stock.picking``, không đổi trạng thái
    ``purchase.order``, không đối soát số lượng. Dòng này chỉ trả lời đúng một câu: người đi
    nhận có lấy được đơn này về hay không, lúc mấy giờ.
    """

    _name = 'hlv.pickup.line'
    _description = 'Đơn mua hàng trong chuyến nhận'
    _order = 'stop_id, id'

    stop_id = fields.Many2one(
        'hlv.pickup.stop', string='Điểm nhận', required=True, index=True, ondelete='cascade',
    )
    run_id = fields.Many2one(related='stop_id.run_id', store=True, index=True, string='Chuyến')
    date = fields.Date(related='stop_id.date', store=True, index=True)
    point_id = fields.Many2one(related='stop_id.point_id', store=True, index=True)

    purchase_order_id = fields.Many2one(
        'purchase.order', string='Đơn mua hàng', index=True, ondelete='set null',
        help='Chỉ là tham chiếu. Nhận hàng ở đây không xác nhận đơn, không tạo phiếu kho.',
    )
    # Snapshot: đơn bị sửa hoặc xoá sau chuyến thì lịch sử đi nhận vẫn đọc được. Không có
    # mấy field này thì một lần dọn dữ liệu mua hàng sẽ xoá trắng số liệu đo được.
    po_name = fields.Char(string='Số đơn', required=True)
    po_partner_name = fields.Char(string='Nhà cung cấp')
    po_amount = fields.Monetary(string='Giá trị', currency_field='currency_id')
    po_date = fields.Date(string='Ngày đặt')
    currency_id = fields.Many2one('res.currency', string='Tiền tệ')

    state = fields.Selection(
        [
            ('pending', 'Chưa xử lý'),
            ('received', 'Đã nhận'),
            ('partial', 'Nhận một phần'),
            ('not_ready', 'Chưa có hàng'),
            ('cancelled', 'Bỏ đơn'),
        ],
        default='pending', required=True, index=True,
    )
    received_at = fields.Datetime(string='Nhận lúc', readonly=True, copy=False)
    received_by_id = fields.Many2one('res.users', string='Người nhận', readonly=True, copy=False)
    package_note = fields.Char(
        string='Kiện hàng',
        help='Người đi nhận gõ tay, VD "3 kiện, 1 pallet". Đây KHÔNG phải số lượng nghiệp '
             'vụ — kế toán và kho đối soát ở luồng riêng.',
    )
    note = fields.Char(string='Ghi chú', help='Bắt buộc khi chưa có hàng hoặc chỉ nhận một phần.')

    @api.constrains('purchase_order_id', 'stop_id')
    def _check_single_open_run(self):
        """Một đơn chỉ nằm trong một chuyến ĐANG MỞ.

        Viết ở Python chứ không ở SQL constraint vì luật phụ thuộc trạng thái chuyến: đơn
        chưa lấy được ở chuyến hôm qua (``not_ready``) phải xếp lại được vào chuyến hôm nay,
        còn unique(purchase_order_id) sẽ chặn luôn cả trường hợp đó.
        """
        for line in self:
            if not line.purchase_order_id:
                continue
            duplicate = self.search([
                ('id', '!=', line.id),
                ('purchase_order_id', '=', line.purchase_order_id.id),
                ('run_id.state', 'in', OPEN_RUN_STATES),
            ], limit=1)
            if duplicate:
                raise ValidationError(
                    'Đơn %s đã nằm trong chuyến "%s" đang mở. Gỡ khỏi chuyến đó trước.'
                    % (line.po_name, duplicate.run_id.name)
                )

    @api.model
    def snapshot_values(self, order):
        """Giá trị chép cứng từ một ``purchase.order`` lúc xếp vào chuyến.

        Trả về dict dùng thẳng cho create. Gom ở một chỗ để wizard và API không chép lệch nhau.
        """
        return {
            'purchase_order_id': order.id,
            'po_name': order.name,
            'po_partner_name': order.partner_id.display_name or '',
            'po_amount': order.amount_total,
            'po_date': order.date_order.date() if order.date_order else False,
            'currency_id': order.currency_id.id,
        }

    def mark_state(self, state, note=None, package_note=None, when=None):
        """Đánh dấu kết quả nhận đơn.

        state: một trong ``received / partial / not_ready / cancelled``.
        Các trạng thái không phải "đã nhận" bắt buộc có lý do — không có lý do thì lần sau
        không ai biết vì sao đơn này cứ trượt hết chuyến này tới chuyến khác.
        """
        self.ensure_one()
        if state not in ('received', 'partial', 'not_ready', 'cancelled'):
            raise UserError('Trạng thái "%s" không hợp lệ cho đơn nhận hàng.' % state)
        if self.run_id.state in ('done', 'cancelled'):
            raise UserError('Chuyến đã kết thúc nên không sửa được đơn %s.' % self.po_name)
        if state != 'received' and not (note or self.note or '').strip():
            raise UserError('Phải ghi lý do cho đơn %s.' % self.po_name)

        values = {'state': state}
        if note is not None:
            values['note'] = note
        if package_note is not None:
            values['package_note'] = package_note
        if state in ('received', 'partial'):
            values['received_at'] = when or fields.Datetime.now()
            values['received_by_id'] = self.env.user.id
        self.write(values)
        return True

    def action_received(self):
        for line in self:
            line.mark_state('received')
        return True

    def action_open_purchase_order(self):
        self.ensure_one()
        if not self.purchase_order_id:
            raise UserError('Đơn %s không còn trên hệ thống (đã bị xoá).' % self.po_name)
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'purchase.order',
            'res_id': self.purchase_order_id.id,
            'view_mode': 'form',
        }
