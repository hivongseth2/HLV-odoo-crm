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

    def _domain(self):
        """
        Override _domain to filter for Shopee orders only
        """
        self.ensure_one()
        if self.date_from > self.date_to:
            raise UserError(_("Khoảng ngày không hợp lệ."))

        domain = [
            ("picking_type_code", "=", "outgoing"),
            ("date_done", ">=", fields.Date.to_date(self.date_from)),
            ("date_done", "<=", fields.Date.to_date(self.date_to)),
            ("state", "=", "done"),
        ]

        if self.warehouse_ids:
            domain.append(("picking_type_id.warehouse_id", "in", self.warehouse_ids.ids))

        # Filter: Only customers with 'shopee' in name (case-insensitive)
        domain.append(('partner_id.name', 'ilike', 'shopee'))

        return domain

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
        if sol_product.id == move.product_id.id:
            return ''

        # Check if sol_product is a BoM Kit (phantom)
        # We search for any active phantom BoM for this product template.
        is_kit = self.env['mrp.bom'].search_count([
            ('product_tmpl_id', '=', sol_product.product_tmpl_id.id),
            ('type', '=', 'phantom'),
            ('active', '=', True)
        ])
        
        if is_kit:
            return sol_product.default_code
            
        return ''

    def _build_row_data(self, picking, so, prod, ml, move,
                        scheduled_date_str, picking_name, partner_code, partner_name,
                        partner_address, partner_vat, sale_name, sale_user_code,
                        dien_giai, ly_do_xuat, warehouse_code, pos_line=None, sale_line=None, forced_qty=None):
        """
        Override to fix fields showing FALSE and hardcode warehouse code, 
        plus apply SHOPEE OVERRIDE LOGIC from stock_export_wizard.
        """
        row = super()._build_row_data(
            picking, so, prod, ml, move,
            scheduled_date_str, picking_name, partner_code, partner_name,
            partner_address, partner_vat, sale_name, sale_user_code,
            dien_giai, ly_do_xuat, warehouse_code, pos_line=pos_line, sale_line=sale_line, forced_qty=forced_qty
        )
        
        # --- SHOPEE OVERRIDE LOGIC (Ported from stock_export_wizard.py) ---
        if so and hasattr(so, 'shopee_shop_id') and so.shopee_shop_id:
            shop = so.shopee_shop_id
            # Check Account Name contains 2014645
            account = getattr(shop, 'account_id', False)
            if account and '2014645' in getattr(account, 'name', ''):
                shop_id = getattr(shop, 'shop_identifier', 0)
                target_pid = False
                
                if shop_id == 796817584:
                    target_pid = 9715 # MILWAUKEE
                elif shop_id == 1357810112:
                    target_pid = 9720 # DEWALT
                elif shop_id == 326259406:
                    target_pid = 9701 # HLV
                
                if target_pid:
                    target_partner = self.env['res.partner'].browse(target_pid)
                    if target_partner.exists():
                        # Recalculate partner code
                        s_ref = False
                        if target_partner.commercial_partner_id and target_partner.commercial_partner_id.ref:
                            s_ref = target_partner.commercial_partner_id.ref
                        elif target_partner.parent_id and target_partner.parent_id.ref:
                            s_ref = target_partner.parent_id.ref
                        elif target_partner.ref:
                            s_ref = target_partner.ref
                        
                        new_partner_code = s_ref or ''
                        new_partner_name = target_partner.name
                        
                        # Override Row Data
                        row['ten_khach_hang'] = new_partner_name
                        row['ma_khach_hang'] = new_partner_code
                        row['nguoi_nop'] = new_partner_name
                        
                        # Fix ly_do_xuat / dien_giai
                        new_reason = "Xuất kho bán hàng cho " + new_partner_name
                        row['ly_do_xuat'] = new_reason
                        row['dien_giai'] = new_reason
                        
                        # Update address if needed? Stock wizard doesn't explicitly do it but it's good practice
                        # For now sticking to what stock wizard did (mostly name/code/reason)

        # 1. Fix FALSE issue for 3 fields
        if not row.get('hinh_thuc_giao_hang'):
             row['hinh_thuc_giao_hang'] = ''
        if not row.get('hinh_thuc_thanh_toan_so'):
             row['hinh_thuc_thanh_toan_so'] = ''
        if not row.get('ben_tra_phi_van_chuyen'):
             row['ben_tra_phi_van_chuyen'] = ''

        # 2. Hardcode Ma kho
        row['ma_kho'] = 'HLV'
        
        return row

    def _get_columns_definition(self):
        """
        Override to match 'Copy of mau_ban_hang (1).xlsx' exactly (52 columns).
        Remove 'vi_tri' and 'misa_sync' which exist in parent but not in template.
        """
        columns = super()._get_columns_definition()
        return [c for c in columns if c['key'] not in ['vi_tri', 'misa_sync']]

    def action_export(self):
        self.ensure_one()
        if Workbook is None:
            raise UserError(_("Thiếu thư viện openpyxl. Vui lòng cài đặt 'openpyxl' cho Python."))

        pickings = self.env["stock.picking"].sudo().search(self._domain(), order="scheduled_date asc, id asc")
        if not pickings:
            raise UserError(_("Không tìm thấy phiếu xuất kho Shopee nào trong khoảng ngày đã chọn."))

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
