import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Bao lâu không nhận được heartbeat từ script watchdog trên máy chủ kho thì coi là máy đã
# tắt/mất mạng. Có thể override ở Settings > HLV Delivery Planner.
DEFAULT_WATCHDOG_MAX_SILENCE_MINUTES = 5
# Đang lỗi thì nhắc lại tối đa mỗi 30 phút (tránh spam mail mỗi lần cron chạy).
WATCHDOG_ALERT_REPEAT_MINUTES = 30


class StockWarehouse(models.Model):
    _inherit = 'stock.warehouse'

    # Máy in IoT Box gán riêng cho kho này — dùng để tự động in phiếu giao hàng
    # thẳng ra đúng máy in của kho khi sale bấm nút in trên trang /sale_plan,
    # không cần chọn máy in mỗi lần (xem services/delivery_planner_printing.py).
    x_iot_printer_device_id = fields.Many2one(
        'iot.device',
        string='Máy in IoT của kho',
        domain=[('type', '=', 'printer')],
        help='Máy in IoT Box được gán cho kho này. Khi in phiếu giao hàng cho đơn '
             'thuộc kho này, hệ thống sẽ tự chọn đúng máy in này thay vì phải chọn tay.',
    )
    x_iot_report_id = fields.Many2one(
        'ir.actions.report',
        string='Mẫu phiếu lấy hàng IoT của kho',
        domain=[('model', '=', 'stock.picking')],
        help='Report template dùng khi sale bấm in phiếu lấy hàng cho kho này qua IoT. '
             'Để trống thì dùng mẫu mặc định (tìm theo tên "Hoạt động lấy hàng TSN").',
    )
    x_iot_queue_limit = fields.Integer(
        string='Số đơn tối đa trong hàng chờ in',
        default=0,
        help='Số đơn TỐI ĐA đang xử lý (chưa hủy/chưa hoàn tất giao) mà kho này cho phép '
             'cùng lúc trong hàng chờ in IoT — sale sẽ không gửi được yêu cầu in mới nếu kho '
             'đã đủ số này. Để 0 = không giới hạn.',
    )

    # --- Watchdog: heartbeat do script chạy TRÊN MÁY CHỦ KHO gửi về (bin/iot_watchdog_windows.ps1) ---
    # Lý do cần: iot.device.connected có thể giữ True mãi khi hộp IoT chết đột ngột, còn
    # write_date của device KHÔNG phải heartbeat liên tục (xem models/iot_print_queue.py,
    # IOT_DEVICE_STALE_SECONDS) — nên Odoo KHÔNG có cách tự biết máy chủ kho còn sống hay không.
    # Script watchdog chạy định kỳ trên chính máy đó là nguồn tin cậy duy nhất.
    x_iot_watchdog_last_seen = fields.Datetime(
        string='Watchdog: lần cuối nhận tín hiệu',
        readonly=True, copy=False, index=True,
        help='Thời điểm cuối cùng script watchdog trên máy chủ kho gửi tín hiệu về Odoo. '
             'Trống = chưa từng cài watchdog cho kho này (không theo dõi).',
    )
    x_iot_watchdog_service_ok = fields.Boolean(
        string='Watchdog: service đang chạy',
        readonly=True, copy=False,
        help='Lần heartbeat gần nhất, service Odoo IoT (odoo-server-18.0) trên máy chủ kho có '
             'đang ở trạng thái Running hay không.',
    )
    x_iot_watchdog_note = fields.Char(
        string='Watchdog: ghi chú lần cuối',
        readonly=True, copy=False,
        help='Thông tin thêm do script watchdog gửi kèm (tên máy, trạng thái máy in, đã tự '
             'khởi động lại service hay chưa...).',
    )
    x_iot_watchdog_alert_sent_at = fields.Datetime(
        string='Watchdog: lần cuối gửi cảnh báo',
        readonly=True, copy=False,
        help='Dùng để không gửi lặp cảnh báo mỗi lần cron chạy (xem WATCHDOG_ALERT_REPEAT_MINUTES).',
    )

    # ------------------------------------------------------------------
    # Watchdog helpers
    # ------------------------------------------------------------------

    @api.model
    def _iot_watchdog_max_silence_minutes(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'hlv_sale_delivery_planning.iot_watchdog_max_silence_minutes'
        )
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 0
        return value if value > 0 else DEFAULT_WATCHDOG_MAX_SILENCE_MINUTES

    def _iot_watchdog_state(self, now=None, max_silence_minutes=None):
        """Tình trạng "in được hay không" của kho này, gộp 2 nguồn tin:
          - Odoo <-> hộp IoT: iot.device.connected (Odoo có nhận diện được hộp/máy in không).
          - Máy chủ kho <-> Odoo: heartbeat của script watchdog (máy còn sống + service Running).
        Trả về dict để dùng chung cho cả chip trạng thái trên UI lẫn cron gửi cảnh báo."""
        self.ensure_one()
        now = now or fields.Datetime.now()
        max_silence = max_silence_minutes or self._iot_watchdog_max_silence_minutes()
        device = self.x_iot_printer_device_id
        device_connected = bool(device and device.connected)

        # Chưa từng nhận heartbeat = chưa cài watchdog cho kho này → KHÔNG báo lỗi oan,
        # chỉ theo dõi khi đã từng có tín hiệu (cài rồi mới bắt đầu giám sát).
        watchdog_installed = bool(self.x_iot_watchdog_last_seen)
        silent_minutes = None
        if watchdog_installed:
            silent_minutes = (now - self.x_iot_watchdog_last_seen).total_seconds() / 60.0

        watchdog_silent = bool(watchdog_installed and silent_minutes > max_silence)
        watchdog_service_down = bool(
            watchdog_installed and not watchdog_silent and not self.x_iot_watchdog_service_ok
        )
        watchdog_ok = not (watchdog_silent or watchdog_service_down)

        problems = []
        if not device:
            problems.append('Kho chưa gán máy in IoT.')
        elif not device_connected:
            problems.append('Odoo không kết nối được máy in/hộp IoT "%s".' % (device.name or ''))
        if watchdog_silent:
            problems.append(
                'Máy chủ kho không phản hồi %d phút (watchdog im lặng từ %s) — máy có thể '
                'đã tắt hoặc mất mạng.' % (
                    int(silent_minutes), fields.Datetime.to_string(self.x_iot_watchdog_last_seen),
                )
            )
        elif watchdog_service_down:
            problems.append('Service Odoo IoT trên máy chủ kho đang KHÔNG chạy (Stopped).')

        return {
            'ok': not problems,
            'message': ' '.join(problems),
            'device_connected': device_connected,
            'watchdog_installed': watchdog_installed,
            'watchdog_ok': watchdog_ok,
            'watchdog_last_seen': self.x_iot_watchdog_last_seen,
            'watchdog_service_ok': self.x_iot_watchdog_service_ok,
            'watchdog_note': self.x_iot_watchdog_note or '',
        }

    def _iot_watchdog_alert_emails(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'hlv_sale_delivery_planning.iot_alert_emails'
        ) or ''
        return [e.strip() for e in raw.replace(';', ',').split(',') if e.strip()]

    def _iot_watchdog_send_alert(self, message, recovered=False):
        """Cảnh báo cho NGƯỜI DÙNG khi máy in/máy chủ kho có vấn đề (hoặc đã hoạt động lại).
        3 kênh, vì mỗi kênh bù khuyết điểm của kênh kia:
          - bus: dashboard "Điều phối Giao hàng" đang mở sẽ hiện toast NGAY (nhưng chỉ ai đang mở).
          - email: tới được người phụ trách kể cả khi KHÔNG ai mở dashboard (đây mới là kênh
            chính, vì đúng tình huống hỏng là "không ai để ý").
          - log server: để đối soát về sau.
        """
        self.ensure_one()
        subject = '[HLV] Máy in IoT kho %s: %s' % (
            self.name, 'ĐÃ HOẠT ĐỘNG LẠI' if recovered else 'CÓ SỰ CỐ',
        )
        body = message or ('Kho %s đã hoạt động lại bình thường.' % self.name)
        if recovered:
            _logger.info('IoT watchdog: kho %s đã hoạt động lại.', self.name)
        else:
            _logger.warning('IoT watchdog: kho %s có sự cố — %s', self.name, body)

        try:
            self.env['bus.bus']._sendone(
                'delivery_planner_channel', 'iot_watchdog_alert',
                {
                    'warehouse_id': self.id,
                    'warehouse_name': self.name,
                    'recovered': recovered,
                    'message': body,
                },
            )
        except Exception:
            _logger.debug('IoT watchdog: không gửi được bus notification', exc_info=True)

        emails = self._iot_watchdog_alert_emails()
        if emails:
            try:
                self.env['mail.mail'].sudo().create({
                    'subject': subject,
                    'body_html': '<p>%s</p><p>Kho: <b>%s</b></p>' % (body, self.name),
                    'email_to': ','.join(emails),
                    'auto_delete': True,
                }).send()
            except Exception:
                _logger.exception('IoT watchdog: không gửi được email cảnh báo cho %s', emails)

    @api.model
    def cron_check_iot_watchdog(self):
        """Cron: soát trạng thái máy in/máy chủ kho, gửi cảnh báo khi CHUYỂN sang lỗi và khi
        hồi phục. Chỉ soát kho đã gán máy in IoT (kho khác không có gì để canh)."""
        now = fields.Datetime.now()
        max_silence = self._iot_watchdog_max_silence_minutes()
        warehouses = self.sudo().search([('x_iot_printer_device_id', '!=', False)])
        for wh in warehouses:
            state = wh._iot_watchdog_state(now=now, max_silence_minutes=max_silence)
            if not state['ok']:
                last_alert = wh.x_iot_watchdog_alert_sent_at
                due = (
                    not last_alert
                    or (now - last_alert).total_seconds() / 60.0 >= WATCHDOG_ALERT_REPEAT_MINUTES
                )
                if due:
                    wh._iot_watchdog_send_alert(state['message'])
                    wh.x_iot_watchdog_alert_sent_at = now
            elif wh.x_iot_watchdog_alert_sent_at:
                wh._iot_watchdog_send_alert('', recovered=True)
                wh.x_iot_watchdog_alert_sent_at = False
        return True

    @api.model
    def iot_watchdog_heartbeat(self, warehouse_code, service_ok, note=''):
        """Ghi nhận 1 heartbeat từ script watchdog trên máy chủ kho. Gọi từ controller
        /api/iot_watchdog/heartbeat (xem controllers/iot_watchdog_controller.py)."""
        code = (warehouse_code or '').strip()
        if not code:
            return {'success': False, 'message': 'Thiếu warehouse_code'}
        warehouse = self.sudo().search([('code', '=ilike', code)], limit=1)
        if not warehouse:
            return {'success': False, 'message': 'Không tìm thấy kho có mã %r' % code}
        warehouse.write({
            'x_iot_watchdog_last_seen': fields.Datetime.now(),
            'x_iot_watchdog_service_ok': bool(service_ok),
            'x_iot_watchdog_note': (note or '')[:255],
        })
        return {
            'success': True,
            'warehouse_id': warehouse.id,
            'warehouse_name': warehouse.name,
            'service_ok': bool(service_ok),
        }
