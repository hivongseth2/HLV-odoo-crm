from odoo import models, fields, _
import logging
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

class MisaCronFetch(models.Model):
    _name = "misa.cron.fetch"
    _description = "MISA Cron Fetch"

    def _fetch_po_periodically(self):
        """Lấy PO từ MISA định kỳ mỗi phút."""
        misa_utils = self.env['misa.api.utils']
        odoo_utils = self.env['odoo.utils']
        misa_config = self.env['misa.config']
        access_token = misa_utils._get_misa_token()

        # Lấy dữ liệu từ ngày hôm qua đến hiện tại (có thể điều chỉnh khoảng thời gian)
        date_from = datetime.now() - timedelta(days=1)
        date_to = datetime.now()

        headers = misa_config.get_default_headers(access_token)

        payload = {
            "filter": [
                {
                    "property": 4658,
                    "value": 3,
                    "operator": 7,
                    "operand": 1,
                    "data_type": 4
                },
                {
                    "property": 3972,
                    "value": date_from.isoformat() + "Z",
                    "operator": 10,
                    "operand": 1,
                    "data_type": 3
                },
                {
                    "property": 3972,
                    "value": date_to.isoformat() + "Z",
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

        page_index = 1
        while True:
            payload["pageIndex"] = page_index
            _logger.info("📄 Đang fetch PO trang %s...", page_index)

            response = misa_utils._fetch_with_retry(
                "https://actapp.misa.vn/g1/api/pu/v1/pu_list/paging_filter_v2",
                headers, payload
            )

            if response.status_code != 200:
                _logger.warning("❌ Gọi API PO thất bại ở trang %s", page_index)
                break

            page_data = response.json().get("Data", {}).get("PageData", [])
            if not page_data:
                _logger.info("✅ Hết dữ liệu PO, dừng ở trang %s", page_index)
                break

            for po in page_data:
                refid = po.get("refid")
                supplier_name = po.get("account_object_name")
                refno = po.get("refno", "PO-MISA")
                memo = po.get("journal_memo", "")
                partner = odoo_utils._get_or_create_partner(supplier_name)
                misa_purchase_status = po.get("custom_field10", "")

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
                    "pageIndex": 1,
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
                    _logger.warning("Không lấy được chi tiết PO %s", refid)
                    continue

                lines = detail_res.json().get("Data", {}).get("PageData", [])
                has_hcm = any(line.get("stock_code", "").strip().upper() == "HCM" for line in lines)
                if not has_hcm:
                    _logger.info("❌ Bỏ qua đơn hàng %s vì không có dòng nào thuộc kho HCM", refid)
                    continue

                po_rec = self.env["purchase.order"].create({
                    "partner_id": partner.id,
                    "origin": refno,
                    "x_studio_misa_purchase_status": misa_purchase_status or False,
                })

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

                    self.env["purchase.order.line"].create({
                        "order_id": po_rec.id,
                        "name": name,
                        "product_id": product.id,
                        "product_qty": qty,
                        "product_uom": product.uom_id.id,
                        "price_unit": price
                    })
            page_index += 1

    def _fetch_transfer_periodically(self):
        """Lấy Internal Transfer từ MISA định kỳ mỗi phút."""
        misa_utils = self.env['misa.api.utils']
        odoo_utils = self.env['odoo.utils']
        misa_config = self.env['misa.config']
        access_token = misa_utils._get_misa_token()

        # Lấy dữ liệu từ ngày hôm qua đến hiện tại (có thể điều chỉnh)
        date_from = datetime.now() - timedelta(days=1)
        date_to = datetime.now()

        headers = misa_config.get_default_headers(access_token)

        payload = {
            "sort": "[{\"property\":3654,\"desc\":true,\"data_type\":3,\"operand\":1},{\"property\":3972,\"desc\":true,\"data_type\":3,\"operand\":1},{\"property\":4018,\"desc\":true,\"data_type\":1,\"operand\":1}]",
            "filter": [
                {"property": 4041, "value": "[2030,2031,2032]", "operator": 13, "data_type": 4, "operand": 1},
                {"property": 3654, "value": date_from.isoformat() + "Z", "operator": 10, "data_type": 3, "operand": 1},
                {"property": 3654, "value": date_to.isoformat() + "Z", "operator": 12, "data_type": 3, "operand": 1}
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
            _logger.info("📄 Đang fetch Transfer trang %s...", page_index)

            response = misa_utils._fetch_with_retry(
                "https://actapp.misa.vn/g1/api/in/v1/in_inward_outward_list/paging_filter_v2",
                headers, payload
            )

            if response.status_code != 200:
                _logger.warning("❌ Gọi API Transfer thất bại ở trang %s", page_index)
                break

            page_data = response.json().get("Data", {}).get("PageData", [])
            if not page_data:
                _logger.info("✅ Hết dữ liệu Transfer, dừng ở trang %s", page_index)
                break

            ref_map = {item['refid']: {
                'refno_finance': item.get('refno_finance', ''),
                'contact_name': item.get('contact_name', '')
            } for item in page_data}

            for refid, ref_info in ref_map.items():
                detail_payload = {
                    "columns": [2157, 1355, 1867, 5030, 1195, 1065, 5687, 5690, 5274, 3870, 5283, 289, 2818, 2358],
                    "filter": [
                        {"property": 3993, "operator": 7, "operand": 1, "value": refid, "data_type": 10}
                    ],
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
                    _logger.warning("Không lấy được chi tiết Transfer %s", refid)
                    continue

                lines = detail_res.json().get("Data", {}).get("PageData", [])
                if not lines:
                    _logger.info("Không có chi tiết cho Transfer %s", refid)
                    continue

                # Lấy kho mặc định (có thể điều chỉnh logic chọn kho)
                warehouse = self.env['stock.warehouse'].search([], limit=1)
                if not warehouse:
                    _logger.warning("Không tìm thấy kho mặc định")
                    continue

                keyword = "HCM"  # Có thể lấy từ cấu hình hoặc tham số
                direction = None
                from_code = str(lines[0].get("from_stock_code", "")).strip().upper()
                to_code = str(lines[0].get("to_stock_code", "")).strip().upper()

                if from_code == keyword:
                    direction = "outgoing"
                elif to_code == keyword:
                    direction = "incoming"
                else:
                    _logger.info("Bỏ qua Transfer %s không liên quan đến từ khóa %s", refid, keyword)
                    continue

                picking_type = self._get_picking_type(direction, warehouse)
                if not picking_type:
                    _logger.warning("Không tìm thấy picking type phù hợp cho kho %s", warehouse.name)
                    continue

                contact_name = ref_info.get('contact_name', '').strip()
                partner = odoo_utils._get_or_create_partner(contact_name) if contact_name else False

                picking = self.env['stock.picking'].create({
                    'picking_type_id': picking_type.id,
                    'location_id': picking_type.default_location_src_id.id,
                    'location_dest_id': picking_type.default_location_dest_id.id,
                    'origin': ref_info.get('refno_finance', ''),
                    'partner_id': partner.id if partner else False,
                })

                _logger.info("Tạo phiếu %s (%s): %s", direction, picking_type.code, ref_info.get('refno_finance'))

                for line in lines:
                    product_code = str(line.get("inventory_item_code", "")).strip()
                    product_name = str(line.get("description", "")).strip()
                    uom_name = str(line.get("unit_name", "Cái")).strip()
                    qty = float(line.get("quantity", 0))
                    cost = float(line.get("unit_price_finance", 0) or 0)

                    if not product_code or not product_name or qty <= 0:
                        _logger.warning("Bỏ qua dòng không hợp lệ: %s", line)
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
                        'name': product_name,
                        'product_id': product.id,
                        'product_uom_qty': qty,
                        'product_uom': product.uom_id.id,
                        'picking_id': picking.id,
                        'location_id': picking.location_id.id,
                        'location_dest_id': picking.location_dest_id.id,
                    })
                    _logger.info("  + Tạo dòng chuyển: %s x%s", product_code, qty)

            page_index += 1

    def _get_picking_type(self, direction, warehouse):
        if direction == "outgoing":
            return self.env['stock.picking.type'].search([
                ('code', '=', 'internal'),
                ('warehouse_id', '=', warehouse.id),
                ('sequence_code', 'ilike', 'PICK')
            ], limit=1)
        else:
            return self.env['stock.picking.type'].search([
                ('code', '=', 'incoming'),
                ('warehouse_id', '=', warehouse.id)
            ], limit=1)