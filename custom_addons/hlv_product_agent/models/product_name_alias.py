# -*- coding: utf-8 -*-
"""Tên gọi khác của loại hàng, tự học từ dữ liệu — không trông vào sale hay kho chỉ.

Hai nguồn: (1) cron gửi Claude danh sách TÊN LOẠI kho đang dùng (phần đầu tên 50k sản phẩm), nhờ
liệt kê cách sale hay gọi; (2) mỗi lượt trợ lý quét theo cách gọi A ra rỗng rồi quét cách khác ra
hàng thì ghi A = tên loại của hàng vừa ra. Tool quet_san_pham dùng bảng này để quét luôn tên kho.
"""
import logging

from odoo import api, fields, models

from ..services.claude_client import api_error_message, load_anthropic, make_client
from ..services.name_alias import (
    ALIAS_SYSTEM, alias_prompt, leading_type, learned_pairs, parse_alias_reply,
)
from ..services.query_format import squash_text
from .product_agent_api_runner import PARAM_API_KEY

_logger = logging.getLogger(__name__)

PARAM_ALIAS_MODEL = 'hlv_product_agent.alias_model'
DEFAULT_ALIAS_MODEL = 'claude-sonnet-5-5'
# Một lô tên loại mỗi lần gọi; mỗi lần chạy cron xử lý tối đa STUDY_LIMIT loại chưa đọc (lần đầu vài
# nghìn loại thì trải ra nhiều giờ, không chiếm worker lâu).
STUDY_BATCH = 120
STUDY_LIMIT = 600
STUDY_MAX_TOKENS = 8000
SOURCES = [('catalog', "Claude đọc danh mục"), ('learned', "Tự học khi tìm"), ('seed', "Khởi đầu"),
           ('manual', "Quản lý thêm")]


class HlvProductNameAlias(models.Model):
    _name = 'hlv.product.name.alias'
    _description = "Tên gọi khác của loại hàng"
    _order = 'type_name, alias'
    _rec_name = 'alias'

    type_name = fields.Char("Tên loại trong kho", required=True, help="Đúng như phần đầu tên sản phẩm, vd 'Chữ T PVC'.")
    alias = fields.Char("Cách gọi khác", required=True, help="Cách sale / khách gọi, vd 'tê nhựa'.")
    type_key = fields.Char(compute='_compute_keys', store=True, index=True)
    alias_key = fields.Char(compute='_compute_keys', store=True, index=True)
    source = fields.Selection(SOURCES, string="Nguồn", default='manual', required=True)

    _sql_constraints = [
        ('alias_type_unique', 'unique(alias_key, type_key)', "Cặp tên này đã có."),
    ]

    @api.depends('type_name', 'alias')
    def _compute_keys(self):
        for record in self:
            record.type_key = squash_text(record.type_name)
            record.alias_key = squash_text(record.alias)

    def expansions(self, terms):
        """{cách gọi đã chuẩn hoá: [tên loại kho đã chuẩn hoá]} cho các cụm bat_dau trợ lý quét."""
        keys = [term for term in terms if term]
        if not keys:
            return {}
        result = {}
        for record in self.sudo().search([('alias_key', 'in', keys)]):
            result.setdefault(record.alias_key, []).append(record.type_key)
        return result

    def remember(self, pairs, source):
        """Ghi các cặp (cách gọi, tên loại kho) chưa có. Trả số cặp mới."""
        Alias = self.sudo()
        added = 0
        for alias, type_name in pairs:
            alias_key, type_key = squash_text(alias), squash_text(type_name)
            if not alias_key or not type_key or alias_key == type_key:
                continue
            if Alias.search_count([('alias_key', '=', alias_key), ('type_key', '=', type_key)]):
                continue
            Alias.create({'alias': alias, 'type_name': type_name, 'source': source})
            added += 1
        return added

    def learn_from_scans(self, scans):
        """Ghi cặp học được từ các lần quet_san_pham của một lượt (xem name_alias.learned_pairs)."""
        added = self.remember(learned_pairs(scans), 'learned')
        if added:
            _logger.info("PRODUCT_AGENT tự học %s tên gọi khác", added)
        return added


class HlvProductNameType(models.Model):
    _name = 'hlv.product.name.type'
    _description = "Tên loại hàng trong kho (để Claude đọc tìm cách gọi khác)"
    _order = 'product_count desc'
    _rec_name = 'type_name'

    type_name = fields.Char("Tên loại", required=True)
    type_key = fields.Char(required=True, index=True)
    product_count = fields.Integer("Số mã")
    studied_at = fields.Datetime("Claude đã đọc lúc")

    _sql_constraints = [('type_key_unique', 'unique(type_key)', "Tên loại này đã có.")]

    def _refresh_from_catalog(self):
        """Cập nhật danh sách tên loại từ tên mọi sản phẩm đang bán; loại mới chưa có studied_at."""
        self.env.cr.execute("""
            SELECT COALESCE(pt.name->>'vi_VN', pt.name->>'en_US')
              FROM product_template pt WHERE pt.active AND pt.sale_ok
        """)
        counts, names = {}, {}
        for (name,) in self.env.cr.fetchall():
            kind = leading_type(name)
            key = squash_text(kind)
            if key:
                counts[key] = counts.get(key, 0) + 1
                names.setdefault(key, kind)
        Type = self.sudo()
        existing = {record.type_key: record for record in Type.search([])}
        for key, count in counts.items():
            if key in existing:
                if existing[key].product_count != count:
                    existing[key].product_count = count
            else:
                Type.create({'type_name': names[key], 'type_key': key, 'product_count': count})

    @api.model
    def _cron_study_catalog(self, limit=STUDY_LIMIT):
        """Gửi Claude các tên loại chưa đọc (nhiều mã trước), lưu cách gọi khác vào bảng alias."""
        get = self.env['ir.config_parameter'].sudo().get_param
        api_key = (get(PARAM_API_KEY) or '').strip()
        anthropic = load_anthropic()
        if not api_key or not anthropic:
            _logger.info("PRODUCT_AGENT đọc danh mục: chưa có API key / thư viện anthropic, bỏ qua")
            return 0
        self._refresh_from_catalog()
        todo = self.sudo().search([('studied_at', '=', False)], limit=limit)
        if not todo:
            return 0
        client = make_client(anthropic, api_key, timeout=300)
        model = get(PARAM_ALIAS_MODEL) or DEFAULT_ALIAS_MODEL
        Alias = self.env['hlv.product.name.alias']
        added = 0
        for start in range(0, len(todo), STUDY_BATCH):
            batch = todo[start:start + STUDY_BATCH]
            names = batch.mapped('type_name')
            try:
                response = client.messages.create(
                    model=model, max_tokens=STUDY_MAX_TOKENS, system=ALIAS_SYSTEM,
                    messages=[{'role': 'user', 'content': alias_prompt(names)}])
            except anthropic.APIError as error:
                _logger.warning("PRODUCT_AGENT đọc danh mục lỗi: %s", api_error_message(anthropic, error))
                break
            text = "".join(block.text for block in response.content if block.type == 'text')
            added += Alias.remember([(alias, kind) for kind, alias in parse_alias_reply(text, names)], 'catalog')
            batch.write({'studied_at': fields.Datetime.now()})
            # Lô đã đọc phải lưu ngay: lô sau lỗi thì lần chạy tới không gửi lại lô này.
            self.env.cr.commit()
            _logger.info("PRODUCT_AGENT đọc danh mục %s: %s loại, in=%s out=%s", model, len(names),
                         response.usage.input_tokens, response.usage.output_tokens)
        return added
