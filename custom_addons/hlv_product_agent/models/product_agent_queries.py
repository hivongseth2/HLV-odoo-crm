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

from ..services.query_format import clamp_int, fit_result, name_tokens, similarity
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
# Tool tra theo mô tả tự do, không cần (và có thể không có) đúng một mã trong Odoo.
FREE_TEXT_QUERIES = frozenset({'tim_hang_tuong_tu', 'tim_ncc_dong_hang'})
# Hàng tương tự: lấy rộng theo từ khoá + cùng nhóm, rồi chấm điểm giống tên.
SIMILAR_KEYWORDS = 4
SIMILAR_CANDIDATES = 300
SIMILAR_MIN_SCORE = 0.3
SAME_CATEGORY_BONUS = 0.15
SIMILAR_RESULTS = 10
# NCC theo dòng hàng: đọc các dòng mua gần nhất cùng nhóm / có đủ từ khoá.
VENDOR_LINE_LIMIT = 500
# Mức khớp, mạnh nhất trước: NCC xếp theo mức khớp tốt nhất của các lần mua.
VENDOR_TIERS = ['tu_khoa_va_nhom', 'cung_nhom', 'tu_khoa']
# Đoán nhóm hàng từ từ khoá: nhóm phải chiếm ít nhất ngần này phần các món khớp.
VENDOR_CATEGORY_SAMPLE = 200
VENDOR_CATEGORY_SHARE = 0.4
VENDOR_SAMPLE_ITEMS = 3
VENDOR_RESULTS = 10


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
        if name in FREE_TEXT_QUERIES:
            # Hàng có thể chưa có trong Odoo: tra theo mô tả, không bắt phải ra đúng một mã.
            return self._run_free_text(name, handler, args)
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

    def _run_free_text(self, name, handler, args):
        try:
            data = handler(args)
        except Exception as error:  # noqa: BLE001 — Claude phải nhận được lỗi, không làm chết lượt
            _logger.exception("PRODUCT_AGENT tra cứu %s lỗi", name)
            return {'status': 'error', 'message': "Tra cứu lỗi: %s" % error}
        if data.get('status'):
            return data
        return dict({'status': 'found'}, **fit_result(data))

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

    # =========================================================================
    # Tư vấn khi hàng hết / không có: mã tương tự còn tồn, NCC hay bán dòng hàng
    # =========================================================================
    def _q_tim_hang_tuong_tu(self, args):
        """Mã còn tồn giống món sale hỏi nhất. Món gốc lấy theo mã (nếu Odoo có) hoặc theo mô tả."""
        base, _problem, _note = self._resolve_product(args.get('code'), args.get('product_id'))
        text = ' '.join(filter(None, [base.name if base else '', args.get('mo_ta') or '', args.get('code') or '']))
        base_tokens = name_tokens(text)
        if not base_tokens:
            return {'status': 'error', 'message': "Cần code hoặc mo_ta đủ chữ để tìm hàng tương tự."}
        Product = self.env['product.product'].sudo()
        domain = [('sale_ok', '=', True), ('id', '!=', base.id if base else 0)]
        # Mọi món có chung từ đặc trưng (ưu tiên từ có số: M18, 6204...) + cùng nhóm với món gốc.
        keywords = sorted(base_tokens, key=lambda word: (not any(ch.isdigit() for ch in word), -len(word)))
        keywords = keywords[:SIMILAR_KEYWORDS]
        name_domain = ['|'] * (len(keywords) - 1) + [('name', 'ilike', word) for word in keywords]
        candidates = Product.search(domain + name_domain, limit=SIMILAR_CANDIDATES)
        if base and base.categ_id:
            candidates |= Product.search(domain + [('categ_id', '=', base.categ_id.id)], limit=SIMILAR_CANDIDATES)
        rows = []
        for product in candidates:
            stock = product.qty_available
            if stock <= 0:
                continue
            score = similarity(base_tokens, name_tokens(product.name + ' ' + (product.default_code or '')))
            if base and product.categ_id == base.categ_id:
                score += SAME_CATEGORY_BONUS
            if score >= SIMILAR_MIN_SCORE:
                rows.append({'code': product.default_code or '', 'name': product.name, 'ton': stock,
                             'gia_ban': product.list_price, 'do_giong': round(score, 2)})
        rows.sort(key=lambda row: (-row['do_giong'], -row['ton']))
        return {
            'mon_goc': self._product_label(base) if base else {'mo_ta': args.get('mo_ta') or args.get('code')},
            'goi_y_con_ton': rows[:SIMILAR_RESULTS],
        }

    def _q_tim_ncc_dong_hang(self, args):
        """NCC đã bán cho mình dòng hàng này: khớp từ khoá + cùng nhóm hàng > cùng nhóm > chỉ từ khoá.

        Nhóm hàng lấy từ món tham chiếu (code / product_id), không có thì lấy nhóm chiếm đa số
        trong các sản phẩm khớp từ khoá. Từ khoá so KHÔNG DẤU bằng Python: tìm "chứa" của SQL
        phân biệt dấu, "phot viton" sẽ trượt "Phốt dầu VITON".
        """
        keyword_text = args.get('tu_khoa') or ''
        words = name_tokens(keyword_text)
        base = None
        if args.get('code') or args.get('product_id'):
            base, _problem, _note = self._resolve_product(args.get('code'), args.get('product_id'))
        category = base.categ_id if base else self._dominant_category(keyword_text, words)
        if not words and not category:
            return {'status': 'error', 'message': "Cần tu_khoa (hãng + dòng / loại hàng) hoặc code của một "
                                                  "món cùng dòng để biết nhóm hàng."}
        Line = self.env['purchase.order.line'].sudo()
        bought = [('order_id.state', 'in', ('purchase', 'done')), ('product_id', '!=', False)]
        lines = Line.browse()
        if category:
            lines |= Line.search(bought + [('product_id.categ_id', '=', category.id)],
                                 order='id desc', limit=VENDOR_LINE_LIMIT)
        if words:
            lines |= Line.search(bought + self._keyword_prefilter(keyword_text),
                                 order='id desc', limit=VENDOR_LINE_LIMIT)
        vendors = {}
        for line in lines.sorted('id', reverse=True):
            same_group = bool(category) and line.product_id.categ_id == category
            has_words = bool(words) and words <= self._line_tokens(line)
            if not (same_group or has_words):
                continue  # dòng lấy về nhờ lọc thô nhưng không đủ từ khoá khi so không dấu
            if has_words and same_group:
                tier = VENDOR_TIERS[0]
            else:
                tier = VENDOR_TIERS[1] if same_group else VENDOR_TIERS[2]
            partner = line.order_id.partner_id.commercial_partner_id
            entry = vendors.setdefault(partner.id, {
                'ncc': partner.display_name, 'khop': tier, 'so_lan_mua': 0, 'lan_mua_cuoi': '', 'mat_hang': [],
            })
            if VENDOR_TIERS.index(tier) < VENDOR_TIERS.index(entry['khop']):
                entry['khop'] = tier
            entry['so_lan_mua'] += 1
            if not entry['lan_mua_cuoi']:
                entry['lan_mua_cuoi'] = fields.Date.to_string(line.order_id.date_order)
            label = '%s — %s' % (line.product_id.default_code or '', line.product_id.name or line.name)
            if label not in entry['mat_hang'] and len(entry['mat_hang']) < VENDOR_SAMPLE_ITEMS:
                entry['mat_hang'].append(label)
        ranked = sorted(vendors.values(),
                        key=lambda entry: (VENDOR_TIERS.index(entry['khop']), -entry['so_lan_mua'], entry['ncc']))
        return {
            'tieu_chi': {
                'tu_khoa': keyword_text or None,
                'nhom_hang': category.complete_name if category else None,
                'nhom_lay_tu': ('mã ' + (base.default_code or base.name)) if base else (
                    'nhóm chiếm đa số trong các món khớp từ khoá' if category else None),
            },
            'ncc': ranked[:VENDOR_RESULTS],
        }

    def _dominant_category(self, keyword_text, words):
        """Nhóm hàng của đa số sản phẩm có đủ từ khoá (so không dấu). None nếu không rõ ràng."""
        if not words:
            return None
        products = self.env['product.product'].sudo().search(
            self._keyword_prefilter(keyword_text, field='name'), limit=VENDOR_CATEGORY_SAMPLE)
        counts = {}
        for product in products:
            if words <= name_tokens('%s %s' % (product.name, product.default_code or '')):
                counts[product.categ_id] = counts.get(product.categ_id, 0) + 1
        if not counts:
            return None
        category, count = max(counts.items(), key=lambda item: item[1])
        return category if category and count / sum(counts.values()) >= VENDOR_CATEGORY_SHARE else None

    @staticmethod
    def _keyword_prefilter(keyword_text, field='name'):
        """Lọc thô bằng SQL trước khi so không dấu: từ ASCII (hãng, model) so thẳng được; không
        có từ ASCII nào thì lọc theo từ đầu tiên đúng như gõ (có dấu)."""
        raw = [word for word in keyword_text.split() if len(word) >= 2]
        ascii_words = [word for word in raw if word.isascii()]
        return [(field, 'ilike', word) for word in (ascii_words or raw[:1])]

    @staticmethod
    def _line_tokens(line):
        return name_tokens('%s %s %s' % (line.product_id.name or '', line.product_id.default_code or '',
                                          line.name or ''))

    def _q_xem_gia_nhap(self, product, args):
        try:
            from odoo.addons.hlv_vendor_quotation.services.price_lookup import product_prices
        except ImportError:
            return {'message': "Odoo chưa cài module hỏi giá NCC (hlv_vendor_quotation)."}
        prices = product_prices(self.env(su=True), product)
        return {'theo_ncc': prices.get('vendors'), 'lan_mua': prices.get('purchases'),
                'bao_gia': prices.get('quotes')}
