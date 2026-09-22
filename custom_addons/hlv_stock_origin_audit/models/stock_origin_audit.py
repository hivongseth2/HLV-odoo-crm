"""Điều tra: một lượng hàng đang nằm ở một vị trí thì từ đâu mà có.

Khác với hlv_stock_trace (theo dõi *số dư* theo thời gian), module này chạy ở
mức stock.move.line và trả lời câu hỏi pháp y: đúng cái 1 Cái đang nằm ở
TSN/Khu vực đóng gói này vào kho bằng đường nào, ai làm, phiếu nào, và truy
ngược lên tới tận nguồn ngoài kho (nhà cung cấp / khách trả / kiểm kho).
"""

from datetime import timedelta

from odoo import api, fields, models

from .stock_origin_fifo import attribute_fifo, split_proportionally
from .stock_origin_utils import (
    SEV_ALERT,
    SEV_INFO,
    SEV_WARN,
    SEVERITY_CODE,
    anomaly,
    build_verdict,
    classify_source,
    fmt_qty,
    worst_severity,
)

# Truy ngược sâu hơn mức này gần như luôn là hàng đi qua lại giữa các vị trí
# nội bộ, không thêm thông tin gì cho người điều tra.
MAX_DEPTH = 6
# Trần số node để một sản phẩm luân chuyển dày đặc không treo giao diện.
MAX_NODES = 250
# Số dòng sổ cái trả về cho giao diện (mới nhất trước).
LEDGER_LIMIT = 80
# Ngưỡng coi là "ghi lùi ngày": lệch hơn 1 ngày giữa ngày hiệu lực và ngày tạo.
BACKDATE_DAYS = 1
# Ngưỡng mặc định coi hàng là tồn đọng ở vị trí trung chuyển.
STUCK_DAYS = 7

QTY_EPS = 0.001


