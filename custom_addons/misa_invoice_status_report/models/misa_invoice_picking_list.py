from odoo import api, fields, models

from .stock_picking import MISA_INVOICE_UNASSIGNED_SALER

# Danh sách phiếu xuất kho "phẳng" (tab 'Phiếu xuất kho' trên dashboard nội bộ) + vài báo cáo
# nhỏ đứng cạnh (top phiếu cần hối gấp, danh sách mã sale cho dropdown lọc) — tách khỏi
# stock_picking.py (đã quá lớn). Chỉ ĐỌC (search/search_count/read_group) dựa trên field đã
# tính sẵn, không tự khớp/tính toán gì — an toàn để tách riêng.


class StockPickingMisaInvoicePickingList(models.Model):
    _inherit = 'stock.picking'

    @api.model
    def get_misa_invoice_urgent_list(
        self, limit=10, date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
    ):
        """Top phiếu cần hối gấp nhất: chưa xuất HĐ, không ngoại lệ, xuất kho lâu nhất."""
        domain = self._misa_invoice_dashboard_base_domain(
            date_from, date_to, invoice_date_from, invoice_date_to
        ) + [
            ('misa_invoice_state', 'in', ('missing', 'requested')),
            ('misa_invoice_exception', '=', False),
        ]
        pickings = self.sudo().search(domain, order='date_done asc', limit=limit)
        today = fields.Date.context_today(self)
        return [self._misa_invoice_picking_to_row(picking, today) for picking in pickings]

    def _misa_invoice_picking_list_domain(
        self, search=False, state=False, saler_code=False,
        date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
    ):
        domain = self._misa_invoice_dashboard_base_domain(
            date_from, date_to, invoice_date_from, invoice_date_to
        )
        if search:
            domain.append('|')
            domain.append(('name', 'ilike', search))
            domain.append(('misa_invoice_root_partner_id.display_name', 'ilike', search))
        if state:
            domain.append(('misa_invoice_state', '=', state))
        if saler_code:
            value = False if saler_code == MISA_INVOICE_UNASSIGNED_SALER else saler_code
            domain.append(('misa_invoice_saler_code', '=', value))
        return domain

    @api.model
    def get_misa_invoice_picking_list(
        self, limit=20, offset=0, search=False, state=False, saler_code=False,
        date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
    ):
        """Danh sách phiếu XUẤT KHO 'phẳng' (mọi trạng thái, không group, key là
        stock.picking KBC/OUT/...) — tab 'Phiếu xuất kho' trên dashboard. Có phân trang
        server-side vì có thể lên tới hàng nghìn dòng."""
        Picking = self.sudo()
        domain = self._misa_invoice_picking_list_domain(
            search, state, saler_code, date_from, date_to, invoice_date_from, invoice_date_to
        )
        total = Picking.search_count(domain)
        pickings = Picking.search(domain, order='date_done desc', limit=limit, offset=offset)
        today = fields.Date.context_today(self)
        return {
            'rows': [self._misa_invoice_picking_to_row(picking, today) for picking in pickings],
            'total': total,
        }

    @api.model
    def get_misa_invoice_saler_options(self):
        """Danh sách mã sale (toàn bộ phạm vi đối soát, không giới hạn ngày) để đổ vào dropdown
        lọc — dùng cho trang "Danh sách đơn hàng" độc lập, nơi không có sẵn state.data.by_saler
        như dashboard Tổng quan."""
        Picking = self.sudo()
        domain = self._misa_invoice_dashboard_base_domain()
        groups = Picking.read_group(domain, ['id'], ['misa_invoice_saler_code'])
        return [
            {
                'code': grp['misa_invoice_saler_code'] or MISA_INVOICE_UNASSIGNED_SALER,
                'count': grp['misa_invoice_saler_code_count'],
            }
            for grp in groups
        ]
