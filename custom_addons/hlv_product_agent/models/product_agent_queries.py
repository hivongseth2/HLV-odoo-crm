# -*- coding: utf-8 -*-
"""Tra cứu Odoo CHỈ ĐỌC cho trợ lý: tồn kho, dự báo, ai đang giữ, lịch sử xuất nhập, giá...

Không tự tính lại: gọi đúng hàm trang tra tồn (website_public_inventory_18) và các module
đang dùng, để số trợ lý báo khớp từng con số sale thấy trên trang. Đọc bằng sudo giống các
trang đó — mọi nhân viên nội bộ đều đã xem được những số này trên /search_stock.

Mọi handler trả dict có 'status' (found / not_found / error), như tool MISA.
"""
import logging
from datetime import date, timedelta

from odoo import fields, models
from odoo.addons.website_public_inventory_18.controllers.main import (
    PublicInventory, _get_active_holds, _get_so_reservation_map,
)

from ..services.query_format import clamp_int, fit_result
from ..services.search_ranking import normalize_code, rank_products, single_non_combo

_logger = logging.getLogger(__name__)

# Trường giá trên product.template (Studio / wordpress_sync) -> nhãn như trang tra tồn.
PRICE_FIELDS = [
    ('list_price', "Giá bán"),
    ('x_studio_ga_web', "Giá web"),
    ('x_studio_gia_san_tmdt', "Giá TMĐT"),
    ('x_studio_ga_hng_nim_yt', "Giá niêm yết"),
    ('x_studio_gi_bn_thng_mi', "Giá thương mại"),
    ('standard_price', "Giá vốn"),
]
PRODUCT_CANDIDATES = 10
# Tìm "chứa" lấy rộng rồi tự xếp: một model hay bán khớp hàng chục combo.
RESOLVE_SEARCH_LIMIT = 80
DEFAULT_HISTORY_DAYS = 90