class StockOriginAudit(models.AbstractModel):
    _name = "stock.origin.audit"
    _description = "Điều tra nguồn gốc tồn kho"

    # ------------------------------------------------------------------
    # hạ tầng dùng chung
    # ------------------------------------------------------------------
    def _fmt_dt(self, value, fmt="%d/%m/%Y %H:%M"):
        # Dùng lại bộ đổi múi giờ của hlv_stock_trace: cùng một quy ước hiển
        # thị giờ VN, không dựng lại lần hai.
        return self.env["stock.trace"]._utc_to_local_str(value, fmt=fmt)

    def _days_since(self, value):
        if not value:
            return None
        return max(0, (fields.Datetime.now() - value).days)

    @api.model
    def staging_location_map(self):
        """{location_id: {"warehouse", "role"}} cho các vị trí chỉ để hàng đi ngang.

        Lấy từ cấu hình kho (Input / QC / Đóng gói / Output) chứ không dò theo
        tên vị trí: tên do người dùng đặt, đổi lúc nào không biết, còn field
        cấu hình thì luôn đúng với luồng mà Odoo thực sự chạy.
        """
        roles = [
            ("wh_input_stock_loc_id", "Nhận hàng"),
            ("wh_qc_stock_loc_id", "Kiểm hàng"),
            ("wh_pack_stock_loc_id", "Đóng gói"),
            ("wh_output_stock_loc_id", "Xuất hàng"),
        ]
        result = {}
        for warehouse in self.env["stock.warehouse"].sudo().search([]):
            for field_name, role in roles:
                location = warehouse[field_name]
                if location:
                    result[location.id] = {"warehouse": warehouse.name, "role": role}
        return result

    # ------------------------------------------------------------------
    # sổ cái một vị trí
    # ------------------------------------------------------------------
    def _event_from_line(self, line, signed_qty, staging):
        source = line.location_id
        dest = line.location_dest_id
        move = line.move_id
        return {
            "key": line.id,
            "qty": signed_qty,
            "abs_qty": abs(signed_qty),
            "date": line.date,
            "date_str": self._fmt_dt(line.date),
            "created_str": self._fmt_dt(line.create_date),
            "age_days": self._days_since(line.date),
            "reference": line.reference or move.reference or "",
            "origin": move.origin or "",
            "picking_id": line.picking_id.id or False,
            "picking_name": line.picking_id.name or "",
            "move_id": move.id or False,
            "src_id": source.id,
            "src_name": source.complete_name or source.display_name,
            "src_usage": source.usage,
            "dest_id": dest.id,
            "dest_name": dest.complete_name or dest.display_name,
            "dest_usage": dest.usage,
            "is_inventory": bool(move.is_inventory),
            "is_scrap_src": bool(source.scrap_location),
            "staging_role": (staging.get(dest.id) or {}).get("role", ""),
            "lot_name": line.lot_id.name or "",
            "user": line.create_uid.name or "",
            "partner": line.picking_id.partner_id.display_name or "",
            "backdated_days": self._backdate_days(line),
        }

    def _backdate_days(self, line):
        """Số ngày move được ghi lùi so với lúc nó được tạo (0 nếu không lùi)."""
        if not line.date or not line.create_date:
            return 0
        delta = (line.create_date - line.date).days
        return delta if delta > BACKDATE_DAYS else 0

    def _ledger(self, product_id, location_id, lot_id, cache):
        """Sổ cái + kết quả khớp FIFO của (sản phẩm, vị trí[, lô]), có cache.

        Cache theo (location_id, lot_id) vì truy ngược nhiều nhánh rất hay đi
        lại đúng một vị trí nguồn; không cache thì mỗi nhánh lại quét lại toàn
        bộ move line của vị trí đó.
        """
        cache_key = (location_id, lot_id or False)
        if cache_key in cache:
            return cache[cache_key]

        domain = [
            ("state", "=", "done"),
            ("product_id", "=", product_id),
            "|",
            ("location_id", "=", location_id),
            ("location_dest_id", "=", location_id),
        ]
        if lot_id:
            domain.append(("lot_id", "=", lot_id))
        lines = self.env["stock.move.line"].sudo().search(domain, order="date asc, id asc")

        staging = cache.setdefault("__staging__", self.staging_location_map())
        events = []
        for line in lines:
            qty = float(line.quantity or 0.0)
            if qty <= 0:
                continue
            incoming = line.location_dest_id.id == location_id
            outgoing = line.location_id.id == location_id
            if incoming and outgoing:
                # Xê dịch ngay trong vị trí đó (đổi lô, đổi kiện): tồn không đổi.
                continue
            events.append(self._event_from_line(line, qty if incoming else -qty, staging))

        result = {
            "events": events,
            "by_key": {event["key"]: event for event in events},
            "fifo": attribute_fifo(events),
        }
        cache[cache_key] = result
        return result

    def _quant_state(self, product_id, location_id, lot_id):
        domain = [("product_id", "=", product_id), ("location_id", "=", location_id)]
        if lot_id:
            domain.append(("lot_id", "=", lot_id))
        quants = self.env["stock.quant"].sudo().search(domain)
        in_dates = [d for d in quants.mapped("in_date") if d]
        quantity = sum(quants.mapped("quantity"))
        reserved = sum(quants.mapped("reserved_quantity"))
        return {
            "quantity": quantity,
            "quantity_text": fmt_qty(quantity),
            "reserved": reserved,
            "reserved_text": fmt_qty(reserved),
            "in_date_str": self._fmt_dt(min(in_dates)) if in_dates else "",
            "in_age_days": self._days_since(min(in_dates)) if in_dates else None,
        }

    # ------------------------------------------------------------------
    # cây nguồn gốc
    # ------------------------------------------------------------------
    def _origin_node(self, product_id, event, qty, lot_id, cache, depth, visited, budget):
        """Một mắt xích nguồn gốc, kèm các mắt xích cha nếu còn truy ngược được."""
        kind = classify_source(
            event["src_usage"],
            is_inventory=event["is_inventory"],
            is_scrap=event["is_scrap_src"],
            has_picking=bool(event["picking_id"]),
            has_origin=bool(event["origin"]),
        )
        node = {
            "qty": qty,
            "qty_text": fmt_qty(qty),
            "code": kind["code"],
            "label": kind["label"],
            "severity": kind["severity"],
            "severity_code": SEVERITY_CODE.get(kind["severity"], "ok"),
            "notes": list(kind["notes"]),
            "date_str": event["date_str"],
            "age_days": event["age_days"],
            "reference": event["reference"],
            "origin_doc": event["origin"],
            "picking_id": event["picking_id"],
            "picking_name": event["picking_name"],
            "move_id": event["move_id"],
            "src_id": event["src_id"],
            "src_name": event["src_name"],
            "dest_name": event["dest_name"],
            "user": event["user"],
            "partner": event["partner"],
            "lot_name": event["lot_name"],
            "backdated_days": event["backdated_days"],
            "children": [],
            "dead_end": False,
        }
        if event["backdated_days"]:
            node["notes"].append(
                f"Ghi lùi {event['backdated_days']} ngày (tạo lúc {event['created_str']})"
            )

        step = (event["src_id"], event["key"])
        if not kind["recurse"] or depth <= 0 or step in visited or budget["left"] <= 0:
            if kind["recurse"] and depth <= 0:
                node["notes"].append("Dừng truy ngược: đã đủ sâu")
            return node

        parent_ledger = self._ledger(product_id, event["src_id"], lot_id, cache)
        parents = parent_ledger["fifo"]["sources"].get(event["key"], [])
        if not parents and lot_id:
            # Lô hay được gán hoặc đổi ngay tại move nhập, nên sổ cái đã lọc
            # theo lô không nhìn thấy lượt xuất tương ứng ở vị trí nguồn. Thử
            # lại không lọc lô trước khi kết luận là đứt chuỗi.
            parent_ledger = self._ledger(product_id, event["src_id"], False, cache)
            parents = parent_ledger["fifo"]["sources"].get(event["key"], [])
        if not parents:
            # Hàng rời vị trí nguồn mà ở đó chưa từng ghi nhận nhập: chuỗi đứt.
            node["dead_end"] = True
            node["severity"] = max(node["severity"], SEV_ALERT)
            node["severity_code"] = SEVERITY_CODE[node["severity"]]
            node["notes"].append(f"Không tìm được lượt nhập nào tại {event['src_name']}")
            return node

        shares = split_proportionally(parents, qty)
        next_visited = visited | {step}
        for parent, share in zip(parents, shares):
            if share <= QTY_EPS or budget["left"] <= 0:
                continue
            parent_event = parent_ledger["by_key"].get(parent["key"])
            if not parent_event:
                continue
            budget["left"] -= 1
            node["children"].append(self._origin_node(
                product_id, parent_event, share, lot_id, cache,
                depth - 1, next_visited, budget,
            ))
        return node

    def _collect_nodes(self, nodes):
        """Duyệt phẳng cây nguồn gốc (để soi bất thường trên toàn cây)."""
        stack = list(nodes)
        flat = []
        while stack:
            node = stack.pop()
            flat.append(node)
            stack.extend(node.get("children") or [])
        return flat

    # ------------------------------------------------------------------
    # bất thường của một vị trí
    # ------------------------------------------------------------------
    def _investigation_anomalies(self, ledger, quant, location, origins, stuck_days):
        found = []
        balance = ledger["fifo"]["balance"]
        gap = quant["quantity"] - balance
        if abs(gap) > QTY_EPS:
            found.append(anomaly(
                "lech_so_sach",
                f"Tồn thực {fmt_qty(quant['quantity'])} nhưng cộng dồn move ra "
                f"{fmt_qty(balance)} (lệch {fmt_qty(gap)}).",
            ))

        shortfalls = ledger["fifo"]["shortfalls"]
        if shortfalls:
            total = sum(item["qty"] for item in shortfalls)
            found.append(anomaly(
                "xuat_khong_nguon",
                f"{len(shortfalls)} lượt xuất thiếu nguồn, tổng {fmt_qty(total)}.",
            ))

        if quant["quantity"] < -QTY_EPS:
            found.append(anomaly("ton_am", f"Đang là {fmt_qty(quant['quantity'])}."))

        if quant["reserved"] - quant["quantity"] > QTY_EPS:
            found.append(anomaly(
                "giu_cho_vuot_ton",
                f"Giữ chỗ {fmt_qty(quant['reserved'])} trên tồn "
                f"{fmt_qty(quant['quantity'])}.",
            ))

        staging = self.staging_location_map().get(location.id)
        oldest = max([node["age_days"] or 0 for node in origins], default=0)
        if staging and quant["quantity"] > QTY_EPS and oldest >= stuck_days:
            found.append(anomaly(
                "ton_dong_trung_chuyen",
                f"Vị trí {staging['role']} của kho {staging['warehouse']}, "
                f"hàng nằm đây {oldest} ngày.",
            ))

        for node in self._collect_nodes(origins):
            if node["code"] == "dieu_chinh":
                found.append(anomaly(
                    "nhap_tu_dieu_chinh",
                    f"{node['qty_text']} vào kho ngày {node['date_str']} qua "
                    f"{node['reference'] or 'điều chỉnh không tên'}"
                    + (f" do {node['user']}" if node["user"] else "") + ".",
                ))
            if node["dead_end"]:
                found.append(anomaly(
                    "mat_dau_vet",
                    f"Đứt chuỗi tại {node['src_name']} ngày {node['date_str']}.",
                ))
            if node["backdated_days"]:
                found.append(anomaly(
                    "ngay_lui",
                    f"{node['reference'] or 'Move'} hiệu lực {node['date_str']} "
                    f"nhưng {node['backdated_days']} ngày sau mới được tạo.",
                ))
            if not node["picking_id"] and not node["origin_doc"] and node["code"] != "dieu_chinh":
                found.append(anomaly(
                    "move_khong_phieu",
                    f"{node['qty_text']} ngày {node['date_str']} từ {node['src_name']}"
                    + (f" do {node['user']}" if node["user"] else "") + ".",
                ))
        return found

    # ------------------------------------------------------------------
    # điểm vào cho giao diện
    # ------------------------------------------------------------------
    @api.model
    def investigate(self, product_id, location_id, lot_id=None, max_depth=MAX_DEPTH,
                    stuck_days=STUCK_DAYS):
        """Kết quả điều tra đầy đủ cho một (sản phẩm, vị trí[, lô])."""
        product = self.env["product.product"].browse(product_id)
        location = self.env["stock.location"].browse(location_id)
        lot = self.env["stock.lot"].browse(lot_id) if lot_id else None

        cache = {}
        ledger = self._ledger(product_id, location_id, lot_id or False, cache)
        quant = self._quant_state(product_id, location_id, lot_id or False)

        budget = {"left": MAX_NODES}
        origins = []
        for layer in ledger["fifo"]["remaining"]:
            event = ledger["by_key"].get(layer["key"])
            if not event:
                continue
            budget["left"] -= 1
            origins.append(self._origin_node(
                product_id, event, layer["qty_left"], lot_id or False,
                cache, max_depth, set(), budget,
            ))
        origins.sort(key=lambda node: node["qty"], reverse=True)

        traced = sum(node["qty"] for node in origins)
        unexplained = max(0.0, quant["quantity"] - traced)
        anomalies = self._investigation_anomalies(
            ledger, quant, location, origins, stuck_days,
        )
        severity = max(
            worst_severity(anomalies),
            worst_severity(self._collect_nodes(origins)),
        )
        staging = self.staging_location_map().get(location.id) or {}

        return {
            "product": {
                "id": product.id,
                "name": product.display_name,
                "uom": product.uom_id.name or "",
            },
            "location": {
                "id": location.id,
                "name": location.complete_name or location.display_name,
                "usage": location.usage,
                "role": staging.get("role", ""),
                "warehouse": staging.get("warehouse", ""),
            },
            "lot": {"id": lot.id, "name": lot.name} if lot else None,
            "quant": quant,
            "ledger_balance": ledger["fifo"]["balance"],
            "event_count": len(ledger["events"]),
            "origins": origins,
            "traced": traced,
            "traced_text": fmt_qty(traced),
            "unexplained": unexplained,
            "unexplained_text": fmt_qty(unexplained),
            "anomalies": anomalies,
            "severity": severity,
            "severity_code": SEVERITY_CODE.get(severity, "ok"),
            "verdict": build_verdict(
                origins, anomalies, unexplained,
                fmt_qty(quant["quantity"]), product.uom_id.name or "",
            ),
            "ledger": self._ledger_rows(ledger),
        }

    def _ledger_rows(self, ledger):
        """LEDGER_LIMIT dòng sổ cái gần nhất, kèm số dư lũy kế tại từng dòng."""
        rows = []
        balance = 0.0
        for event in ledger["events"]:
            balance += event["qty"]
            rows.append({
                "date_str": event["date_str"],
                "qty_text": fmt_qty(abs(event["qty"])),
                "direction": "in" if event["qty"] > 0 else "out",
                "balance_text": fmt_qty(balance),
                "counterpart": event["src_name"] if event["qty"] > 0 else event["dest_name"],
                "reference": event["reference"],
                "origin_doc": event["origin"],
                "picking_id": event["picking_id"],
                "user": event["user"],
                "lot_name": event["lot_name"],
                "is_inventory": event["is_inventory"],
            })
        rows.reverse()
        return rows[:LEDGER_LIMIT]

    @api.model
    def get_product_overview(self, product_id):
        """Mọi vị trí đang giữ hàng của sản phẩm, kèm cờ nhanh để chọn chỗ soi.

        Cố ý *không* chạy FIFO ở đây: màn hình này chỉ để chọn vị trí, chạy FIFO
        cho mọi vị trí sẽ chậm mà phần lớn kết quả không ai mở ra xem.
        """
        product = self.env["product.product"].browse(product_id)
        quants = self.env["stock.quant"].sudo().search([
            ("product_id", "=", product_id),
            ("location_id.usage", "in", ("internal", "transit")),
        ])
        staging = self.staging_location_map()
        rows = []
        for quant in quants:
            if abs(quant.quantity) <= QTY_EPS and abs(quant.reserved_quantity) <= QTY_EPS:
                continue
            role = staging.get(quant.location_id.id) or {}
            age = self._days_since(quant.in_date)
            flags = []
            if role:
                flags.append(f"Vị trí {role['role']}")
            if quant.quantity < -QTY_EPS:
                flags.append("Tồn âm")
            if quant.reserved_quantity - quant.quantity > QTY_EPS:
                flags.append("Giữ chỗ vượt tồn")
            if role and age is not None and age >= STUCK_DAYS:
                flags.append(f"Nằm đây {age} ngày")
            if quant.quantity < -QTY_EPS:
                severity = SEV_ALERT
            elif len(flags) > 1:
                severity = SEV_WARN
            elif flags:
                severity = SEV_INFO
            else:
                severity = 0
            rows.append({
                "location_id": quant.location_id.id,
                "location_name": quant.location_id.complete_name or quant.location_id.display_name,
                "lot_id": quant.lot_id.id or False,
                "lot_name": quant.lot_id.name or "",
                "quantity": quant.quantity,
                "quantity_text": fmt_qty(quant.quantity),
                "reserved_text": fmt_qty(quant.reserved_quantity),
                "in_date_str": self._fmt_dt(quant.in_date),
                "age_days": age,
                "role": role.get("role", ""),
                "flags": flags,
                "severity": severity,
                "severity_code": SEVERITY_CODE.get(severity, "ok"),
            })
        rows.sort(key=lambda row: (-row["severity"], -abs(row["quantity"])))
        return {
            "product": {
                "id": product.id,
                "name": product.display_name,
                "uom": product.uom_id.name or "",
            },
            "total_text": fmt_qty(sum(row["quantity"] for row in rows)),
            "rows": rows,
        }

    @api.model
    def search_products(self, term, limit=12):
        """Gợi ý sản phẩm cho ô tìm kiếm. Biên: term rỗng -> []."""
        if not (term or "").strip():
            return []
        found = self.env["product.product"].name_search(term.strip(), limit=limit)
        return [{"id": product_id, "name": name} for product_id, name in found]

    @api.model
    def recent_incoming_moves(self, product_id, days=30, limit=40):
        """Mọi lượt hàng từ ngoài vào kho gần đây của sản phẩm, để soi bằng mắt.

        Dùng khi tồn đã bị xuất hết nên FIFO không còn lớp nào để truy: vẫn phải
        cho người điều tra thấy hàng đã vào bằng những đường nào.
        """
        since = fields.Datetime.now() - timedelta(days=days)
        lines = self.env["stock.move.line"].sudo().search([
            ("state", "=", "done"),
            ("product_id", "=", product_id),
            ("date", ">=", since),
            ("location_id.usage", "not in", ("internal", "transit")),
            ("location_dest_id.usage", "in", ("internal", "transit")),
        ], order="date desc, id desc", limit=limit)
        staging = self.staging_location_map()
        rows = []
        for line in lines:
            event = self._event_from_line(line, float(line.quantity or 0.0), staging)
            kind = classify_source(
                event["src_usage"], event["is_inventory"], event["is_scrap_src"],
                bool(event["picking_id"]), bool(event["origin"]),
            )
            rows.append({
                "date_str": event["date_str"],
                "qty_text": fmt_qty(event["abs_qty"]),
                "label": kind["label"],
                "severity_code": SEVERITY_CODE.get(kind["severity"], "ok"),
                "src_name": event["src_name"],
                "dest_name": event["dest_name"],
                "reference": event["reference"],
                "origin_doc": event["origin"],
                "picking_id": event["picking_id"],
                "user": event["user"],
                "partner": event["partner"],
            })
        return rows
