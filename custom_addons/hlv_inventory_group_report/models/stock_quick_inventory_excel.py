from odoo import api, models
from odoo.exceptions import UserError
import base64
import io


class HlvStockQuick(models.TransientModel):
    _inherit = 'hlv.stock.quick'

    @api.model
    def export_excel(self, group_id, warehouse_ids, show_zero, include_outgoing=True, extra_cols=None):
        try:
            import xlsxwriter
        except ImportError:
            raise UserError("xlsxwriter chua duoc cai.")
        extra_cols = extra_cols or []
        data = self.get_data(group_id, warehouse_ids, show_zero, include_outgoing, extra_cols)
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
        n_extra = len(extra_cols)
        has_outgoing = include_outgoing and n > 0
        extra_col_start = (5 + n + (1 if has_outgoing else 0)) if n else 5
        if n_extra:
            last_col = extra_col_start + n_extra - 1
        elif n:
            last_col = 4 + n + (1 if has_outgoing else 0)
        else:
            last_col = 4
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
        for j in range(n_extra):
            ws.set_column(extra_col_start + j, extra_col_start + j, 18)
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
        _extra_labels = {
            "sale_price": "Gi\u00e1 b\u00e1n (ch\u01b0a VAT)",
            "price_web": "Gi\u00e1 Web",
            "price_listed": "Gi\u00e1 Ni\u00eam Y\u1ebft",
            "price_tmdt": "Gi\u00e1 S\u00e0n TM\u0110T",
            "price_commercial": "Gi\u00e1 Th\u01b0\u01a1ng M\u1ea1i",
            "purchase_price": "Gi\u00e1 mua",
            "sales_cycle": "Chu k\u1ef3 b\u00e1n (ng\u00e0y/\u0111\u01a1n)",
            "avg_cost": "Gi\u00e1 v\u1ed1n TB",
            "incoming_qty": "D\u1ef1 ki\u1ebfn nh\u1eadp",
            "reserved_qty": "D\u1ef1 ki\u1ebfn giao",
        }
        for j, ec in enumerate(extra_cols):
            ws.write(2, extra_col_start + j, _extra_labels.get(ec, ec), fh)
        f_money = wb.add_format({"border": 1, "num_format": "#,##0", "align": "right", "font_color": "#0d47a1"})
        f_cycle = wb.add_format({"border": 1, "num_format": "#,##0.0", "align": "right", "font_color": "#7b1fa2"})
        fl_extra = wb.add_format({"bg_color": "#e8f5e9", "border": 1})
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
            for j, ec in enumerate(extra_cols):
                val = line.get("extra", {}).get(ec)
                if val is None:
                    ws.write(row, extra_col_start + j, "-", ft)
                elif ec == "sales_cycle":
                    ws.write(row, extra_col_start + j, val, f_cycle)
                elif ec in ("incoming_qty", "reserved_qty"):
                    fq = wb.add_format({"border": 1, "num_format": "#,##0.##", "align": "right",
                                        "font_color": "#1565c0" if ec == "incoming_qty" else "#e65100", "bold": True})
                    ws.write(row, extra_col_start + j, val, fq if val > 0 else f0)
                    if ec == "incoming_qty":
                        pending = line.get("extra", {}).get("incoming_pending") or 0
                        on_hand_val = line.get("total", 0)
                        if pending > 0:
                            ws.write_comment(row, extra_col_start + j,
                                             "Tồn kho: %g + Chờ nhập: %g = %g" % (on_hand_val, pending, val))
                else:
                    ws.write(row, extra_col_start + j, val, f_money)
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
        for j in range(n_extra):
            ws.write(row, extra_col_start + j, "", fl_extra)
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
