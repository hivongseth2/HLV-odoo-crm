from odoo import api, fields, models
from odoo.exceptions import UserError

REPORT_NAME_SEARCH = 'Hoạt động lấy hàng TSN'


class HlvIotPrintQueue(models.Model):
    _name = 'hlv.iot.print.queue'
    _description = 'Hàng chờ in phiếu lấy hàng IoT (sale gửi từ /sale_plan, tự động in ở backend)'
    _order = 'create_date desc'
    _rec_name = 'sale_order_id'

    sale_order_id = fields.Many2one('sale.order', string='Đơn hàng', required=True,
                                     ondelete='cascade', index=True)
    warehouse_id = fields.Many2one('stock.warehouse', string='Kho', required=True, index=True)
    picking_ids = fields.Many2many('stock.picking', string='Phiếu lấy hàng')
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
    ], string='Trạng thái', default='pending', required=True, index=True)
    error_message = fields.Char(string='Lý do lỗi')
    requested_by_id = fields.Many2one('res.users', string='Sale yêu cầu',
                                       default=lambda self: self.env.user)
    requested_at = fields.Datetime(string='Thời gian yêu cầu', default=fields.Datetime.now)
    printed_by_id = fields.Many2one('res.users', string='Người/phiên đã in')
    printed_at = fields.Datetime(string='Thời gian in')

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
