from odoo import models, fields, _
import logging
import json
from datetime import datetime, timedelta, timezone  # ⬅️ NEW


_logger = logging.getLogger(__name__)

class MisaPOFetch(models.TransientModel):
    _name = "misa.po.fetch"
    _description = "MISA PO Fetch"
    date_from = fields.Date(string="Từ ngày", required=True)
    date_to = fields.Date(string="Đến ngày", required=True)

    def action_fetch_po(self):
        misa_utils = self.env['misa.api.utils']
        odoo_utils = self.env['odoo.utils']
        misa_config = self.env['misa.config']
        access_token = misa_utils._get_misa_token()

        date_from_utc = datetime.combine(self.date_from, datetime.min.time()) - timedelta(hours=7)
        date_to_utc = datetime.combine(self.date_to, datetime.max.time()) - timedelta(hours=7)

        headers = misa_config.get_default_headers(access_token)

        payload = {
            "filter": [
                {
                    "property": 3972,
                    "value": date_from_utc.isoformat() + "Z",
                    "operator": 10,
                    "operand": 1,
                    "data_type": 3
                },
                {
                    "property": 3972,
                    "value": date_to_utc.isoformat() + "Z",
                    "operator": 12,
                    "operand": 1,
                    "data_type": 3
                }
            ],
            "loadMode": 2,
            "pageIndex": 1,
            "pageSize": 20,
            "sort": "[{\"property\":3972,\"desc\":true,\"data_type\":3,\"operand\":1},{\"property\":4008,\"desc\":true,\"data_type\":1,\"operand\":1}]",
            "summaryColumns": [5039, 5104, 247],
            "useSp": False,
            "view": 2
        }
        stock_mapping = {
                "HCM": "TSN/Stock",
                "BENCAM": "KBC/Tồn kho",
                "HIENDUC": "KHD/Tồn kho",
                "HCM_SHOWROOM":"TSNSR/Stock"
            }


        page_index = 1
        while True:
            payload["pageIndex"] = page_index
            _logger.info("📄 Đang fetch trang %s...", page_index)
            
            response = misa_utils._fetch_with_retry(
                "https://actapp.misa.vn/g1/api/pu/v1/pu_list/paging_filter_v2",
                headers, payload
            )

            if response.status_code != 200:
                _logger.warning("❌ Gọi API thất bại ở trang %s", page_index)
                break

            page_data = response.json().get("Data", {}).get("PageData", [])
            if not page_data:
                _logger.info("✅ Hết dữ liệu, dừng ở trang %s", page_index)
                break

# ===============================
            for po in page_data:
                refid = po.get("refid")
                supplier_name = po.get("account_object_name")
                refno = po.get("refno", "PO-MISA")
                memo = po.get("journal_memo", "")
                
                receive_date_str = po.get("receive_date") or po.get("refdate")
                planned_dt_utc = None
                if receive_date_str:
                    try:
                        # "2025-08-26T00:00:00.000+07:00" -> aware -> UTC
                        planned_local = datetime.fromisoformat(receive_date_str)
                        planned_dt_utc = planned_local.astimezone(timezone.utc)  # ⬅️ NEW
                    except Exception as e:
                        _logger.warning("⚠️ Không parse được receive_date/refdate: %s (%s)", receive_date_str, e)


                partner = odoo_utils._get_or_create_partner(supplier_name)

                detail_page_index = 1
                all_detail_lines = []

                while True:
                    detail_payload = {
                        "columns": [2157, 1355, 2161, 4670, 5683, 5274, 3870, 3895, 5279, 308, 5364, 5350, 3404, 2358],
                        "filter": [
                            {
                                "property": 3993,
                                "operator": 7,
                                "operand": 1,
                                "value": refid,
                                "data_type": 10
                            }
                        ],
                        "loadMode": 2,
                        "pageIndex": detail_page_index,
                        "pageSize": 20,
                        "sort": "[{\"property\":4555,\"desc\":false,\"data_type\":4,\"operand\":1}]",
                        "summaryColumns": [3488, 3870, 3895, 3896, 308, 5350],
                        "useSp": False,
                        "view": 92
                    }

                    detail_res = misa_utils._fetch_with_retry(
                        "https://actapp.misa.vn/g1/api/pu/v1/pu_voucher/get_paging_detail",
                        headers, detail_payload
                    )

                    if detail_res.status_code != 200:
                        _logger.warning("Không lấy được chi tiết PO %s ở trang %s", refid, detail_page_index)
                        break

                    page_lines = detail_res.json().get("Data", {}).get("PageData", [])
                    if not page_lines:
                        break

                    all_detail_lines.extend(page_lines)
                    detail_page_index += 1

                # Sau khi loop hết các trang thì gán lại cho lines để xử lý như cũ
                lines = all_detail_lines


                # lines = detail_res.json().get("Data", {}).get("PageData", [])
                # stock_code = lines[0].get("stock_code", "").strip().upper() if lines else None
                stock_code = (
                    lines[0].get("stock_code", "").strip().replace(" ", "").upper()
                    if lines else None
)
                if stock_code not in stock_mapping:
                    _logger.warning("📛 Kho %s không nằm trong mapping, bỏ PO %s", stock_code, refno)
                    continue

                location_name = stock_mapping[stock_code]
                location = self.env['stock.location'].search([
                    ('complete_name', '=', location_name)
                ], limit=1)

                if not location:
                    _logger.warning("❌ Không tìm thấy stock.location cho kho %s (%s)", stock_code, location_name)
                    continue
                
                
                existing_po = self.env["purchase.order"].search([("name", "=", refno)], limit=1)
                if existing_po:
                    _logger.info("⚠️ Bỏ qua đơn hàng %s vì name %s đã tồn tại", refid, refno)
                    continue
                
                warehouse = self.env['stock.warehouse'].search([
                    ('view_location_id', '=', location.location_id.id)
                ], limit=1)

                if not warehouse:
                    _logger.warning("❌ Không tìm thấy warehouse cho kho %s", stock_code)
                    continue
                picking_type = warehouse.in_type_id
                
                po_vals = {
                    "partner_id": partner.id,
                    "origin": memo,
                    "picking_type_id": picking_type.id,
                    "name": refno,
                }
                
                if planned_dt_utc:
                    po_vals["date_planned"] = planned_dt_utc  # ⬅️ NEW (Receipt Date trên đầu đơn)

                po_rec = self.env["purchase.order"].create(po_vals)


                for line in lines:
                    code = line.get("inventory_item_code", "unknown_code").strip()
                    name = line.get("description", "unknown product").strip()
                    qty = float(line.get("quantity", 1))
                    price = float(line.get("unit_price", 0))
                    unit_name = line.get("unit_name", "Cái").strip()
                    vat_rate = float(line.get("vat_rate", 0))

                    product = odoo_utils._get_or_create_product(
                        code=code,
                        name=name,
                        unit_name=unit_name,
                        cost=price,
                        purchase_ok=True,
                        sale_ok=False
                    )
                    pol_vals = {
                        "order_id": po_rec.id,
                        "name": name,
                        "product_id": product.id,
                        "product_qty": qty,
                        "product_uom": product.uom_id.id,
                        "price_unit": price,
                    }
                    
                    if planned_dt_utc:
                        pol_vals["date_planned"] = planned_dt_utc

                    # self.env["purchase.order.line"].create({
                    #     "order_id": po_rec.id,
                    #     "name": name,
                    #     "product_id": product.id,
                    #     "product_qty": qty,
                    #     "product_uom": product.uom_id.id,
                    #     "price_unit": price
                    # })
                    
                    self.env["purchase.order.line"].create(pol_vals)
            page_index += 1