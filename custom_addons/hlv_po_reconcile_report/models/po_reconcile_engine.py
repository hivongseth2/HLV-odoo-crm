# -*- coding: utf-8 -*-
"""Logic đối chiếu Đơn mua hàng Odoo - MISA cho cron báo cáo.

Ban đầu chép từ misa_purchase_request_sync/controllers/extension_api.py (endpoint
/api/extension/po/reconcile_only của Chrome extension), nay độc lập: sửa cách đối
chiếu cho báo cáo thì sửa ở đây, không ảnh hưởng extension.
Gọi trực tiếp trong cron (không qua HTTP) để không bị timeout khi có nhiều đơn.
"""
import logging

_logger = logging.getLogger(__name__)


def _classify_po_status(po_data, amis_po, amis_lines, odoo_lines_detail):
    """
    Phân loại trạng thái đối chiếu PO dựa trên dữ liệu Odoo và AMIS.
    
    Trả về: (status, severity, root_cause, suggested_action, differences)
    """
    differences = []
    
    # Trường hợp 1: Không tìm thấy trên AMIS
    if not amis_po:
        return (
            "missing_in_misa",
            "critical",
            "workflow_missing",
            "Đơn hàng chưa được đồng bộ sang MISA. Kiểm tra workflow AMIS Mua hàng, đồng bộ thủ công hoặc tạo lại đơn trên MISA",
            []
        )

    # Trường hợp 2: Có trên AMIS, so sánh chi tiết
    # CHỈ so sánh tổng tiền SAU KHI check từng dòng, để tránh False Positive do
    # MISA trả về total_amount = tổng chưa thuế, Odoo amount_total = tổng đã gồm thuế.
    # Việc so sánh này chỉ có ý nghĩa khi không có lệch line nào.
    odoo_total = po_data.get("amount_total", 0.0)
    odoo_untaxed = po_data.get("amount_untaxed", odoo_total)
    amis_total = float(amis_po.get("total_amount") or 0.0)

    # So sánh từng dòng sản phẩm — aggregate by code
    # Odoo: aggregate qty_received (số lượng đã nhận thực tế, KHÔNG phải product_qty đặt hàng)
    odoo_prod_map = {}  # code -> {"qty": float, "price_unit": float, "price_tax": float, "vat_rate": float, "display": str, "name": str, "uom_name": str}
    for oline in odoo_lines_detail:
        code = oline["code"]
        if code not in odoo_prod_map:
            odoo_prod_map[code] = {
                "qty": 0.0,
                "price_unit": oline.get("price_unit", 0.0),
                "price_tax": 0.0,
                "vat_rate": oline.get("vat_rate", 0.0),
                "display": oline["display"],
                "name": oline["name"],
                "uom_name": oline.get("uom_name", ""),
            }
        odoo_prod_map[code]["qty"] += oline.get("qty_received", oline.get("qty", 0.0))
        odoo_prod_map[code]["price_tax"] += oline.get("price_tax", 0.0)

    # AMIS: aggregate quantity_receipt
    amis_prod_map = {}  # code -> {"qty": float, "price_unit": float, "price_tax": float, "vat_rate": float, "name": str, "unit_name": str, "main_unit_name": str, "main_convert_rate": float}
    for aline in amis_lines:
        orig_code = aline.get("inventory_item_code", "unknown_code").strip()
        code = orig_code.lower()
        a_qty = float(aline.get("quantity_receipt", 0))
        a_price = float(aline.get("unit_price", 0) or 0)
        a_tax = float(aline.get("vat_amount", aline.get("tax_amount", 0)) or 0)
        a_vat_rate = float(aline.get("vat_rate", 0) or 0)
        a_name = aline.get("inventory_item_name", "")
        a_main_qty = float(aline.get("main_quantity", 0) or 0)
        a_main_convert = float(aline.get("main_convert_rate", 1) or 1)
        if code not in amis_prod_map:
            amis_prod_map[code] = {
                "qty": 0.0, "price_unit": a_price, "price_tax": 0.0, "vat_rate": a_vat_rate,
                "name": a_name, "orig_code": orig_code,
                "unit_name": aline.get("unit_name", ""), "main_unit_name": aline.get("main_unit_name", ""),
                "main_convert_rate": a_main_convert,
                "main_qty": 0.0,
            }
        amis_prod_map[code]["qty"] += a_qty
        amis_prod_map[code]["main_qty"] += a_main_qty
        amis_prod_map[code]["price_tax"] += a_tax

    all_codes = set(list(odoo_prod_map.keys()) + list(amis_prod_map.keys()))
    
    has_qty_diff = False
    has_price_diff = False
    has_missing_in_amis = False
    has_missing_in_odoo = False
    has_total_diff = False
    has_tax_diff = False
    has_vat_diff = False
    
    if abs(odoo_untaxed - amis_total) >= 1.0:
        has_total_diff = True
    elif abs(odoo_total - amis_total) >= 1.0:
        # Chỉ lệch do thuế - đánh dấu info, không warning
        has_tax_diff = True
        differences.append({
            "type": "tax_diff",
            "product_code": "__total__",
            "product_name": "Thuế GTGT",
            "field": "amount_tax",
            "odoo_value": odoo_total - odoo_untaxed,
            "misa_value": 0,
            "severity": "info"
        })

    for code in all_codes:
        o_item = odoo_prod_map.get(code)
        a_item = amis_prod_map.get(code)
        
        if o_item:
            display_code = o_item["display"]
            prod_name = o_item["name"]
        elif a_item:
            display_code = f"[{a_item.get('orig_code', code)}] {a_item.get('name', '')}"
            prod_name = a_item.get("name", "")
        else:
            display_code = code
            prod_name = ""

        if o_item and not a_item:
            # Thử fallback match theo tên sản phẩm cho trường hợp Odoo code = unknown_code (sản phẩm đã archive)
            fallback_matched = False
            if code == "unknown_code" and o_item.get("name"):
                o_name_lower = o_item["name"].lower().strip()
                for alt_code, alt_item in amis_prod_map.items():
                    alt_name = (alt_item.get("name") or "").lower().strip()
                    if alt_name and (alt_name == o_name_lower or o_name_lower in alt_name or alt_name in o_name_lower):
                        # Match found: merge odoo data into amis item
                        a_item = alt_item
                        fallback_matched = True
                        _logger.info("✅ Fallback match by name: Odoo '%s' (name='%s') -> AMIS code='%s'", code, o_item["name"], alt_code)
                        break
            if not fallback_matched:
                # Sản phẩm chỉ có trên Odoo
                has_missing_in_amis = True
                differences.append({
                    "type": "missing_in_amis",
                    "product_code": code,
                    "product_name": prod_name,
                    "field": "qty",
                    "odoo_value": o_item["qty"],
                    "misa_value": 0,
                    "severity": "critical"
                })
        elif a_item and not o_item:
            # Sản phẩm chỉ có trên AMIS
            has_missing_in_odoo = True
            differences.append({
                "type": "missing_in_odoo",
                "product_code": code,
                "product_name": prod_name,
                "field": "qty",
                "odoo_value": 0,
                "misa_value": a_item["qty"],
                "severity": "critical"
            })
        else:
            # Cả 2 đều có, so sánh số lượng đã nhập kho
            o_qty = o_item["qty"]
            a_qty = a_item["qty"]
            if abs(o_qty - a_qty) > 0.01:
                has_qty_diff = True
                differences.append({
                    "type": "qty_mismatch",
                    "product_code": code,
                    "product_name": prod_name,
                    "field": "qty_received",
                    "odoo_value": o_qty,
                    "misa_value": a_qty,
                    "severity": "warning"
                })
            
            # So sánh đơn giá
            o_price = o_item.get("price_unit", 0.0)
            a_price = a_item.get("price_unit", 0.0)
            if o_price > 0 and a_price > 0 and abs(o_price - a_price) > 100:
                has_price_diff = True
                differences.append({
                    "type": "price_mismatch",
                    "product_code": code,
                    "product_name": prod_name,
                    "field": "price_unit",
                    "odoo_value": o_price,
                    "misa_value": a_price,
                    "severity": "warning"
                })
                
            # So sánh Thuế % (vat_rate)
            o_vat = float(o_item.get("vat_rate", 0.0))
            a_vat = float(a_item.get("vat_rate", 0.0))
            if abs(o_vat - a_vat) > 0.01:
                has_vat_diff = True
                differences.append({
                    "type": "tax_diff",
                    "product_code": code,
                    "product_name": prod_name,
                    "field": "vat_rate",
                    "odoo_value": o_vat,
                    "misa_value": a_vat,
                    "severity": "warning"
                })

            # So sánh Tiền thuế từng dòng (price_tax)
            o_tax_amt = float(o_item.get("price_tax", 0.0))
            a_tax_amt = float(a_item.get("price_tax", 0.0))
            if abs(o_tax_amt - a_tax_amt) > 100.0:
                has_tax_diff = True
                differences.append({
                    "type": "tax_diff",
                    "product_code": code,
                    "product_name": prod_name,
                    "field": "price_tax",
                    "odoo_value": o_tax_amt,
                    "misa_value": a_tax_amt,
                    "severity": "warning"
                })

    # Xác định status tổng thể
    if not differences:
        return ("matched", "info", None, None, [])
    
    # Xác định root_cause
    if has_missing_in_amis:
        root_cause = "workflow_missing"
        suggested = "Đơn hàng chưa được đồng bộ sang MISA. Kiểm tra workflow AMIS Mua hàng"
    elif has_missing_in_odoo:
        root_cause = "workflow_missing"
        suggested = "Sản phẩm tồn tại trên MISA nhưng chưa có trên Odoo. Kiểm tra app auto đồng bộ"
    elif has_qty_diff and has_price_diff:
        root_cause = "manual_edit"
        suggested = "Cả số lượng và đơn giá đều lệch. Kiểm tra chứng từ gốc và đối chiếu với nhà cung cấp"
    elif has_qty_diff:
        root_cause = "partial_receipt"
        suggested = "Số lượng nhập kho không khớp. Kiểm tra phiếu nhập kho thực tế, đối chiếu với chứng từ gốc"
    elif has_price_diff:
        root_cause = "manual_edit"
        suggested = "Đơn giá giữa Odoo và MISA không khớp. Kiểm tra biên bản thỏa thuận giá"
    elif has_total_diff:
        root_cause = "tax_fee_diff"
        suggested = "Lệch tổng tiền do Thuế, Phí hoặc làm tròn. Kiểm tra chi phí phát sinh"
    else:
        root_cause = "unknown"
        suggested = "Có sai lệch không xác định. Kiểm tra thủ công"

    # Xác định severity tổng thể
    severities = [d["severity"] for d in differences]
    if "critical" in severities:
        overall_severity = "critical"
    elif "warning" in severities:
        overall_severity = "warning"
    else:
        overall_severity = "info"

    # Xác định status tổng thể
    if has_missing_in_amis or has_missing_in_odoo:
        status = "missing_in_misa" if has_missing_in_amis else "missing_in_odoo"
    elif has_qty_diff and has_price_diff:
        status = "qty_price_mismatch"
    elif has_qty_diff:
        status = "qty_mismatch"
    elif has_price_diff:
        status = "price_mismatch"
    elif has_vat_diff or has_total_diff or has_tax_diff:
        status = "tax_diff"
    else:
        status = "diff"

    return (status, overall_severity, root_cause, suggested, differences)


