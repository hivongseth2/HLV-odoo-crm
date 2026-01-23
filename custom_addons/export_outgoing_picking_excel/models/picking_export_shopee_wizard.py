# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import base64
from io import BytesIO

try:
    from openpyxl import Workbook
except ImportError:
    Workbook = None

class PickingExportShopeeWizard(models.TransientModel):
    _name = "picking.export.shopee.wizard"
    _inherit = "picking.export.wizard"
    _description = "Xuất Excel lệnh xuất kho Shopee"

    def _thuoc_combo_code_for_move(self, move):
        """
        Overridden to use BoM Kit logic.
        If the product on the Sale Order Line is a Kit (has a phantom BoM),
        return its default_code.
        """
        sol = getattr(move, 'sale_line_id', False)
        if not sol:
            return ''
        
        sol_product = sol.product_id
        if not sol_product:
            return ''

        # If move product is same as SOL product, it hasn't successfully exploded into components 
        # (or it's not a kit).
        # However, we should just check if SOL product is a kit.
        if sol_product.id == move.product_id.id:
            # Check if it really is a kit but somehow didn't explode or is just top level?
            # Usuaully if it's a kit, move product should be component.
            # If they are same, assume not a component of a combo.
            return ''

        # Check if sol_product is a BoM Kit (phantom)
        # We search for any active phantom BoM for this product template.
        # This is a simplified check.
        is_kit = self.env['mrp.bom'].search_count([
            ('product_tmpl_id', '=', sol_product.product_tmpl_id.id),
            ('type', '=', 'phantom'),
            ('active', '=', True)
        ])
        
        if is_kit:
            return sol_product.default_code
            
        return ''

    def action_export(self):
        """
        Copy of action_export to fix res_model in attachment
        """
        self.ensure_one()
        if Workbook is None:
            raise UserError(_("Thiếu thư viện openpyxl. Vui lòng cài đặt 'openpyxl' cho Python."))

        pickings = self.env["stock.picking"].sudo().search(self._domain(), order="scheduled_date asc, id asc")
        if not pickings:
            raise UserError(_("Không tìm thấy phiếu xuất kho nào trong khoảng ngày đã chọn."))

        # Tạo dữ liệu
        all_rows = []
        for picking in pickings:
            rows = self._get_move_line_rows(picking)
            all_rows.extend(rows)

        if not all_rows:
            raise UserError(_("Không có dữ liệu chi tiết để xuất."))

        # Tạo Excel workbook
        wb = self._create_excel_workbook(all_rows)

        # Xuất file
        out = BytesIO()
        wb.save(out)
        out.seek(0)

        filename = f"Xuat_ban_hang_Shopee_{self.date_from}_{self.date_to}.xlsx"
        attachment = self.env["ir.attachment"].sudo().create({
            "name": filename,
            "type": "binary",
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "datas": base64.b64encode(out.getvalue()),
            "res_model": self._name,  # Correct model name
            "res_id": self.id,
        })

        return {
            "type": "ir.actions.act_url",
            "url": f"/web/content/{attachment.id}?download=true",
            "target": "self",
        }
