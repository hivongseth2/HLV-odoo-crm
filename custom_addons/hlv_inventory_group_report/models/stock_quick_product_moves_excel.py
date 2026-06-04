from odoo import api, models
from odoo.exceptions import UserError
import base64
import io


class HlvStockQuick(models.TransientModel):
    _inherit = 'hlv.stock.quick'

    @api.model
    def export_moves_excel(self, product_id, warehouse_ids, date_from=None, date_to=None):
        import io
        try:
            import xlsxwriter
        except ImportError:
            raise UserError("xlsxwriter ch\u01b0a \u0111\u01b0\u1ee3c c\u00e0i \u0111\u1eb7t.")

        data = self.get_product_moves(product_id, warehouse_ids, date_from, date_to)
        product = self.env["product.product"].browse(product_id)

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {"in_memory": True})
        ws = wb.add_worksheet("S\u1ed5 chi ti\u1ebft")

        # Formats
        ftitle = wb.add_format({"bold": True, "font_size": 14, "align": "center", "valign": "vcenter", "font_color": "#1b5e20"})
        finfo  = wb.add_format({"font_size": 11, "italic": True, "font_color": "#546e7a", "border": 0})
        fh     = wb.add_format({"bold": True, "bg_color": "#33691e", "font_color": "#fff", "border": 1, "align": "center", "valign": "vcenter", "font_size": 11})
        ft     = wb.add_format({"border": 1})
        fmono  = wb.add_format({"border": 1, "font_name": "Courier New", "font_size": 9, "font_color": "#1a2639"})
        fdate  = wb.add_format({"border": 1, "align": "center", "font_color": "#546e7a"})
        fuom   = wb.add_format({"border": 1, "align": "center", "font_color": "#6c757d"})
        fprice = wb.add_format({"border": 1, "num_format": "#,##0", "align": "right", "font_color": "#5d4037"})
        fcombo = wb.add_format({"border": 1, "align": "left", "font_color": "#e65100", "italic": True, "font_size": 10})
        fqty_in  = wb.add_format({"border": 1, "num_format": "#,##0.##", "align": "right", "font_color": "#1565c0", "bold": True})
        fqty_out = wb.add_format({"border": 1, "num_format": "#,##0.##", "align": "right", "font_color": "#b71c1c", "bold": True})
        fqty_bal = wb.add_format({"border": 1, "num_format": "#,##0.##", "align": "right", "font_color": "#1b5e20", "bold": True})
        fqty_neg = wb.add_format({"border": 1, "num_format": "#,##0.##", "align": "right", "font_color": "#e53935", "bold": True})
        fempty   = wb.add_format({"border": 1})
        fopening = wb.add_format({"bold": True, "italic": True, "bg_color": "#e8f5e9", "font_color": "#1b5e20", "border": 1})
        fopening_qty = wb.add_format({"bold": True, "bg_color": "#c8e6c9", "font_color": "#1b5e20", "border": 1, "num_format": "#,##0.##", "align": "right"})
        fclosing = wb.add_format({"bold": True, "italic": True, "bg_color": "#a5d6a7", "font_color": "#1b5e20", "border": 1})
        fclosing_qty = wb.add_format({"bold": True, "bg_color": "#81c784", "font_color": "#1b5e20", "border": 1, "num_format": "#,##0.##", "align": "right", "font_size": 12})

        # Column widths
        ws.set_column(0, 0, 12)   # Ngay
        ws.set_column(1, 1, 20)   # So CT
        ws.set_column(2, 2, 20)   # So HD/Nguon
        ws.set_column(3, 3, 20)   # Dien giai
        ws.set_column(4, 4, 8)    # DVT
        ws.set_column(5, 5, 18)   # Don gia
        ws.set_column(6, 6, 12)   # Nhap SL
        ws.set_column(7, 7, 12)   # Xuat SL
        ws.set_column(8, 8, 12)   # Ton
        ws.set_column(9, 9, 14)   # Ma DT
        ws.set_column(10, 10, 28) # Ten DT

        # Title
        ws.set_row(0, 28)
        ws.set_row(1, 6)
        ws.merge_range(0, 0, 0, 10, "S\u1ed4 CHI TI\u1ebeT NH\u1eacP/XU\u1ea4T KHO", ftitle)
        ws.set_row(2, 18)
        ws.merge_range(2, 0, 2, 4,
            "S\u1ea3n ph\u1ea9m: %s [%s]" % (product.name, product.default_code or ""), finfo)
        ws.write(2, 5, "T\u1eeb: %s" % (data["date_from"] or ""), finfo)
        ws.write(2, 7, "\u0110\u1ebfn: %s" % (data["date_to"] or ""), finfo)

        # Header row
        ws.set_row(3, 22)
        for i, h in enumerate(["Ng\u00e0y", "S\u1ed1 ch\u1ee9ng t\u1eeb", "S\u1ed1 H\u0110/Ngu\u1ed3n",
                                "Di\u1ec5n gi\u1ea3i", "\u0110VT", "\u0110\u01a1n gi\u00e1",
                                "Nh\u1eadp SL", "Xu\u1ea5t SL", "T\u1ed3n",
                                "M\u00e3 \u0110T", "T\u00ean \u0111\u1ed1i t\u00e1c"]):
            ws.write(3, i, h, fh)

        row = 4

        # Opening
        ws.merge_range(row, 0, row, 7, "S\u1ed1 d\u01b0 \u0111\u1ea7u k\u1ef3", fopening)
        ws.write(row, 8, data["opening"], fopening_qty)
        ws.write(row, 9, "", fopening)
        ws.write(row, 10, "", fopening)
        row += 1

        # Move rows
        for mv in data["moves"]:
            label = ("\u2b07 NK " if mv["type"] == "in" else "\u2b06 XK ") + mv["reference"]
            ws.write(row, 0, mv["date"], fdate)
            ws.write(row, 1, label, fmono)
            ws.write(row, 2, mv["origin"], fmono)
            ws.write(row, 3, mv["description"], ft)
            ws.write(row, 4, mv["uom"], fuom)
            combo = mv.get("combo_info")
            if combo:
                combo_label = "Combo: %s" % (combo.get("code") or combo.get("name", ""))
                if combo.get("price"):
                    combo_label += " / %s\u20ab" % "{:,.0f}".format(combo["price"]).replace(",", ".")
                ws.write(row, 5, combo_label, fcombo)
            else:
                ws.write(row, 5, mv.get("price") or 0, fprice)
            if mv["in_qty"] > 0:
                ws.write(row, 6, mv["in_qty"], fqty_in)
                ws.write(row, 7, "", fempty)
            else:
                ws.write(row, 6, "", fempty)
                ws.write(row, 7, mv["out_qty"], fqty_out)
            bal = mv["balance"]
            ws.write(row, 8, bal, fqty_bal if bal >= 0 else fqty_neg)
            ws.write(row, 9, mv["partner_code"], fmono)
            ws.write(row, 10, mv["partner_name"], ft)
            row += 1

        # Closing
        ws.merge_range(row, 0, row, 7, "S\u1ed1 d\u01b0 cu\u1ed1i k\u1ef3", fclosing)
        ws.write(row, 8, data["closing"], fclosing_qty)
        ws.write(row, 9, "", fclosing)
        ws.write(row, 10, "", fclosing)

        wb.close()
        output.seek(0)

        pname = (product.default_code or product.name or "sp").replace("/", "-").replace(" ", "_")[:30]
        att = self.env["ir.attachment"].create({
            "name": "so_chi_tiet_%s.xlsx" % pname,
            "type": "binary",
            "datas": base64.b64encode(output.read()).decode(),
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "res_model": self._name,
            "res_id": 0,
        })
        return att.id
