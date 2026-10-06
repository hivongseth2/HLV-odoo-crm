# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models
from odoo.osv import expression

from .wordpress_api import WooCommerceAPIError
from .wordpress_sync_utils import (
    STATE_CASE_MISMATCH,
    STATE_DUPLICATE,
    STATE_LINKED,
    STATE_NO_SKU,
    STATE_ORPHAN,
    catalogue_entry,
    match_entries,
    normalize_sku,
    should_track,
)

_logger = logging.getLogger(__name__)

# Webhook chỉ đụng 1-2 mã: tìm mã Odoo bằng ilike cho nhanh. Quá ngưỡng này (lượt quét
# cả web) thì đọc hết mã Odoo một lần còn rẻ hơn dựng domain hàng nghìn OR.
ILIKE_LOOKUP_LIMIT = 20


class WordPressProductLink(models.Model):
    """
    Bản sao danh mục sản phẩm của từng web, kèm sản phẩm Odoo khớp mã.

    Mỗi dòng là một sản phẩm (hoặc biến thể) đang có trên một web. Sản phẩm Odoo không có
    dòng nào ở web X nghĩa là web X không bán sản phẩm đó.
    """
    _name = 'wordpress.product.link'
    _description = 'Sản phẩm trên web WordPress'
    _order = 'config_id, state, wc_sku'
    _rec_name = 'wc_name'

    config_id = fields.Many2one(
        'wordpress.config', string='Web', required=True, ondelete='cascade', index=True
    )
    product_id = fields.Many2one(
        'product.template', string='Sản phẩm Odoo', ondelete='set null', index=True, readonly=True
    )
    product_code = fields.Char(related='product_id.default_code', string='Mã Odoo')
    state = fields.Selection([
        (STATE_LINKED, 'Đã khớp'),
        (STATE_CASE_MISMATCH, 'Lệch hoa/thường, khoảng trắng'),
        (STATE_DUPLICATE, 'Trùng mã'),
        (STATE_ORPHAN, 'Odoo không có mã này'),
        (STATE_NO_SKU, 'Web chưa nhập mã'),
    ], string='Khớp mã', required=True, default=STATE_ORPHAN, index=True, readonly=True)

    wc_product_id = fields.Integer(string='ID trên web', required=True, readonly=True)
    wc_parent_id = fields.Integer(
        string='ID sản phẩm cha', readonly=True, help='Khác 0 nghĩa là biến thể của sản phẩm cha này'
    )
    wc_type = fields.Char(string='Loại', readonly=True)
    wc_sku = fields.Char(string='Mã trên web', readonly=True)
    wc_name = fields.Char(string='Tên trên web', readonly=True)
    wc_url = fields.Char(string='Link', readonly=True)
    wc_status = fields.Char(string='Trạng thái web', readonly=True, help='publish, draft, private, pending')
    last_seen = fields.Datetime(string='Thấy trên web lần cuối', readonly=True)

    _sql_constraints = [
        ('config_wc_product_unique', 'unique(config_id, wc_product_id)',
         'Mỗi sản phẩm web chỉ có một dòng liên kết.'),
    ]

    # ===========================================
    # QUÉT CẢ WEB
    # ===========================================
    @api.model
    def _cron_scan_all(self):
        """Quét lại mọi web đang hoạt động; web lỗi thì ghi log và quét web tiếp theo."""
        for config in self.env['wordpress.config'].search([('active', '=', True)]):
            wc_key, wc_secret = config.get_credentials()
            if not wc_key or not wc_secret:
                continue
            try:
                self._scan_config(config)
            except WooCommerceAPIError as e:
                _logger.error(f"Quét liên kết {config.name} thất bại, giữ nguyên bảng cũ: {e}")

    @api.model
    def _scan_config(self, config):
        """
        Đồng bộ bảng liên kết của một web với danh mục thật trên web đó.

        Kéo hết danh mục trước rồi mới ghi: fetch lỗi giữa chừng thì không xoá nhầm dòng nào.
        """
        entries = config._api_client().fetch_catalogue()
        seen_ids = {entry['wc_product_id'] for entry in entries}

        self._upsert_entries(config, entries)
        self.search([
            ('config_id', '=', config.id),
            ('wc_product_id', 'not in', list(seen_ids)),
        ]).unlink()
        self._rematch(config)
        config.link_scan_date = fields.Datetime.now()
        _logger.info(f"Quét liên kết {config.name}: {len(entries)} sản phẩm web")

    # ===========================================
    # CẬP NHẬT TỪNG SẢN PHẨM (webhook, sync tìm theo SKU)
    # ===========================================
    @api.model
    def _apply_webhook(self, config, topic, payload):
        """
        Áp một sự kiện webhook sản phẩm của WooCommerce vào bảng liên kết.

        Args:
            topic: header X-WC-Webhook-Topic, vd 'product.updated'
            payload: JSON body — sản phẩm đầy đủ, riêng product.deleted chỉ có 'id'
        """
        resource, _dot, event = (topic or '').partition('.')
        wc_id = int(payload.get('id') or 0)
        if resource != 'product' or not wc_id:
            return

        # Phạm vi một sự kiện: chính sản phẩm đó và các biến thể của nó.
        scope = self.search([
            ('config_id', '=', config.id),
            '|', ('wc_product_id', '=', wc_id), ('wc_parent_id', '=', wc_id),
        ])
        old_skus = {normalize_sku(sku) for sku in scope.mapped('wc_sku')}

        if event == 'deleted' or payload.get('status') == 'trash':
            entries = []
        else:
            entries = self._entries_from_payload(config, payload)

        keep_ids = {entry['wc_product_id'] for entry in entries}
        scope.filtered(lambda link: link.wc_product_id not in keep_ids).unlink()
        self._upsert_entries(config, entries)
        self._rematch(config, old_skus | {normalize_sku(entry['wc_sku']) for entry in entries})

    @api.model
    def _record_web_products(self, config, raws):
        """
        Ghi các sản phẩm web vừa đọc được qua API rồi khớp mã lại.

        Returns:
            recordset các dòng tương ứng raws.
        """
        entries = [entry for entry in map(catalogue_entry, raws) if should_track(entry)]
        links = self._upsert_entries(config, entries)
        self._rematch(config, {normalize_sku(entry['wc_sku']) for entry in entries})
        return links

    @api.model
    def _entries_from_payload(self, config, payload):
        """
        Dòng cần có cho một sản phẩm trong payload webhook.

        Sản phẩm variable: payload chỉ có danh sách ID biến thể, không có SKU, nên hỏi lại
        API lấy biến thể — sửa biến thể trong trang quản trị luôn bắn update của cha.
        """
        entry = catalogue_entry(payload)
        entries = [entry] if should_track(entry) else []
        if entry['wc_type'] == 'variable':
            entries.extend(config._api_client().fetch_variations(entry['wc_product_id'], entry['wc_name']))
        return entries

    # ===========================================
    # GHI & KHỚP MÃ
    # ===========================================
    @api.model
    def _upsert_entries(self, config, entries):
        """
        Ghi đè các field wc_* theo wc_product_id, tạo dòng mới nếu chưa có.

        Returns:
            recordset các dòng ứng với entries.
        """
        if not entries:
            return self.browse()

        now = fields.Datetime.now()
        existing = {
            link.wc_product_id: link
            for link in self.search([
                ('config_id', '=', config.id),
                ('wc_product_id', 'in', [entry['wc_product_id'] for entry in entries]),
            ])
        }
        unchanged = self.browse()
        changed = self.browse()
        to_create = []
        for entry in entries:
            link = existing.get(entry['wc_product_id'])
            if not link:
                to_create.append(dict(entry, config_id=config.id, last_seen=now))
            # So qua `or False`: Odoo đọc Char rỗng về False, còn entry giữ ''.
            elif any((link[field] or False) != (value or False) for field, value in entry.items()):
                link.write(dict(entry, last_seen=now))
                changed |= link
            else:
                unchanged |= link

        # Phần lớn dòng không đổi giữa hai lượt quét: gộp một lệnh ghi last_seen.
        unchanged.write({'last_seen': now})
        return unchanged | changed | self.create(to_create)

    @api.model
    def _rematch(self, config, skus=None):
        """
        Gán lại sản phẩm Odoo và trạng thái khớp mã cho các dòng của một web.

        Args:
            skus: tập SKU đã chuẩn hoá cần xét lại; None = cả web. Luôn xét trọn nhóm cùng
                  SKU chuẩn hoá, thiếu một dòng là không phát hiện được trùng mã.
        """
        links = self.search([('config_id', '=', config.id)])
        if skus is not None:
            links = links.filtered(lambda link: normalize_sku(link.wc_sku) in skus)

        entries = [{'wc_product_id': link.wc_product_id, 'wc_sku': link.wc_sku} for link in links]
        wanted = {normalize_sku(entry['wc_sku']) for entry in entries} - {''}
        matches = match_entries(entries, self._odoo_codes(wanted))

        for link in links:
            product_id, state = matches[link.wc_product_id]
            if link.product_id.id != product_id or link.state != state:
                link.write({'product_id': product_id, 'state': state})

    @api.model
    def _odoo_codes(self, wanted):
        """
        Mã Odoo có thể khớp với các SKU chuẩn hoá trong wanted.

        Chỉ xét product.template đang hoạt động — đồng bộ giá cũng chạy trên template.

        Returns:
            list (product_id, default_code); có thể thừa, match_entries tự lọc.
        """
        if not wanted:
            return []

        Product = self.env['product.template']
        if len(wanted) <= ILIKE_LOOKUP_LIMIT:
            domain = expression.OR([[('default_code', 'ilike', sku)] for sku in wanted])
        else:
            domain = [('default_code', '!=', False)]
        return [
            (row['id'], row['default_code'])
            for row in Product.search_read(domain, ['default_code'])
            if normalize_sku(row['default_code']) in wanted
        ]
