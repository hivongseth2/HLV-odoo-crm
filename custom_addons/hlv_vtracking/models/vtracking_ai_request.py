"""Yêu cầu nhân viên gửi cho AI: "đơn này giao sớm được không", "dời chuyến giúp"...

Vì sao cần một model riêng thay vì cho nhân viên sửa thẳng kế hoạch: người bán hàng biết
KHÁCH cần gì, nhưng không biết xe nào còn chỗ, cụm nào còn trần điểm, hàng đã về đủ chưa.
Phiếu này là chỗ họ nói mong muốn, AI tính hộ phần còn lại, và người điều phối vẫn là
người quyết. Mọi thứ để lại vết: ai xin, AI trả lời gì, ai duyệt.

AI được gọi dậy NGAY khi phiếu được tạo (xem ``_notify_worker``), không chờ cron.
"""

from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError

# Đặt bí danh cho hàm thuần: model có field cùng tên ``waiting_minutes``, để nguyên thì đọc
# code không biết chỗ nào là field chỗ nào là hàm.
from ..tools.vtracking_request import claimable, is_stale, state_after_answer
from ..tools.vtracking_request import waiting_minutes as _waiting_minutes

# Chờ quá mức này mà chưa ai nhận việc thì worker trên máy điều phối nhiều khả năng đang
# tắt. Hiện cảnh báo để người ta xử lý tay chứ không ngồi đợi một cái máy đã tắt.
STALE_AFTER_MINUTES = 10

BUS_MESSAGE_TYPE = 'hlv_vtracking/ai_request'