class HlvProductAgentQueries(models.AbstractModel):
    _name = 'hlv.product.agent.queries'
    _description = "Tra cứu Odoo cho trợ lý (chỉ đọc)"

    def run(self, name, args):
        """Chạy một tool tra cứu. Trả dict luôn có 'status'."""
        handler = getattr(self, '_q_' + (name or ''), None)
        if not handler:
            return {'status': 'error', 'message': "Tool tra cứu %s chưa có." % name}
        if not isinstance(args, dict):
            return {'status': 'error', 'message': "Tham số phải là object JSON."}
        product, problem, note = self._resolve_product(args.get('code'), args.get('product_id'))
        if problem:
            return problem
        try:
            data = handler(product, args)
        except Exception as error:  # noqa: BLE001 — Claude phải nhận được lỗi, không làm chết lượt
            _logger.exception("PRODUCT_AGENT tra cứu %s lỗi", name)
            return {'status': 'error', 'message': "Tra cứu lỗi: %s" % error}
        result = dict({'status': 'found', 'product': self._product_label(product)}, **fit_result(data))
        if note:
            result['luu_y'] = note
        return result

    # =========================================================================
    # Tìm sản phẩm / kho từ chữ Claude đưa
    # =========================================================================
    def _resolve_product(self, code, product_id=None):
        """``(product, None, ghi chú)`` khi chọn được một sản phẩm; ``(None, dict lỗi / ứng viên, None)`` nếu không.

        Thứ tự: product_id (Claude chọn từ danh sách ứng viên) -> trùng MÃ khi bỏ khoảng trắng /
        dấu gạch -> tìm "chứa" trong mã + tên. Bước cuối lấy rộng rồi tự xếp: tìm "chứa" theo
        thứ tự mã thì combo "CB-..." đứng trước, máy lẻ đúng mã bị đẩy khỏi danh sách.
        Nhiều sản phẩm khớp mà chỉ MỘT hàng lẻ (không BOM kit): lấy hàng lẻ — sale không nói
        "combo" là hỏi hàng lẻ; các combo cùng mã nằm trong ghi chú để chọn lại nếu cần.
        """
        Product = self.env['product.product'].sudo()
        if product_id:
            product = Product.browse(clamp_int(product_id, 0, 0, 2 ** 31 - 1)).exists()
            if product:
                return product, None, None
        code = (code or '').strip()
        if not code:
            return None, {'status': 'error', 'message': "Thiếu code (mã hoặc tên hàng)."}, None
        same_code = self._products_with_code(code)
        if len(same_code) == 1:
            return same_code, None, None
        found = same_code | Product.search(
            ['|', ('default_code', 'ilike', code), ('name', 'ilike', code)], limit=RESOLVE_SEARCH_LIMIT)
        if len(found) == 1:
            return found, None, None
        if not found:
            return None, {'status': 'not_found', 'message': "Odoo không có sản phẩm khớp '%s'." % code}, None
        rows = rank_products(self._candidate_rows(found), code)
        single, combos = single_non_combo(rows, code)
        if single:
            note = None
            if combos:
                note = {
                    'message': "Đang tra HÀNG LẺ. Có %s combo chứa mã này; sale hỏi combo thì gọi lại với "
                               "product_id của combo." % len(combos),
                    'combo_cung_ma': [{key: row[key] for key in ('product_id', 'code', 'name')}
                                      for row in combos[:PRODUCT_CANDIDATES]],
                }
            return Product.browse(single['product_id']), None, note
        return None, {
            'status': 'ambiguous',
            'message': "Nhiều sản phẩm khớp '%s' (hàng lẻ đúng mã xếp đầu, combo xếp cuối) — gọi lại "
                       "với product_id của đúng sản phẩm." % code,
            'candidates': rows[:PRODUCT_CANDIDATES],
        }, None

    def _products_with_code(self, code):
        """Sản phẩm đang dùng có mã trùng `code` khi bỏ khoảng trắng / - _ . / và không phân biệt hoa thường.

        So bằng SQL trên cả bảng: mã nhập tay hay lệch khoảng trắng ("M18 FPD3-0X " / "M18FPD3-0X"),
        so =ilike thì trượt mất đúng sản phẩm cần tìm.
        """
        key = normalize_code(code)
        if not key:
            return self.env['product.product'].sudo()
        self.env.cr.execute("""
            SELECT id FROM product_product
             WHERE active AND regexp_replace(upper(coalesce(default_code, '')), '[[:space:]_./-]+', '', 'g') = %s
             LIMIT 5
        """, [key])
        return self.env['product.product'].sudo().browse([row[0] for row in self.env.cr.fetchall()])

    def _candidate_rows(self, products):
        """Dòng ứng viên cho Claude chọn: id, mã, tên, có phải combo (BOM kit) không."""
        combo_templates = set(self.env['mrp.bom'].sudo().search([
            ('product_tmpl_id', 'in', products.product_tmpl_id.ids), ('active', '=', True), ('type', '=', 'phantom'),
        ]).product_tmpl_id.ids)
        return [{
            'product_id': product.id, 'code': product.default_code or '', 'name': product.name,
            'is_combo': product.product_tmpl_id.id in combo_templates,
        } for product in products]

    @staticmethod
    def _product_label(product):
        return {'product_id': product.id, 'code': product.default_code or '', 'name': product.name}

    def _warehouse_id(self, text):
        """ID kho theo mã / tên; None khi để trống hoặc không khớp đúng một kho (= mọi kho)."""
        text = (text or '').strip()
        if not text:
            return None
        Warehouse = self.env['stock.warehouse'].sudo()
        found = Warehouse.search(['|', ('code', '=ilike', text), ('name', 'ilike', text)], limit=2)
        return found.id if len(found) == 1 else None

    @staticmethod
    def _inventory():
        # Controller của trang tra tồn: dùng các hàm _..._data nhận env, không cần request.
        return PublicInventory()

    # =========================================================================
    # Truy vấn nhẹ
    # =========================================================================
    def _q_xem_ton_kho(self, product, args):
        return self._inventory()._product_breakdown_data(
            self.env, product.id, self._warehouse_id(args.get('warehouse')))

    def _q_xem_gia(self, product, args):
        template = product.product_tmpl_id
        return {'gia': {label: template[field] for field, label in PRICE_FIELDS if field in template._fields}}

    def _q_xem_thanh_phan_combo(self, product, args):
        bom = self.env['mrp.bom'].sudo().search([
            ('product_tmpl_id', '=', product.product_tmpl_id.id), ('active', '=', True), ('type', '=', 'phantom'),
        ], limit=1)
        if not bom:
            return {'combo': False, 'message': "Mã này không phải combo (không có BOM kit)."}
        return {
            'combo': True,
            'rap_duoc_bo': self._inventory()._compute_combo_qty(self.env, product, None),
            'thanh_phan': [{
                'code': line.product_id.default_code or '', 'name': line.product_id.name,
                'so_luong_moi_bo': line.product_qty, 'ton_hien_co': line.product_id.qty_available,
            } for line in bom.bom_line_ids],
        }

    # =========================================================================
    # Truy vấn nặng (chế độ API giao model phụ đọc)
    # =========================================================================
    def _q_xem_du_bao(self, product, args):
        return self._inventory()._forecast_details_data(
            self.env, product.id, self._warehouse_id(args.get('warehouse')))

    def _q_xem_vi_tri(self, product, args):
        return self._inventory()._location_details_data(
            self.env, product.id, self._warehouse_id(args.get('warehouse')))

    def _q_xem_dang_giu(self, product, args):
        holds = _get_active_holds(self.env, [product.id])
        reservations = _get_so_reservation_map(self.env, [product.id])
        Warehouse = self.env['stock.warehouse'].sudo()
        return {
            'phieu_giu_hang': [{
                'sale': hold.sale_name, 'khach': hold.partner_id.display_name, 'kho': hold.warehouse_id.name,
                'so_luong': hold.quantity, 'giu_den': fields.Date.to_string(hold.hold_until_date),
                'du_an': hold.project_name, 'ghi_chu': hold.description,
            } for hold in holds],
            'don_ban_dang_giu': [{
                'kho': Warehouse.browse(warehouse_id).name, 'tong': total, 'chi_tiet': details,
            } for (_pid, warehouse_id), (total, details) in reservations.items()],
        }

    def _q_xem_lich_su_xuat_nhap(self, product, args):
        if 'stock.trace' not in self.env:
            return {'message': "Odoo chưa cài module truy vết xuất nhập (hlv_stock_trace)."}
        date_to = (args.get('date_to') or '').strip() or None
        date_from = (args.get('date_from') or '').strip() or fields.Date.to_string(
            date.today() - timedelta(days=DEFAULT_HISTORY_DAYS))
        return self.env['stock.trace'].sudo().get_company_overview(product.id, date_from, date_to)

    def _q_xem_lich_su_gia_ban(self, product, args):
        limit = clamp_int(args.get('limit'), 20, 1, 50)
        lines = self.env['sale.order.line'].sudo().search([
            ('product_id', '=', product.id), ('order_id.state', 'in', ('sale', 'done')),
        ], order='id desc', limit=limit)
        return {'dong_don_ban': [{
            'ngay': fields.Date.to_string(line.order_id.date_order),
            'don': line.order_id.name,
            'khach': line.order_id.partner_id.display_name,
            'sale': getattr(line.order_id, 'x_studio_misa_saler_code', '') or line.order_id.user_id.name,
            'so_luong': line.product_uom_qty,
            'don_gia': line.price_unit,
            'chiet_khau_pct': line.discount,
        } for line in lines]}

    def _q_xem_gia_nhap(self, product, args):
        try:
            from odoo.addons.hlv_vendor_quotation.services.price_lookup import product_prices
        except ImportError:
            return {'message': "Odoo chưa cài module hỏi giá NCC (hlv_vendor_quotation)."}
        prices = product_prices(self.env(su=True), product)
        return {'theo_ncc': prices.get('vendors'), 'lan_mua': prices.get('purchases'),
                'bao_gia': prices.get('quotes')}
