from odoo import models, api
from odoo.exceptions import UserError
import io
import base64


class HlvStockQuick(models.TransientModel):
    _name = "hlv.stock.quick"
    _description = "Xem ton kho theo nhom"

    @api.model
    def get_data(self, group_id, warehouse_ids, show_zero):
        if not group_id:
            return {"lines": [], "total": 0.0, "columns": []}
        group = self.env["hlv.product.report.group"].browse(group_id)
        if warehouse_ids:
            warehouses = self.env["stock.warehouse"].browse(warehouse_ids)
            columns = [{"id": wh.id, "name": wh.name} for wh in warehouses]
        else:
            warehouses = []
            columns = []
        lines = []
        total = 0.0
        for product in group.product_ids.sorted("default_code"):
            if warehouses:
                col_qtys = [
                    product.with_context(warehouse=wh.id).qty_available
                    for wh in warehouses
                ]
                prod_total = sum(col_qtys)
            else:
                col_qtys = []
                prod_total = product.qty_available
            if not show_zero and prod_total == 0:
                continue
            total += prod_total
            lines.append({
                "code": product.default_code or "",
                "name": product.name,
                "col_qtys": col_qtys,
                "total": prod_total,
            })
        return {"lines": lines, "total": total, "columns": columns}

    @api.model
    def export_excel(self, group_id, warehouse_ids, show_zero):
        try:
            import xlsxwriter
        except ImportError:
            raise UserError("xlsxwriter chua duoc cai.")
        data = self.get_data(group_id, warehouse_ids, show_zero)
        columns = data["columns"]
        lines = data["lines"]
        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {"in_memory": True})
        ws = wb.add_worksheet("Ton kho")
        fh = wb.add_format({"bold": True, "bg_color": "#1a2639", "font_color": "#ffffff", "border": 1, "align": "center", "valign": "vcenter"})
        fc = wb.add_format({"border": 1, "font_name": "Courier New", "font_size": 9, "font_color": "#546e7a"})
        ft = wb.add_format({"border": 1})
        fn = wb.add_format({"border": 1, "num_format": "#,##0.##", "align": "right", "font_color": "#198754", "bold": True})
        f0 = wb.add_format({"border": 1, "num_format": "#,##0.##", "align": "right", "font_color": "#adb5bd"})
        fl = wb.add_format({"bold": True, "bg_color": "#e8f5e9", "font_color": "#155724", "border": 1, "align": "right"})
        fg = wb.add_format({"bold": True, "bg_color": "#e8f5e9", "font_color": "#198754", "border": 1, "num_format": "#,##0.##", "align": "right", "font_size": 12})
        fs = wb.add_format({"border": 1, "align": "center", "font_color": "#adb5bd"})
        n = len(columns)
        last_col = 3 + n if n else 3
        ws.merge_range(0, 0, 1, last_col, "BAO CAO TON KHO", wb.add_format({"bold": True, "font_size": 14, "align": "center", "valign": "vcenter"}))
        ws.set_row(0, 28)
        ws.set_row(1, 8)
        ws.set_column(0, 0, 5)
        ws.set_column(1, 1, 16)
        ws.set_column(2, 2, 45)
        for i in range(n + 1):
            ws.set_column(3 + i, 3 + i, 16)
        ws.set_row(2, 24)
        ws.write(2, 0, "#", fh)
        ws.write(2, 1, "Ma SP", fh)
        ws.write(2, 2, "Ten san pham", fh)
        if columns:
            for i, col in enumerate(columns):
                ws.write(2, 3 + i, col["name"], fh)
            ws.write(2, 3 + n, "TONG", fh)
        else:
            ws.write(2, 3, "Ton kho", fh)
        row = 3
        for idx, line in enumerate(lines):
            ws.write(row, 0, idx + 1, fs)
            ws.write(row, 1, line["code"], fc)
            ws.write(row, 2, line["name"], ft)
            if columns:
                for i, qty in enumerate(line["col_qtys"]):
                    ws.write(row, 3 + i, qty, fn if qty > 0 else f0)
                ws.write(row, 3 + n, line["total"], fn if line["total"] > 0 else f0)
            else:
                ws.write(row, 3, line["total"], fn if line["total"] > 0 else f0)
            row += 1
        ws.merge_range(row, 0, row, 2, "TONG TON KHO", fl)
        if columns:
            for i in range(n):
                ct = sum(l["col_qtys"][i] for l in lines)
                ws.write(row, 3 + i, ct, fg)
            ws.write(row, 3 + n, data["total"], fg)
        else:
            ws.write(row, 3, data["total"], fg)
        wb.close()
        output.seek(0)
        att = self.env["ir.attachment"].create({
            "name": "ton_kho.xlsx",
            "type": "binary",
            "datas": base64.b64encode(output.read()).decode(),
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "res_model": self._name,
            "res_id": 0,
        })
        return att.id

    @api.model
    def get_group_products(self, group_id):
        group = self.env["hlv.product.report.group"].browse(group_id)
        result = []
        for p in group.product_ids.sorted("name"):
            result.append({"id": p.id, "name": p.name, "code": p.default_code or ""})
        return result

    @api.model
    def search_products(self, query, exclude_ids):
        domain = [
            ("type", "in", ["consu", "product"]),
            "|",
            ("name", "ilike", query),
            ("default_code", "ilike", query),
            ("id", "not in", exclude_ids or []),
        ]
        products = self.env["product.product"].search(domain, limit=20, order="name")
        return [{"id": p.id, "name": p.name, "code": p.default_code or ""} for p in products]
