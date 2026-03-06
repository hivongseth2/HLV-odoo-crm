from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging
import json

_logger = logging.getLogger(__name__)


class GoogleAdsGtmItem(models.Model):
    """Lưu dữ liệu Tag / Trigger / Variable kéo từ GTM về (chỉ đọc)"""
    _name = 'google.ads.gtm.item'
    _description = 'Thành Phần GTM (Tag / Trigger / Biến)'
    _order = 'item_type, name'
    _rec_name = 'name'

    tag_config_id = fields.Many2one(
        'google.ads.tag', string='Cấu Hình GTM',
        required=True, ondelete='cascade', index=True,
    )
    account_id = fields.Many2one(
        related='tag_config_id.account_id', store=True, string='Tài Khoản',
    )

    # ── Dữ liệu từ GTM ──────────────────────────
    gtm_item_id = fields.Char(string='GTM ID', index=True)
    name = fields.Char(string='Tên', required=True)
    item_type = fields.Selection([
        ('tag',      'Tag'),
        ('trigger',  'Trigger'),
        ('variable', 'Biến (Variable)'),
    ], string='Loại', required=True)

    # ── Chi tiết Tag ─────────────────────────────
    tag_subtype = fields.Selection([
        ('ua',               'Google Analytics (UA)'),
        ('ga4_config',       'GA4 — Cấu hình'),
        ('ga4_event',        'GA4 — Sự kiện'),
        ('awct',             'Google Ads — Chuyển Đổi'),
        ('aw_remarketing',   'Google Ads — Remarketing'),
        ('html',             'HTML Tùy Chỉnh'),
        ('floodlight',       'Floodlight'),
        ('other',            'Khác'),
    ], string='Loại Tag')

    # ── Chi tiết Trigger ─────────────────────────
    trigger_subtype = fields.Selection([
        ('pageview',         'Xem Trang'),
        ('click',            'Nhấp Chuột'),
        ('form_submit',      'Gửi Form'),
        ('timer',            'Bộ Đếm Thời Gian'),
        ('scroll_depth',     'Cuộn Trang'),
        ('custom_event',     'Sự Kiện Tùy Chỉnh'),
        ('history_change',   'Thay Đổi URL (SPA)'),
        ('dom_ready',        'DOM Sẵn Sàng'),
        ('window_loaded',    'Trang Tải Xong'),
        ('other',            'Khác'),
    ], string='Loại Trigger')

    # ── Dữ liệu Kéo Về (GA4 Data) ───────────
    ga4_event_count = fields.Integer(
        string='Số Lượt Kích Hoạt (30 Ngày)',
        help='Tổng số lần kích hoạt sự kiện này trên GA4 trong 30 ngày qua (chỉ dành cho Tag GA4 Event)',
        default=0,
    )

    # ── Trạng thái ───────────────────────────────
    is_paused = fields.Boolean(string='Tạm Dừng', default=False)
    firing_trigger_names = fields.Char(
        string='Trigger Kích Hoạt',
        help='Danh sách trigger kích hoạt tag này',
    )
    notes = fields.Text(string='Ghi Chú / Tham Số')

    last_synced = fields.Datetime(string='Đồng Bộ Lần Cuối', readonly=True)