def _get_odoo_line_details(po):
    """Trích xuất chi tiết dòng sản phẩm từ PO Odoo, bao gồm receipt history."""
    lines = []
    for oline in po.order_line:
        if oline.display_type:
            continue
        orig_code = (oline.product_id.default_code or "").strip()
        prod_name = (oline.product_id.name or "").strip()
        code = orig_code.lower()
        if not code:
            # Sản phẩm đã bị archive và mất default_code (do tạo lại sản phẩm mới cùng mã)
            # Fallback: tìm sản phẩm active có cùng tên để lấy default_code
            try:
                active_prod = po.env['product.product'].sudo().search([
                    ('name', '=', oline.product_id.name),
                    ('default_code', '!=', False),
                    ('active', '=', True)
                ], limit=1)
                if active_prod and active_prod.default_code:
                    orig_code = active_prod.default_code.strip()
                    code = orig_code.lower()
            except Exception:
                pass
        if not code:
            code = "unknown_code"
            orig_code = "Unknown"
        
        # Lấy lịch sử nhập kho
        receipt_history = []
        for pick in po.picking_ids.filtered(lambda p: p.state == 'done'):
            for move in pick.move_ids.filtered(lambda m: m.product_id == oline.product_id):
                receipt_history.append({
                    "picking": pick.name,
                    "date": pick.date_done.strftime("%Y-%m-%d") if pick.date_done else "",
                    "qty": move.product_uom_qty
                })
        
        display = f"[{orig_code}] {prod_name}" if orig_code != "Unknown" else "Unknown Code"
        display = display.replace("'", "`")
        
        vat_rate = oline.taxes_id[0].amount if oline.taxes_id else 0.0
        
        lines.append({
            "code": code,
            "orig_code": orig_code,
            "name": prod_name,
            "display": display,
            "qty": oline.product_qty,
            "qty_received": oline.qty_received,
            "price_unit": oline.price_unit,
            "price_subtotal": oline.price_subtotal,
            "price_tax": oline.price_tax,
            "vat_rate": vat_rate,
            "uom_name": oline.product_uom.name if oline.product_uom else "",
            "receipt_history": receipt_history
        })
    return lines


