import json
import logging
from datetime import timedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Số phút chờ trước khi dám kết luận 1 lệnh in "chưa ra giấy" — phải lớn hơn chu kỳ heartbeat
# của script watchdog (mặc định 2 phút) để lệnh in có đủ thời gian chạy xong và được đếm.
DEFAULT_VERIFY_GRACE_MINUTES = 5
# Số điểm đo counter máy in giữ lại cho mỗi kho (2 phút/điểm => ~2 giờ) để đối chiếu ngược.
PRINTED_COUNTER_LOG_MAX = 60

# Bao lâu không nhận được heartbeat từ script watchdog trên máy chủ kho thì coi là máy đã
# tắt/mất mạng. Có thể override ở Settings > HLV Delivery Planner.
DEFAULT_WATCHDOG_MAX_SILENCE_MINUTES = 5
# Đang lỗi thì nhắc lại tối đa mỗi 30 phút (tránh spam mail mỗi lần cron chạy).
WATCHDOG_ALERT_REPEAT_MINUTES = 30

# Yêu cầu in nằm ở 'pending' quá số phút này = gần như chắc chắn KHÔNG có phiên "Điều phối
# Giao hàng" nào đang mở để đẩy lệnh in xuống hộp IoT. Việc dispatch BẮT BUỘC do JS của trình
# duyệt làm (server Odoo.sh không nói chuyện được với máy in trong LAN kho), nên đóng tab là
# hàng chờ nằm im vô thời hạn — không mất dữ liệu, nhưng phải BÁO chứ không được im lặng.
DEFAULT_PENDING_STALE_MINUTES = 10
# Đường dẫn tới dashboard điều phối — gửi kèm cảnh báo để người ở kho bấm mở là dispatch ngay.
DISPATCHER_ACTION_PATH = '/odoo/action-hlv_sale_delivery_planning.action_delivery_planner_dashboard'


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
    x_iot_printed_counter_log = fields.Text(
        string='Watchdog: lịch sử số job máy in đã in',
        readonly=True, copy=False,
        help='JSON danh sách [thời điểm, tổng số job Windows đã in] do script watchdog báo về. '
             'Dùng để ĐỐI CHIẾU: Odoo đã gửi bao nhiêu lệnh in vs máy in thật sự in bao nhiêu, '
             'từ đó phát hiện phiếu "đã gửi lệnh in" mà không ra giấy.',
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

    @api.model
    def _iot_pending_stale_minutes(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'hlv_sale_delivery_planning.iot_pending_stale_minutes'
        )
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 0
        return value if value > 0 else DEFAULT_PENDING_STALE_MINUTES

    @api.model
    def _iot_dispatcher_url(self):
        base = (self.env['ir.config_parameter'].sudo().get_param('web.base.url') or '').rstrip('/')
        return (base + DISPATCHER_ACTION_PATH) if base else ''

    def _iot_pending_stuck(self, now=None, stale_minutes=None):
        """Các yêu cầu in 'pending' quá lâu = ĐÃ GỬI nhưng chưa ai đẩy xuống máy in.

        Nguyên nhân gần như luôn là không có tab "Điều phối Giao hàng" nào đang mở. Chỉ tính
        các yêu cầu kho CHƯA quyết định gì (warehouse_action='none') — phiếu kho đã chọn "xử lý
        sau"/"từ chối" thì nằm chờ là đúng ý người dùng, không phải sự cố."""
        self.ensure_one()
        now = now or fields.Datetime.now()
        minutes = stale_minutes or self._iot_pending_stale_minutes()
        return self.env['hlv.iot.print.queue'].sudo().search([
            ('warehouse_id', '=', self.id),
            ('state', '=', 'pending'),
            ('warehouse_action', '=', 'none'),
            ('requested_at', '<=', now - timedelta(minutes=minutes)),
        ], order='requested_at asc')

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

        # Máy in + máy chủ kho có thể OK hết mà phiếu vẫn không ra giấy, vì thiếu người
        # DISPATCH (không tab điều phối nào mở). Đây là sự cố riêng, phải soi riêng.
        pending_stuck = self._iot_pending_stuck(now=now)
        pending_stuck_count = len(pending_stuck)
        pending_oldest_minutes = 0
        if pending_stuck:
            pending_oldest_minutes = int(
                (now - pending_stuck[0].requested_at).total_seconds() / 60.0
            )

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
        if pending_stuck:
            problems.append(
                '%d yêu cầu in đang chờ chưa được gửi xuống máy in (cũ nhất %d phút) — CẦN MỞ '
                'trang "Điều phối Giao hàng" trên máy ở kho: lệnh in được đẩy từ trình duyệt, '
                'server không tự gửi xuống máy in được.'
                % (pending_stuck_count, pending_oldest_minutes)
            )

        return {
            'ok': not problems,
            'message': ' '.join(problems),
            'device_connected': device_connected,
            'pending_stuck': pending_stuck_count,
            'pending_oldest_minutes': pending_oldest_minutes,
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

    # ------------------------------------------------------------------
    # Đối chiếu "Odoo đã gửi lệnh in" vs "máy in Windows thật sự đã in"
    # ------------------------------------------------------------------

    @api.model
    def _iot_verify_grace_minutes(self):
        raw = self.env['ir.config_parameter'].sudo().get_param(
            'hlv_sale_delivery_planning.iot_verify_grace_minutes'
        )
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = 0
        return value if value > 0 else DEFAULT_VERIFY_GRACE_MINUTES

    def _iot_read_counter_log(self):
        self.ensure_one()
        try:
            data = json.loads(self.x_iot_printed_counter_log or '[]')
        except (TypeError, ValueError):
            return []
        out = []
        for row in data:
            try:
                out.append((fields.Datetime.to_datetime(row[0]), int(row[1])))
            except Exception:
                continue
        return out

    def _iot_append_counter_log(self, value, now=None):
        """Ghi 1 điểm đo (thời điểm, tổng số job đã in) vào lịch sử. Trả về True nếu phát hiện
        counter TỤT (Spooler/máy vừa khởi động lại — counter của Windows đếm từ lúc Spooler
        chạy, nên tụt là dấu hiệu hàng đợi in đã bị xoá sạch giữa đường)."""
        self.ensure_one()
        now = now or fields.Datetime.now()
        log = self._iot_read_counter_log()
        was_reset = bool(log) and value < log[-1][1]
        if was_reset:
            # Counter tụt => mọi điểm đo cũ không còn so sánh được, bỏ hết, bắt đầu lại.
            log = []
        log.append((now, int(value)))
        log = log[-PRINTED_COUNTER_LOG_MAX:]
        self.x_iot_printed_counter_log = json.dumps(
            [[fields.Datetime.to_string(ts), val] for ts, val in log]
        )
        return was_reset

    def _iot_counter_value_at_or_before(self, moment):
        """Giá trị counter tại điểm đo gần nhất KHÔNG SAU `moment`. None nếu chưa có điểm nào
        (chưa đối chiếu được vì không biết mốc bắt đầu)."""
        self.ensure_one()
        value = None
        for ts, val in self._iot_read_counter_log():
            if ts <= moment:
                value = val
            else:
                break
        return value

    def _iot_reconcile_printed_jobs(self, counter_reset=False, now=None):
        """ĐỐI CHIẾU 2 HÀNG ĐỢI cho kho này, gọi mỗi lần nhận heartbeat có số job đã in.

        Nguyên tắc (cố ý làm "rộng tay" để hạn chế báo oan):
          - Lấy các yêu cầu đã dispatch (state='printed') CHƯA đối chiếu và đã quá thời gian
            chờ (grace) — gọi là C1..Cn theo thứ tự gửi.
          - printed_since = counter mới nhất − counter tại thời điểm ngay trước C1 được gửi.
            Khoảng này RỘNG NHẤT có thể (tính cả job in tay của thủ kho) nên nếu vẫn thiếu thì
            gần như chắc chắn là thiếu thật.
          - printed_since >= n  => coi như đủ, đánh dấu tất cả 'printed_ok'.
          - Thiếu k = n − printed_since => hàng đợi in là FIFO, nên k phiếu GỬI SAU CÙNG là
            những phiếu chưa ra giấy => đánh dấu 'suspect'; các phiếu trước đó 'printed_ok'.
          - counter_reset (Spooler vừa restart) => KHÔNG kết luận được job nào đã in xong trước
            khi bị xoá, mà không ra giấy thì thiệt hại lớn hơn in trùng => đánh 'suspect' hết
            cho người xử lý quyết định.

        Trả về recordset các yêu cầu bị đánh 'suspect' (để caller cảnh báo/gửi lại)."""
        self.ensure_one()
        now = now or fields.Datetime.now()
        cutoff = now - timedelta(minutes=self._iot_verify_grace_minutes())
        Queue = self.env['hlv.iot.print.queue'].sudo()
        candidates = Queue.search([
            ('warehouse_id', '=', self.id),
            ('state', '=', 'printed'),
            ('verify_state', '=', 'waiting'),
            ('printed_at', '!=', False),
            ('printed_at', '<=', cutoff),
        ], order='printed_at asc, id asc')
        if not candidates:
            return Queue.browse()

        if counter_reset:
            candidates.write({
                'verify_state': 'suspect',
                'verify_note': 'Hàng đợi in của Windows bị xoá/khởi động lại giữa đường — '
                               'không xác nhận được đã ra giấy hay chưa.',
                'verified_at': now,
            })
            return candidates

        log = self._iot_read_counter_log()
        base = self._iot_counter_value_at_or_before(candidates[0].printed_at)
        if base is None or not log:
            # Chưa có điểm đo nào trước lúc gửi (VD mới bật watchdog) => không đủ dữ liệu để
            # kết luận. Đánh 'no_data' để KHÔNG treo mãi ở 'Chờ đối chiếu' và cũng không vu oan.
            candidates.write({
                'verify_state': 'no_data',
                'verify_note': 'Chưa có số liệu máy in tại thời điểm gửi lệnh in để đối chiếu.',
                'verified_at': now,
            })
            return Queue.browse()

        printed_since = max(log[-1][1] - base, 0)
        ok_count = min(printed_since, len(candidates))
        if ok_count:
            candidates[:ok_count].write({
                'verify_state': 'printed_ok',
                'verify_note': 'Máy in đã in đủ số lệnh trong khoảng thời gian này.',
                'verified_at': now,
            })
        suspects = candidates[ok_count:]
        if suspects:
            suspects.write({
                'verify_state': 'suspect',
                'verify_note': 'Odoo đã gửi %d lệnh in nhưng máy in chỉ in %d — phiếu này CHƯA '
                               'RA GIẤY, cần gửi in lại.' % (len(candidates), printed_since),
                'verified_at': now,
            })
        return suspects

    def _iot_handle_unprinted(self, suspects):
        """Phát hiện phiếu đã gửi mà chưa ra giấy thì KHÔNG được im lặng: ghi chatter từng bản
        ghi, cảnh báo (bus + email), và nếu admin bật thì tự gửi lại lệnh in luôn."""
        self.ensure_one()
        if not suspects:
            return
        auto_requeue = self.env['ir.config_parameter'].sudo().get_param(
            'hlv_sale_delivery_planning.iot_auto_requeue_unprinted'
        ) in ('1', 'True', 'true')
        orders = ', '.join(suspects.mapped('sale_order_id.name'))
        for rec in suspects:
            rec.message_post(body=(
                '⚠️ Đối chiếu với máy in kho: lệnh in đã gửi nhưng máy in KHÔNG in ra giấy. %s'
                % ('Hệ thống đang tự gửi lại lệnh in.' if auto_requeue else
                   'Kho cần bấm "Gửi lại lệnh in" để in lại.')
            ))
        message = (
            'Có %d yêu cầu in đã gửi cho kho %s nhưng máy in KHÔNG in ra giấy (đơn: %s). %s'
            % (
                len(suspects), self.name, orders,
                'Hệ thống đã tự gửi lại lệnh in.' if auto_requeue
                else 'Vào "Hàng chờ in (IoT)" bấm "Gửi lại lệnh in" cho những đơn này.',
            )
        )
        self._iot_watchdog_send_alert(message)
        if auto_requeue:
            suspects.action_requeue()
            try:
                self.env['bus.bus']._sendone(
                    'delivery_planner_channel', 'iot_print_queue_changed',
                    {'warehouse_ids': [self.id], 'sale_order_id': False},
                )
            except Exception:
                _logger.debug('Không gửi được bus sau khi tự gửi lại lệnh in', exc_info=True)

    @api.model
    def iot_watchdog_heartbeat(self, warehouse_code, service_ok, note='', printed_total=None):
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

        # Đối chiếu 2 hàng đợi ngay khi có số liệu mới từ máy kho (không cần thêm cron):
        # Odoo đã gửi bao nhiêu lệnh in vs máy in Windows thật sự in bao nhiêu.
        suspects_count = 0
        if printed_total is not None:
            try:
                counter_reset = warehouse._iot_append_counter_log(int(printed_total))
                suspects = warehouse._iot_reconcile_printed_jobs(counter_reset=counter_reset)
                suspects_count = len(suspects)
                warehouse._iot_handle_unprinted(suspects)
            except Exception:
                # Đối chiếu lỗi thì KHÔNG được làm hỏng heartbeat (mất heartbeat sẽ bị báo
                # "máy kho mất kết nối" oan) — chỉ ghi log rồi bỏ qua vòng này.
                _logger.exception('Đối chiếu hàng đợi in thất bại cho kho %s', warehouse.name)

        # Hàng chờ nằm im vì KHÔNG có tab điều phối nào mở: máy ở kho là nơi duy nhất có người
        # ngồi và mở được tab đó, nên trả về đây để watchdog báo NGAY tại máy đó.
        pending_stuck = warehouse._iot_pending_stuck()
        pending_stuck_message = ''
        if pending_stuck:
            pending_stuck_message = (
                '%d yeu cau in dang cho chua duoc gui xuong may in (cu nhat %d phut). '
                'MO trang "Dieu phoi Giao hang" tren may nay de in.'
                % (
                    len(pending_stuck),
                    int((fields.Datetime.now() - pending_stuck[0].requested_at).total_seconds() / 60.0),
                )
            )

        return {
            'success': True,
            'warehouse_id': warehouse.id,
            'warehouse_name': warehouse.name,
            'service_ok': bool(service_ok),
            'unprinted_found': suspects_count,
            'pending_stuck': len(pending_stuck),
            'pending_stuck_message': pending_stuck_message,
            'dispatcher_url': self._iot_dispatcher_url(),
        }
