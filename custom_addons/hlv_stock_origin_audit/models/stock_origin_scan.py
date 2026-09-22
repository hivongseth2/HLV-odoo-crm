"""Quét cả kho để tìm sẵn những chỗ "hàng ở đâu chui ra" trước khi có ai hỏi.

Trang điều tra (stock.origin.audit) trả lời cho *một* vị trí đã biết. Model này
làm chiều ngược lại: rà toàn kho bằng vài truy vấn gộp rẻ tiền, liệt kê các
trường hợp đáng ngờ, rồi đưa thẳng (sản phẩm, vị trí, lô) sang trang điều tra.

Mỗi luật là một hàm _rule_* trả về list dòng cùng một khuôn, nhờ vậy thêm luật
mới chỉ là viết thêm một hàm và khai vào RULES.
"""

from datetime import timedelta

from odoo import api, fields, models

from .stock_origin_utils import ANOMALY_META, SEVERITY_CODE, fmt_qty

# Số dòng tối đa mỗi luật trả về: quét ra 5.000 dòng thì không ai đọc, mà giao
# diện thì treo.
RULE_LIMIT = 60
QTY_EPS = 0.001
# Luật đối chiếu sổ sách phải gộp toàn bộ lịch sử move nên đắt hơn hẳn các luật
# còn lại -> chỉ chạy khi người dùng bật.
HEAVY_RULES = ("lech_so_sach",)


