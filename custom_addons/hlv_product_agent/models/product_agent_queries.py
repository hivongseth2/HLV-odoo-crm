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
    PublicInventory, _get_active_holds, _get_so_reservation_map, _rg_sum,
)

from ..services.price_summary import compact_prices
from ..services.product_scan import MAX_SCAN_RESULTS, has_scan_filter, scan_criteria, scan_match
from ..services.query_format import (
    TIER_NAME_TYPE, clamp_int, fit_result, has_all_words, keyword_rank, name_tokens, usable_keywords,
)
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
# Nhóm quyền của trang hỏi / tra giá NCC: trợ lý chỉ đưa giá mua cho đúng người trang đó cho xem.
PRICE_PAGE_GROUP = 'hlv_vendor_quotation.group_vendor_quote_user'
PRICE_PAGE_LINK = '/hoi-gia-ncc/tra-gia?p=%s'
# Dòng giữ chỗ của phiếu không phải đơn bán: đủ cho một mã, chặn trường hợp lỗi dữ liệu dồn hàng nghìn dòng.
OTHER_RESERVATION_LIMIT = 200
# Tool tra theo mô tả tự do, không cần (và có thể không có) đúng một mã trong Odoo.
FREE_TEXT_QUERIES = frozenset({'tim_hang_tuong_tu', 'tim_ncc_dong_hang', 'quet_san_pham'})
# Hàng thay thế: số ứng viên còn tồn đưa Claude xét (nhiều hơn thì Claude lọc thêm từ khoá).
SUBSTITUTE_CANDIDATES = 40
SUBSTITUTE_DESCRIPTION_CHARS = 300
MAX_KEYWORD_VARIANTS = 6
# "Hay bán" = số lượng đã bán trong khoảng này: đủ dài để mã bán đều không lép vế mã vừa có một đơn lớn.
SOLD_WINDOW_DAYS = 180
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
        label = {'product_id': product.id, 'code': product.default_code or '', 'name': product.name}
        if product.image_128:  # xem _product_brief: chỉ đưa ảnh khi sản phẩm có ảnh thật
            label['anh'] = '/search_stock/image/%s' % product.id
        return label

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
        data = self._inventory()._product_breakdown_data(
            self.env, product.id, self._warehouse_id(args.get('warehouse')))
        # Cột 'Giữ' gồm cả phiếu chuyển kho: chỉ có tổng là trợ lý gọi hết thành "giữ cho đơn" và
        # coi hàng đang trên đường là hết. Kèm luôn ở đây vì khả dụng không ít thì nó không gọi
        # xem_dang_giu.
        others = self._other_reservations(product) if data.get('ok') else []
        if others:
            data = dict(data, phieu_khac_dang_giu=others, ghi_chu_giu=(
                "Một phần cột Giữ là các phiếu này, KHÔNG phải đơn bán / khách giữ. Phiếu chuyển kho: "
                "hàng đang chuyển tới kho 'chuyen_den', cộng vào kho đó. So ngay_du_kien với hôm nay."))
        return data

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
            'phieu_khac_dang_giu': self._other_reservations(product),
            # Model tóm tắt hay bỏ nguồn thứ ba (chuyển kho...) vì nghĩ "ai giữ" là người: nói thẳng.
            'ghi_chu': "Cột 'Giữ' trên trang tra tồn = phieu_giu_hang + don_ban_dang_giu + phieu_khac_dang_giu; "
                       "báo đủ cả ba, phiếu có ngay_du_kien đã qua lâu là phiếu treo cần hỏi kho.",
        }

    def _other_reservations(self, product):
        """Hàng bị giữ chỗ bởi phiếu KHÔNG phải đơn bán (chuyển kho, trả NCC, phiếu tay...).

        Cột "Giữ" trên trang tra tồn là reserved_quantity của quant, gồm cả các phiếu này, còn
        _get_so_reservation_map chỉ đếm phiếu có đơn bán: thiếu phần này thì trợ lý thấy "Giữ: 2"
        mà không chỉ ra được phiếu nào giữ. Phiếu của tính năng Giữ hàng đã nằm ở phieu_giu_hang.
        """
        lines = self.env['stock.move.line'].sudo().search([
            ('product_id', '=', product.id),
            ('state', 'not in', ('done', 'cancel')),
            ('location_id.usage', '=', 'internal'),
            ('quantity', '>', 0),
        ], limit=OTHER_RESERVATION_LIMIT)
        rows = {}
        for line in lines:
            picking, move = line.picking_id, line.move_id
            # Lọc ở Python: domain qua picking_id.* không chắc giữ lại dòng không có phiếu.
            if picking.sale_id or getattr(picking, 'is_stock_hold_picking', False):
                continue
            row = rows.setdefault((line.location_id.warehouse_id.id, picking.id or move.id), {
                'kho': line.location_id.warehouse_id.name or line.location_id.display_name,
                'phieu': picking.name or move.reference or '',
                'loai': (picking.picking_type_id or move.picking_type_id).name or '',
                'chuyen_den': (picking.location_dest_id or move.location_dest_id).warehouse_id.name or '',
                'doi_tac': picking.partner_id.display_name or '',
                'nguon': picking.origin or move.origin or '',
                'ngay_du_kien': fields.Datetime.to_string(picking.scheduled_date or move.date),
                'so_luong': 0.0,
            })
            row['so_luong'] += line.quantity
        return list(rows.values())

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
        """Ứng viên CÒN TỒN để AI tự xét thay món gốc, hoặc để tư vấn khi sale hỏi chung một loại
        hàng (không có món gốc) — tool không chấm điểm.

        Giống nhau / hợp nhu cầu hay không phải xét bằng thông số (công năng, điện áp, kích thước
        lắp...), việc đó Claude làm (đọc mô tả, tìm web), không đoán theo chữ trong tên. Tool chỉ
        khoanh vùng: cùng nhóm hàng với món gốc (hoặc nhóm Claude chỉ định), lọc thêm bằng từ khoá
        Claude đặt; xếp mã bán chạy lên trước để khi tư vấn ưu tiên mã hay bán.
        """
        base = None
        if args.get('code') or args.get('product_id'):
            base, _problem, _note = self._resolve_product(args.get('code'), args.get('product_id'))
        category = self._find_category(args.get('nhom')) if args.get('nhom') else None
        if not category and base and args.get('cung_nhom', True):
            category = base.categ_id
        # Một loại máy nhiều cách gọi ("khoan bê tông" / "khoan búa"): khớp MỘT cách gọi là lấy.
        variants = [args.get('tu_khoa') or ''] + [text for text in (args.get('tu_khoa_khac') or [])
                                                  if isinstance(text, str)][:MAX_KEYWORD_VARIANTS]
        keywords = usable_keywords(variants)
        if not category and not keywords:
            return {'status': 'error', 'message': "Cần code của món gốc (để lấy nhóm hàng), nhom, hoặc tu_khoa "
                                                  "loại hàng để khoanh vùng ứng viên."}
        stock = self._stock_by_product(category)
        products = self.env['product.product'].sudo().browse(list(stock)).filtered(
            lambda product: product.sale_ok and product != base)
        # Xếp theo độ khớp TÊN trước, bán chạy sau: xếp theo bán chạy thì "keo trắng đục" bán 280 cái
        # đứng đầu danh sách "máy đục", máy đục thật chưa bán cái nào bị cắt khỏi danh sách.
        ranks = {product.id: keyword_rank(keywords, product.name, '%s %s' % (
            product.default_code or '', product.description_sale or '')) for product in products}
        products = products.filtered(lambda product: ranks[product.id] is not None)
        tiers = {product_id: rank[0] for product_id, rank in ranks.items() if rank}
        sold = self._sold_qty(products)
        products = products.sorted(lambda product: (
            ranks[product.id], -sold.get(product.id, 0.0), -stock[product.id][0]))
        shown = products[:SUBSTITUTE_CANDIDATES]
        specs = self.env['hlv.product.spec'].fresh_by_product(shown | base if base else shown)
        result = {
            'mon_goc': self._with_saved_specs(self._product_brief(base), specs) if base else None,
            'tieu_chi': {'nhom_hang': category.complete_name if category else None,
                         'tu_khoa': keywords or None},
            'tong_ung_vien': len(products),
            # Số mã tên mở đầu đúng loại hàng sale hỏi: báo "kho còn N mẫu" theo số này, không theo
            # tong_ung_vien (gồm cả phụ tùng / mũi / hàng chỉ dính chữ).
            'so_ma_dung_loai': (sum(1 for product in products if tiers[product.id] <= TIER_NAME_TYPE)
                                if keywords else len(products)),
            'ung_vien': [self._with_saved_specs(dict(
                self._product_brief(product), ton=stock[product.id][0], kha_dung=stock[product.id][1],
                gia_ban=product.list_price, da_ban_180_ngay=sold.get(product.id, 0.0)), specs)
                for product in shown],
        }
        if len(products) > len(shown):
            result['ghi_chu_danh_sach'] = (
                "Danh sách đã cắt: còn %s mã không hiện (xếp theo độ khớp tên, rồi bán chạy). Sale hỏi "
                "'tất cả' thì đừng kết luận chỉ từ danh sách này — thu hẹp tu_khoa (thêm hãng / dòng) và "
                "gọi lại." % (len(products) - len(shown)))
        if specs:
            result['ghi_chu_thong_so'] = ("Mã có thong_so_da_luu: dùng luôn, KHÔNG tìm web lại; chỉ tìm web "
                                          "cho mã chưa có.")
        return result

    @staticmethod
    def _with_saved_specs(brief, specs):
        if brief['product_id'] in specs:
            brief['thong_so_da_luu'] = specs[brief['product_id']]
        return brief

    def _q_quet_san_pham(self, args):
        """ĐỦ mọi sản phẩm đang bán có tên khớp điều kiện Claude đặt — không xếp hạng, không cắt.

        Đọc mã + tên mọi sản phẩm một lần bằng SQL (vài chục nghìn dòng, nhẹ) rồi lọc ở Python: so
        không dấu / bỏ khoảng trắng mà ilike của Odoo không làm được ("bu lông" = "bulong").
        """
        criteria = scan_criteria(args)
        if not has_scan_filter(criteria):
            return {'status': 'error', 'message': "Cần ít nhất một trong bat_dau / chua / ma_chua (cụm >= 3 ký tự)."}
        self.env.cr.execute("""
            SELECT pp.id, pp.default_code, COALESCE(pt.name->>'vi_VN', pt.name->>'en_US')
              FROM product_product pp JOIN product_template pt ON pt.id = pp.product_tmpl_id
             WHERE pp.active AND pt.active AND pt.sale_ok
        """)
        matched = [(pid, code or '', name or '') for pid, code, name in self.env.cr.fetchall()
                   if scan_match(criteria, name, code)]
        stock = self._stock_by_product()
        in_stock_only = args.get('con_ton', True) is not False
        if in_stock_only:
            matched = [row for row in matched if row[0] in stock]
        if len(matched) > MAX_SCAN_RESULTS:
            return {'status': 'too_many', 'tong': len(matched),
                    'message': "Khớp %s mã, quá %s: thêm điều kiện (bat_dau cụ thể hơn, hang, khong_chua) rồi "
                               "quét lại." % (len(matched), MAX_SCAN_RESULTS),
                    'vi_du': [name for _pid, _code, name in matched[:15]]}
        prices = {p.id: p.list_price for p in self.env['product.product'].sudo().browse([row[0] for row in matched])}
        rows = sorted(({
            'code': code, 'name': name, 'ton': stock.get(pid, (0.0, 0.0))[0],
            'kha_dung': stock.get(pid, (0.0, 0.0))[1], 'gia_ban': prices.get(pid, 0.0),
        } for pid, code, name in matched), key=lambda row: (-row['ton'], row['name']))
        return {'status': 'found', 'tong': len(rows), 'chi_hang_con_ton': in_stock_only, 'ma': rows}

    def _sold_qty(self, products):
        """{product_id: số lượng đã bán (đơn đã xác nhận) trong SOLD_WINDOW_DAYS ngày}; mã chưa bán thì không có."""
        if not products:
            return {}
        groups = self.env['sale.order.line'].sudo().read_group([
            ('product_id', 'in', products.ids),
            ('order_id.state', 'in', ('sale', 'done')),
            ('order_id.date_order', '>=', fields.Date.to_string(date.today() - timedelta(days=SOLD_WINDOW_DAYS))),
        ], ['product_id', 'product_uom_qty:sum'], ['product_id'], lazy=False)
        return {group['product_id'][0]: _rg_sum(group, 'product_uom_qty') for group in groups if group.get('product_id')}

    def _stock_by_product(self, category=None):
        """{product_id: (tồn, khả dụng)} của các sản phẩm đang có hàng trong kho nội bộ (có thể lọc nhóm)."""
        domain = [('location_id.usage', '=', 'internal'), ('quantity', '>', 0)]
        if category:
            domain.append(('product_id.categ_id', 'child_of', category.id))
        groups = self.env['stock.quant'].sudo().read_group(
            domain, ['product_id', 'quantity:sum', 'reserved_quantity:sum'], ['product_id'], lazy=False)
        return {group['product_id'][0]: (_rg_sum(group, 'quantity'),
                                         _rg_sum(group, 'quantity') - _rg_sum(group, 'reserved_quantity'))
                for group in groups if group.get('product_id')}

    def _find_category(self, name):
        """Nhóm hàng Odoo theo tên (khớp đúng trước, rồi "chứa"). None nếu không ra đúng một nhóm."""
        Category = self.env['product.category'].sudo()
        found = Category.search([('name', '=ilike', name.strip())], limit=2)
        if len(found) != 1:
            found = Category.search([('complete_name', 'ilike', name.strip())], limit=2)
        return found if len(found) == 1 else None

    @staticmethod
    def _product_brief(product):
        """Thông tin để Claude xét thông số: mã, tên, nhóm, mô tả bán hàng (cắt ngắn), ảnh nếu có.

        'anh' chỉ có khi sản phẩm CÓ ảnh trong Odoo — phần lớn chưa có, đưa link ảnh trống là
        Claude chèn khung ảnh rỗng; không có thì Claude lấy ảnh chính hãng trên web.
        """
        brief = {
            'product_id': product.id, 'code': product.default_code or '', 'name': product.name,
            'nhom': product.categ_id.complete_name,
            'mo_ta': (product.description_sale or '')[:SUBSTITUTE_DESCRIPTION_CHARS],
        }
        if product.image_128:
            brief['anh'] = '/search_stock/image/%s' % product.id
        return brief

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
            has_words = bool(words) and has_all_words(words, self._line_text(line))
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
            if has_all_words(words, '%s %s' % (product.name, product.default_code or '')):
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
    def _line_text(line):
        return '%s %s %s' % (line.product_id.name or '', line.product_id.default_code or '', line.name or '')

    def _q_xem_gia_nhap(self, product, args):
        try:
            from odoo.addons.hlv_vendor_quotation.services.price_lookup import product_prices
        except ImportError:
            return {'message': "Odoo chưa cài module hỏi giá NCC (hlv_vendor_quotation)."}
        # Tool chạy dưới quyền quản trị (luồng nền / agent): kiểm quyền theo tài khoản đang chat,
        # không thì sale không được vào trang tra giá vẫn hỏi ra giá mua qua trợ lý.
        user = self.env['res.users'].browse(self.env.context.get('chat_user_id')).exists()
        if not user or not user.has_group(PRICE_PAGE_GROUP):
            return {'status': 'error', 'message': "Tài khoản đang chat chưa được cấp quyền hỏi giá NCC nên "
                                                  "không xem được giá mua / báo giá NCC."}
        prices = product_prices(self.env(su=True), product)
        return compact_prices(prices, PRICE_PAGE_LINK % product.id)