class HlvVtrackingAiRequest(models.Model):
    _name = 'hlv.vtracking.ai.request'
    _description = 'Yêu cầu gửi AI điều phối'
    _inherit = ['mail.thread']
    _order = 'create_date desc, id desc'

    name = fields.Char(compute='_compute_name', store=True)
    company_id = fields.Many2one(
        'res.company', required=True, index=True, default=lambda self: self.env.company,
    )
    requester_id = fields.Many2one(
        'res.users', string='Người gửi', required=True, index=True,
        default=lambda self: self.env.user, readonly=True,
    )
    request_type = fields.Selection(
        [
            ('earlier', 'Xin giao sớm hơn'),
            ('reschedule', 'Xin dời ngày / buổi khác'),
            ('add', 'Xin xếp vào chuyến'),
            ('remove', 'Xin gỡ khỏi chuyến'),
            ('question', 'Hỏi ý kiến'),
        ],
        string='Loại yêu cầu', required=True, default='earlier',
    )
    message = fields.Text(
        string='Nội dung', required=True,
        help='Viết như nói với người điều phối: khách cần gì, vì sao gấp, có ràng buộc gì.',
    )
    sale_order_id = fields.Many2one('sale.order', string='Đơn bán', index=True)
    picking_id = fields.Many2one('stock.picking', string='Phiếu giao', index=True)
    plan_id = fields.Many2one('hlv.vtracking.plan', string='Kế hoạch', index=True)
    desired_date = fields.Date(string='Ngày mong muốn')
    desired_session = fields.Selection(
        [('morning', 'Sáng'), ('afternoon', 'Chiều'), ('full_day', 'Cả ngày')],
        string='Buổi mong muốn',
    )

    state = fields.Selection(
        [
            ('pending', 'Chờ AI'),
            ('processing', 'AI đang xem'),
            ('answered', 'AI đã trả lời'),
            ('done', 'Xong'),
            ('rejected', 'Từ chối'),
            ('failed', 'AI lỗi'),
            ('cancelled', 'Đã huỷ'),
        ],
        default='pending', required=True, index=True, tracking=True,
    )
    approved = fields.Boolean(
        string='Đã duyệt đề xuất', readonly=True, copy=False,
        help='Người điều phối đồng ý cho AI áp đề xuất vào kế hoạch.',
    )
    verdict = fields.Selection(
        [
            ('feasible', 'Được'),
            ('conditional', 'Được nếu…'),
            ('not_feasible', 'Không được'),
            ('info', 'Trả lời'),
        ],
        string='Kết luận của AI', readonly=True, copy=False, tracking=True,
    )
    answer = fields.Html(
        string='AI trả lời', readonly=True, copy=False,
        help='Lý do, phương án, và điều AI chưa chắc.',
    )
    applied = fields.Boolean(
        string='AI đã sửa kế hoạch', readonly=True, copy=False,
        help='AI đã đổi kế hoạch NHÁP theo yêu cầu. Kế hoạch đã chốt thì AI chỉ đề xuất.',
    )
    error = fields.Text(string='Lỗi', readonly=True, copy=False)

    worker = fields.Char(string='Máy xử lý', readonly=True, copy=False)
    claimed_at = fields.Datetime(string='Nhận việc lúc', readonly=True, copy=False)
    answered_at = fields.Datetime(string='Trả lời lúc', readonly=True, copy=False)
    attempt_count = fields.Integer(string='Số lần thử', readonly=True, copy=False)

    waiting_minutes = fields.Integer(
        string='Chờ (phút)', compute='_compute_waiting', help='Từ lúc gửi tới lúc AI nhận việc.',
    )
    is_stale = fields.Boolean(
        string='AI chưa nhận', compute='_compute_waiting', search='_search_is_stale',
        help='Chờ quá %s phút mà chưa máy nào nhận việc — worker có thể đang tắt. Xử lý tay.'
             % STALE_AFTER_MINUTES,
    )
    # Nhãn dạng chữ để người bán hàng (không có quyền xem kế hoạch) vẫn đọc được phiếu
    # của mình mà không vướng lỗi truy cập khi client đọc display_name của many2one.
    plan_label = fields.Char(string='Kế hoạch (tên)', compute='_compute_plan_label')

    @api.depends('request_type', 'sale_order_id', 'picking_id', 'plan_id')
    def _compute_name(self):
        labels = dict(self._fields['request_type'].selection)
        for record in self:
            about = (record.sale_order_id.name or record.picking_id.name
                     or record.plan_id.name or '')
            record.name = '%s%s' % (labels.get(record.request_type, 'Yêu cầu'),
                                    ' · %s' % about if about else '')

    @api.depends('create_date', 'claimed_at', 'state')
    def _compute_waiting(self):
        now = fields.Datetime.now()
        for record in self:
            waiting = _waiting_minutes(record.create_date, record.claimed_at, now)
            record.waiting_minutes = waiting or 0
            record.is_stale = is_stale(record.state, waiting, STALE_AFTER_MINUTES)

    def _search_is_stale(self, operator, value):
        """Cho phép lọc "AI chưa nhận" trên danh sách.

        Field tính theo GIỜ HIỆN TẠI nên không lưu được; không có hàm này thì bộ lọc ném
        lỗi ngay khi bấm. Quy về điều kiện tương đương trên cột thật.
        """
        if operator not in ('=', '!='):
            raise UserError('Chỉ lọc được "AI chưa nhận" bằng = hoặc !=.')
        cutoff = fields.Datetime.now() - timedelta(minutes=STALE_AFTER_MINUTES)
        stale = [('state', '=', 'pending'), ('create_date', '<=', cutoff)]
        wants_stale = bool(value) == (operator == '=')
        return stale if wants_stale else ['!', '&'] + stale

    @api.depends('plan_id')
    def _compute_plan_label(self):
        for record in self:
            record.plan_label = record.plan_id.sudo().name or ''

    @api.constrains('sale_order_id', 'picking_id', 'plan_id', 'request_type')
    def _check_target(self):
        for record in self:
            if not (record.sale_order_id or record.picking_id or record.plan_id):
                raise ValidationError('Phải chọn đơn bán, phiếu giao hoặc kế hoạch để AI '
                                      'biết yêu cầu nói về cái gì.')

    # ------------------------------------------------------------------
    # Gọi AI dậy
    # ------------------------------------------------------------------
    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        records._notify_worker()
        return records

    def _notify_worker(self):
        """Đẩy một tin qua bus tới tài khoản worker — máy đang giữ websocket nhận ngay.

        Bus chỉ gửi SAU KHI commit, nên worker không bao giờ thấy phiếu trước khi nó có
        trong cơ sở dữ liệu. Gửi trượt cũng không sao: worker vét lại bằng API mỗi lần nối
        lại, và cron dự phòng vẫn chạy.
        """
        for record in self.filtered(lambda r: r.state == 'pending'):
            worker_user = record.company_id.sudo().ai_worker_user_id
            if not worker_user:
                continue
            self.env['bus.bus']._sendone(
                worker_user.partner_id, BUS_MESSAGE_TYPE,
                {'request_id': record.id, 'company_id': record.company_id.id},
            )

    # ------------------------------------------------------------------
    # Worker gọi (qua API)
    # ------------------------------------------------------------------
    def claim(self, worker):
        """Nhận việc. Trả về True nếu phiếu này thuộc về worker gọi, False nếu người khác
        đã nhận trước — hai worker chạy song song không xử lý trùng.

        Khoá dòng bằng ``FOR UPDATE SKIP LOCKED``: bỏ qua dòng đang bị giao dịch khác giữ
        thay vì ngồi đợi nó.
        """
        self.ensure_one()
        self.env.cr.execute(
            'SELECT state FROM hlv_vtracking_ai_request WHERE id = %s FOR UPDATE SKIP LOCKED',
            (self.id,),
        )
        row = self.env.cr.fetchone()
        if not row or not claimable(row[0]):
            return False
        self.write({
            'state': 'processing',
            'worker': worker or 'không rõ',
            'claimed_at': fields.Datetime.now(),
            'attempt_count': self.attempt_count + 1,
            'error': False,
        })
        return True

    def write_answer(self, verdict, answer, applied=False):
        """AI trả lời. Người gửi nhận thông báo ngay trên phiếu."""
        self.ensure_one()
        self.write({
            'verdict': verdict,
            'answer': answer,
            'applied': applied,
            'answered_at': fields.Datetime.now(),
            'state': state_after_answer(applied),
        })
        self.message_post(
            body=answer, message_type='notification',
            partner_ids=self.requester_id.partner_id.ids,
        )
        return True

    def write_failure(self, error):
        self.ensure_one()
        self.write({'state': 'failed', 'error': error})
        return True

    # ------------------------------------------------------------------
    # Nút trên form
    # ------------------------------------------------------------------
    def action_approve(self):
        """Điều phối đồng ý cho AI áp đề xuất.

        Kế hoạch đã chốt thì đưa VỀ NHÁP tại đây — do người bấm, không phải AI tự làm.
        Xong việc, người điều phối chốt lại.
        """
        for record in self:
            if record.state != 'answered':
                raise UserError('Chỉ duyệt được phiếu AI đã trả lời.')
            if record.plan_id.state == 'confirmed':
                record.plan_id.action_back_to_draft()
                record.plan_id.message_post(
                    body='Về nháp để áp đề xuất của AI (yêu cầu #%s).' % record.id,
                    message_type='notification',
                )
            record.write({'approved': True, 'state': 'pending'})
        self._notify_worker()
        return True

    def action_reject(self):
        self.write({'state': 'rejected'})
        return True

    def action_retry(self):
        """Gửi lại cho AI — dùng khi worker lỗi hoặc lúc gửi máy đang tắt."""
        self.write({'state': 'pending', 'error': False})
        self._notify_worker()
        return True

    def action_cancel(self):
        for record in self:
            if record.requester_id != self.env.user and not self.env.user.has_group(
                'hlv_vtracking.group_vtracking_user'
            ):
                raise UserError('Chỉ người gửi hoặc người điều phối mới huỷ được phiếu này.')
        self.write({'state': 'cancelled'})
        return True

    @api.model
    def _cron_retry_stale(self):
        """Dự phòng cho lúc bus gửi trượt: gọi lại các phiếu còn chờ.

        Không đổi trạng thái, chỉ bắn lại tin bus. Phiếu nào worker đã nhận rồi thì
        ``claim`` từ chối, nên gọi lại nhiều lần vô hại.
        """
        pending = self.search([('state', '=', 'pending')])
        pending._notify_worker()
        return len(pending)
