from datetime import datetime, time as dt_time

from odoo import api, fields, models

from .stock_picking import MISA_INVOICE_AMOUNT_TOLERANCE

# Tab "Trả hàng / Điều chỉnh" tách khỏi stock_picking.py (đã quá lớn) — chỉ ĐỌC dữ liệu đã
# tính sẵn (misa_invoice_net_actual_amount/effective_amount/returned_amount...), không tự tính
# toán/khớp gì thêm nên an toàn để tách riêng.


class StockPickingMisaInvoiceReturns(models.Model):
    _inherit = 'stock.picking'

    def _misa_invoice_returns_domain(self, date_from=False, date_to=False):
        """Cùng bộ lọc nền (outgoing, done, từ mốc đối soát, theo ngày xuất kho) như
        _misa_invoice_dashboard_base_domain, nhưng ĐẢO NGƯỢC điều kiện trả hàng: chỉ lấy đúng
        các phiếu CÓ trả hàng. Gộp chung cả luồng MISA lẫn Shopee vào đây (không tách theo
        misa_invoice_is_shopee) vì đây là 1 khu vực xử lý riêng, không phải đối soát theo luồng."""
        lower = self._get_misa_invoice_cutoff_date()
        if date_from:
            try:
                parsed_from = fields.Date.from_string(date_from)
            except Exception:
                parsed_from = False
            if parsed_from and parsed_from > lower:
                lower = parsed_from
        domain = [
            ('picking_type_id.code', '=', 'outgoing'),
            ('state', '=', 'done'),
            ('date_done', '>=', fields.Datetime.to_string(datetime.combine(lower, dt_time.min))),
            ('misa_invoice_returned_amount', '>', 0),
        ]
        if date_to:
            try:
                parsed_to = fields.Date.from_string(date_to)
            except Exception:
                parsed_to = False
            if parsed_to:
                domain.append(
                    ('date_done', '<=', fields.Datetime.to_string(datetime.combine(parsed_to, dt_time.max)))
                )
        return domain

    def _misa_invoice_return_picking_to_row(self, picking, today):
        done_date = picking.date_done.date() if picking.date_done else False
        is_full_return = (picking.misa_invoice_net_actual_amount or 0.0) <= MISA_INVOICE_AMOUNT_TOLERANCE
        return {
            'id': picking.id,
            'name': picking.name,
            'partner_name': picking.misa_invoice_root_partner_id.display_name or picking.partner_id.display_name or '',
            'sale_order_name': ', '.join(picking.misa_invoice_sale_order_ids.mapped('name')),
            'saler_code': picking.misa_invoice_saler_code or '',
            'date_done': fields.Date.to_string(done_date) if done_date else '',
            'gross_amount': picking.x_studio_tng_tin_sau_thu or 0.0,
            'returned_amount': picking.misa_invoice_returned_amount or 0.0,
            'net_actual_amount': picking.misa_invoice_net_actual_amount or 0.0,
            'is_full_return': is_full_return,
            # Hóa đơn GỐC (thật, đã fetch từ MISA trước đây) — giữ nguyên để kế toán đối chiếu,
            # KHÔNG bị sửa/xóa bởi tính năng này.
            'original_invoice_no': picking.misa_invoice_no or False,
            'original_invoice_date': (
                fields.Date.to_string(picking.misa_invoice_date) if picking.misa_invoice_date else False
            ),
            # Tiền HĐ áp dụng thật sự dùng ở mọi tab khác (misa_invoice_effective_amount) — CÙNG
            # 1 nguồn với các nơi khác, không tính riêng ở đây nữa để tránh 2 nơi lệch nhau.
            'effective_invoice_amount': picking.misa_invoice_effective_amount or 0.0,
            'note': (
                "Trả hết — hóa đơn coi như đã được kế toán điều chỉnh về 0đ (không xác minh được "
                "điều chỉnh thật trên MISA)."
                if is_full_return else
                "Trả một phần — hóa đơn coi như đã được kế toán điều chỉnh xuống đúng bằng tiền "
                "thực xuất ròng (không xác minh được điều chỉnh thật trên MISA)."
            ),
            'exception': picking.misa_invoice_exception,
        }

    @api.model
    def get_misa_invoice_return_list(self, limit=20, offset=0, search=False, date_from=False, date_to=False):
        Picking = self.sudo()
        domain = Picking._misa_invoice_returns_domain(date_from, date_to)
        if search:
            domain = domain + [
                '|', ('name', 'ilike', search), ('misa_invoice_sale_order_ids.name', 'ilike', search),
            ]
        pickings = Picking.search(domain, order='date_done desc', limit=limit, offset=offset)
        today = fields.Date.context_today(self)
        return {
            'rows': [Picking._misa_invoice_return_picking_to_row(p, today) for p in pickings],
            'total': Picking.search_count(domain),
            'full_return_count': Picking.search_count(
                domain + [('misa_invoice_net_actual_amount', '<=', MISA_INVOICE_AMOUNT_TOLERANCE)]
            ),
        }
