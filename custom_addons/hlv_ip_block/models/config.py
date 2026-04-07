from odoo import models, fields, api
import logging

_logger = logging.getLogger(__name__)


class IPBlockSettings(models.Model):
    _name = 'hlv.ip.block.settings'
    _description = 'Cấu hình chặn IP & chống bot'

    name = fields.Char(default='Cấu hình mặc định', readonly=True)

    # Rate limiting
    rate_limit_per_second = fields.Integer(
        string='Request tối đa / giây',
        default=5,
        help='Nếu 1 IP gửi quá X request/giây (tính trung bình trong cửa sổ), tự động chặn. '
             'Bot scan thường 10+/giây. User thật hiếm khi vượt 3-4/giây.',
    )
    rate_window = fields.Integer(
        string='Cửa sổ đo tốc độ (giây)',
        default=10,
        help='Đo rate limit trong khoảng thời gian này. '
             'Ngưỡng block = rate_limit_per_second × rate_window.',
    )

    # Suspicious path detection
    suspicious_threshold = fields.Integer(
        string='Số path đáng ngờ trước khi chặn',
        default=20,
        help='Bao nhiêu request đến path lạ (không phải Odoo) trong cửa sổ thời gian thì chặn. '
             'Bot scan thường hit 10-50 path lạ chỉ trong vài giây.',
    )
    suspect_window = fields.Integer(
        string='Cửa sổ phát hiện path lạ (giây)',
        default=30,
        help='Đếm số path lạ trong khoảng thời gian này.',
    )

    # Suspicious path patterns (comma-separated)
    suspicious_patterns = fields.Text(
        string='Pattern path đáng ngờ',
        default=(
            '.php,.asp,.aspx,.jsp,.cgi,.env,.git,.svn,.DS_Store,'
            '/etc/passwd,/etc/shadow,/proc/self,'
            '/wp-admin,/wp-content,/wp-includes,/wp-login,/wp-config,'
            '/xmlrpc.php,/administrator,/admin.php,'
            '../,..\\,%2e%2e,%252e,'
            '/phpmyadmin,/pma,/myadmin,/mysql,'
            '/shell,/cmd,/exec,/eval,'
            '/config.json,/package.json,/composer.json,'
            '/.well-known/security.txt,'
            '/debug/,/console,/server-status,'
            '/nacos/,/actuator,/druid,'
            '/vendor/,/node_modules/,'
            '/login.action,/struts,/solr,'
            '/tmp.,/temp.,/backup.,'
            '.sql,.sqlite,.bak,.old,.7z,.rar'
        ),
        help='Danh sách pattern (phân cách bằng dấu phẩy). '
             'Nếu path chứa bất kỳ pattern nào thì coi là đáng ngờ. '
             'VD: .php, /wp-admin, /etc/passwd, ../'
    )

    # Computed display
    effective_rate_limit = fields.Integer(
        string='Tổng request được phép / cửa sổ',
        compute='_compute_effective',
        help='= rate_limit_per_second × rate_window',
    )

    @api.depends('rate_limit_per_second', 'rate_window')
    def _compute_effective(self):
        for rec in self:
            rec.effective_rate_limit = rec.rate_limit_per_second * rec.rate_window

    @api.model
    def get_settings(self):
        """Return current settings as dict. Creates default if none exists."""
        settings = self.search([], limit=1)
        if not settings:
            settings = self.create({'name': 'Cấu hình mặc định'})
        return {
            'rate_limit_per_second': settings.rate_limit_per_second,
            'rate_window': settings.rate_window,
            'rate_limit': settings.rate_limit_per_second * settings.rate_window,
            'suspicious_threshold': settings.suspicious_threshold,
            'suspect_window': settings.suspect_window,
        }

    @api.constrains('rate_limit_per_second', 'rate_window', 'suspicious_threshold', 'suspect_window')
    def _check_values(self):
        for rec in self:
            if rec.rate_limit_per_second < 1:
                raise models.ValidationError('Request tối đa / giây phải >= 1')
            if rec.rate_window < 5:
                raise models.ValidationError('Cửa sổ đo tốc độ phải >= 5 giây')
            if rec.suspicious_threshold < 1:
                raise models.ValidationError('Số path lạ phải >= 1')
            if rec.suspect_window < 10:
                raise models.ValidationError('Cửa sổ phát hiện path lạ phải >= 10 giây')