class StockOriginScan(models.AbstractModel):
    _name = "stock.origin.scan"
    _description = "Quét bất thường nguồn gốc tồn kho"

    RULES = (
        "ton_dong_trung_chuyen",
        "ton_am",
        "giu_cho_vuot_ton",
        "nhap_tu_dieu_chinh",
        "move_khong_phieu",
        "ngay_lui",
        "lech_so_sach",
    )

    # ------------------------------------------------------------------
    # phạm vi quét
    # ------------------------------------------------------------------
    def _scope_locations(self, warehouse_id):
        """Recordset vị trí trong phạm vi quét, hoặc None nghĩa là toàn công ty."""
        if not warehouse_id:
            return None
        warehouse = self.env["stock.warehouse"].browse(warehouse_id)
        # Dùng lại bộ lọc vị trí của hlv_stock_trace để hai module luôn hiểu
        # "các vị trí thuộc kho X" giống hệt nhau.
        return self.env["stock.trace"]._warehouse_location_ids(warehouse)

    def _loc_term(self, field, locations):
        if locations is None:
            return (f"{field}.usage", "in", ("internal", "transit"))
        return (field, "in", locations.ids)

    def _row(self, code, product, location, lot=None, qty=None, detail="",
             date_str="", reference="", picking_id=False, user=""):
        meta = ANOMALY_META.get(code, {"label": code, "severity": 2, "explain": ""})
        return {
            "code": code,
            "label": meta["label"],
            "severity": meta["severity"],
            "severity_code": SEVERITY_CODE.get(meta["severity"], "warn"),
            "explain": meta["explain"],
            "detail": detail,
            "product_id": product.id,
            "product_name": product.display_name,
            "location_id": location.id,
            "location_name": location.complete_name or location.display_name,
            "lot_id": lot.id if lot else False,
            "lot_name": lot.name if lot else "",
            "qty_text": fmt_qty(qty) if qty is not None else "",
            "date_str": date_str,
            "reference": reference,
            "picking_id": picking_id,
            "user": user,
        }

    def _fmt_dt(self, value):
        return self.env["stock.origin.audit"]._fmt_dt(value)

    # ------------------------------------------------------------------
    # các luật
    # ------------------------------------------------------------------
    def _rule_ton_dong_trung_chuyen(self, locations, since, stuck_days):
        staging = self.env["stock.origin.audit"].staging_location_map()
        staging_ids = list(staging)
        if locations is not None:
            staging_ids = [loc_id for loc_id in staging_ids if loc_id in set(locations.ids)]
        if not staging_ids:
            return []
        deadline = fields.Datetime.now() - timedelta(days=stuck_days)
        quants = self.env["stock.quant"].sudo().search([
            ("location_id", "in", staging_ids),
            ("quantity", ">", QTY_EPS),
            "|", ("in_date", "=", False), ("in_date", "<=", deadline),
        ], order="in_date asc", limit=RULE_LIMIT)
        rows = []
        for quant in quants:
            role = staging.get(quant.location_id.id) or {}
            age = self.env["stock.origin.audit"]._days_since(quant.in_date)
            rows.append(self._row(
                "ton_dong_trung_chuyen", quant.product_id, quant.location_id,
                lot=quant.lot_id, qty=quant.quantity,
                detail=f"Vị trí {role.get('role', '')} kho {role.get('warehouse', '')}, "
                       f"nằm đây {age if age is not None else '?'} ngày.",
                date_str=self._fmt_dt(quant.in_date),
            ))
        return rows

    def _rule_ton_am(self, locations, since, stuck_days):
        quants = self.env["stock.quant"].sudo().search([
            self._loc_term("location_id", locations),
            ("quantity", "<", -QTY_EPS),
        ], order="quantity asc", limit=RULE_LIMIT)
        return [
            self._row("ton_am", quant.product_id, quant.location_id, lot=quant.lot_id,
                      qty=quant.quantity, detail=f"Đang là {fmt_qty(quant.quantity)}.",
                      date_str=self._fmt_dt(quant.write_date))
            for quant in quants
        ]

    def _rule_giu_cho_vuot_ton(self, locations, since, stuck_days):
        quants = self.env["stock.quant"].sudo().search([
            self._loc_term("location_id", locations),
            ("reserved_quantity", ">", 0),
        ], limit=RULE_LIMIT * 20)
        rows = []
        for quant in quants:
            if quant.reserved_quantity - quant.quantity <= QTY_EPS:
                continue
            rows.append(self._row(
                "giu_cho_vuot_ton", quant.product_id, quant.location_id, lot=quant.lot_id,
                qty=quant.quantity,
                detail=f"Giữ chỗ {fmt_qty(quant.reserved_quantity)} trên tồn "
                       f"{fmt_qty(quant.quantity)}.",
                date_str=self._fmt_dt(quant.write_date),
            ))
            if len(rows) >= RULE_LIMIT:
                break
        return rows

    def _rule_nhap_tu_dieu_chinh(self, locations, since, stuck_days):
        lines = self.env["stock.move.line"].sudo().search([
            ("state", "=", "done"),
            ("date", ">=", since),
            ("move_id.is_inventory", "=", True),
            ("quantity", ">", QTY_EPS),
            self._loc_term("location_dest_id", locations),
        ], order="date desc, id desc", limit=RULE_LIMIT)
        return [
            self._row("nhap_tu_dieu_chinh", line.product_id, line.location_dest_id,
                      lot=line.lot_id, qty=line.quantity,
                      detail=f"Chỉnh tồn tăng {fmt_qty(line.quantity)}"
                             + (f", lý do ghi: {line.move_id.reference}"
                                if line.move_id.reference else "") + ".",
                      date_str=self._fmt_dt(line.date),
                      reference=line.reference or "", user=line.create_uid.name or "")
            for line in lines
        ]

    def _rule_move_khong_phieu(self, locations, since, stuck_days):
        lines = self.env["stock.move.line"].sudo().search([
            ("state", "=", "done"),
            ("date", ">=", since),
            ("picking_id", "=", False),
            ("move_id.is_inventory", "=", False),
            ("quantity", ">", QTY_EPS),
            self._loc_term("location_dest_id", locations),
        ], order="date desc, id desc", limit=RULE_LIMIT)
        return [
            self._row("move_khong_phieu", line.product_id, line.location_dest_id,
                      lot=line.lot_id, qty=line.quantity,
                      detail=f"Từ {line.location_id.complete_name} vào, không phiếu"
                             + (f", chứng từ gốc {line.move_id.origin}"
                                if line.move_id.origin else ", không chứng từ gốc") + ".",
                      date_str=self._fmt_dt(line.date),
                      reference=line.reference or "", user=line.create_uid.name or "")
            for line in lines
        ]

    def _rule_ngay_lui(self, locations, since, stuck_days):
        lines = self.env["stock.move.line"].sudo().search([
            ("state", "=", "done"),
            ("create_date", ">=", since),
            ("quantity", ">", QTY_EPS),
            self._loc_term("location_dest_id", locations),
        ], order="create_date desc, id desc", limit=RULE_LIMIT * 20)
        rows = []
        for line in lines:
            lag = self.env["stock.origin.audit"]._backdate_days(line)
            if not lag:
                continue
            rows.append(self._row(
                "ngay_lui", line.product_id, line.location_dest_id, lot=line.lot_id,
                qty=line.quantity,
                detail=f"Hiệu lực {self._fmt_dt(line.date)} nhưng {lag} ngày sau mới "
                       f"được tạo ({self._fmt_dt(line.create_date)}).",
                date_str=self._fmt_dt(line.date),
                reference=line.reference or "", picking_id=line.picking_id.id or False,
                user=line.create_uid.name or "",
            ))
            if len(rows) >= RULE_LIMIT:
                break
        return rows

    def _rule_lech_so_sach(self, locations, since, stuck_days):
        """Đối chiếu tồn thực với cộng dồn move của từng (sản phẩm, vị trí).

        Ba truy vấn gộp trên toàn bộ lịch sử: tồn hiện tại, tổng nhập, tổng
        xuất. Lệch nghĩa là có hàng vào/ra không đi qua move — đúng kiểu "cái áo
        mưa ở đâu chui ra".
        """
        trace = self.env["stock.trace"]
        loc_term = self._loc_term("location_id", locations)
        quant_rows = self.env["stock.quant"].sudo().read_group(
            [loc_term], ["product_id", "location_id", "quantity:sum"],
            ["product_id", "location_id"], lazy=False,
        )
        balances = {}
        for row in quant_rows:
            if not (row.get("product_id") and row.get("location_id")):
                continue
            key = (row["product_id"][0], row["location_id"][0])
            balances[key] = balances.get(key, 0.0) + trace._rg_num(row, "quantity")

        for field, sign in (("location_dest_id", 1.0), ("location_id", -1.0)):
            move_rows = self.env["stock.move.line"].sudo().read_group(
                [("state", "=", "done"), self._loc_term(field, locations)],
                ["product_id", field, "quantity:sum"],
                ["product_id", field], lazy=False,
            )
            for row in move_rows:
                if not (row.get("product_id") and row.get(field)):
                    continue
                key = (row["product_id"][0], row[field][0])
                moved = sign * trace._rg_num(row, "quantity")
                balances[key] = balances.get(key, 0.0) - moved

        rows = []
        for (product_id, location_id), gap in sorted(
            balances.items(), key=lambda item: -abs(item[1])
        ):
            if abs(gap) <= QTY_EPS:
                continue
            rows.append(self._row(
                "lech_so_sach",
                self.env["product.product"].browse(product_id),
                self.env["stock.location"].browse(location_id),
                qty=gap,
                detail=f"Tồn thực lệch {fmt_qty(gap)} so với cộng dồn move.",
            ))
            if len(rows) >= RULE_LIMIT:
                break
        return rows

    # ------------------------------------------------------------------
    # điểm vào cho giao diện
    # ------------------------------------------------------------------
    @api.model
    def get_scan_options(self):
        warehouses = self.env["stock.warehouse"].sudo().search([])
        return {
            "warehouses": [{"id": wh.id, "name": wh.name} for wh in warehouses],
            "rules": [
                {
                    "code": code,
                    "label": ANOMALY_META[code]["label"],
                    "explain": ANOMALY_META[code]["explain"],
                    "heavy": code in HEAVY_RULES,
                }
                for code in self.RULES
            ],
        }

    @api.model
    def scan(self, warehouse_id=None, days=60, stuck_days=7, rules=None):
        """Chạy các luật đã chọn trên phạm vi đã chọn.

        days: cửa sổ thời gian cho các luật soi move (các luật soi tồn hiện tại
        không dùng tới). rules: list mã luật, None = tất cả trừ luật nặng.
        """
        selected = list(rules) if rules else [c for c in self.RULES if c not in HEAVY_RULES]
        locations = self._scope_locations(warehouse_id)
        since = fields.Datetime.now() - timedelta(days=max(1, int(days or 60)))
        stuck_days = max(0, int(stuck_days or 0))

        findings = []
        counts = {}
        for code in self.RULES:
            if code not in selected:
                continue
            rule = getattr(self, f"_rule_{code}", None)
            if not rule:
                continue
            rows = rule(locations, since, stuck_days)
            counts[code] = len(rows)
            findings += rows

        findings.sort(key=lambda row: (-row["severity"], row["code"], row["product_name"]))
        warehouse = self.env["stock.warehouse"].browse(warehouse_id) if warehouse_id else None
        return {
            "scope_label": warehouse.name if warehouse else "Toàn công ty",
            "days": days,
            "stuck_days": stuck_days,
            "counts": counts,
            "findings": findings,
            "rule_limit": RULE_LIMIT,
            "generated_str": self._fmt_dt(fields.Datetime.now()),
        }
