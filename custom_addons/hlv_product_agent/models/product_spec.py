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

    def lookup(self, codes):
        """Thông số đã lưu của các mã. Trả dict cho tool ``xem_thong_so_da_luu``."""
        wanted = lookup_codes(codes)
        if not wanted:
            return {'status': 'error', 'message': "Thiếu codes (danh sách mã cần xem)."}
        stored = {rec.code_key: rec for rec in self.sudo().search(
            [('code_key', 'in', [normalize_code(code) for code in wanted])])}
        now = fields.Datetime.now()
        rows = []
        for code in wanted:
            rec = stored.get(normalize_code(code))
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
        Spec = self.sudo()
        existing = Spec.search([('code_key', '=', normalize_code(code))], limit=1)
        if existing:
            existing.write(values)
            return {'status': 'success', 'message': "Đã cập nhật thông số %s." % existing.code}
        Spec.create(dict(values, code=code))
        return {'status': 'success', 'message': "Đã lưu thông số %s." % code}
