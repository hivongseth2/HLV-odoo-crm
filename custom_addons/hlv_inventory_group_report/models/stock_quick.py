from odoo import models, api
from odoo.exceptions import UserError
import io
import base64


class HlvStockQuick(models.TransientModel):
    _name = "hlv.stock.quick"
    _description = "Xem ton kho theo nhom"

    @api.model
    def get_data(self, group_id, warehouse_ids, show_zero, include_outgoing=True):
        if not group_id:
            return {"lines": [], "total": 0.0, "outgoing_total": 0.0, "columns": []}
        group = self.env["hlv.product.report.group"].browse(group_id)
        if warehouse_ids:
            warehouses = self.env["stock.warehouse"].browse(warehouse_ids)
            columns = [{"id": wh.id, "name": wh.name} for wh in warehouses]
        else:
            warehouses = []
            columns = []
        # Pre-compute outgoing location ids per warehouse (pack zone + output zone)
        wh_outgoing_locs = {}
        if include_outgoing and warehouses:
            for wh in warehouses:
                ids = []
                for loc in [wh.wh_pack_stock_loc_id, wh.wh_output_stock_loc_id]:
                    if loc:
                        children = self.env["stock.location"].search([("id", "child_of", loc.id)])
                        ids.extend(children.ids)
                wh_outgoing_locs[wh.id] = ids
        lines = []
        total = 0.0
        outgoing_total = 0.0
        for product in group.product_ids.sorted("default_code"):
            if warehouses:
                col_qtys = []
                col_outgoing_qtys = []
                for wh in warehouses:
                    sq = product.with_context(location=wh.lot_stock_id.id).qty_available
                    col_qtys.append(sq)
                    oq = 0.0
                    if include_outgoing and wh_outgoing_locs.get(wh.id):
                        quants = self.env["stock.quant"].search([
                            ("product_id", "=", product.id),
                            ("location_id", "in", wh_outgoing_locs[wh.id]),
                            ("quantity", ">", 0),
                        ])
                        oq = sum(q.quantity for q in quants)
                    col_outgoing_qtys.append(oq)
                prod_total = sum(col_qtys)
                prod_outgoing = sum(col_outgoing_qtys)
            else:
                col_qtys = []
                col_outgoing_qtys = []
                prod_total = product.qty_available
                prod_outgoing = 0.0
            if not show_zero and prod_total == 0 and prod_outgoing == 0:
                continue
            total += prod_total
            outgoing_total += prod_outgoing
            lines.append({
                "id": product.id,
                "code": product.default_code or "",
                "name": product.name,
                "uom": product.uom_id.name or "",
                "image_url": "/web/image/product.product/%d/image_128" % product.id,
                "col_qtys": col_qtys,
                "col_outgoing_qtys": col_outgoing_qtys,
                "total": prod_total,
                "outgoing_total": prod_outgoing,
            })
        return {"lines": lines, "total": total, "outgoing_total": outgoing_total, "columns": columns}

    @api.model
    def export_excel(self, group_id, warehouse_ids, show_zero, include_outgoing=True):
        try:
            import xlsxwriter
        except ImportError:
            raise UserError("xlsxwriter chua duoc cai.")
        data = self.get_data(group_id, warehouse_ids, show_zero, include_outgoing)
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
        fo = wb.add_format({"border": 1, "num_format": "#,##0.##", "align": "right", "font_color": "#e65100", "bold": True})
        fog = wb.add_format({"bold": True, "bg_color": "#fff8e1", "font_color": "#e65100", "border": 1, "num_format": "#,##0.##", "align": "right", "font_size": 12})
        n = len(columns)
        has_outgoing = include_outgoing and n > 0
        last_col = (4 + n + (1 if has_outgoing else 0)) if n else 4
        ws.merge_range(0, 0, 1, last_col, "B\u00c1O C\u00c1O T\u1ed2N KHO", wb.add_format({"bold": True, "font_size": 14, "align": "center", "valign": "vcenter"}))
        ws.set_row(0, 28)
        ws.set_row(1, 8)
        ws.set_column(0, 0, 5)
        ws.set_column(1, 1, 16)
        ws.set_column(2, 2, 45)
        ws.set_column(3, 3, 10)
        for i in range(n + 1):
            ws.set_column(4 + i, 4 + i, 16)
        if has_outgoing:
            ws.set_column(4 + n + 1, 4 + n + 1, 16)
        ws.set_row(2, 24)
        ws.write(2, 0, "#", fh)
        ws.write(2, 1, "M\u00e3 SP", fh)
        ws.write(2, 2, "T\u00ean s\u1ea3n ph\u1ea9m", fh)
        ws.write(2, 3, "\u0110VT", fh)
        if columns:
            for i, col in enumerate(columns):
                ws.write(2, 4 + i, col["name"], fh)
            ws.write(2, 4 + n, "T\u1ed4NG", fh)
            if has_outgoing:
                ws.write(2, 4 + n + 1, "\u0110\u00f3ng g\u00f3i/Out", fh)
        else:
            ws.write(2, 4, "T\u1ed3n kho", fh)
        row = 3
        for idx, line in enumerate(lines):
            ws.write(row, 0, idx + 1, fs)
            ws.write(row, 1, line["code"], fc)
            ws.write(row, 2, line["name"], ft)
            ws.write(row, 3, line.get("uom", ""), ft)
            if columns:
                for i, qty in enumerate(line["col_qtys"]):
                    ws.write(row, 4 + i, qty, fn if qty > 0 else f0)
                ws.write(row, 4 + n, line["total"], fn if line["total"] > 0 else f0)
                if has_outgoing:
                    oqt = line.get("outgoing_total", 0)
                    ws.write(row, 4 + n + 1, oqt, fo if oqt > 0 else f0)
            else:
                ws.write(row, 4, line["total"], fn if line["total"] > 0 else f0)
            row += 1
        ws.merge_range(row, 0, row, 3, "T\u1ed4NG T\u1ed2N KHO", fl)
        if columns:
            for i in range(n):
                ct = sum(l["col_qtys"][i] for l in lines)
                ws.write(row, 4 + i, ct, fg)
            ws.write(row, 4 + n, data["total"], fg)
            if has_outgoing:
                ogt = data.get("outgoing_total", 0)
                ws.write(row, 4 + n + 1, ogt, fog if ogt > 0 else f0)
        else:
            ws.write(row, 4, data["total"], fg)
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
            result.append({"id": p.id, "name": p.name, "code": p.default_code or "", "image_url": "/web/image/product.product/%d/image_128" % p.id})
        return result

    @api.model
    def search_products(self, query, exclude_ids, offset=0):
        domain = [
            ("type", "in", ["consu", "product"]),
            "|",
            ("name", "ilike", query),
            ("default_code", "ilike", query),
            ("id", "not in", exclude_ids or []),
        ]
        total = self.env["product.product"].search_count(domain)
        products = self.env["product.product"].search(domain, limit=50, offset=offset, order="name")
        items = [{"id": p.id, "name": p.name, "code": p.default_code or "", "image_url": "/web/image/product.product/%d/image_128" % p.id} for p in products]
        return {"items": items, "total": total}

    @api.model
    def get_product_locations(self, product_id, warehouse_ids):
        outgoing_loc_ids = set()
        if warehouse_ids:
            warehouses = self.env["stock.warehouse"].browse(warehouse_ids)
            loc_ids = []
            for wh in warehouses:
                # Khu vuc stock chinh
                stock_locs = self.env["stock.location"].search([
                    ("id", "child_of", wh.lot_stock_id.id),
                    ("usage", "=", "internal"),
                ])
                loc_ids.extend(stock_locs.ids)
                # Khu vuc dong goi (pack zone) - chuan bi giao
                if wh.wh_pack_stock_loc_id:
                    pack_locs = self.env["stock.location"].search([
                        ("id", "child_of", wh.wh_pack_stock_loc_id.id),
                    ])
                    loc_ids.extend(pack_locs.ids)
                    outgoing_loc_ids.update(pack_locs.ids)
                # Khu vuc output - chuan bi giao
                if wh.wh_output_stock_loc_id:
                    out_locs = self.env["stock.location"].search([
                        ("id", "child_of", wh.wh_output_stock_loc_id.id),
                    ])
                    loc_ids.extend(out_locs.ids)
                    outgoing_loc_ids.update(out_locs.ids)
            loc_ids = list(set(loc_ids))
        else:
            locs = self.env["stock.location"].search([("usage", "=", "internal")])
            loc_ids = locs.ids
        quants = self.env["stock.quant"].search([
            ("product_id", "=", product_id),
            ("location_id", "in", loc_ids),
            ("quantity", ">", 0),
        ], order="quantity desc")
        result = []
        for q in quants:
            wh = q.location_id.warehouse_id
            result.append({
                "location": q.location_id.display_name,
                "warehouse": wh.name if wh else "",
                "qty": q.quantity,
                "outgoing": q.location_id.id in outgoing_loc_ids,
            })
        return result

    @api.model
    def import_products_from_excel(self, group_id, b64data):
        try:
            import openpyxl
        except ImportError:
            raise UserError("openpyxl ch\u01b0a \u0111\u01b0\u1ee3c c\u00e0i \u0111\u1eb7t.")
        import io as _io, base64 as _b64
        raw = _b64.b64decode(b64data)
        try:
            wb = openpyxl.load_workbook(_io.BytesIO(raw), read_only=True, data_only=True)
        except Exception as e:
            raise UserError("Kh\u00f4ng th\u1ec3 \u0111\u1ecdc file Excel: %s" % str(e))
        ws = wb.active
        codes = []
        skip_headers = {"m\u00e3 sp", "default_code", "ma sp", "code", "m\u00e3sp"}
        for row in ws.iter_rows(min_row=1, values_only=True):
            if row and row[0] is not None:
                val = str(row[0]).strip()
                if val and val.lower() not in skip_headers:
                    codes.append(val)
        wb.close()
        if not codes:
            return {"added": [], "not_found": [], "already_in": [], "total": 0}
        group = self.env["hlv.product.report.group"].browse(group_id)
        existing_ids = set(group.product_ids.ids)
        added, not_found, already_in = [], [], []
        for code in codes:
            product = self.env["product.product"].search([("default_code", "=", code)], limit=1)
            if not product:
                not_found.append(code)
            elif product.id in existing_ids:
                already_in.append({"code": code, "name": product.name})
            else:
                group.write({"product_ids": [(4, product.id)]})
                existing_ids.add(product.id)
                added.append({"code": code, "name": product.name})
        return {"added": added, "not_found": not_found, "already_in": already_in, "total": len(codes)}
