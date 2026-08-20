import html

from bs4 import BeautifulSoup
from markupsafe import Markup

from odoo import api, fields, models
from odoo.exceptions import UserError

REPORT_NAME_SEARCH = 'Hoạt động lấy hàng TSN'


class HlvIotPrintQueue(models.Model):
    _name = 'hlv.iot.print.queue'
    _inherit = ['mail.thread']
    _description = 'Hàng chờ in phiếu lấy hàng IoT (sale gửi từ /sale_plan, tự động in ở backend)'
    _order = 'create_date desc'
    _rec_name = 'sale_order_id'

    sale_order_id = fields.Many2one('sale.order', string='Đơn hàng', required=True,
                                     ondelete='cascade', index=True)
    warehouse_id = fields.Many2one('stock.warehouse', string='Kho', required=True, index=True)
    picking_ids = fields.Many2many('stock.picking', string='Phiếu lấy hàng')
    # tracking=True: mỗi lần đổi state/error_message, Odoo tự ghi 1 dòng vào chatter (mail.thread)
    # kèm người bấm + thời gian — dùng để ĐỐI SOÁT khi sale nói "đã gửi in" nhưng kho không thấy
    # giấy: xem lại chatter của đúng bản ghi này biết chính xác ai gửi lúc nào, hệ thống có thật sự
    # dispatch được không, có bị báo lỗi/gửi lại lần nào không.
    state = fields.Selection([
        ('pending', 'Chờ in'),
        ('printing', 'Đang in...'),
        # Chỉ có nghĩa "đã GỬI lệnh in thành công" (report action đã dispatch) — KHÔNG chắc chắn
        # máy in vật lý đã in ra giấy (IoT Box có thể mất kết nối máy in SAU khi lệnh đã gửi,
        # Odoo không có cách nào báo lại lỗi đó cho ta biết theo thời gian thực). Nếu kho thấy máy
        # không ra giấy dù trạng thái ở đây là "đã gửi lệnh in", dùng action_requeue để gửi lại.
        ('printed', 'Đã gửi lệnh in'),
        ('error', 'Lỗi'),
        ('cancelled', 'Đã hủy'),
    ], string='Trạng thái', default='pending', required=True, index=True, tracking=True)
    error_message = fields.Char(string='Lý do lỗi', tracking=True)
    requested_by_id = fields.Many2one('res.users', string='Sale yêu cầu',
                                       default=lambda self: self.env.user, tracking=True)
    requested_at = fields.Datetime(string='Thời gian yêu cầu', default=fields.Datetime.now)
    printed_by_id = fields.Many2one('res.users', string='Người/phiên đã in', tracking=True)
    printed_at = fields.Datetime(string='Thời gian in')

    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            # Markup(...) % (...) tự escape các giá trị chèn vào (tên user/đơn/kho), chỉ giữ
            # nguyên phần thẻ <b> tĩnh do mình viết — KHÔNG dùng body_is_html=True với chuỗi str
            # thường, vì message_post() sẽ escape luôn cả thẻ <b> lẫn nội dung (double-escape,
            # hiện ra &lt;b&gt; trên UI) nếu body không phải kiểu Markup.
            rec.message_post(body=Markup(
                'Sale <b>%s</b> gửi yêu cầu in đơn <b>%s</b> cho kho <b>%s</b>.'
            ) % (rec.requested_by_id.name or '?', rec.sale_order_id.name, rec.warehouse_id.name))
        return records

    def _claim_ids(self, ids):
        """Atomically chuyển state pending -> printing cho đúng những id còn 'pending' tại thời
        điểm này (1 câu UPDATE ... WHERE state='pending' duy nhất) — tránh 2 phiên dashboard đang
        mở cùng lúc (VD dispatcher + vài máy kho) cùng nhận bus event rồi in trùng lặp 1 yêu cầu.
        Trả về recordset CHỈ gồm những bản ghi request này thực sự thắng (claim được)."""
        if not ids:
            return self.browse()
        self.env.cr.execute(
            "UPDATE hlv_iot_print_queue SET state = 'printing' "
            "WHERE id = ANY(%s) AND state = 'pending' RETURNING id",
            (list(ids),),
        )
        claimed_ids = [r[0] for r in self.env.cr.fetchall()]
        return self.browse(claimed_ids)

    def _do_print(self):
        """Thực hiện in 1 bản ghi ĐÃ claim (state='printing'). Set device_ids của report theo
        đúng kho rồi TRẢ VỀ report action (không tự render PDF trong Python) — phải để trình
        duyệt (FE) gọi action.doAction() thì mới thực sự kích hoạt in qua IoT Box (đã xác nhận:
        gọi _render_qweb_pdf() thẳng trong Python không in ra máy, chỉ tải PDF).
        Trả về action dict nếu OK, hoặc False nếu lỗi (đã ghi state='error' + error_message —
        CHÚ Ý: chỉ bắt được lỗi truớc-khi-in (thiếu máy in/report/phiếu), không biết được máy in
        vật lý có thực sự in ra giấy hay không sau khi action đã dispatch)."""
        self.ensure_one()
        try:
            if not self.picking_ids:
                self.write({'state': 'error', 'error_message': 'Không có phiếu nào để in.'})
                return False

            report = self.env['ir.actions.report'].sudo().search([
                ('name', 'ilike', REPORT_NAME_SEARCH),
            ], limit=1)
            if not report:
                self.write({'state': 'error', 'error_message': 'Không tìm thấy report template cho phiếu lấy hàng.'})
                return False

            device = self.warehouse_id.x_iot_printer_device_id
            if not device:
                self.write({
                    'state': 'error',
                    'error_message': 'Kho "%s" chưa gán máy in IoT (vào Kho hàng > cấu hình).' % (self.warehouse_id.name or ''),
                })
                return False

            # Kiểm tra máy in có đang online không TRƯỚC khi gửi lệnh — trước đây gửi mù (dispatch
            # ngay không hỏi trước), nếu IoT Box/máy in mất kết nối thì phải chờ doAction() ở FE
            # thất bại mới biết. iot.device.connected là cờ Odoo tự cập nhật theo heartbeat từ IoT
            # Box (đã xác minh có phản ánh đúng thực tế qua bin/check_iot_device_fields.py — 1 máy
            # mất kết nối thật có connected=False, write_date cũ hẳn so với máy cùng box còn sống).
            # Không thay được việc "in thật lên giấy", nhưng chặn được sớm case "IoT Box/máy in
            # offline" thay vì phải chờ máy khác báo kho không ra giấy.
            if not device.connected:
                last_seen = fields.Datetime.to_string(device.write_date) if device.write_date else 'không rõ'
                self.write({
                    'state': 'error',
                    'error_message': 'Máy in "%s" (kho %s) đang OFFLINE (lần cuối phản hồi: %s) — '
                                      'kiểm tra IoT Box/máy in trước khi gửi lại.' % (
                                          device.name or '', self.warehouse_id.name or '', last_seen,
                                      ),
                })
                return False

            target_ids = {device.id}
            if set(report.device_ids.ids) != target_ids:
                report.sudo().write({'device_ids': [(6, 0, list(target_ids))]})

            self.write({
                'state': 'printed',
                'printed_by_id': self.env.uid,
                'printed_at': fields.Datetime.now(),
            })
            return report.report_action(self.picking_ids)
        except Exception as e:
            # Bảo đảm KHÔNG bao giờ kẹt ở state='printing' nếu có lỗi bất ngờ (VD constraint,
            # ACL...) — luôn rơi về 'error' để hàng chờ hiển thị được và có thể "Đưa lại vào hàng chờ".
            self.write({'state': 'error', 'error_message': str(e)[:500]})
            return False

    def action_print_now(self):
        """Nút "In ngay" thủ công (backend, kho bấm tay — dùng để thử lại 1 yêu cầu, cơ chế tự
        động xem auto_claim_and_print). Dùng chung claim atomic với auto-processor để tránh
        đụng độ nếu 1 phiên khác cũng đang tự động xử lý đúng lúc."""
        self.ensure_one()
        claimed = self._claim_ids([self.id])
        if not claimed:
            raise UserError('Yêu cầu này đang được xử lý bởi phiên khác hoặc đã xử lý xong, hãy tải lại danh sách.')
        action = claimed._do_print()
        if not action:
            raise UserError(claimed.error_message or 'In thất bại.')
        return action

    def action_retry(self):
        """Đưa các bản ghi lỗi về lại 'pending' để auto-processor / nút In ngay thử lại."""
        self.filtered(lambda q: q.state == 'error').write({'state': 'pending', 'error_message': False})

    def action_requeue(self):
        """"Gửi lại lệnh in" — dùng khi trạng thái đang là 'Đã gửi lệnh in' NHƯNG máy in vật lý
        thực tế không ra giấy (VD: IoT Box mất kết nối máy in sau khi lệnh đã gửi — Odoo không có
        cách báo lỗi này lại cho hệ thống theo thời gian thực, kho phải tự nhận biết và bấm nút
        này). Khác action_retry ở chỗ áp dụng được cho CẢ state='printed', không chỉ 'error'."""
        self.filtered(lambda q: q.state in ('printed', 'error')).write({
            'state': 'pending', 'error_message': False, 'printed_by_id': False, 'printed_at': False,
        })

    def action_cancel(self):
        self.filtered(lambda q: q.state in ('pending', 'error')).write({'state': 'cancelled'})

    def _to_summary_dict(self):
        self.ensure_one()
        return {
            'id': self.id,
            'sale_order_id': self.sale_order_id.id,
            'sale_order_name': self.sale_order_id.name,
            'warehouse_id': self.warehouse_id.id,
            'warehouse_name': self.warehouse_id.name,
            'state': self.state,
            'error_message': self.error_message or '',
            'requested_by_name': self.requested_by_id.name or '',
            'requested_at': self.requested_at.isoformat() if self.requested_at else False,
            'printed_by_name': self.printed_by_id.name or '',
            'printed_at': self.printed_at.isoformat() if self.printed_at else False,
        }

    @api.model
    def get_printer_status_by_warehouse(self):
        """Trạng thái ONLINE/OFFLINE của máy in IoT theo từng kho — để sale VÀ kho đều thấy
        ngay lý do 1 yêu cầu in có thể bị kẹt/lỗi (máy in mất kết nối), không cần đợi bấm in
        rồi mới biết. Chỉ trả về kho ĐÃ gán máy in (chưa gán thì không có gì để báo trạng thái)."""
        warehouses = self.env['stock.warehouse'].sudo().search([
            ('x_iot_printer_device_id', '!=', False),
        ])
        result = []
        for wh in warehouses:
            device = wh.x_iot_printer_device_id
            result.append({
                'warehouse_id': wh.id,
                'warehouse_name': wh.name,
                'device_name': device.name or '',
                'connected': bool(device.connected),
                'last_seen': device.write_date.isoformat() if device.write_date else False,
            })
        return result

    @api.model
    def get_recent_for_dashboard(self, limit=100):
        """Danh sách cho drawer "Yêu cầu in (IoT)" trên dashboard backend "Điều phối Giao hàng"."""
        return [r._to_summary_dict() for r in self.search([], limit=limit)]

    @api.model
    def get_recent_for_sale_plan(self, limit=200):
        """Danh sách cho drawer "Yêu cầu in" trên /sale_plan — kèm mã sale MISA của đơn để FE
        nhóm theo sale (nhiều sale có thể dùng chung 1 tài khoản đăng nhập, xem "Đơn của tôi")."""
        result = []
        for r in self.search([], limit=limit):
            d = r._to_summary_dict()
            d['saler_code'] = r.sale_order_id.x_studio_misa_saler_code or ''
            result.append(d)
        return result

    def _messages_to_log(self, queues):
        """Đổi message chatter của các bản ghi hàng chờ `queues` thành list nhật ký thuần text
        (sắp theo thời gian), dùng chung cho get_log_for_picking/get_log_for_sale_order."""
        if not queues:
            return []
        messages = self.env['mail.message'].sudo().search([
            ('model', '=', 'hlv.iot.print.queue'),
            ('res_id', 'in', queues.ids),
        ], order='date asc')
        result = []
        for msg in messages:
            # html.unescape trước để xử lý các message cũ (tạo trước bản fix Markup) bị lưu dạng
            # double-escaped ("&lt;b&gt;...&lt;/b&gt;" là TEXT thật, không phải thẻ) — sau đó
            # BeautifulSoup lấy lại đúng text thuần, bỏ mọi thẻ HTML (cũ lẫn mới).
            body_text = BeautifulSoup(html.unescape(msg.body or ''), 'html.parser').get_text().strip()
            if not body_text:
                continue
            result.append({
                'date': msg.date.isoformat() if msg.date else False,
                'author': msg.author_id.name or msg.email_from or 'Hệ thống',
                'body': body_text,
            })
        return result

    @api.model
    def get_log_for_picking(self, picking_id):
        """Nhật ký các yêu cầu in liên quan tới 1 phiếu CỤ THỂ — gắn thẳng vào phiếu để đối soát
        (VD 1 ngày cả trăm yêu cầu in, không thể mò trong danh sách chung của tất cả hàng chờ).
        Gộp message của MỌI bản ghi hàng chờ từng chứa phiếu này (1 phiếu có thể được gửi in lại
        nhiều lần nếu trước đó lỗi/không ra giấy), sắp theo thời gian."""
        picking_id = int(picking_id)
        queues = self.search([('picking_ids', 'in', [picking_id])])
        return self._messages_to_log(queues)

    @api.model
    def get_log_for_sale_order(self, sale_order_id):
        """Nhật ký in gộp cho CẢ ĐƠN (mọi phiếu) — dùng cho tab "Nhật ký" trong drawer đơn ở
        dashboard backend "Điều phối Giao hàng"."""
        sale_order_id = int(sale_order_id)
        queues = self.search([('sale_order_id', '=', sale_order_id)])
        return self._messages_to_log(queues)

    @api.model
    def auto_claim_and_print(self, limit=20):
        """RPC gọi từ dashboard backend (OWL, xem delivery_planner_iot_print_mixin.js): claim tối
        đa `limit` bản ghi đang 'pending', in từng bản ghi, trả về danh sách report action mà FE
        cần lần lượt doAction() để thực sự kích hoạt in qua IoT Box. Bản ghi lỗi đã tự chuyển
        state='error' ở đây, không có trong kết quả trả về (FE không cần doAction cho nó)."""
        pending_ids = self.search([('state', '=', 'pending')], order='id', limit=limit).ids
        claimed = self._claim_ids(pending_ids)
        results = []
        for rec in claimed:
            action = rec._do_print()
            if action:
                results.append({'queue_id': rec.id, 'sale_order_id': rec.sale_order_id.id,
                                 'warehouse_id': rec.warehouse_id.id, 'action': action})
            else:
                results.append({'queue_id': rec.id, 'sale_order_id': rec.sale_order_id.id,
                                 'warehouse_id': rec.warehouse_id.id, 'error': rec.error_message})
        return results
