from odoo import api, fields, models
from odoo.exceptions import UserError


class HlvStockQuick(models.TransientModel):
    _inherit = 'hlv.stock.quick'

    @api.model
    def get_group_products(self, group_id, query="", offset=0, limit=50):
        domain = [("group_id", "=", group_id)]
        query = (query or "").strip()
        if query:
            domain += [
                "|",
                ("product_id.name", "ilike", query),
                ("product_id.default_code", "ilike", query),
            ]
        Line = self.env["hlv.product.report.group.line"]
        total = Line.search_count(domain)
        lines = Line.search(domain, offset=offset, limit=limit, order="created_at desc, id desc")
        items = []
        for line in lines:
            p = line.product_id
            items.append({
                "id": p.id,
                "line_id": line.id,
                "name": p.name,
                "code": p.default_code or "",
                "created_at": fields.Datetime.to_string(line.created_at) if line.created_at else "",
                "updated_at": fields.Datetime.to_string(line.updated_at) if line.updated_at else "",
                "image_url": "/web/image/product.product/%d/image_128" % p.id,
            })
        return {"items": items, "total": total}

    @api.model
    def search_products(self, query, group_id=False, offset=0, limit=50):
        existing_ids = []
        if group_id:
            existing_ids = self.env["hlv.product.report.group.line"].search([
                ("group_id", "=", group_id),
            ]).mapped("product_id").ids
        domain = [
            ("type", "in", ["consu", "product"]),
            "|",
            ("name", "ilike", query),
            ("default_code", "ilike", query),
            ("id", "not in", existing_ids),
        ]
        total = self.env["product.product"].search_count(domain)
        products = self.env["product.product"].search(domain, limit=limit, offset=offset, order="name")
        items = [{"id": p.id, "name": p.name, "code": p.default_code or "", "image_url": "/web/image/product.product/%d/image_128" % p.id} for p in products]
        return {"items": items, "total": total}

    @api.model
    def add_product_to_group(self, group_id, product_id):
        Line = self.env["hlv.product.report.group.line"]
        line = Line.search([
            ("group_id", "=", group_id),
            ("product_id", "=", product_id),
        ], limit=1)
        if not line:
            Line.create({"group_id": group_id, "product_id": product_id})
        return True

    @api.model
    def remove_product_from_group(self, group_id, product_id):
        lines = self.env["hlv.product.report.group.line"].search([
            ("group_id", "=", group_id),
            ("product_id", "=", product_id),
        ])
        lines.unlink()
        return True

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
        Line = self.env["hlv.product.report.group.line"]
        existing_ids = set(Line.search([
            ("group_id", "=", group_id),
        ]).mapped("product_id").ids)
        added, not_found, already_in = [], [], []
        for code in codes:
            product = self.env["product.product"].search([("default_code", "=", code)], limit=1)
            if not product:
                not_found.append(code)
            elif product.id in existing_ids:
                already_in.append({"code": code, "name": product.name})
            else:
                Line.create({"group_id": group_id, "product_id": product.id})
                existing_ids.add(product.id)
                added.append({"code": code, "name": product.name})
        return {"added": added, "not_found": not_found, "already_in": already_in, "total": len(codes)}
