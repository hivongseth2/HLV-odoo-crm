# -*- coding: utf-8 -*-
"""Thông số kỹ thuật trợ lý đã tra trên web, lưu theo mã để lần sau khỏi tìm lại.

Khoá theo mã đã chuẩn hoá chứ không theo sản phẩm Odoo: trợ lý hay tra cả mã chưa có trong
kho (máy hãng khác khách hỏi, mã MISA chưa đồng bộ). Chỉ thông số kỹ thuật, không lưu giá thị
trường — giá đổi nhanh, lưu lại là báo giá cũ.
"""
from odoo import api, fields, models

from ..services.search_ranking import normalize_code
from ..services.spec_memory import (
    MAX_SOURCE_CHARS, MAX_SPEC_CHARS, SPEC_FRESH_DAYS, clean_text, is_fresh, lookup_codes, spec_age_days,
)


# Khoá tên model ngắn hơn ngần này (vd 'GSB') dễ nằm trong tên hàng khác.
MIN_MODEL_KEY = 5


class HlvProductSpec(models.Model):
    _name = 'hlv.product.spec'
    _description = "Thông số đã tra trên web"
    _order = 'checked_at desc'
    _rec_name = 'code'

    code = fields.Char("Mã", required=True, index=True)
    code_key = fields.Char(compute='_compute_code_key', store=True, index=True)
    product_id = fields.Many2one(
        'product.product', string="Sản phẩm Odoo", compute='_compute_product_id', store=True,
        help="Sản phẩm có đúng mã này (bỏ khoảng trắng / gạch). Trống nếu Odoo chưa có mã.")
    specs = fields.Text("Thông số", required=True)
    sources = fields.Text("Nguồn")
    checked_at = fields.Datetime("Ngày tra", required=True, default=fields.Datetime.now)
    sale_name = fields.Char("Tra khi ai hỏi", readonly=True)

    _sql_constraints = [
        ('code_key_unique', 'unique(code_key)', "Mã này đã có thông số lưu — sửa dòng cũ."),
    ]

    @api.depends('code')
    def _compute_code_key(self):
        for record in self:
            record.code_key = normalize_code(record.code)

    @api.depends('code_key')
    def _compute_product_id(self):
        queries = self.env['hlv.product.agent.queries']
        for record in self:
            record.product_id = queries._products_with_code(record.code)[:1] if record.code_key else False

    def _canonical_code(self, code):
        """Mã dùng làm khoá: mã Odoo của đúng một hàng lẻ khớp `code`, không thì chính `code`.

        Claude lúc lưu theo tên model ("GWS 900-100 S"), lúc tra theo mã Odoo ("06013961K0"):
        không quy về một mã thì một máy thành hai dòng và lần hỏi sau vẫn đi tìm web.
        """
        product, _problem, _note = self.env['hlv.product.agent.queries']._resolve_product(code)
        return (product.default_code or code) if product else code

    def fresh_by_product(self, products):
        """{product_id: thông số} của các sản phẩm có thông số lưu còn hạn.

        Kèm vào danh sách ứng viên mã thay thế: trợ lý chỉ gọi xem_thong_so_da_luu cho mã gốc rồi
        đi tìm web lại cả những ứng viên đã lưu.
        """
        if not products:
            return {}
        now = fields.Datetime.now()
        return {rec.product_id.id: rec.specs for rec in self.sudo().search([('product_id', 'in', products.ids)])
                if is_fresh(rec.checked_at, now)}

    def _by_model_name(self, code):
        """Dòng lưu theo tên model nằm trong tên sản phẩm Odoo của `code` (vd 'GHG 20-63' cho 06012A62K0).

        Tên model khớp nhiều hàng (máy + bo mạch cùng tên) thì lúc lưu không quy được về mã Odoo.
        Chỉ dòng chưa nối sản phẩm (dòng đã nối là của đúng hàng khác, vd máy chứ không phải bo mạch);
        lấy khoá dài nhất cho chắc; khoá ngắn hơn MIN_MODEL_KEY dễ khớp nhầm.
        """
        product = self.env['hlv.product.agent.queries']._products_with_code(code)[:1]
        if not product:
            return self.browse()
        self.env.cr.execute("""
            SELECT id FROM hlv_product_spec
             WHERE product_id IS NULL AND length(code_key) >= %s AND position(code_key IN %s) > 0
             ORDER BY length(code_key) DESC LIMIT 1
        """, [MIN_MODEL_KEY, normalize_code(product.name)])
        row = self.env.cr.fetchone()
        return self.sudo().browse(row[0]) if row else self.browse()

    def lookup(self, codes):
        """Thông số đã lưu của các mã. Trả dict cho tool ``xem_thong_so_da_luu``."""
        wanted = lookup_codes(codes)
        if not wanted:
            return {'status': 'error', 'message': "Thiếu codes (danh sách mã cần xem)."}
        keys = {code: normalize_code(self._canonical_code(code)) for code in wanted}
        stored = {rec.code_key: rec for rec in self.sudo().search(
            [('code_key', 'in', list(set(keys.values()) | {normalize_code(code) for code in wanted}))])}
        now = fields.Datetime.now()
        rows = []
        for code in wanted:
            rec = stored.get(keys[code]) or stored.get(normalize_code(code))
            rec = rec or self._by_model_name(code)
            if not rec:
                rows.append({'code': code, 'co_luu': False})
                continue
            fresh = is_fresh(rec.checked_at, now)
            rows.append({
                'code': code, 'co_luu': True, 'con_dung': fresh,
                'ngay_tra': fields.Date.to_string(rec.checked_at), 'so_ngay': spec_age_days(rec.checked_at, now),
                'thong_so': rec.specs, 'nguon': rec.sources or '',
            })
        return {
            'status': 'found', 'ma': rows,
            'ghi_chu': "con_dung=true: dùng luôn, khỏi tìm web, ghi 'theo thông số đã tra ngày ...'. "
                       "Quá %s ngày (con_dung=false) hoặc chưa lưu: tìm web rồi gọi luu_thong_so." % SPEC_FRESH_DAYS,
        }

    def remember(self, code, specs, sources, sale_name=''):
        """Lưu / cập nhật thông số một mã. Trả dict cho tool ``luu_thong_so``."""
        code = clean_text(code, 64)
        specs = clean_text(specs, MAX_SPEC_CHARS)
        if not code or not specs:
            return {'status': 'error', 'message': "Cần code và thong_so (không lưu giá)."}
        values = {
            'specs': specs, 'sources': clean_text(sources, MAX_SOURCE_CHARS),
            'checked_at': fields.Datetime.now(), 'sale_name': sale_name or False,
        }
        code = self._canonical_code(code)
        Spec = self.sudo()
        existing = Spec.search([('code_key', '=', normalize_code(code))], limit=1)
        if existing:
            existing.write(values)
            return {'status': 'success', 'message': "Đã cập nhật thông số %s." % existing.code}
        Spec.create(dict(values, code=code))
        return {'status': 'success', 'message': "Đã lưu thông số %s." % code}