def _detect_duplicate_po(po_name, all_po_names):
    """
    Phát hiện PO Odoo có khả năng bị trùng/ghép với PO MISA.
    VD: DMH123 và DMH123-1 cùng mapping với 1 PO MISA.
    """
    # Tìm các PO khác có cùng prefix
    base_name = po_name
    # Loại bỏ hậu tố như -1, -2, _copy, v.v.
    import re as _re
    m = _re.match(r"^(.*?)(?:[-_]\d+|_copy\d*)$", po_name)
    if m:
        base_name = m.group(1)
    
    duplicates = []
    for other in all_po_names:
        if other == po_name:
            continue
        if other.startswith(base_name) or base_name.startswith(other):
            duplicates.append(other)
    return duplicates


def reconcile_po(env_admin, date_from_str, date_to_str):
    """Đối chiếu PO Odoo - MISA trong khoảng ngày (bản sao độc lập của /api/extension/po/reconcile_only).
    env_admin phải là env superuser. Trả về dict {ok, data, summary, reconciled}.
    """
    from datetime import datetime, timezone
    import concurrent.futures
    
    misa_utils = env_admin['misa.api.utils']
    misa_config = env_admin['misa.config']
    access_token = misa_utils._get_misa_token()
    headers = misa_config.get_default_headers(access_token)
    
    date_from_dt = datetime.strptime(date_from_str, "%Y-%m-%d")
    date_to_dt = datetime.strptime(date_to_str, "%Y-%m-%d")
    
    date_from_utc = date_from_dt.strftime('%Y-%m-%d 00:00:00')
    date_to_utc = date_to_dt.strftime('%Y-%m-%d 23:59:59')
    
    date_from_iso = date_from_dt.strftime('%Y-%m-%dT00:00:00.00Z')
    date_to_iso = date_to_dt.strftime('%Y-%m-%dT23:59:59.00Z')
    
    # Lấy các Đơn mua hàng được tạo/duyệt trong khoảng ngày HOẶC có phiếu nhập kho hoàn tất trong khoảng ngày
    odoo_pos_approved = env_admin['purchase.order'].search([
        ('date_approve', '>=', date_from_utc),
        ('date_approve', '<=', date_to_utc),
        ('state', 'in', ['purchase', 'done'])
    ])
    odoo_pos_ordered = env_admin['purchase.order'].search([
        ('date_order', '>=', date_from_utc),
        ('date_order', '<=', date_to_utc),
        ('state', 'in', ['purchase', 'done'])
    ])
    pickings_done = env_admin['stock.picking'].search([
        ('date_done', '>=', date_from_utc),
        ('date_done', '<=', date_to_utc),
        ('state', '=', 'done'),
        ('picking_type_id.code', '=', 'incoming'),
        ('purchase_id', '!=', False)
    ])
    odoo_pos_from_pickings = pickings_done.mapped('purchase_id').filtered(
        lambda p: p.state in ['purchase', 'done']
    )
    
    # Kết hợp các Đơn mua hàng từ cả 2 nguồn (tự động loại bỏ trùng lặp)
    odoo_pos = odoo_pos_approved | odoo_pos_ordered | odoo_pos_from_pickings
    odoo_pos_list = list(odoo_pos)
    
    # Tìm kiếm ALL POs trong MISA AMIS theo Date
    _logger.info("🔍 Fetching ALL POs from MISA between %s and %s", date_from_iso, date_to_iso)
    amis_dict = {}
    amis_all_list = []
    
    for page in range(1, 10):
        amis_payload = {
            "sort": "[{\"property\":3972,\"desc\":true,\"data_type\":3,\"operand\":1},{\"property\":4008,\"desc\":true,\"data_type\":1,\"operand\":1}]",
            "filter": [
                {
                    "property": 3972,
                    "value": date_from_iso,
                    "operator": 10,
                    "operand": 1,
                    "data_type": 3
                },
                {
                    "property": 3972,
                    "value": date_to_iso,
                    "operator": 12,
                    "operand": 1,
                    "data_type": 3
                }
            ],
            "pageIndex": page,
            "pageSize": 500,
            "useSp": False,
            "view": 2,
            "summaryColumns": [5039, 5104, 247],
            "loadMode": 2
        }

        local_headers = dict(headers)
        response = misa_utils._fetch_with_retry(
            "https://actapp.misa.vn/g2/api/pu/v1/pu_order/paging_filter_v2",
            local_headers, amis_payload
        )

        if response.status_code == 200:
            resp_json = response.json()
            data_obj = resp_json.get("Data")
            if isinstance(data_obj, str):
                import json as json_lib
                try: data_obj = json_lib.loads(data_obj)
                except: data_obj = {}
            if not data_obj: break
            
            page_data = data_obj.get("PageData", [])
            if not page_data: break
                
            for apo in page_data:
                refno = apo.get("refno")
                if refno:
                    amis_dict[refno.strip()] = apo
                    amis_all_list.append(apo)
        else:
            break
    
    # CROSS-CHECK: Search Odoo POs that are missing in amis_dict
    def _search_po_in_misa_by_code(po_name):
        try:
            custom_filter = [{
                "property": 4008,
                "value": po_name,
                "operator": 1,
                "operand": 1,
                "data_type": 1
            }]
            payload2 = {
                "sort": "[{\"property\":3972,\"desc\":true,\"data_type\":3,\"operand\":1},{\"property\":4008,\"desc\":true,\"data_type\":1,\"operand\":1}]",
                "filter": [
                    {"property": 3972, "value": "2015-01-01T00:00:00.00Z", "operator": 10, "operand": 1, "data_type": 3},
                    {"property": 3972, "value": datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'), "operator": 12, "operand": 1, "data_type": 3}
                ],
                "customFilter": custom_filter,
                "pageIndex": 1,
                "pageSize": 100,
                "useSp": False,
                "view": 2,
                "summaryColumns": [5039, 5104, 247],
                "loadMode": 2
            }
            res2 = misa_utils._fetch_with_retry("https://actapp.misa.vn/g2/api/pu/v1/pu_order/paging_filter_v2", dict(headers), payload2)
            if res2.status_code == 200:
                d2 = res2.json().get("Data", {})
                if isinstance(d2, str):
                    import json as json_lib
                    try: d2 = json_lib.loads(d2)
                    except: d2 = {}
                p2 = d2.get("PageData", []) if isinstance(d2, dict) else []
                for a2 in p2:
                    r2 = a2.get("refno")
                    if r2 and r2.strip() == po_name.strip():
                        return po_name, a2
                if p2: return po_name, p2[0]
        except Exception as e:
            _logger.warning("_search_po_in_misa_by_code ex for %s: %s", po_name, e)
        return po_name, None

    missing_in_misa_names = []
    for po in odoo_pos_list:
        if po.name.strip() not in amis_dict:
            missing_in_misa_names.append(po.name.strip())
            
    if missing_in_misa_names:
        _logger.info("🔍 CROSS-CHECK: %d Odoo POs missing in MISA date range. Searching exact matches...", len(missing_in_misa_names))
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = {executor.submit(_search_po_in_misa_by_code, name): name for name in missing_in_misa_names}
            for future in concurrent.futures.as_completed(futures):
                po_name, apo = future.result()
                if apo:
                    _logger.info("✅ CROSS-CHECK: Found PO %s in MISA!", po_name)
                    amis_dict[po_name.strip()] = apo
                    amis_all_list.append(apo)
                    
    # CROSS-CHECK: Search MISA POs that are missing in odoo_pos_list
    odoo_po_names_lower = {po.name.strip().lower() for po in odoo_pos_list}
    missing_in_odoo_refnos = []
    for apo in amis_all_list:
        refno = apo.get("refno", "").strip()
        if refno and refno.lower() not in odoo_po_names_lower:
            missing_in_odoo_refnos.append(refno)
            
    if missing_in_odoo_refnos:
        _logger.info("🔍 CROSS-CHECK: %d MISA POs missing in Odoo date range. Searching exact matches...", len(missing_in_odoo_refnos))
        found_in_odoo = env_admin['purchase.order'].search([
            ('name', 'in', missing_in_odoo_refnos),
            ('state', 'in', ['purchase', 'done'])
        ])
        for po in found_in_odoo:
            if po.name.strip().lower() not in odoo_po_names_lower:
                _logger.info("✅ CROSS-CHECK: Found PO %s in Odoo!", po.name)
                odoo_pos_list.append(po)
                odoo_po_names_lower.add(po.name.strip().lower())

    # ============================================================
    # BUILD RECONCILED DATA
    # ============================================================
    reconciled = []
    matched_old = []
    diff_old = []
    odoo_only_old = []
    
    processed_misa_refnos = set()
    all_po_names = [po.name for po in odoo_pos_list]

    for po in odoo_pos_list:
        po_name = po.name
        po_origin = (po.origin or "").strip()
        
        odoo_lines_detail = _get_odoo_line_details(po)
        
        amis_po = amis_dict.get(po_name.strip())
        if amis_po:
            processed_misa_refnos.add(po_name.strip())
        if not amis_po and po_origin:
            for org in po_origin.split(','):
                org = org.strip()
                if org and org in amis_dict:
                    amis_po = amis_dict[org]
                    processed_misa_refnos.add(org)
                    break
        
        reconciled_item = {
            "po_name": po_name,
            "po_origin": po_origin,
            "partner": po.partner_id.name if po.partner_id else "",
            "date_order": po.date_order.strftime("%Y-%m-%d") if po.date_order else "",
            "odoo": {
                "partner": po.partner_id.name if po.partner_id else "",
                "date_order": po.date_order.strftime("%Y-%m-%d") if po.date_order else "",
                "amount_total": po.amount_total,
                "lines": odoo_lines_detail
            },
            "amis": None,
            "differences": [],
            "duplicate_warning": None
        }
        
        dup_po_names = _detect_duplicate_po(po_name, all_po_names)
        if dup_po_names:
            reconciled_item["duplicate_warning"] = {
                "message": f"Odoo có nhiều PO cùng mã gốc: {', '.join([po_name] + dup_po_names)}.",
                "related_pos": dup_po_names
            }
        
        if not amis_po:
            status, severity, root_cause, suggested, diffs = _classify_po_status(
                {"amount_total": po.amount_total}, None, [], odoo_lines_detail
            )
            reconciled_item["status"] = "missing_in_misa"
            reconciled_item["severity"] = "critical"
            reconciled_item["root_cause"] = "odoo_only"
            reconciled_item["suggested_action"] = "Tạo ĐMH trên AMIS"
            reconciled_item["differences"] = [{"type": "system", "desc": "Đơn không tồn tại trên MISA"}]
            
            odoo_only_old.append(po_name)
        else:
            refid = amis_po.get("refid")
            amis_total = float(amis_po.get("total_amount") or 0.0)
            amis_total_oc = float(amis_po.get("total_amount_oc", amis_total))
            
            amis_lines = []
            amis_header = {}
            try:
                import base64
                import json as _json
                import requests
                detail_full_payload = [{
                    "Type": "pu_order",
                    "Key": refid,
                    "RefType": 301,
                    "RefTypeCategory": 301,
                    "View": "view_pu_order",
                    "Details": [
                        {"Type": "pu_order_detail", "Alias": "detail", "View": "view_pu_order_detail"}
                    ]
                }]
                req_base64 = base64.b64encode(
                    _json.dumps(detail_full_payload, separators=(',', ':')).encode('utf-8')
                ).decode('utf-8')
                detail_url = f"https://actapp.misa.vn/g2/api/pu/v1/pu_order/detail_full?req={req_base64}"
                detail_res = requests.get(detail_url, headers=headers, timeout=30)
                
                if detail_res.status_code == 200:
                    dt_json = detail_res.json()
                    d_obj = dt_json.get("Data", {}) if isinstance(dt_json, dict) else {}
                    if isinstance(d_obj, str):
                        try: d_obj = _json.loads(d_obj)
                        except Exception: d_obj = {}
                    if isinstance(d_obj, dict):
                        pu_orders = d_obj.get("pu_order", [])
                        if pu_orders:
                            amis_header = pu_orders[0] if isinstance(pu_orders, list) else pu_orders
                        amis_lines = d_obj.get("pu_order_detail", [])
            except Exception as e:
                _logger.warning("detail_full exception for %s: %s", po_name, e)
            
            amis_lines_detail = []
            for aline in amis_lines:
                if not isinstance(aline, dict): continue
                
                orig_code = (aline.get("inventory_item_code") or "").strip()
                prod_name = (aline.get("description") or aline.get("inventory_item_name") or "").strip()
                code = orig_code.lower()
                # Lấy thông tin ĐVT để đối chiếu đúng (có thể MISA dùng unit_name còn Odoo dùng main_unit_name)
                misa_main_qty = float(aline.get("main_quantity") or 0)
                misa_main_convert = float(aline.get("main_convert_rate") or 1)
                # Nếu main_convert_rate > 0 và main_quantity > 0, tính lại qty từ main để so sánh
                misa_qty = float(aline.get("quantity") or 0)
                misa_qty_receipt = float(aline.get("quantity_receipt") or 0)
                amis_lines_detail.append({
                    "code": code,
                    "orig_code": orig_code,
                    "name": prod_name,
                    "display": f"[{orig_code}] {prod_name}" if orig_code else "Unknown Code",
                    "qty": misa_qty,
                    "qty_receipt": misa_qty_receipt,
                    "main_quantity": misa_main_qty,
                    "main_quantity_receipt": float(aline.get("main_quantity_receipt") or 0),
                    "main_convert_rate": misa_main_convert,
                    "unit_name": aline.get("unit_name") or "",
                    "main_unit_name": aline.get("main_unit_name") or "",
                    "price_unit": float(aline.get("unit_price") or aline.get("main_unit_price") or 0),
                    "amount": float(aline.get("amount") or aline.get("amount_oc") or 0),
                    "price_tax": float(aline.get("vat_amount") or aline.get("vat_amount_oc") or 0),
                    "vat_rate": float(aline.get("vat_rate") or 0)
                })
            
            acc_obj_code = (amis_header.get("account_object_code") or (amis_po.get("account_object_code") if amis_po else "") or "").strip()
            reconciled_item["account_object_code"] = acc_obj_code
            reconciled_item["amis"] = {
                "partner": (amis_header.get("account_object_name") or (amis_po.get("account_object_name") if amis_po else "") or "").strip(),
                "account_object_code": acc_obj_code,
                "date_order": amis_po.get("refdate", "")[:10],
                "amount_total": amis_total_oc,
                "lines": amis_lines_detail
            }
            
            status, severity, root_cause, suggested, diffs = _classify_po_status(
                reconciled_item["odoo"], amis_po, amis_lines, odoo_lines_detail
            )
            reconciled_item["status"] = status
            reconciled_item["severity"] = severity
            reconciled_item["root_cause"] = root_cause
            reconciled_item["suggested_action"] = suggested
            reconciled_item["differences"] = diffs
            
            if status == "matched":
                matched_old.append(po_name)
            else:
                diff_old.append(po_name)
        
        reconciled.append(reconciled_item)

    # ============================================================
    # MISA ONLY
    # ============================================================
    for apo in amis_all_list:
        refno = apo.get("refno", "").strip()
        if refno not in processed_misa_refnos:
            # MISA Only item
            misa_code = (apo.get("account_object_code") or "").strip()
            reconciled_item = {
                "po_name": refno,
                "po_origin": "",
                "partner": apo.get("account_object_name") or "",
                "account_object_code": misa_code,
                "date_order": apo.get("refdate", "")[:10],
                "odoo": None,
                "amis": {
                    "partner": apo.get("account_object_name") or "",
                    "account_object_code": misa_code,
                    "date_order": apo.get("refdate", "")[:10],
                    "amount_total": float(apo.get("total_amount_oc", apo.get("total_amount") or 0)),
                    "lines": []
                },
                "status": "missing_in_odoo",
                "severity": "critical",
                "root_cause": "misa_only",
                "suggested_action": "Tạo PO trên Odoo",
                "differences": [{"type": "system", "desc": "Đơn có trên MISA nhưng không có trên Odoo"}],
                "duplicate_warning": None
            }
            reconciled.append(reconciled_item)

    reconciled.sort(key=lambda x: (x.get("status", ""), x.get("po_name", "")))

    by_status = {}
    by_severity = {}
    for item in reconciled:
        s = item["status"]
        by_status[s] = by_status.get(s, 0) + 1
        sev = item["severity"]
        if sev:
            by_severity[sev] = by_severity.get(sev, 0) + 1
    
    summary = {
        "total_odoo": len(odoo_pos_list),
        "total_misa": len(amis_dict),
        "by_status": by_status,
        "by_severity": by_severity
    }
    
    return {
        "ok": True,
        "data": {
            "matched": matched_old,
            "diff": diff_old,
            "odoo_only": odoo_only_old,
            "total_odoo": len(odoo_pos_list)
        },
        "summary": summary,
        "reconciled": reconciled
    }
