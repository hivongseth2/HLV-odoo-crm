from odoo import api, models
from odoo.exceptions import UserError
import base64
import io


class HlvStockQuick(models.TransientModel):
    _inherit = 'hlv.stock.quick'

    @api.model
    def export_all_moves_excel(self, group_id, warehouse_ids, date_from=None, date_to=None):
        import io
        try:
            import xlsxwriter
        except ImportError:
            raise UserError("xlsxwriter ch\u01b0a \u0111\u01b0\u1ee3c c\u00e0i \u0111\u1eb7t.")

        group = self.env["hlv.product.report.group"].browse(group_id)
        products = group.product_ids.sorted("name")
        if not products:
            raise UserError("Nh\u00f3m kh\u00f4ng c\u00f3 s\u1ea3n ph\u1ea9m n\u00e0o.")

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {"in_memory": True})

        # Shared formats
        ftitle    = wb.add_format({"bold": True, "font_size": 13, "align": "center", "valign": "vcenter", "font_color": "#1b5e20"})
        finfo     = wb.add_format({"font_size": 10, "italic": True, "font_color": "#546e7a"})
        fh        = wb.add_format({"bold": True, "bg_color": "#33691e", "font_color": "#fff", "border": 1, "align": "center", "valign": "vcenter", "font_size": 11})
        ft        = wb.add_format({"border": 1})
        fmono     = wb.add_format({"border": 1, "font_name": "Courier New", "font_size": 9, "font_color": "#1a2639"})
        fdate     = wb.add_format({"border": 1, "align": "center", "font_color": "#546e7a"})
        fuom      = wb.add_format({"border": 1, "align": "center", "font_color": "#6c757d"})
        fprice    = wb.add_format({"border": 1, "num_format": "#,##0", "align": "right", "font_color": "#5d4037"})
        fcombo    = wb.add_format({"border": 1, "align": "left", "font_color": "#e65100", "italic": True, "font_size": 10})
        fqty_in   = wb.add_format({"border": 1, "num_format": "#,##0.##", "align": "right", "font_color": "#1565c0", "bold": True})
        fqty_out  = wb.add_format({"border": 1, "num_format": "#,##0.##", "align": "right", "font_color": "#b71c1c", "bold": True})
        fqty_bal  = wb.add_format({"border": 1, "num_format": "#,##0.##", "align": "right", "font_color": "#1b5e20", "bold": True})
        fqty_neg  = wb.add_format({"border": 1, "num_format": "#,##0.##", "align": "right", "font_color": "#e53935", "bold": True})
        fempty    = wb.add_format({"border": 1})
        fopening  = wb.add_format({"bold": True, "italic": True, "bg_color": "#e8f5e9", "font_color": "#1b5e20", "border": 1})
        fopen_qty = wb.add_format({"bold": True, "bg_color": "#c8e6c9", "font_color": "#1b5e20", "border": 1, "num_format": "#,##0.##", "align": "right"})
        fclosing  = wb.add_format({"bold": True, "italic": True, "bg_color": "#a5d6a7", "font_color": "#1b5e20", "border": 1})
        fclose_qty= wb.add_format({"bold": True, "bg_color": "#81c784", "font_color": "#1b5e20", "border": 1, "num_format": "#,##0.##", "align": "right", "font_size": 12})
        HEADERS   = ["Ng\u00e0y", "S\u1ed1 ch\u1ee9ng t\u1eeb", "S\u1ed1 H\u0110/Ngu\u1ed3n",
                     "Di\u1ec5n gi\u1ea3i", "\u0110VT", "\u0110\u01a1n gi\u00e1",
                     "Nh\u1eadp SL", "Xu\u1ea5t SL", "T\u1ed3n",
                     "M\u00e3 \u0110T", "T\u00ean \u0111\u1ed1i t\u00e1c"]

        # Summary sheet (first sheet)
        ws_idx = wb.add_worksheet("T\u1ed5ng quan")
        ws_idx.set_column(0, 0, 8)
        ws_idx.set_column(1, 1, 18)
        ws_idx.set_column(2, 2, 40)
        ws_idx.set_column(3, 3, 10)
        ws_idx.set_column(4, 4, 12)
        ws_idx.set_column(5, 5, 12)
        ws_idx.set_column(6, 6, 12)
        ws_idx.set_row(0, 26)
        ws_idx.merge_range(0, 0, 0, 6, "S\u1ed4 CHI TI\u1ebeT NH\u1eacP/XU\u1ea4T KHO - %s" % group.name, ftitle)
        ws_idx.write(1, 0, "T\u1eeb: %s" % (date_from or ""), finfo)
        ws_idx.write(1, 2, "\u0110\u1ebfn: %s" % (date_to or ""), finfo)
        fhidx = wb.add_format({"bold": True, "bg_color": "#1a2639", "font_color": "#fff", "border": 1, "align": "center"})
        ftidx = wb.add_format({"border": 1, "num_format": "#,##0.##", "align": "right", "font_color": "#198754", "bold": True})
        ftidxb= wb.add_format({"border": 1, "align": "left"})
        ws_idx.set_row(2, 18)
        for i, h in enumerate(["#", "M\u00e3 SP", "T\u00ean s\u1ea3n ph\u1ea9m", "\u0110VT", "\u0110\u1ea7u k\u1ef3", "Ph\u00e1t sinh", "Cu\u1ed1i k\u1ef3"]):
            ws_idx.write(2, i, h, fhidx)

        idx_row = 3
        for seq, product in enumerate(products):
            def _write_product_sheet(prod, seq_no):
                data = self.get_product_moves(prod.id, warehouse_ids, date_from, date_to)
                sheet_name = ("%s" % (prod.default_code or prod.name or "SP%d" % seq_no))[:31]
                # Sanitize sheet name (Excel forbidden chars)
                for ch in [":", "\\", "/", "?", "*", "[", "]"]:
                    sheet_name = sheet_name.replace(ch, "_")
                ws = wb.add_worksheet(sheet_name)
                ws.set_column(0, 0, 12)
                ws.set_column(1, 1, 20)
                ws.set_column(2, 2, 20)
                ws.set_column(3, 3, 20)
                ws.set_column(4, 4, 8)
                ws.set_column(5, 5, 18)
                ws.set_column(6, 6, 12)
                ws.set_column(7, 7, 12)
                ws.set_column(8, 8, 12)
                ws.set_column(9, 9, 14)
                ws.set_column(10, 10, 28)
                ws.set_row(0, 26)
                ws.merge_range(0, 0, 0, 10,
                    "S\u1ed4 CHI TI\u1ebeT: %s [%s]" % (prod.name, prod.default_code or ""), ftitle)
                ws.write(1, 0, "T\u1eeb: %s" % (data["date_from"] or ""), finfo)
                ws.write(1, 4, "\u0110\u1ebfn: %s" % (data["date_to"] or ""), finfo)
                ws.set_row(2, 20)
                for ci, h in enumerate(HEADERS):
                    ws.write(2, ci, h, fh)
                r = 3
                ws.merge_range(r, 0, r, 7, "S\u1ed1 d\u01b0 \u0111\u1ea7u k\u1ef3", fopening)
                ws.write(r, 8, data["opening"], fopen_qty)
                ws.write(r, 9, "", fopening)
                ws.write(r, 10, "", fopening)
                r += 1
                net_in = 0.0
                net_out = 0.0
                for mv in data["moves"]:
                    label = ("\u2b07 NK " if mv["type"] == "in" else "\u2b06 XK ") + mv["reference"]
                    ws.write(r, 0, mv["date"], fdate)
                    ws.write(r, 1, label, fmono)
                    ws.write(r, 2, mv["origin"], fmono)
                    ws.write(r, 3, mv["description"], ft)
                    ws.write(r, 4, mv["uom"], fuom)
                    combo = mv.get("combo_info")
                    if combo:
                        combo_label = "Combo: %s" % (combo.get("code") or combo.get("name", ""))
                        if combo.get("price"):
                            combo_label += " / %s\u20ab" % "{:,.0f}".format(combo["price"]).replace(",", ".")
                        ws.write(r, 5, combo_label, fcombo)
                    else:
                        ws.write(r, 5, mv.get("price") or 0, fprice)
                    if mv["in_qty"] > 0:
                        ws.write(r, 6, mv["in_qty"], fqty_in)
                        ws.write(r, 7, "", fempty)
                        net_in += mv["in_qty"]
                    else:
                        ws.write(r, 6, "", fempty)
                        ws.write(r, 7, mv["out_qty"], fqty_out)
                        net_out += mv["out_qty"]
                    bal = mv["balance"]
                    ws.write(r, 8, bal, fqty_bal if bal >= 0 else fqty_neg)
                    ws.write(r, 9, mv["partner_code"], fmono)
                    ws.write(r, 10, mv["partner_name"], ft)
                    r += 1
                ws.merge_range(r, 0, r, 7, "S\u1ed1 d\u01b0 cu\u1ed1i k\u1ef3", fclosing)
                ws.write(r, 8, data["closing"], fclose_qty)
                ws.write(r, 9, "", fclosing)
                ws.write(r, 10, "", fclosing)
                return data["opening"], net_in + net_out, data["closing"]

            opening_val, total_moves, closing_val = _write_product_sheet(product, seq + 1)
            ws_idx.write(idx_row, 0, seq + 1, wb.add_format({"border": 1, "align": "center", "font_color": "#adb5bd"}))
            ws_idx.write(idx_row, 1, product.default_code or "", wb.add_format({"border": 1, "font_name": "Courier New", "font_size": 9}))
            ws_idx.write(idx_row, 2, product.name or "", ftidxb)
            ws_idx.write(idx_row, 3, product.uom_id.name if product.uom_id else "", wb.add_format({"border": 1, "align": "center"}))
            ws_idx.write(idx_row, 4, opening_val, ftidx)
            ws_idx.write(idx_row, 5, total_moves, ftidx)
            ws_idx.write(idx_row, 6, closing_val, ftidx)
            idx_row += 1

        wb.close()
        output.seek(0)
        fname = "so_chi_tiet_tat_ca_%s.xlsx" % (group.name or "nhom").replace(" ", "_")[:40]
        att = self.env["ir.attachment"].create({
            "name": fname,
            "type": "binary",
            "datas": base64.b64encode(output.read()).decode(),
            "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            "res_model": self._name,
            "res_id": 0,
        })
        return att.id
