from odoo import models, fields, _
import logging
import json
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)

class MisaTransferFetch(models.TransientModel):
    _name = "misa.transfer.fetch"
    _description = "MISA Internal Transfer Fetch"

    date_from = fields.Date(string="Từ ngày", required=True)
    date_to   = fields.Date(string="Đến ngày", required=True)

    def action_fetch_transfers(self):
        misa_utils  = self.env['misa.api.utils']
        odoo_utils  = self.env['odoo.utils']
        misa_config = self.env['misa.config']

        access_token = misa_utils._get_misa_token()

        # MISA lưu UTC, hệ thống dùng Asia/Ho_Chi_Minh (+7)
        date_from_utc = datetime.combine(self.date_from, datetime.min.time()) - timedelta(hours=7)
        date_to_utc   = datetime.combine(self.date_to,   datetime.max.time()) - timedelta(hours=7)

        headers = misa_config.get_default_headers(access_token)

        # Map code MISA -> đường dẫn complete_name của stock.location trong Odoo
        stock_mapping = {
            "HCM":        "TSN/Stock",
            "SHOWROOM161":"TSN/showroom",
            "BENCAM":     "KBC/Tồn kho",
            "HIENDUC":    "KHD/Tồn kho",
        }
        default_location_path = "Partners/Vendors"  # fallback (ít dùng)

        payload = {
            "sort": "[{\"property\":3654,\"desc\":true,\"data_type\":3,\"operand\":1},"
                    "{\"property\":3972,\"desc\":true,\"data_type\":3,\"operand\":1},"
                    "{\"property\":4018,\"desc\":true,\"data_type\":1,\"operand\":1}]",
            "filter": [
                {"property": 4041, "value": "[2030,2031,2032]", "operator": 13, "data_type": 4, "operand": 1},
                {"property": 3654, "value": date_from_utc.isoformat() + "Z", "operator": 10, "data_type": 3, "operand": 1},
                {"property": 3654, "value": date_to_utc.isoformat()   + "Z", "operator": 12, "data_type": 3, "operand": 1},
            ],
            "pageIndex": 1,
            "pageSize": 100,
            "useSp": False,
            "view": 62,
            "summaryColumns": [5042],
            "loadMode": 2,
        }

        page_index = 1
        while True:
            payload["pageIndex"] = page_index
            _logger.info("📄 Đang fetch trang %s...", page_index)

            response = misa_utils._fetch_with_retry(
                "https://actapp.misa.vn/g1/api/in/v1/in_inward_outward_list/paging_filter_v2",
                headers, payload
            )

            _logger.warning("warning: %s", getattr(response, "text", ""))
            _logger.info("status %s", getattr(response, "status_code", "NA"))

            if response.status_code != 200:
                _logger.info("response: %s", response.text)
                _logger.warning("❌ Gọi API thất bại ở trang %s", page_index)
                break

            page_data = response.json().get("Data", {}).get("PageData", [])
            if not page_data:
                _logger.info("✅ Hết dữ liệu, dừng ở trang %s", page_index)
                break

            ref_map = {
                item['refid']: {
                    'refno_finance': item.get('refno_finance', ''),
                    'contact_name': item.get('contact_name', '').strip(),
                }
                for item in page_data
            }

            for refid, ref_info in ref_map.items():
                # Lấy chi tiết chứng từ
                detail_payload = {
                    "columns": [2157, 1355, 1867, 5030, 1195, 1065, 5687, 5690, 5274, 3870, 5283, 289, 2818, 2358],
                    "filter": [{"property": 3993, "operator": 7, "operand": 1, "value": refid, "data_type": 10}],
                    "sort": "[{\"property\":4555,\"desc\":false,\"data_type\":4,\"operand\":1}]",
                    "pageIndex": 1,
                    "pageSize": 100,
                    "useSp": False,
                    "view": 63,
                    "summaryColumns": [3488, 3870, 289],
                    "loadMode": 2,
                }

                detail_res = misa_utils._fetch_with_retry(
                    "https://actapp.misa.vn/g1/api/in/v1/in_transfer/get_paging_detail",
                    headers, detail_payload
                )
                if detail_res.status_code != 200:
                    _logger.warning("Không lấy được chi tiết chứng từ %s", refid)
                    continue

                lines = detail_res.json().get("Data", {}).get("PageData", [])
                if not lines:
                    _logger.info("Không có chi tiết cho chứng từ %s", refid)
                    continue

                # Gom theo (from_location_id, to_location_id)
                grouped = {}  # key: (from_id, to_id) -> list(lines)
                for line in lines:
                    from_code = str(line.get("from_stock_code", "")).strip().upper()
                    to_code   = str(line.get("to_stock_code", "")).strip().upper()

                    from_path = stock_mapping.get(from_code, default_location_path)
                    to_path   = stock_mapping.get(to_code,   default_location_path)

                    from_location = self.env['stock.location'].search([('complete_name', '=', from_path)], limit=1)
                    to_location   = self.env['stock.location'].search([('complete_name', '=', to_path)],   limit=1)

                    if not from_location or not to_location:
                        _logger.warning("❌ Không tìm thấy location cho from:%s (%s) hoặc to:%s (%s)",
                                        from_code, from_path, to_code, to_path)
                        continue

                    key = (from_location.id, to_location.id)
                    grouped.setdefault(key, []).append(line)

                if not grouped:
                    _logger.info("Bỏ qua chứng từ %s vì không có dòng hợp lệ theo mapping", refid)
                    continue

                # Đối tác (nếu có)
                partner = False
                if ref_info.get('contact_name'):
                    partner = odoo_utils._get_or_create_partner(ref_info['contact_name'])

                # Tạo/Update picking cho từng cặp kho nguồn/đích
                for (from_id, to_id), related_lines in grouped.items():
                    from_location = self.env['stock.location'].browse(from_id)
                    to_location   = self.env['stock.location'].browse(to_id)

                    picking_type = self._get_internal_picking_type()
                    if not picking_type:
                        _logger.warning("Không tìm thấy picking type 'internal' cho công ty hiện tại")
                        continue

                    # Kiểm tra tồn tại theo (name/refno_finance + from/to) để tránh đè nhầm
                    picking = self.env['stock.picking'].search([
                        ('name', '=', ref_info.get('refno_finance', '')),
                        ('picking_type_id', '=', picking_type.id),
                        ('location_id', '=', from_id),
                        ('location_dest_id', '=', to_id),
                    ], limit=1)

                    if picking:
                        _logger.info("🔁 Phiếu đã tồn tại: %s (from:%s -> to:%s)", picking.name, from_location.display_name, to_location.display_name)
                        odoo_utils._update_picking_lines(picking, related_lines)  # hàm này cần hỗ trợ cập nhật theo from/to cố định
                    else:
                        picking = self.env['stock.picking'].create({
                            'name': ref_info.get('refno_finance', ''),
                            'picking_type_id': picking_type.id,
                            'location_id': from_id,
                            'location_dest_id': to_id,
                            'origin': ref_info.get('refno_finance', ''),
                            'partner_id': partner.id if partner else False,
                        })
                        _logger.info("🆕 Tạo phiếu mới: %s (from:%s -> to:%s)", picking.name, from_location.display_name, to_location.display_name)

                        for line in related_lines:
                            product_code = str(line.get("inventory_item_code", "")).strip()
                            product_name = str(line.get("description", "")).strip()
                            uom_name     = str(line.get("unit_name", "Cái")).strip()
                            qty          = float(line.get("quantity", 0))
                            cost         = float(line.get("unit_price_finance", 0) or 0)

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
                                'location_id': from_id,
                                'location_dest_id': to_id,
                            })
                            _logger.info("  + Tạo dòng chuyển: %s x%s", product_code, qty)

            page_index += 1

    def _get_internal_picking_type(self):
        """Lấy picking type 'internal' theo company hiện tại."""
        return self.env['stock.picking.type'].search([
            ('code', '=', 'internal'),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
