from odoo import models, fields, _
import logging
import json
from datetime import datetime, timedelta

_logger = logging.getLogger(__name__)
# ... các import như cũ ...

class MisaTransferFetch(models.TransientModel):
    _name = "misa.transfer.fetch"
    _description = "MISA Internal Transfer Fetch"

    date_from = fields.Date(string="Từ ngày", required=True)
    date_to   = fields.Date(string="Đến ngày", required=True)

    # ===== Helper: kho chứa location nguồn -> picking type internal =====
    def _get_internal_picking_type_for_location(self, from_location):
        if not from_location:
            return False
        wh = self.env['stock.warehouse'].search([
            ('view_location_id', 'parent_of', from_location.id)
        ], limit=1)
        if wh and wh.int_type_id:
            return wh.int_type_id
        # fallback theo prefix code (TSN/Stock -> TSN)
        wh_code = (from_location.complete_name or "").split('/')[0].strip() if from_location.complete_name else False
        if wh_code:
            wh2 = self.env['stock.warehouse'].search([('code', '=', wh_code)], limit=1)
            if wh2 and wh2.int_type_id:
                return wh2.int_type_id
        return False

    # ===== Helper: lấy Transit Location chuẩn =====
    def _get_transit_location(self):
        Location = self.env['stock.location']
        # Ưu tiên đúng đường dẫn bạn muốn
        transit = Location.search([
            ('complete_name', '=', 'Physical Locations/Inter-warehouse transit'),
            ('active', '=', True)
        ], limit=1)
        if transit:
            return transit

        # Fallback: usage = transit nhưng loại trừ cross-dock
        transit = Location.search([
            ('usage', '=', 'transit'),
            ('active', '=', True),
            ('name', 'not ilike', 'cross'),
        ], limit=1)
        if transit:
            return transit

        raise UserError(_("Không tìm thấy 'Physical Locations/Inter-warehouse transit'. \
                    Vào Kho hàng > Cấu hình > Vị trí, tạo đúng tên & dùng 'Transit'."))


    # ===== Helper: kho đích theo mã MISA (để lấy partner của kho đích) =====
    def _get_dest_warehouse_by_code(self, to_code):
        """Ví dụ: to_code = 'TSN' -> trả về record stock.warehouse của TSN"""
        # Tùy theo mapping của bạn, ở dưới mình map code MISA -> warehouse.code
        code_map = {
            # 'HCM': 'KHSG',
            # 'BENCAM': 'KBC',
            # 'HIENDUC': 'KHD',
            # 'TSN': 'TSN',
            # 'HCM_SHOWROOM': 'TSNSR',
            "HCM":        "TSN",
            # "SHOWROOM161":"TSN/showroom",
            "HCM_SHOWROOM":"TSNSR",
            "BENCAM":     "KBC",
            "HIENDUC":    "KHD",
        }
        wh_code = code_map.get(to_code.upper())
        if not wh_code:
            return False
        return self.env['stock.warehouse'].search([('code', '=', wh_code)], limit=1)

    def action_fetch_transfers(self):
        misa_utils  = self.env['misa.api.utils']
        odoo_utils  = self.env['odoo.utils']
        misa_config = self.env['misa.config']

        access_token = misa_utils._get_misa_token()

        date_from_utc = datetime.combine(self.date_from, datetime.min.time()) - timedelta(hours=7)
        date_to_utc   = datetime.combine(self.date_to,   datetime.max.time()) - timedelta(hours=7)
        headers = misa_config.get_default_headers(access_token)

        # map mã MISA -> complete_name location NGUỒN (chỉ dùng cho from)
        source_location_map = {
            "HCM":        "KHSG/Stock",
            "BENCAM":     "KBC/Tồn kho",
            "HIENDUC":    "KHD/Tồn kho",
            "TSN":        "TSN/Stock",
            "HCM_SHOWROOM":"TSNSR/Stock",
        }
        default_location_path = "Partners/Vendors"

        transit_loc = self._get_transit_location()  # dùng 1 lần cho toàn batch

        payload = {
            "sort": "[{\"property\":3654,\"desc\":true,\"data_type\":3,\"operand\":1},"
                    "{\"property\":3972,\"desc\":true,\"data_type\":3,\"operand\":1},"
                    "{\"property\":4018,\"desc\":true,\"data_type\":1,\"operand\":1}]",
            "filter": [
                {"property": 4041, "value": "[2030,2031,2032]", "operator": 13, "data_type": 4, "operand": 1},
                {"property": 3654, "value": date_from_utc.isoformat() + "Z", "operator": 10, "data_type": 3, "operand": 1},
                {"property": 3654, "value": date_to_utc.isoformat()   + "Z", "operator": 12, "data_type": 3, "operand": 1},
            ],
            "pageIndex": 1, "pageSize": 100, "useSp": False, "view": 62,
            "summaryColumns": [5042], "loadMode": 2,
        }

        page_index = 1
        while True:
            payload["pageIndex"] = page_index
            response = misa_utils._fetch_with_retry(
                "https://actapp.misa.vn/g1/api/in/v1/in_inward_outward_list/paging_filter_v2",
                headers, payload
            )
            if response.status_code != 200:
                break

            page_data = response.json().get("Data", {}).get("PageData", [])
            if not page_data:
                break

            ref_map = {
                item['refid']: {
                    'refno_finance': item.get('refno_finance', ''),
                    'contact_name': item.get('contact_name', '').strip(),
                } for item in page_data
            }

            for refid, ref_info in ref_map.items():
                
                refno = (ref_info.get('refno_finance') or '').strip()
                if not refno:
                    _logger.warning("❌ Bỏ qua refid %s vì thiếu refno_finance", refid)
                    continue

                # Nếu đã có bất kỳ stock.picking nào trùng name => skip toàn bộ refid này
                already = self.env['stock.picking'].sudo().search_count([('name', '=', refno)])
                if already:
                    _logger.info("🔁 Bỏ qua chứng từ %s vì đã tồn tại picking name='%s' (%s bản ghi)", refid, refno, already)
                    continue
                # lấy chi tiết
                detail_payload = {
                    "columns": [2157,1355,1867,5030,1195,1065,5687,5690,5274,3870,5283,289,2818,2358],
                    "filter": [{"property": 3993, "operator": 7, "operand": 1, "value": refid, "data_type": 10}],
                    "sort": "[{\"property\":4555,\"desc\":false,\"data_type\":4,\"operand\":1}]",
                    "pageIndex": 1, "pageSize": 100, "useSp": False, "view": 63,
                    "summaryColumns": [3488,3870,289], "loadMode": 2,
                }
                detail_res = misa_utils._fetch_with_retry(
                    "https://actapp.misa.vn/g1/api/in/v1/in_transfer/get_paging_detail",
                    headers, detail_payload
                )
                if detail_res.status_code != 200:
                    continue

                lines = detail_res.json().get("Data", {}).get("PageData", [])
                if not lines:
                    continue

                # gom theo (from_location_id, dest_warehouse) — ĐÍCH lúc tạo phiếu 1 luôn là TRANSIT
                grouped = {}  # key: (from_location_id, to_wh_id or None) -> [lines]
                for ln in lines:
                    from_code = str(ln.get("from_stock_code", "")).strip().upper()
                    to_code   = str(ln.get("to_stock_code", "")).strip().upper()

                    from_path = source_location_map.get(from_code, default_location_path)
                    from_loc  = self.env['stock.location'].search([('complete_name', '=', from_path)], limit=1)
                    if not from_loc:
                        continue

                    # kho đích để lấy partner (phục vụ auto second transfer của module)
                    to_wh = self._get_dest_warehouse_by_code(to_code)
                    key = (from_loc.id, to_wh.id if to_wh else 0)
                    grouped.setdefault(key, []).append(ln)

                if not grouped:
                    continue

                for (from_id, to_wh_id), related_lines in grouped.items():
                    from_loc = self.env['stock.location'].browse(from_id)
                    dest_wh  = self.env['stock.warehouse'].browse(to_wh_id) if to_wh_id else False

                    picking_type = self._get_internal_picking_type_for_location(from_loc)
                    if not picking_type:
                        continue

                    # partner: lấy partner của KHO ĐÍCH (để module auto tạo phiếu 2)
                    partner_id = dest_wh.partner_id.id if dest_wh and dest_wh.partner_id else False

                    # PHIẾU 1: từ kho nguồn -> TRANSIT (KHÔNG đổ thẳng kho đích)
                    picking = self.env['stock.picking'].search([
                        ('name', '=', ref_info.get('refno_finance', '')),
                        ('picking_type_id', '=', picking_type.id),
                        ('location_id', '=', from_id),
                        ('location_dest_id', '=', transit_loc.id),
                    ], limit=1)

                    if not picking:
                        picking = self.env['stock.picking'].create({
                            'name': ref_info.get('refno_finance', ''),
                            'picking_type_id': picking_type.id,
                            'location_id': from_id,
                            'location_dest_id': transit_loc.id,
                            # 'origin': ref_info.get('refno_finance', ''),
                            'partner_id': partner_id,  # để auto second transfer biết kho đích
                        })

                    # dòng chuyển
                    for ln in related_lines:
                        product_code = (ln.get("inventory_item_code") or "").strip()
                        product_name = (ln.get("description") or "").strip()
                        uom_name     = (ln.get("unit_name") or "Cái").strip()
                        qty          = float(ln.get("quantity") or 0)
                        cost         = float(ln.get("unit_price_finance") or 0)
                        if not product_code or not product_name or qty <= 0:
                            continue

                        product = odoo_utils._get_or_create_product(
                            code=product_code, name=product_name,
                            unit_name=uom_name, cost=cost,
                            product_type="consu", purchase_ok=True, sale_ok=True
                        )

                        # tạo move nếu chưa có
                        self.env['stock.move'].create({
                            'name': product_name,
                            'product_id': product.id,
                            'product_uom_qty': qty,
                            'product_uom': product.uom_id.id,
                            'picking_id': picking.id,
                            'location_id': from_id,
                            'location_dest_id': transit_loc.id,
                        })

            page_index += 1
