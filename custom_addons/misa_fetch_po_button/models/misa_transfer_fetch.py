from odoo import models, fields, _
import logging
import json
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

class MisaTransferFetch(models.TransientModel):
    _name = "misa.transfer.fetch"
    _description = "MISA Internal Transfer Fetch"

    date_from = fields.Date(string="Từ ngày", required=True)
    date_to = fields.Date(string="Đến ngày", required=True)
    warehouse_id = fields.Many2one("stock.warehouse", string="Kho đại diện (HCM)", required=True)
    excel_hcm_keyword = fields.Char(string="Từ khóa HCM trong MISA", default="HCM", required=True)

    def action_fetch_transfers(self):
        misa_utils = self.env['misa.api.utils']
        odoo_utils = self.env['odoo.utils']
        misa_config = self.env['misa.config']
        access_token = misa_utils._get_misa_token()
        keyword = self.excel_hcm_keyword.strip().upper()

        # Hardcoded mapping
        stock_mapping = {
            "HCM": "TSN/Stock",
            "SHOWROOM161": "TSN/Showroom",
        }

        date_from_utc = datetime.combine(self.date_from, datetime.min.time()) - timedelta(hours=7)
        date_to_utc = datetime.combine(self.date_to, datetime.max.time()) - timedelta(hours=7)

        headers = misa_config.get_default_headers(access_token)

        payload = {
            "sort": "[{\"property\":3654,\"desc\":true,\"data_type\":3,\"operand\":1},{\"property\":3972,\"desc\":true,\"data_type\":3,\"operand\":1},{\"property\":4018,\"desc\":true,\"data_type\":1,\"operand\":1}]",
            "filter": [
                {"property": 4041, "value": "[2030,2031,2032]", "operator": 13, "data_type": 4, "operand": 1},
                {"property": 3654, "value": date_from_utc.isoformat() + "Z", "operator": 10, "data_type": 3, "operand": 1},
                {"property": 3654, "value": date_to_utc.isoformat() + "Z", "operator": 12, "data_type": 3, "operand": 1}
            ],
            "pageIndex": 1,
            "pageSize": 100,
            "useSp": False,
            "view": 62,
            "summaryColumns": [5042],
            "loadMode": 2
        }

        page_index = 1
        while True:
            payload["pageIndex"] = page_index
            _logger.info("\ud83d\udcc4 \u0110ang fetch trang %s...", page_index)

            response = misa_utils._fetch_with_retry(
                "https://actapp.misa.vn/g1/api/in/v1/in_inward_outward_list/paging_filter_v2",
                headers, payload
            )

            if response.status_code != 200:
                _logger.warning("\u274c G\u1ecdi API th\u1ea5t b\u1ea1i: %s", response.text)
                break

            page_data = response.json().get("Data", {}).get("PageData", [])
            if not page_data:
                _logger.info("\u2705 H\u1ebft d\u1eef li\u1ec7u")
                break

            ref_map = {item['refid']: {
                'refno_finance': item.get('refno_finance', ''),
                'contact_name': item.get('contact_name', '')
            } for item in page_data}

            for refid, ref_info in ref_map.items():
                detail_payload = {
                    "columns": [2157, 1355, 1867, 5030, 1195, 1065, 5687, 5690, 5274, 3870, 5283, 289, 2818, 2358],
                    "filter": [{"property": 3993, "operator": 7, "operand": 1, "value": refid, "data_type": 10}],
                    "sort": "[{\"property\":4555,\"desc\":false,\"data_type\":4,\"operand\":1}]",
                    "pageIndex": 1,
                    "pageSize": 100,
                    "useSp": False,
                    "view": 63,
                    "summaryColumns": [3488, 3870, 289],
                    "loadMode": 2
                }

                detail_res = misa_utils._fetch_with_retry(
                    "https://actapp.misa.vn/g1/api/in/v1/in_transfer/get_paging_detail",
                    headers, detail_payload
                )

                if detail_res.status_code != 200:
                    _logger.warning("Kh\u00f4ng l\u1ea5y \u0111\u01b0\u1ee3c chi ti\u1ebft: %s", refid)
                    continue

                lines = detail_res.json().get("Data", {}).get("PageData", [])
                if not lines:
                    continue

                related_lines = []
                for line in lines:
                    from_code = str(line.get("from_stock_code", "")).strip().upper()
                    to_code = str(line.get("to_stock_code", "")).strip().upper()

                    from_loc_name = stock_mapping.get(from_code)
                    to_loc_name = stock_mapping.get(to_code)
                    if not from_loc_name or not to_loc_name:
                        _logger.warning("\u26a0\ufe0f Kh\u00f4ng mapping: %s / %s", from_code, to_code)
                        continue

                    from_loc = self.env['stock.location'].search([('complete_name', '=', from_loc_name)], limit=1)
                    to_loc = self.env['stock.location'].search([('complete_name', '=', to_loc_name)], limit=1)
                    if not from_loc or not to_loc:
                        _logger.warning("\u26a0\ufe0f Kh\u00f4ng t\u00ecm th\u1ea5y location: %s / %s", from_loc_name, to_loc_name)
                        continue

                    direction = None
                    if from_code == keyword:
                        direction = "outgoing"
                    elif to_code == keyword:
                        direction = "incoming"

                    if not direction:
                        continue

                    line.update({
                        "direction": direction,
                        "location_id": from_loc.id,
                        "location_dest_id": to_loc.id
                    })
                    related_lines.append(line)

                if not related_lines:
                    continue

                picking_type = self._get_picking_type(related_lines[0]["direction"])
                if not picking_type:
                    continue

                partner = False
                if ref_info.get('contact_name'):
                    partner = odoo_utils._get_or_create_partner(ref_info['contact_name'])

                picking = self.env['stock.picking'].search([('name', '=', ref_info['refno_finance'])], limit=1)
                if not picking:
                    picking = self.env['stock.picking'].create({
                        'name': ref_info['refno_finance'],
                        'picking_type_id': picking_type.id,
                        'location_id': related_lines[0]['location_id'],
                        'location_dest_id': related_lines[0]['location_dest_id'],
                        'origin': ref_info['refno_finance'],
                        'partner_id': partner.id if partner else False,
                    })

                for line in related_lines:
                    product_code = str(line.get("inventory_item_code", "")).strip()
                    product_name = str(line.get("description", "")).strip()
                    uom_name = str(line.get("unit_name", "C\u00e1i")).strip()
                    qty = float(line.get("quantity", 0))
                    cost = float(line.get("unit_price_finance", 0) or 0)

                    if not product_code or not product_name or qty <= 0:
                        continue

                    product = odoo_utils._get_or_create_product(
                        code=product_code,
                        name=product_name,
                        unit_name=uom_name,
                        cost=cost,
                        product_type="consu",
                        purchase_ok=False,
                        sale_ok=False
                    )

                    self.env['stock.move'].create({
                        'name': product.name,
                        'product_id': product.id,
                        'product_uom_qty': qty,
                        'product_uom': product.uom_id.id,
                        'picking_id': picking.id,
                        'location_id': line['location_id'],
                        'location_dest_id': line['location_dest_id'],
                    })

            page_index += 1

    def _get_picking_type(self, direction):
        return self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('warehouse_id', '=', self.warehouse_id.id)
        ], limit=1)

