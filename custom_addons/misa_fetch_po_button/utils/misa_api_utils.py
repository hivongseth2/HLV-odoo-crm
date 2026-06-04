import requests
import logging
import time
from odoo import models
import re
from dateutil import parser as dtparser
from requests.utils import dict_from_cookiejar
from http.cookiejar import Cookie

_logger = logging.getLogger(__name__)
import json

class MisaApiUtils(models.AbstractModel):
    _name = 'misa.api.utils'
    _description = 'MISA API Utilities'
    
    def _sync_customer_from_misa_account_api(self, account_id, headers):
        """
        Sync customer detailed info from MISA Account API.
        Columns: ID;Debt;DebtLimit;FormLayoutID;AccountName;AccountNumber;TaxCode
        Uses AccountNumber as unique identifier (ref) in Odoo.
        """
        if not account_id:
            return None
        
        url = f"https://amisapp.misa.vn/crm/g2/api/business/Account/{account_id}/?columns=ID;Debt;DebtLimit;FormLayoutID;AccountName;AccountNumber;TaxCode"
        
        try:
            # Note: MISA often works with POST for filtering, but for simple ID retrieval with columns in URL, GET is standard.
            # If GET fails, we might need to verify auth headers or method. Assuming GET based on URL structure.
            resp = requests.get(url, headers=headers, timeout=30)
            
            # Helper to handle potential 404 or other issues
            if not resp.ok:
                _logger.warning("⚠️ MISA Account API error %s: %s", resp.status_code, resp.text)
                return None
                
            js = resp.json()
            if not js.get("Success"):
                _logger.warning("⚠️ MISA Account API success=False for ID %s: %s", account_id, js.get("UserMsg"))
                return None
            
            data = js.get("Data", {})
            if not data:
                 return None
            
            account_number = (str(data.get("AccountNumber") or "")).strip()
            account_name = (data.get("AccountName") or "").strip()
            tax_code = (str(data.get("TaxCode") or "")).strip()
            
            if not account_number:
                # If no account number in MISA, we cannot link by 'ref'. 
                # Fallback to name-based logic in main loop logic.
                _logger.warning("⚠️ MISA Account ID %s has no AccountNumber", account_id)
                return None
                
            Partner = self.env['res.partner']
            
            # Find by ref (AccountNumber)
            # Case-insensitive search ideally, but 'ref' is usually exact.
            partner = Partner.search([('ref', '=', account_number)], limit=1)
            
            vals = {}
            # Always update name if provided? Or only if different?
            # User wants to update info.
            if account_name:
                vals['name'] = account_name
            if tax_code:
                vals['vat'] = tax_code
            
            # Ensure company type
            if not partner and not vals.get('name'):
                 # Should rare happen if account_name exists
                 vals['name'] = account_number

            if partner:
                # Update existing
                if vals:
                    partner.write(vals)
                _logger.info("✅ Synced customer %s (ref=%s) from MISA Account API", partner.name, account_number)
            else:
                # Create new
                vals['ref'] = account_number
                vals['company_type'] = 'company' 
                partner = Partner.create(vals)
                _logger.info("🆕 Created customer %s (ref=%s) from MISA Account API", partner.name, account_number)
                
            return partner
            
        except Exception as e:
             _logger.error("❌ Error syncing MISA Account %s: %s", account_id, e)
             return None

    def get_or_create_combo_product(self, combo_data, children_data, env=None, sale_headers=None):
        """
        Tạo/cập nhật combo product VỚI BOM (Kit/phantom) thay vì combo.product lines
        - Chuyển sang loại storable (is_storable=True)
        - Tạo BOM Kit để tự động giao các thành phần khi bán
        """
        env = env or self.env
        Product = env['product.product']
        ProductTmpl = env['product.template']
        OdooUtils = env['odoo.utils']
        MrpBom = env['mrp.bom']
        MrpBomLine = env['mrp.bom.line']

        combo_code = (combo_data.get('ProductIDText') or '').strip()
        combo_name = (combo_data.get('Description') or combo_code).strip()
        combo_uom_name = (combo_data.get('UnitIDText') or 'Cái').strip()
        # Lấy số lượng combo cha từ đơn hàng (để tính lại số lượng base cho children)
        combo_qty_in_order = float(combo_data.get('Amount') or 1.0)
        
        if not combo_code:
            _logger.error("❌ Thiếu ProductIDText cho combo")
            return False

        # Lấy/tạo UoM cho combo cha
        try:
            combo_uom = OdooUtils._get_or_create_uom(combo_uom_name)
        except Exception:
            combo_uom = False

        # === Helper: TẠO/CẬP NHẬT BOM TỪ CHILDREN ===
        def _write_bom_from_children(target_tmpl, children_list, parent_qty_in_order=1.0):
            """
            Tạo/cập nhật BOM Kit (phantom) từ danh sách children
            target_tmpl: record product.template
            children_list: [{ProductIDText, Amount, UnitIDText, Price, ...}]
            parent_qty_in_order: số lượng combo cha trong đơn hàng (để tính lại base qty)
            """
            if not target_tmpl or not children_list:
                return

            # 1) PRE-FILTER: Lọc danh sách con hợp lệ trước
            # Tránh trường hợp children_list có item rác nhưng không có ProductIDText -> tạo BoM rỗng
            valid_children = []
            seen_codes = set()
            for ch in children_list:
                c_code = (ch.get('ProductIDText') or '').strip()
                if c_code and c_code not in seen_codes:
                    seen_codes.add(c_code)
                    valid_children.append(ch)
            
            if not valid_children:
                _logger.warning("⚠️ Không tìm thấy children hợp lệ cho combo %s. Bỏ qua tạo BoM.", target_tmpl.display_name)
                return

            # 2) Tìm BOM hiện có (active) cho sản phẩm này
            existing_bom = MrpBom.search([
                ('product_tmpl_id', '=', target_tmpl.id),
                ('active', '=', True)
            ], limit=1)

            # 3) Nếu có BOM cũ -> xóa các lines và cập nhật
            if existing_bom:
                if existing_bom.bom_line_ids:
                    existing_bom.bom_line_ids.sudo().unlink()
                bom = existing_bom
            else:
                # Tạo BOM mới (Kit/phantom)
                bom = MrpBom.sudo().create({
                    'product_tmpl_id': target_tmpl.id,
                    'type': 'phantom',  # Kit - tự động giao các thành phần
                    'product_qty': 1.0,
                    'code': f'BOM-MISA: {target_tmpl.default_code}',
                })
                _logger.info("✅ Đã tạo BOM Kit mới cho %s (id=%s)", target_tmpl.display_name, bom.id)

            # 4) Tạo BOM lines cho từng child
            created = 0
            for ch in valid_children:
                c_code = (ch.get('ProductIDText') or '').strip()
                
                c_name = (ch.get('Description') or c_code).strip()
                c_uom_name = (ch.get('UnitIDText') or 'Cái').strip()
                c_qty_raw = float(ch.get('Amount') or 1.0)
                c_price = float(ch.get('Price') or 0.0)
                
                # 🔧 FIX: Tính lại số lượng base (MISA trả về Amount đã nhân với qty đơn hàng)
                if parent_qty_in_order and parent_qty_in_order > 0:
                    c_qty = c_qty_raw / parent_qty_in_order
                else:
                    c_qty = c_qty_raw

                # Tìm/tạo sản phẩm con
                c_prod = Product.search([('default_code', '=', c_code)], limit=1)
                if not c_prod:
                    try:
                        c_prod = OdooUtils._get_or_create_product(
                            code=c_code, 
                            name=c_name, 
                            unit_name=c_uom_name,
                            cost=c_price, 
                            product_type='consu',  # storable
                            purchase_ok=True, 
                            sale_ok=True
                        )
                        # Set storable nếu có field is_storable
                        if c_prod and hasattr(c_prod.product_tmpl_id, 'is_storable'):
                            c_prod.product_tmpl_id.write({'is_storable': True})
                    except Exception as e:
                        _logger.error("❌ Không tạo được sản phẩm con %s: %s", c_code, e)
                        continue

                if not c_prod:
                    _logger.warning("⚠️ Bỏ qua sản phẩm con %s (không tạo được)", c_code)
                    continue

                # Lấy UoM cho BOM line
                c_uom = c_prod.uom_id

                # Tạo BOM line
                try:
                    MrpBomLine.sudo().create({
                        'bom_id': bom.id,
                        'product_id': c_prod.id,
                        'product_qty': c_qty,
                        'product_uom_id': c_uom.id if c_uom else False,
                    })
                    created += 1
                    _logger.info("✅ Thêm BOM line: %s (qty=%s) vào BOM %s", 
                            c_code, c_qty, target_tmpl.display_name)
                except Exception as e:
                    _logger.error("❌ Lỗi tạo BOM line cho %s: %s", c_code, e)

            _logger.info("✅ Đã tạo %s BOM lines cho combo %s", created, target_tmpl.display_name)

        # === Lấy/tạo combo cha ===
        combo_prod = Product.search([('default_code', '=', combo_code)], limit=1)
        
        if combo_prod:
            # Sản phẩm đã tồn tại
            tmpl = combo_prod.product_tmpl_id
            
            # Chuyển sang storable (type=consu + is_storable=True)
            update_vals = {}
            
            # Chuyển sang storable (type=consu + is_storable=True)
            if tmpl.type == 'service':
                update_vals['type'] = 'consu'
            if hasattr(tmpl, 'is_storable') and not tmpl.is_storable:
                update_vals['is_storable'] = True
            
            if combo_uom:
                try:
                    if not tmpl.uom_id:
                        update_vals['uom_id'] = combo_uom.id
                    elif tmpl.uom_id.category_id == combo_uom.category_id and tmpl.uom_id != combo_uom:
                        update_vals['uom_id'] = combo_uom.id
                except Exception as e:
                    _logger.warning("⚠️ Không cập nhật UoM cho combo %s: %s", combo_code, e)
            
            if update_vals:
                try:
                    tmpl.write(update_vals)
                    _logger.info("🔄 Đã cập nhật combo template: %s", list(update_vals.keys()))
                except Exception as e:
                    _logger.error("❌ Lỗi cập nhật template combo %s: %s", combo_code, e)

            # Nếu thiếu children -> tự fetch từ API
            qty_divider = combo_qty_in_order  # Mặc định: children từ đơn hàng cần chia
            if not children_data and sale_headers:
                try:
                    master = combo_data.get("ProductID") or combo_data.get("ProductId") or combo_code
                    kids = self.get_combo_children_by_product(master, sale_headers) or []
                    children_data = [{
                        "ProductIDText": (k.get("ProductIDText") or "").strip(),
                        "Description": (k.get("Description") or k.get("ProductIDText") or "").strip(),
                        "UnitIDText": (k.get("UnitIDText") or "Cái").strip(),
                        "Amount": float(k.get("Amount") or 1.0),
                        "Price": float(k.get("Price") or 0.0),
                    } for k in kids]
                    qty_divider = 1.0  # ✅ Data từ API riêng = BASE qty, không cần chia
                    _logger.info("📡 Đã fetch %d sản phẩm con cho combo %s từ API", 
                            len(children_data), combo_code)
                except Exception as e:
                    _logger.warning("⚠️ Không fetch được children cho combo %s: %s", combo_code, e)

            # 🔥 TẠO/CẬP NHẬT BOM TỪ CHILDREN
            _write_bom_from_children(tmpl, children_data or [], qty_divider)
            _logger.info("✅ Đã cập nhật BOM cho combo đã tồn tại: %s", combo_code)
            return combo_prod

        # === Chưa có -> tạo mới ===
        _logger.info("🆕 Tạo mới combo product: %s", combo_code)
        
        vals = {
            'name': combo_name or combo_code,
            'default_code': combo_code,
            'type': 'consu',  # Consumable/Goods (thay vì service)
            'sale_ok': True,
            'purchase_ok': False,
        }
        
        # Set storable nếu có field
        if 'is_storable' in ProductTmpl._fields:
            vals['is_storable'] = True
        
        if combo_uom:
            vals['uom_id'] = combo_uom.id
            vals['uom_po_id'] = combo_uom.id
        
        try:
            tmpl = ProductTmpl.create(vals)
            # Check for existing product.product with same template and empty combination_indices
            existing_combo_prod = Product.search([
                ('product_tmpl_id', '=', tmpl.id),
                ('combination_indices', '=', False)
            ], limit=1)
            if existing_combo_prod:
                combo_prod = existing_combo_prod
                _logger.info("♻️ Đã tìm thấy combo product tồn tại: %s (id=%s)", combo_code, combo_prod.id)
            else:
                combo_prod = Product.create({
                    'product_tmpl_id': tmpl.id,
                    'default_code': combo_code
                })
                _logger.info("✅ Đã tạo combo product mới: %s (id=%s)", combo_code, combo_prod.id)
        except Exception as e:
            _logger.error("❌ Lỗi tạo combo product %s: %s", combo_code, e)
            return False

        # Fetch children nếu thiếu
        qty_divider = combo_qty_in_order  # Mặc định: children từ đơn hàng cần chia
        if not children_data and sale_headers:
            try:
                master = combo_data.get("ProductID") or combo_data.get("ProductId") or combo_code
                kids = self.get_combo_children_by_product(master, sale_headers) or []
                children_data = [{
                    "ProductIDText": (k.get("ProductIDText") or "").strip(),
                    "Description": (k.get("Description") or k.get("ProductIDText") or "").strip(),
                    "UnitIDText": (k.get("UnitIDText") or "Cái").strip(),
                    "Amount": float(k.get("Amount") or 1.0),
                    "Price": float(k.get("Price") or 0.0),
                } for k in kids]
                qty_divider = 1.0  # ✅ Data từ API riêng = BASE qty, không cần chia
            except Exception as e:
                _logger.warning("⚠️ Không fetch được children: %s", e)

        # Tạo BOM từ children
        _write_bom_from_children(tmpl, children_data or [], qty_divider)
        
        return combo_prod


    def _get_misa_token(self):
            # Step 1: Đăng nhập lấy cookie
            login_url = "https://amisapp.misa.vn/APIS/AuthenAPI/api/Account/login"
            login_payload = {
                "UserName": "thanhluan.hlv@gmail.com",
                "Password": "ThanhLuan1303@"
            }
            headers_login = {
                "Content-Type": "application/json",
                "Content-Length": str(len(str(login_payload).replace("'", '"'))),  # optional nhưng an toàn
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36",
                "Origin": "https://amisapp.misa.vn",
                "Referer": "https://amisapp.misa.vn/",
                "Accept": "application/json, text/plain, */*",
                "Host": "amisapp.misa.vn",
                "TenantID":"039c3227-6ba8-49ba-93f5-bde3e8e1f533",
                "cookie":"x-culture=vi; _gid=GA1.2.129736177.1752161341; x-deviceid=cd54430e-8811-4acd-8585-a3709bc0cfd8; _ga_2B9RDZ4E89=GS2.1.s1752161339$o1$g1$t1752161619$j53$l0$h0; x-lastapp=Apps%3B%2Fmarket%2F; x-tenantid=47ab503b-99d5-4eb8-aa11-24927abb3585; _gat_gtag_UA_34323757_8=1; _ga_4N8J1W6EBF=GS2.1.s1752161340$o1$g1$t1752161738$j60$l0$h0; _ga=GA1.1.1231489114.1752161339; _ga_0G4YSV5CQ8=GS2.1.s1752161340$o1$g1$t1752161738$j60$l0$h0"

            }

            _logger.info("content_lenght %s",str(len(str(login_payload).replace("'", '"'))))

            session = requests.Session()
            response = session.post(login_url, json=login_payload, headers=headers_login)

            _logger.warning("Login response: %s", response.json())

            if response.status_code != 200 or not response.json().get("Success"):
                raise Exception("❌ Lỗi đăng nhập bước 1")

            # Step 2: Lấy cookie cần thiết
            cookies_dict = session.cookies.get_dict()
            _logger.warning("Cookies nhận được: %s", cookies_dict)

            x_sessionid = cookies_dict.get("x-sessionid")
            x_tenantid = cookies_dict.get("x-tenantid")

            if not x_sessionid or not x_tenantid:
                raise Exception("❌ Thiếu x-sessionid hoặc x-tenantid trong cookie")

            # Step 3: Gọi API lấy token thật
            token_url = "https://actapp.misa.vn/g1/api/auth/v1/account/login/misa_id"
            form_data = {
                "sid": x_sessionid,
                "dbid": "f4b18d63-6c99-4a53-b974-f6208e84fced",
                "tid": x_tenantid,
                "mid": "1547cc69-a995-421e-9134-7736dabe6cb9"
            }
            headers_token = {
                "Content-Type": "application/x-www-form-urlencoded",
                "x-device": "693017cdc24074e96e4756afbf2b6ab6"
            }

            response2 = session.post(token_url, data=form_data, headers=headers_token)
            json_data = response2.json()
            _logger.warning("Response lấy token: %s", json_data)

            if not response2.ok or not json_data.get("Success"):
                raise Exception("❌ Lỗi khi lấy AccessToken bước 2")

            access_token = json_data.get("Data", {}).get("AccessToken", {}).get("Token", "")
            return access_token

    def _fetch_with_retry(self, url, headers, payload):
        """Fetch API with retry on token expiration"""
        safe_headers = dict(headers or {})
        for key in ("Authorization", "Cookie", "cookie"):
            if key in safe_headers:
                safe_headers[key] = "***MASKED***"

        # _logger.info("[MISA API REQUEST] url=%s headers=%s payload=%s", url, safe_headers, json.dumps(payload, ensure_ascii=False)[:4000])
        try:
            response = requests.post(url, headers=headers, json=payload, timeout=30)
        except Exception:
            _logger.exception("[MISA API REQUEST ERROR] url=%s payload=%s", url, json.dumps(payload, ensure_ascii=False)[:4000])
            raise

        # _logger.info(
        #     "[MISA API RESPONSE] url=%s status=%s headers=%s body=%s",
        #     url,
        #     response.status_code,
        #     dict(response.headers),
        #     (response.text or "")[:4000],
        # )
        if response.status_code == 401:
            _logger.warning("🔁 Token hết hạn, đang đăng nhập lại...")
            new_token = self._get_misa_token()
            _logger.info("🔑 Đăng nhập thành công, token mới: %s", new_token)
            headers["Authorization"] = f"Bearer {new_token}"
            retry_headers = dict(headers or {})
            for key in ("Authorization", "Cookie", "cookie"):
                if key in retry_headers:
                    retry_headers[key] = "***MASKED***"
            _logger.info("[MISA API RETRY REQUEST] url=%s headers=%s payload=%s", url, retry_headers, json.dumps(payload, ensure_ascii=False)[:4000])
            try:
                response = requests.post(url, headers=headers, json=payload, timeout=30)
            except Exception:
                _logger.exception("[MISA API RETRY ERROR] url=%s payload=%s", url, json.dumps(payload, ensure_ascii=False)[:4000])
                raise
            _logger.info(
                "[MISA API RETRY RESPONSE] url=%s status=%s headers=%s body=%s",
                url,
                response.status_code,
                dict(response.headers),
                (response.text or "")[:4000],
            )
        return response

    def search_invoice_api(self, query):
        """API tìm hóa đơn theo mã Đề nghị xuất thay vì Tên Khách Hàng (3 bước)."""
        token = self._get_misa_token()
        headers = self.env['misa.config'].get_default_headers(token)
        
        # Bước 1: Tìm Đề nghị xuất hóa đơn
        url_req = "https://actapp.misa.vn/g2/api/sa/v1/sa_invoice_request/paging_filter_v2"
        payload_req = self.env['misa.config'].get_invoice_request_payload(query)
        resp_req = self._fetch_with_retry(url_req, headers, payload_req)
        
        if resp_req.status_code != 200:
            return resp_req
            
        data_req = resp_req.json()
        page_data_req = data_req.get("Data", {}).get("PageData", [])
        
        class MockResponse:
            status_code = 200
            def __init__(self, data):
                self._data = data
            def json(self):
                return self._data

        if not page_data_req:
            return MockResponse({"Success": True, "Data": {"PageData": []}})
            
        req_info = page_data_req[0]
        target_req_id = req_info.get("refid")
        target_customer = req_info.get("account_object_name")
        
        if not target_customer or not target_req_id:
            return MockResponse({"Success": True, "Data": {"PageData": []}})
            
        # Bước 2: Tìm danh sách Hóa đơn của khách hàng này
        url_inv = "https://actapp.misa.vn/g2/api/sa/v1/sa_invoice_get/paging_filter_v2"
        payload_inv = self.env['misa.config'].get_invoice_full_search_payload(target_customer)
        resp_inv = self._fetch_with_retry(url_inv, headers, payload_inv)
        
        if resp_inv.status_code != 200:
            return resp_inv
            
        data_inv = resp_inv.json()
        page_data_inv = data_inv.get("Data", {}).get("PageData", [])
        
        # Bước 3: Lọc lấy các hóa đơn thuộc về Đề nghị xuất này
        matched_invs = [inv for inv in page_data_inv if inv.get("sa_invoice_request_refid") == target_req_id]
        
        # Cập nhật lại PageData với kết quả đã lọc
        if "Data" not in data_inv:
            data_inv["Data"] = {}
        data_inv["Data"]["PageData"] = matched_invs
        
        return MockResponse(data_inv)

    def preview_invoice_api(self, refid, date):
        """API lấy link PDF của Invoice."""
        token = self._get_misa_token()
        headers = self.env['misa.config'].get_default_headers(token)
        payload = self.env['misa.config'].get_invoice_preview_payload(refid, date)

        def _preview_url(gateway):
            return (
                f"https://actapp.misa.vn/{gateway}/api/einvoice/v1/einvoice/preview_one"
                "?viewType=1&&publishType=1&&decreeType=3&&isFollowSerial=true"
            )

        def _has_preview_data(response):
            if not response.ok:
                return False
            try:
                data = response.json()
            except Exception:
                _logger.exception("[MISA INVOICE PREVIEW] Invalid JSON from gateway")
                return False
            return bool(data.get("Data"))

        g2_url = _preview_url("g2")
        try:
            _logger.info("[MISA INVOICE PREVIEW] Trying gateway g2")
            response = self._fetch_with_retry(g2_url, headers, payload)
            if _has_preview_data(response):
                return response
            _logger.warning(
                "[MISA INVOICE PREVIEW] Gateway g2 missing preview data status=%s body=%s",
                response.status_code,
                (response.text or "")[:4000],
            )
        except Exception as e:
            _logger.exception("[MISA INVOICE PREVIEW] Gateway g2 request error: %s", e)

        g1_url = _preview_url("g1")
        _logger.info("[MISA INVOICE PREVIEW] Retrying gateway g1")
        return self._fetch_with_retry(g1_url, headers, payload)

    def _fetch_login_crm_token(self):
        """Fetch CRM token for MISA"""
        # Sử dụng session để duy trì cookie, bao gồm cả HttpOnly
        session = requests.Session()
        
        login_url = "https://amisapp.misa.vn/APIS/AuthenAPI/api/Account/login"
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "PostmanRuntime/7.44.1",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br,zstd",
            "Connection": "keep-alive",
            "cookie":"x-culture=vi; x-culture-custom=vi; x-deviceid=3fb273d0-dc87-4dc5-b8f0-be3ac7326cf9; TS01f24fc0=019ba1692d374aa2800e4dd3c3b0c947209c3208135a7706e925464b831498efabe058c022e876f0024124e5793b913070df7bdf8dcaeab0a3c2c127807b6a6a307969db0991221da0d38f06735cb173e45ad7d5fc; _ga_YS0Q78T7TT=GS2.1.s1750565472$o1$g1$t1750565500$j32$l0$h0; _gcl_aw=GCL.1750650790.Cj0KCQjw097CBhDIARIsAJ3-nxf5CAGo6Iss3WGJahKvADR9n_fhjMTsednMtevazje6V0VOuYBjcuwaAp4eEALw_wcB; _gcl_gs=2.1.k1$i1750650785$u212452100; _gcl_au=1.1.786027192.1750650790; _fbp=fb.1.1750650790447.993531807792971466; _ga_VEZHTBQZEB=GS2.1.s1750738193$o3$g0$t1750738200$j53$l0$h0; _ga_325VRLQJQ5=GS2.1.s1750747654$o2$g1$t1750748443$j59$l0$h0; _ga_2B9RDZ4E89=GS2.1.s1751102821$o17$g0$t1751102821$j60$l0$h0; _clck=1rnz2o2%7C2%7Cfx6%7C0%7C2000; _ga_2HDB2Z79W3=GS2.1.s1751197863$o3$g0$t1751197863$j60$l0$h0; _clsk=1t0rssn%7C1751197863946%7C1%7C1%7Cq.clarity.ms%2Fcollect; _gid=GA1.2.1944009150.1751197865; mp_d4b9a27f37c8580e68a0df2684f60882_mixpanel=%7B%22distinct_id%22%3A%20%22acd1603f-e988-4099-ac2a-6538a6a62433%22%2C%22%24device_id%22%3A%20%221979a626dce937-0611e5b707d1ec-46534358-1fa400-1979a626dce937%22%2C%22%24initial_referrer%22%3A%20%22%24direct%22%2C%22%24initial_referring_domain%22%3A%20%22%24direct%22%2C%22__mps%22%3A%20%7B%7D%2C%22__mpso%22%3A%20%7B%7D%2C%22__mpus%22%3A%20%7B%7D%2C%22__mpa%22%3A%20%7B%7D%2C%22__mpu%22%3A%20%7B%7D%2C%22__mpr%22%3A%20%5B%5D%2C%22__mpap%22%3A%20%5B%5D%2C%22%24name%22%3A%20%22NGUY%E1%BB%84N%20TH%C3%80NH%20LU%C3%82N%22%2C%22%24email%22%3A%20%22thanhluan.hlv%40gmail.com%22%2C%22%24user_id%22%3A%20%22acd1603f-e988-4099-ac2a-6538a6a62433%22%2C%22company_code%22%3A%20%223R2PY2F4%22%2C%22isUserAction%22%3A%20true%2C%22feature_category%22%3A%20%22CRM%20Cross%20Sale%22%7D; _ga_8M2C69NVRV=GS2.1.s1751209900$o8$g0$t1751209900$j60$l0$h1614643248; cf_clearance=_tH0pjQMfsbas6Cr9hJZ7DkbNkGmp1E_M_Mdh2twWYs-1751215054-1.2.1.1-745dznRXQmrz_dkExdVLZlkigOlHnRWM4HxnpAGSJMeq8mYtVZsbVetD1rP3L90UtFd9SIOloEvC81rE19WM1y4yR4SjK1DPK799B_OQjeJf3yIYuQEMCpK344Uvg_FjU0gfaX8XqCqUMjpzjCpCzI0BGqRJWfP8bQTZoXLBbQjOOwgKK0sSM3NIJEpDx8zVW.iN8EpF2q4dTAe69XFqaS.SyPIflT8.d90wssNmZL4Jt5U3aHzC4NjLRWsu9tkbRM4P6q2BtuXSr0MuUtoKXGjNPOXc0yk7GyH5.SC5zZP8exn3pS2hYsnwdxe2xAHz5ZLLeFmlenZSmZRH.PfgcCLhG7ZbHbCFm5SGwpPWCVI; _ga_W2GLLHS86T=GS2.1.s1751215708$o4$g0$t1751215708$j60$l0$h0; x-tenantid=47ab503b-99d5-4eb8-aa11-24927abb3585; TS01b5a6fe=019ba1692d2e99bc81c5810436f6bc5c3be19d2e9fd1e8585a8ad41fc26b685cb8076f01c0e2c86649d069289cc61362eaad4df413; _gat_gtag_UA_34323757_8=1; _ga_4N8J1W6EBF=GS2.1.s1751223931$o13$g1$t1751226939$j12$l0$h0; _ga=GA1.1.46578994.1750565329; _ga_0G4YSV5CQ8=GS2.1.s1751223931$o12$g1$t1751226939$j12$l0$h0"
        }
        payload = {
            "PassWord": "ThanhLuan1303@",
            "UserName": "thanhluan.hlv@gmail.com",
        }

        # Step 1: Gửi request login
        response = session.post(login_url, headers=headers, json=payload)
        _logger.warning("Đăng nhập MISA với response: %s", response.json())
        _logger.warning("All response headers: %s", dict(response.headers))
        _logger.warning("Full response text: %s", response.text)
        _logger.warning("All cookies in session: %s", dict(session.cookies.get_dict()))  # Log tất cả cookie

        if response.status_code != 200:
            raise Exception(f"Login failed: {response.status_code} - {response.text}")

        # Lấy tất cả cookie từ session (bao gồm HttpOnly)
        cookies_dict = session.cookies.get_dict()
        _logger.warning("Cookies nhận được từ session: %s", cookies_dict)

        # Kiểm tra các cookie cần thiết (dựa vào session)
        x_sessionid = cookies_dict.get("x-sessionid")
        x_tenantid = cookies_dict.get("x-tenantid")

        if not x_sessionid or not x_tenantid:
            raise Exception("Missing required cookies from login response.")

        # Xây dựng cookie header từ session
        cookie_header = ""
        for name, value in cookies_dict.items():
            cookie_header += f"{name}={value}; "
        cookie_header += "x-login-from=basic"

        # Step 2: Gọi HTML page CRM
        crm_url = "https://amisapp.misa.vn/CRM/"
        crm_headers = {
            "Cookie": cookie_header,
            "User-Agent": "PostmanRuntime/7.44.1",
        }
        crm_response = session.get(crm_url, headers=crm_headers)

        if crm_response.status_code != 200:
            raise Exception(f"CRM page fetch failed: {crm_response.status_code}")

        html_content = crm_response.text

        # Step 3: Regex tìm token
        match = re.search(r'"token"\s*:\s*"(?P<token>ey[\w\-\.]+)"', html_content)
        

        if not match:
            raise Exception("Token not found in CRM HTML")
        return match.group("token")

    #=== Hàm lấy OwnerIDText và SaleOrderDate từ SaleOrder ===#
    def get_saleorder_owner_and_date(self, sale_order_id: int | str, sale_headers: object) -> dict:
        """
        Hàm này dùng để lấy ra mã nhân viên sale (OwnerIDText, chỉ lấy phần trong ngoặc),
        ngày đơn hàng (SaleOrderDate), thông tin giao hàng từ CustomField14,
        tên người nhận hàng (ShippingContactIDText),
        mã vận đơn (OtherSysOrderCode, DeliveryOrderNumber),
        hình thức thanh toán (CustomField15 - httt),
        và hình thức giao hàng (CustomField16 - htgh)
        - Gọi API: POST https://amisapp.misa.vn/crm/g1/api/business/SaleOrder/FormDataNew/SaleOrder/37/4
        - Payload: {"ID": "<sale_order_id>", "MISAEntityState": "2"}
        - Header: truyền vào từ biến sale_headers (đã build sẵn)
        """
        url = "https://amisapp.misa.vn/crm/g1/api/business/SaleOrder/FormDataNew/SaleOrder/37/4"
        payload = {"ID": str(sale_order_id), "MISAEntityState": "2"}

        try:
            # Gọi API lấy thông tin chi tiết đơn hàng
            resp = requests.post(url, headers=sale_headers, json=payload, timeout=30)
            if resp.status_code != 200:
                _logger.error("FormDataNew(SaleOrder) HTTP %s: %s", resp.status_code, resp.text[:300])

                return {"owner_code": None, "sale_order_date": None, "misa_delivery": None, "shipping_contact": None, "httt": None, "htgh": None}
                # return {"owner_code": None, "sale_order_date": None, "misa_delivery": None, "other_sys_order_code": None, "delivery_order_number": None, "shipping_contact": None}
            data = resp.json() if resp.content else {}
        except Exception as ex:
            _logger.exception("Lỗi gọi FormDataNew SaleOrder (ID=%s): %s", sale_order_id, ex)
            return {"owner_code": None, "sale_order_date": None, "misa_delivery": None, "shipping_contact": None, "httt": None, "htgh": None}
            # return {"owner_code": None, "sale_order_date": None, "misa_delivery": None, "other_sys_order_code": None, "delivery_order_number": None, "shipping_contact": None}

        # Lấy dữ liệu chi tiết đơn hàng từ response
        cd = (data or {}).get("Data", {}).get("CurrentData", {}) or {}

        # Lấy OwnerIDText và chỉ lấy phần trong ngoặc
        raw_owner = str(cd.get("OwnerIDText") or "").strip()
        owner_code = None
        if raw_owner:
            m = re.search(r"\(([^)]+)\)\s*$", raw_owner)
            owner_code = (m.group(1).strip() if m else raw_owner)

        # Lấy ngày đơn hàng và chuyển về kiểu date
        date_text = cd.get("SaleOrderDate") or None
        sale_date = None
        if date_text:
            try:
                sale_date = dtparser.parse(str(date_text)).date()
            except Exception:
                _logger.warning("Không parse được SaleOrderDate='%s'", date_text)
                sale_date = None

        # Lấy thông tin giao hàng từ CustomField14
        misa_delivery = (cd.get("CustomField14") or "").strip() or None

        # Lấy mã vận đơn từ OtherSysOrderCode và DeliveryOrderNumber
        other_sys_order_code = (cd.get("OtherSysOrderCode") or "").strip() or None
        delivery_order_number = (cd.get("DeliveryOrderNumber") or "").strip() or None

        # Lấy tên người nhận hàng từ ShippingContactIDText
        shipping_contact = (cd.get("ShippingContactIDText") or "").strip() or None

        # Lấy hình thức thanh toán và hình thức giao hàng
        httt = (cd.get("CustomField15") or "").strip() or None  # Hình thức thanh toán
        htgh = (cd.get("CustomField16") or "").strip() or None  # Hình thức giao hàng

        # Trả về kết quả dạng dict
        return {
            "owner_code": owner_code,
            "sale_order_date": sale_date,
            "misa_delivery": misa_delivery,
            "shipping_contact": shipping_contact,
            "other_sys_order_code": other_sys_order_code,
            "delivery_order_number": delivery_order_number,
            "httt": httt,
            "htgh": htgh
        }
    


    def extract_shipping_address_from_data(self, cd):
        """
        Helper tách biệt logic lấy/build địa chỉ từ dict dữ liệu (CurrentData).
        Dùng để tái sử dụng ở chỗ khác (ví dụ resync).
        ƯU TIÊN TUYỆT ĐỐI GIAO HÀNG (Shipping) -> rồi mới tới Billing.
        """
        # Helper: nối các phần địa chỉ, bỏ None/"" và làm sạch dấu phẩy thừa
        def _join_address_parts(*parts):
            items = [str(p).strip() for p in parts if p and str(p).strip()]
            addr = ", ".join(items)
            # làm sạch: nhiều dấu phẩy/space -> 1, bỏ dấu phẩy ở đầu/cuối
            addr = re.sub(r"\s*,\s*", ", ", addr)
            addr = re.sub(r"(,\s*){2,}", ", ", addr).strip(", ").strip()
            return addr or None

        # Helper: chuẩn hóa vài tên hành chính phổ biến
        def _normalize_admin(s: str | None) -> str | None:
            if not s:
                return s
            mapping = {
                "tphcm": "Thành phố Hồ Chí Minh",
                "TPHCM": "Thành phố Hồ Chí Minh",
                "BR-VT": "Bà Rịa - Vũng Tàu",
                "đồng nai": "Tỉnh Đồng Nai",
                "Đồng Nai": "Tỉnh Đồng Nai",
                "q8": "Quận 8",
            }
            raw = s.strip()
            return mapping.get(raw, raw)

        # CHIẾN LƯỢC:
        # 1. Build từ component Shipping -> return
        # 2. Lấy field ShippingAddress -> return
        # 3. Build từ component Billing -> return
        # 4. Lấy field BillingAddress -> return
        
        # DEBUG Log raw address fields
        _logger.info("📍 MISA Resync Addr Debug: ShipAddr='%s', ShipStreet='%s', ShipWard='%s', ShipDist='%s', ShipProv='%s'", 
                     cd.get("ShippingAddress"), cd.get("ShippingStreet"), cd.get("ShippingWardIDText"), 
                     cd.get("ShippingDistrictIDText"), cd.get("ShippingProvinceIDText"))

        # 1. Component Shipping
        ship_parts = [
            cd.get("ShippingStreet"),
            _normalize_admin(cd.get("ShippingWardIDText")),
            _normalize_admin(cd.get("ShippingDistrictIDText")),
            _normalize_admin(cd.get("ShippingProvinceIDCustomText") or cd.get("ShippingProvinceIDText")),
            cd.get("ShippingCountryIDText")
        ]
        
        # Check if we have significant components (Street OR Ward OR District)
        # Avoid matching just "Việt Nam" or "Province" if everything else is empty
        has_significant_ship = (
            cd.get("ShippingStreet") or 
            cd.get("ShippingWardIDText") or 
            cd.get("ShippingDistrictIDText")
        )
        
        built_ship = _join_address_parts(*ship_parts)
        
        # Nếu có thành phần quan trọng (Street/Ward/District) -> Dùng components
        if built_ship and has_significant_ship:
            _logger.info("   -> Using Shipping Components: %s", built_ship)
            return built_ship
            
        # 2. Field ShippingAddress (Fallback)
        shipping_address = (cd.get("ShippingAddress") or "").strip()
        if shipping_address:
            _logger.info("   -> Using ShippingAddress field: %s", shipping_address)
            return shipping_address

        # 3. Component Billing
        bill_parts = [
            cd.get("BillingStreet"),
            _normalize_admin(cd.get("BillingWardIDText")),
            _normalize_admin(cd.get("BillingDistrictIDText")),
            _normalize_admin(cd.get("BillingProvinceIDCustomText") or cd.get("BillingProvinceIDText")),
            cd.get("BillingCountryIDText")
        ]
        built_bill = _join_address_parts(*bill_parts)
        
        # Tương tự check BillingStreet
        if built_bill and cd.get("BillingStreet"):
            return built_bill

        # 4. Field BillingAddress
        billing_address = (cd.get("BillingAddress") or "").strip()
        if billing_address:
            return billing_address

        # 5. Fallback cuối cùng: nếu có built_ship (dù thiếu Street) thì vẫn trả về còn hơn null?
        # Hoặc built_bill?
        if built_ship:
             return built_ship
        if built_bill:
             return built_bill

        return None

    def get_shipping_address(self, sale_order_id, order_ref=None, token=None):
        """
        Lấy địa chỉ giao hàng từ MISA CRM.
        Ưu tiên:
        1) Data.CurrentData.ShippingAddress
        2) Data.CurrentData.BillingAddress
        3) Tự build từ các trường Shipping* (fallback sang Billing* nếu thiếu)
        """
        # Helper: nối các phần địa chỉ, bỏ None/"" và làm sạch dấu phẩy thừa
        def _join_address_parts(*parts):
            items = [str(p).strip() for p in parts if p and str(p).strip()]
            addr = ", ".join(items)
            # làm sạch: nhiều dấu phẩy/space -> 1, bỏ dấu phẩy ở đầu/cuối
            addr = re.sub(r"\s*,\s*", ", ", addr)
            addr = re.sub(r"(,\s*){2,}", ", ", addr).strip(", ").strip()
            return addr or None

        # Helper: chuẩn hóa vài tên hành chính phổ biến (có thể mở rộng theo nhu cầu)
        def _normalize_admin(s: str | None) -> str | None:
            if not s:
                return s
            mapping = {
                "tphcm": "Thành phố Hồ Chí Minh",
                "TPHCM": "Thành phố Hồ Chí Minh",
                "BR-VT": "Bà Rịa - Vũng Tàu",
                "đồng nai": "Tỉnh Đồng Nai",
                "Đồng Nai": "Tỉnh Đồng Nai",
                "q8": "Quận 8",
            }
            raw = s.strip()
            return mapping.get(raw, raw)

        session = requests.Session()
        api_url = "https://amisapp.misa.vn/crm/g1/api/business/SaleOrder/FormDataNew/SaleOrder/37/4"
        api_headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}" if token else "",
            "User-Agent": "PostmanRuntime/7.44.1",
            "Accept": "*/*",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "companycode": "3R2PY2F4",
        }
        api_payload = {"ID": str(sale_order_id), "MISAEntityState": "2"}

        api_response = session.post(api_url, headers=api_headers, json=api_payload) 

        # Nếu không 200 thì vẫn ráng parse JSON để fallback; nếu parse fail thì trả sale_order_id
        try:
            response_data = api_response.json()
        except Exception:
            _logger.exception("Không parse được JSON; trả về sale_order_id làm fallback.")
            return str(sale_order_id)

        try:
            cd = (response_data or {}).get("Data", {}).get("CurrentData", {}) or {}

            # 1) Ưu tiên trường đã gộp sẵn
            shipping_address = (cd.get("ShippingAddress") or "").strip()
            billing_address = (cd.get("BillingAddress") or "").strip()
            if shipping_address:
                return shipping_address
            if billing_address:
                return billing_address

            # 2) Tự build từ các phần tử (ưu tiên Shipping*, thiếu thì mượn Billing*)
            #    Dùng các nhãn *Text và *CustomText nếu có
            ship_street = cd.get("ShippingStreet") or cd.get("BillingStreet")
            ship_ward = cd.get("ShippingWardIDText") or cd.get("BillingWardIDText")
            ship_district = cd.get("ShippingDistrictIDText") or cd.get("BillingDistrictIDText")
            ship_province = (
                cd.get("ShippingProvinceIDCustomText")
                or cd.get("ShippingProvinceIDText")
                or cd.get("BillingProvinceIDCustomText")
                or cd.get("BillingProvinceIDText")
            )
            ship_country = cd.get("ShippingCountryIDText") or cd.get("BillingCountryIDText")

            # Chuẩn hóa vài giá trị hành chính thường gặp
            ship_ward = _normalize_admin(ship_ward)
            ship_district = _normalize_admin(ship_district)
            ship_province = _normalize_admin(ship_province)

            built = _join_address_parts(ship_street, ship_ward, ship_district, ship_province, ship_country)
            if built:
                return built

            # 3) Thua nữa thì lấy Account/Contact text làm fallback mềm, rồi tới sale_order_id
            # (đề phòng dữ liệu quá thiếu)
            acc = (cd.get("AccountIDText") or "").strip()
            contact = (cd.get("ContactIDText") or "").strip()
            soft = _join_address_parts(contact, acc)
            return soft or str(sale_order_id)

        except Exception as e:
            _logger.exception("❌ Lỗi khi xử lý response: %s. Dùng tạm sale_order_id.", e)
            return str(sale_order_id)

        # def get_list_product_by_order_crm(self,api_url,header, payload):
        #     session = requests.Session()

        #     response = session.post(api_url, headers=header, json=payload)
        #     _logger.warning("📦response %s", response)
        #     if response.status_code != 200:
        #         raise Exception(f"API call failed: {response.status_code} - {response.text}")

        #     try:
        #         return response.json().get("Data", [])
        #     except Exception as e:
        #         raise Exception(f"Lỗi khi xử lý response JSON: {e}")


    def get_list_product_by_order_crm(self, api_url, header, payload):
        """
        Lấy TOÀN BỘ sản phẩm của đơn hàng từ MISA CRM.
        Xử lý phân trang dựa vào Total (vì PageCount không tin cậy).
        Có retry khi MISA trả về Success=False (chờ 5s giữa các lần).
        """
        session = requests.Session()
        all_products = []
        page = 1
        page_size = 20  # MISA cố định
        max_pages = 100  # Giới hạn an toàn
        total_expected = None  # Sẽ được set từ response đầu tiên
        max_retry_per_page = 3  # Tối đa 3 lần retry per page
        retry_delay = 5  # Chờ 5 giây giữa các lần retry
        
        while page <= max_pages:
            # Cập nhật payload cho trang hiện tại
            current_payload = payload.copy()
            current_payload['Page'] = page
            current_payload['Start'] = (page - 1) * page_size
            
            retry_count = 0
            success_response = None
            
            # ===== RETRY LOOP cho Success=False =====
            while retry_count < max_retry_per_page:
                try:
                    _logger.info("📄 Fetching MISA products: Page %d (Start=%d) [Attempt %d/%d]", 
                                page, current_payload['Start'], retry_count + 1, max_retry_per_page)
                    
                    response = session.post(api_url, headers=header, json=current_payload)
                    
                    if response.status_code != 200:
                        _logger.error("❌ API call failed at page %d: %s - %s", 
                                    page, response.status_code, response.text)
                        break  # Thoát vòng retry nếu lỗi HTTP
                    
                    data = response.json()
                    
                    if not data.get("Success", True):
                        retry_count += 1
                        err_msg = data.get("Message", "Unknown error")
                        _logger.warning("⚠️ MISA returned Success=False at page %d [Attempt %d/%d]: %s", 
                                    page, retry_count, max_retry_per_page, err_msg)
                        
                        if retry_count < max_retry_per_page:
                            _logger.info("⏳ Chờ %d giây rồi retry...", retry_delay)
                            time.sleep(retry_delay)
                            continue  # Retry
                        else:
                            _logger.error("❌ Đã retry %d lần mà MISA vẫn Success=False. Dừng.", max_retry_per_page)
                            break  # Thoát vòng retry sau khi hết lần retry
                    
                    # ✅ Success=True → lưu response và thoát vòng retry
                    success_response = data
                    break
                    
                except requests.exceptions.RequestException as e:
                    _logger.exception("❌ Request error at page %d (Attempt %d): %s", page, retry_count + 1, e)
                    break  # Không retry cho network error
                except Exception as e:
                    _logger.exception("❌ Unexpected error at page %d (Attempt %d): %s", page, retry_count + 1, e)
                    break  # Không retry cho lỗi khác
            
            # Nếu không lấy được response sau retry → break khỏi main loop
            if success_response is None:
                break
                
            # Xử lý response từ retry loop
            if success_response is None:
                continue  # Skip nếu không lấy được response sau tất cả retry
            
            data = success_response
            
            # Lấy dữ liệu trang hiện tại
            products = data.get("Data", []) or []
            page_count_api = data.get("PageCount", 1)  # Không tin cậy
            total_api = data.get("Total", 0)
            
            # Lưu total từ lần đầu
            if total_expected is None:
                total_expected = total_api
            
            # Tính số trang thực tế dựa vào Total
            actual_pages_needed = (total_expected + page_size - 1) // page_size  # Làm tròn lên
            
            _logger.info("   ✓ Page %d/%d: %d products | Total=%d (API PageCount=%d - IGNORED)", 
                        page, actual_pages_needed, len(products), total_api, page_count_api)
            
            # Thêm vào danh sách tổng
            all_products.extend(products)
            
            # ===== ĐIỀU KIỆN DỪNG (DỰA VÀO TOTAL, KHÔNG DỰA VÀO PageCount) =====
            # Dừng nếu:
            # 1. Không còn data trong response
            if len(products) == 0:
                _logger.info("   → Dừng: Trang %d không có dữ liệu", page)
                break
            
            # 2. Đã lấy đủ số lượng theo Total
            if len(all_products) >= total_expected:
                _logger.info("   → Dừng: Đã đủ %d/%d sản phẩm", len(all_products), total_expected)
                break
            
            # 3. Đã fetch đủ số trang tính toán
            if page >= actual_pages_needed:
                _logger.info("   → Dừng: Đã fetch đủ %d trang", actual_pages_needed)
                break
            
            page += 1
        
        if page > max_pages:
            _logger.warning("⚠️ Reached max_pages limit (%d), may have missing data!", max_pages)
        
        _logger.info("✅ Completed: %d products from %d page(s) (Expected: %d)", 
                    len(all_products), page, total_expected or 0)
        
        # 🔁 GIỮ NGUYÊN, KHÔNG LOẠI COMBO CHA
        return all_products
        

    # === LẤY THÀNH PHẦN COMBO TỪ API g1/Product/DataSubPaging ===
    def get_combo_children_by_product(self, combo_product_id: int | str, sale_headers: object) -> list[dict]:
        """
        Trả về danh sách children combo từ API MISA (rút gọn logger).
        """
        url = "https://amisapp.misa.vn/crm/g1/api/business/Product/DataSubPaging"

        payload = {
            "Columns": "",
            "Sorts": [],
            "Start": 0,
            "Page": 1,
            "PageSize": 200,
            "Filters": [],
            "DefaultTotal": False,
            "IsMappingData": False,
            "MappingValueObject": {
                "MasterID": str(combo_product_id),
                "TableName": "product",
                "MasterKey": "ProductID",
                "SumColumn": ""
            },
            "IsApproved": False,
            "CustomPagingData": {
                "SubFormConfig": {
                    "ColumnFieldSubForm": "",
                    "ColumnAggregateSubForm": "",
                    "TableName": "product",
                    "ParentIDKey": "ProductID",
                    "IsBringSerialType": False,
                    "AggregateField": []
                }
            },
            "IsUsedELTS": True,
            "ListGmailPage": [],
            "ListFacebookPage": {},
            "IsListPaging": True,
            "IsGetCache": True,
            "IsCheckInactive": False,
            "IsConverted": False,
            "SessionID": "combo-fetch",
            "AISearchKeyword": ""
        }

        try:
            resp = requests.post(url, headers=sale_headers, json=payload, timeout=30)

            if not resp.ok:
                _logger.warning("HTTP %s khi gọi combo children cho %s",
                                resp.status_code, combo_product_id)
                return []

            try:
                js = resp.json() if resp.content else {}
            except Exception as json_err:
                _logger.error("Lỗi parse JSON combo children: %s", json_err)
                return []

            if isinstance(js, dict):
                data = js.get("Data", []) or []
                return data if isinstance(data, list) else []

            return []

        except Exception as e:
            _logger.exception("Lỗi gọi Product/DataSubPaging (combo): %s", e)
            return []

    # === Lấy thông tin ID, TaxCode, AccountNumber của đối tác từ MISA CRM ===
    def get_account_identity(self, account_id: int | str, sale_headers: object) -> dict:
        """
        Lấy ID, TaxCode, AccountNumber của đối tác từ FormDataNew:
        POST https://amisapp.misa.vn/crm/g2/api/business/Account/FormDataNew/Account/28/4
        Payload: {"ID": "<AccountID>", "MISAEntityState": "2"}

        Trả về: {"id": "...", "taxcode": "...", "account_number": "..."}
        """
        url = "https://amisapp.misa.vn/crm/g2/api/business/Account/FormDataNew/Account/28/4"
        payload = {"ID": str(account_id), "MISAEntityState": "2"}

        try:
            resp = requests.post(url, headers=sale_headers, json=payload, timeout=30)
            if resp.status_code != 200:
                _logger.error("FormDataNew(Account) HTTP %s: %s", resp.status_code, resp.text[:300])
                return {}
            data = resp.json() if resp.content else {}
        except Exception as ex:
            _logger.exception("Lỗi gọi FormDataNew Account (AccountID=%s): %s", account_id, ex)
            return {}

        # Bóc dữ liệu linh hoạt: Data -> CurrentData / FormData / trả thẳng object
        obj = {}
        if isinstance(data, dict):
            obj = (
                ((data.get("Data") or {}).get("CurrentData"))
                or data.get("CurrentData")
                or data.get("FormData")
                or data
            )
        if not isinstance(obj, dict):
            _logger.warning("FormDataNew(Account) không có CurrentData hợp lệ. Raw keys: %s", list(data.keys()))
            obj = {}

        def pick(d, *keys):
            for k in keys:
                if k in d and d.get(k) not in (None, "", "null"):
                    return d.get(k)
            return None

        rid = pick(obj, "ID", "Id", "id")
        tax = pick(obj, "TaxCode", "taxCode", "taxcode")
        acc = pick(obj, "AccountNumber", "accountNumber", "account_number")

        result = {
            "id": (str(rid).strip() if rid is not None else None),
            "taxcode": (str(tax).strip() if tax else None),
            "account_number": (str(acc).strip() if acc else None),
        }
        _logger.info("FormDataNew(Account) OK id=%s tax=%s acc=%s", result["id"], result["taxcode"], result["account_number"])
        return result

    def map_address_to_tag_ids(self, env, addr_str):
        """
        Ánh xạ địa chỉ sang tag_ids (Tuyến) dựa trên cấu hình Keywords trong crm.tag.
        """
        if not addr_str:
            return []
        
        addr_lower = addr_str.lower()
        
        # 1. Lấy tất cả các tag có cấu hình keywords
        tags_with_keywords = env['crm.tag'].search([('misa_keywords', '!=', False)])
        
        matching_tags = env['crm.tag']
        
        for tag in tags_with_keywords:
            # Tách từ khóa theo dấu phẩy, loại bỏ khoảng trắng thừa
            keywords = [k.strip().lower() for k in tag.misa_keywords.split(',') if k.strip()]
            
            # Kiểm tra xem có từ khóa nào khớp với địa chỉ không
            if any(kw in addr_lower for kw in keywords):
                matching_tags |= tag
                
        if not matching_tags:
            return []
            
        return [(6, 0, matching_tags.ids)]

    # =========================================================================
    # CREATE AND SEARCH PRODUCT APIs
    # =========================================================================

    def _process_create_product(self, product):
        misa_config = self.env['misa.config']
        token = self._fetch_login_crm_token()
        if not token:
            raise Exception("Không lấy được Token đăng nhập MISA")

        headers = misa_config.get_crm_header(token)
        headers.update({"LayoutCode": "product", "X-Misa-Language": "vi-VN"})

        code = (product.default_code or "").strip()
        if not code:
            raise Exception("Sản phẩm chưa có Mã nội bộ (Internal Reference)")
        
        _logger.info(f"🚀 Bắt đầu đồng bộ SP: {code}")

        # --- A. TÌM ID NHÓM HÀNG (Fallback về Hàng hóa/23) ---
        odoo_cat_name = product.categ_id.name or "Hàng hóa"
        cat_id = self._get_category_id_by_name(headers, odoo_cat_name)
        if not cat_id:
             # Nếu không thấy nhóm riêng, tìm nhóm 'Hàng hóa', nếu ko thấy lấy ID 23
             cat_id = self._get_category_id_by_name(headers, "Hàng hóa") or 23 

        # --- B. TÌM ID ĐƠN VỊ TÍNH (Fallback về Cái/4) ---
        odoo_uom = product.uom_id.name or "Cái"
        unit_id, unit_text = self._find_dictionary_item(headers, "UsageUnitID", odoo_uom)
        if not unit_id:
            unit_id, unit_text = 4, "Cái"

        # --- C. TÌM ID THUẾ (Logic thông minh so sánh số) ---
        # Lấy amount thuế Odoo (5.0, 8.0...). Mặc định 10.
        odoo_tax_amount = product.taxes_id[0].amount if product.taxes_id else 10.0
        odoo_tax_name = product.taxes_id[0].name if product.taxes_id else ""
        
        # Hàm tìm kiếm thông minh bằng Regex
        tax_id, tax_text = self._find_tax_id_smart(headers, odoo_tax_amount, odoo_tax_name)

        # --- D. TÍNH CHẤT ---
        prop_id = 2 if product.type == 'service' else 1
        prop_text = "Dịch vụ" if product.type == 'service' else "Hàng hóa"

        # --- E. TẠO PAYLOAD ---
        payload = {
            "ProductCode": code,
            "ProductName": product.name,
            "ProductCategoryID": cat_id,
            "DefaultStockID": "29", 
            "DefaultStockIDText": "HLV",
            "ProductCategoryIDText": odoo_cat_name if cat_id != 23 else "Hàng hóa",
            "UsageUnitID": unit_id, 
            "UsageUnitIDText": unit_text,
            "ProductPropertiesID": prop_id,
            "ProductPropertiesIDText": prop_text,
            "TaxID": str(tax_id),
            "TaxIDText": tax_text,
            "UnitPrice": float(product.list_price or 0),
            "UnitPriceFixed": float(product.list_price or 0),
            "PurchasedPrice": float(product.standard_price or 0),
            "MISAEntityState": 1,
            "Active": True, "Inactive": False, "IsPublic": False, "FormLayoutID": 45,
            "Fields": [], "FieldsCustom": [], 
            "DataCustom": {
                "Avatar": "", 
                "CustomField13": None, 
                "CustomField15": code # Map mã vào trường custom theo yêu cầu cũ
            },
            "CustomTables": [], 
        }

        # --- F. GỬI REQUEST ---
        url = "https://amisapp.misa.vn/crm/g2/api/business/Product"
        _logger.info(f"📤 Payload: Tax={tax_text}({tax_id}) | Unit={unit_text}({unit_id})")

        session = self._get_retry_session()
        try:
            res = session.post(url, headers=headers, json=payload, timeout=30)
            res_json = res.json()

            if not res_json.get("Success"):
                # Parse lỗi chi tiết nếu có
                val_info = res_json.get("ValidateInfo", [])
                err_msg = res_json.get("UserMessage")
                if val_info:
                    err_msg = ", ".join([v.get("ErrorMessage", "") for v in val_info])
                raise Exception(f"MISA Từ chối: {err_msg}")

            # Parse ID trả về
            misa_id = self._parse_misa_id(res_json, code, headers)
            _logger.info(f"✅ Tạo thành công! MISA ID: {misa_id}")
            return misa_id

        except Exception as e:
            _logger.error(f"❌ Lỗi API Create: {e}")
            raise e

    # =========================================================================
    # HELPER FUNCTIONS
    # =========================================================================

    def _find_tax_id_smart(self, headers, odoo_amount, odoo_name):
        """Tìm thuế bằng cách lấy tất cả thuế MISA và so sánh số % (Regex)"""
        all_taxes = self._get_all_dictionary_items(headers, "TaxID")
        
        if not all_taxes:
            return "3", "10%" # Mặc định nếu lỗi mạng

        # Case 1: Không chịu thuế (0%)
        if odoo_amount == 0:
            name_upper = (odoo_name or "").upper()
            is_kct = any(x in name_upper for x in ["KCT", "KHÔNG CHỊU", "NO VAT"])
            for item in all_taxes:
                txt = item.get("text", "").upper()
                if is_kct and ("KCT" in txt or "KHÔNG CHỊU" in txt):
                    return str(item["id"]), item["text"]
                if not is_kct and "0%" in txt:
                    return str(item["id"]), item["text"]

        # Case 2: So sánh số (5%, 8%, 10%...)
        epsilon = 0.001
        for item in all_taxes:
            text = item.get("text", "")
            # Regex tìm số thập phân hoặc số nguyên trong chuỗi
            numbers = re.findall(r"[-+]?\d*\.\d+|\d+", text)
            if numbers:
                try:
                    val = float(numbers[0])
                    # So sánh trị tuyệt đối
                    if abs(val - odoo_amount) < epsilon:
                        return str(item["id"]), item["text"]
                except: continue
        
        # Nếu không tìm thấy khớp số -> Mặc định 10%
        return "3", "10%"

    def _get_all_dictionary_items(self, headers, field_name):
        """Lấy toàn bộ danh sách Dictionary (Xóa Content-Length để tránh Timeout)"""
        url = f"https://amisapp.misa.vn/crm/g2/api/business/Dictionary/Details/Product/{field_name}/false/45/null/null"
        
        # Clean header cho GET request
        get_headers = headers.copy()
        for k in ['content-length', 'Content-Length', 'content-type', 'Content-Type']:
            get_headers.pop(k, None)
            
        params = {"page": "null", "searchText": "", "isView": "true"}
        session = self._get_retry_session()

        try:
            res = session.get(url, headers=get_headers, params=params, timeout=30)
            if res.ok and res.json().get("Success"):
                return res.json().get("Data", [])
        except Exception as e:
            _logger.warning(f"⚠️ Lỗi lấy Dictionary {field_name}: {e}")
        return []

    def _find_dictionary_item(self, headers, field_name, search_text):
        """Tìm chính xác theo text"""
        items = self._get_all_dictionary_items(headers, field_name)
        search = str(search_text).strip().lower()
        for item in items:
            if str(item.get("text")).strip().lower() == search:
                return item["id"], item["text"]
        return None, None
    
    def _get_category_name_by_id(self, headers, cat_id):
        """
        Lấy tên danh mục từ ID bằng cách gọi API chi tiết (FormDataNew)
        """
        if not cat_id:
            return None

        # URL lấy chi tiết (dựa trên fetch log)
        # Số 46/4 có thể là LayoutID/Mode, giữ nguyên theo mẫu
        url = "https://amisapp.misa.vn/crm/g1/api/business/ProductCategory/FormDataNew/ProductCategory/46/4"
        
        # Payload giả lập hành động xem chi tiết
        payload = {
            "ID": str(cat_id),
            "MISAEntityState": 2,  # 2 thường là trạng thái View/Edit trong hệ thống MISA
            "ActiveLayoutCode": None,
            "CustomDicData": None
        }

        try:
            session = self._get_retry_session()
            
            # Đảm bảo header có layoutcode (quan trọng với API FormData)
            post_headers = headers.copy()
            post_headers['layoutcode'] = 'productcategory'
            
            # Xóa các header xung đột nếu có (do copy từ request cũ sang)
            for k in ['content-length', 'Content-Length']:
                post_headers.pop(k, None)

            res = session.post(url, headers=post_headers, json=payload, timeout=20)

            if res.ok:
                data = res.json()
                if data.get("Success"):
                    # Truy xuất theo cấu trúc: Data -> CurrentData -> ProductCategoryName
                    current_data = data.get("Data", {}).get("CurrentData", {})
                    cat_name = current_data.get("ProductCategoryName")
                    
                    if cat_name:
                        return str(cat_name).strip()
                else:
                    _logger.warning(f"⚠️ [GetCatName] API Success=False for ID: {cat_id}")
            else:
                _logger.warning(f"⚠️ [GetCatName] HTTP {res.status_code} for ID: {cat_id}")

        except Exception as e:
            _logger.error(f"❌ [GetCatName] Exception: {e}")

        return None

    def _get_category_id_by_name(self, headers, name):
        """Tìm Category ID: Ưu tiên Tree API -> Fallback Grid Pagination"""
        clean_name = str(name).strip().lower()
        session = self._get_retry_session()

        # CÁCH 1: TREE API
        try:
            get_headers = headers.copy()
            for k in ['content-length', 'Content-Length', 'content-type', 'Content-Type']:
                get_headers.pop(k, None)
            
            url_tree = "https://amisapp.misa.vn/crm/g1/api/business/ProductCategory/tree/0/false"
            
            _logger.info(f"🔎 [MISA] Start Tree Search for: '{clean_name}'")
            res = session.get(url_tree, headers=get_headers, timeout=20)
            
            if res.ok and res.json().get("Success"):
                raw_data = res.json().get("Data")
                nodes = json.loads(raw_data) if isinstance(raw_data, str) else raw_data
                
                if isinstance(nodes, list):
                    def recursive_search(n_list):
                        for node in n_list:
                            if str(node.get("ProductCategoryName") or "").strip().lower() == clean_name:
                                return node.get("ID")
                            childs = node.get("Children")
                            if childs and isinstance(childs, list):
                                found = recursive_search(childs)
                                if found: return found
                        return None
                    
                    found_id = recursive_search(nodes)
                    if found_id:
                        return found_id
        except Exception as e:
            _logger.warning(f"⚠️ [Tree] Exception: {e}")

        # CÁCH 2: GRID PAGINATION
        url_grid = "https://amisapp.misa.vn/crm/g2/api/business/ProductCategory/grid"
        page = 1
        page_size = 200
        max_loop = 50 

        while page <= max_loop:
            payload = {
                "Filters": [], 
                "page": page, 
                "pageSize": page_size, 
                "Columns": "ProductCategoryID,ProductCategoryName", 
                "layoutCode": "ProductCategory"
            }
            
            try:
                res = session.post(url_grid, headers=headers, json=payload, timeout=20)
                if not res.ok or not res.json().get("Success"):
                     break
                
                items = res.json().get("Data", [])
                if not items:
                    break

                for item in items:
                    c_name = str(item.get("ProductCategoryName") or "").strip().lower()
                    if c_name == clean_name:
                         cat_id = item.get("ProductCategoryID")
                         return cat_id or item.get("ID")
                
                if len(items) < page_size:
                    break
                page += 1
            except:
                break
        
        return None

    def _get_retry_session(self):
        """Tạo session có cơ chế thử lại khi lỗi mạng"""
        # Import cục bộ để tránh lỗi 'unresolved' ở đầu file nếu IDE chưa cấu hình đúng
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry
        
        session = requests.Session()
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        return session

    def _parse_misa_id(self, res_json, code, headers):
        """Parse ID từ response, fallback nếu cần"""
        data = res_json.get("Data")
        if isinstance(data, int): return str(data)
        if isinstance(data, str) and data: return data
        if isinstance(data, dict): return data.get("ProductID") or data.get("ID")
        
        # Fallback tìm kiếm lại
        url = "https://amisapp.misa.vn/crm/g2/api/business/Product/DataSubPaging"
        payload = {"Page": 1, "PageSize": 1, "Filters": [{"FieldName": "ProductCode", "Operator": 1, "OperandType": 0, "Value": code}]}
        try:
            r = requests.post(url, headers=headers, json=payload, timeout=10)
            d = r.json()
            if d.get("Success") and d.get("Data"):
                return str(d["Data"][0].get("ProductID"))
        except: pass
        return None
    
    # create product
    def create_product_misa(self, product_id):
        """
        Hàm public để tạo sản phẩm.
        Input: ID của sản phẩm (Integer)
        Output: MISA ID (String)
        """
        product = self.env['product.template'].browse(product_id)
        if not product.exists():
            raise Exception(f"Không tìm thấy sản phẩm có ID {product_id} trong Odoo")
        return self._process_create_product(product)
    
    def _find_dictionary_item_unit(self, headers, search_text):
        """
        Lấy danh sách Unit. Viết lại theo style của _get_category_name_by_id.
        QUAN TRỌNG: Phải set layoutcode='settings' thì mới không bị Timeout.
        """
        if not search_text:
            return None, None

        # 1. URL chuẩn (như fetch mẫu)
        url = "https://amisapp.misa.vn/crm/g1/api/business/Dictionary/DictionaryNotUsedAllFormLayout/Product/UsageUnitID"
        
        try:
            session = self._get_retry_session()
            
            # 2. Xử lý Header (Giống hệt hàm Category đang chạy ngon)
            post_headers = headers.copy()
            
            # --- KHÁC BIỆT QUAN TRỌNG NHẤT ---
            # API này nằm ở module thiết lập, bắt buộc phải là 'settings'. 
            # Nếu để 'product' nó sẽ bị timeout.
            post_headers['layoutcode'] = 'settings' 
            
            # Thêm Referer cho chắc (giống fetch mẫu)
            post_headers['referrer'] = "https://amisapp.misa.vn/crm/settings/main/other-settings/other-settings"

            # Xóa header rác
            for k in ['content-length', 'Content-Length']:
                post_headers.pop(k, None)

            # 3. Gọi POST với body rỗng (json=None)
            _logger.info(f"fetching Unit with layoutcode=settings...")
            res = session.post(url, headers=post_headers, json=None, timeout=30)

            if res.ok:
                data = res.json()
                if data.get("Success"):
                    # Xử lý cấu trúc Data: [[{id:1, text:'Cái'},...], []]
                    # Data nằm trong phần tử đầu tiên của mảng Data
                    raw_data_list = data.get("Data", [])
                    items = []
                    
                    if raw_data_list and isinstance(raw_data_list, list) and len(raw_data_list) > 0:
                        items = raw_data_list[0] # Lấy list thật sự bên trong

                    search_norm = search_text.strip().lower()

                    for item in items:
                        # Key trong response này là 'text' và 'id'
                        item_name = item.get("text") or ""
                        if item_name.strip().lower() == search_norm:
                            found_id = item.get("id")
                            _logger.info(f"✅ Found Unit: '{search_text}' -> ID: {found_id}")
                            return found_id, item_name
                            
                    _logger.warning(f"⚠️ Unit '{search_text}' not found in list.")
                else:
                     _logger.warning(f"⚠️ [GetUnit] API Success=False: {data}")
            else:
                _logger.warning(f"⚠️ [GetUnit] HTTP {res.status_code} | {res.text[:100]}")

        except Exception as e:
            _logger.error(f"❌ [GetUnit] Exception: {e}")

        return None, None
    
    def _find_tax_id_misa(self, headers, tax_percent, default_text=""):
        """
        Lấy danh sách Thuế suất từ cấu hình (DBOption).
        Payload chỉ cần gọi "TaxRateConfig" cho nhẹ.
        """
        # 1. URL & Headers chuẩn Settings
        url = "https://amisapp.misa.vn/crm/g1/api/business/DBOption/otherConfig"
        
        req_headers = headers.copy()
        req_headers['layoutcode'] = 'settings' # Quan trọng
        req_headers['referrer'] = "https://amisapp.misa.vn/crm/settings/main/other-settings/other-settings"
        
        # Chỉ request đúng config Thuế để response nhẹ
        payload = ["TaxRateConfig"] 

        try:
            session = self._get_retry_session()
            
            # Gọi API
            res = session.post(url, headers=req_headers, json=payload, timeout=30)
            
            if res.ok:
                res_json = res.json()
                if res_json.get("Success"):
                    items = res_json.get("Data", [])
                    
                    # 2. Tìm Item có OptionID là TaxRateConfig
                    tax_config_item = next((item for item in items if item["OptionID"] == "TaxRateConfig"), None)
                    
                    if tax_config_item:
                        # 3. Parse chuỗi JSON trong OptionValue
                        # Giá trị trả về là string: "[{\"ID\":1,...}, ...]"
                        option_value_str = tax_config_item.get("OptionValue", "[]")
                        tax_list = json.loads(option_value_str)
                        
                        # 4. So sánh TaxRateValue
                        target_val = float(tax_percent)
                        
                        for tax in tax_list:
                            # MISA lưu: TaxRateValue là float (10.0, 8.0, 5.0, 0.0)
                            if tax.get("TaxRateValue") == target_val:
                                found_id = str(tax.get("TaxRateEnum"))
                                found_text = tax.get("TaxRateText")
                                
                                # Lưu ý: Với mức 0%, MISA có nhiều loại (0%, KCT, KKKNT). 
                                # Code này sẽ lấy cái đầu tiên tìm thấy (thường là 0% - ID 1).
                                _logger.info(f"✅ Found Tax: {tax_percent}% -> ID: {found_id} ({found_text})")
                                return found_id, found_text

                        _logger.warning(f"⚠️ Tax value {tax_percent}% not found in MISA config.")
                else:
                    _logger.warning(f"⚠️ [GetTax] Success=False: {res_json}")
            else:
                 _logger.warning(f"⚠️ [GetTax] HTTP {res.status_code}")

        except Exception as e:
            _logger.error(f"❌ Error in _find_tax_id_misa: {str(e)}")

        # 5. Fallback (Nếu lỗi hoặc không tìm thấy)
        # Mặc định trả về 10% (ID 3) nếu input là 10, hoặc trả về ID 3 cứng để không lỗi create
        _logger.info("Using default Tax: 10% (ID 3)")
        return "3", "10%"
    # -------------------------------------------------------------------------
    # API RAW: CẬP NHẬT LOG CHI TIẾT & CẤU TRÚC CUSTOM TABLES
    # -------------------------------------------------------------------------
    def create_product_misa_raw(self, code, name, price=0, tax_percent=10, unit_name="Cái", category_name="Hàng hóa", product_type="goods", cat_id=None, category_id=None, price_pu=0, description=""):
        misa_config = self.env['misa.config']
        token = self._fetch_login_crm_token()
        if not token:
            raise Exception("Lỗi Token MISA")

        headers = misa_config.get_crm_header(token)
        headers.update({"LayoutCode": "product", "X-Misa-Language": "vi-VN"})

        # --- 1. XỬ LÝ ID ---
        cat_id = category_id or cat_id
        cat_name = self._get_category_name_by_id(headers, cat_id)
        # if not cat_id:
        #      cat_id = self._get_category_id_by_name(headers, "Hàng hóa") or 23 
        
        _logger.debug("catname", cat_name,)

        unit_id, unit_text = self._find_dictionary_item_unit(headers, unit_name)
        _logger.info(f"Checking Unit: {unit_name} -> Found: {unit_id} - {unit_text}")
        

        if not unit_id:
            unit_id, unit_text = 4, "Cái"

        tax_id, tax_text = self._find_tax_id_misa(headers, float(tax_percent), "")

        is_service = (product_type == 'service' or product_type == 'dịch vụ')
        prop_id = 2 if is_service else 1
        prop_text = "Dịch vụ" if is_service else "Hàng hóa"

        # --- 2. PAYLOAD ---
        price_val = float(price)
        price_pu_val = float(price_pu or 0)
        
        payload = {
            "ProductCode": code,
            "ProductName": name,
            "Description": description or "",
            "ProductCategoryID": cat_id,
            # "ProductCategoryIDText": category_name if cat_id != 23 else "Hàng hóa",
            "ProductCategoryIDText": cat_name or "",

            "UsageUnitID": unit_id, 
            "UsageUnitIDText": unit_text,
            "ProductPropertiesID": prop_id,
            "ProductPropertiesIDText": prop_text,
            "TaxID": str(tax_id),
            "TaxIDText": tax_text,
            "UnitPrice": price_val,
            "UnitPriceFixed": price_val,
            "PurchasedPrice": 0,
            "MISAEntityState": 1,
            "Active": True, "Inactive": False, "IsPublic": False, 
            "FormLayoutID": 45, "FormLayoutIDText": "Mẫu tiêu chuẩn",
            "IsFollowSerialNumber": False,
            "IsUseTax": False, "PriceAfterTax": False,
            "Fields": [], "FieldsCustom": [], 
            "DefaultStockID": "29", 
            "DefaultStockIDText": "HLV",
            "DataCustom": {
                "CustomField13": None,
                "CustomField13Text": "",
                "CustomField14": None,
                "CustomField15": None,
                "CustomField16": int(price_pu_val), 
                "Avatar": ""
            },
            
            "CustomTables": [
                {
                    "DataFields": [], "Summary": {}, "Data": [], "OldData": [], "SummaryFields": [],
                    "GroupBoxText": "Thông tin đơn vị chuyển đổi", "IsRequired": False,
                    "ParentIDKey": "ProductID", "TableName": "product_conversion_unit", "IsProductChange": False
                },
                {
                    "DataFields": [], "Summary": {},
                    "Data": [self._get_empty_serial_row(i) for i in range(1, 6)],
                    "OldData": [self._get_empty_serial_row(i) for i in range(1, 6)],
                    "SummaryFields": [], "GroupBoxText": "Thông tin mã quy cách", "IsRequired": False,
                    "ParentIDKey": "ProductID", "TableName": "product_detail_serial_type", "IsProductChange": True
                }
            ],
            "IsProductChange": False,
            "IsMultiCurrency": False,
            "FormModeState": 1,
            "IsGetFieldFormLayout": True,
            "IsSetProduct": "\u0000"
        }

        # 3. Gửi Request & LOG
        url = "https://amisapp.misa.vn/crm/g2/api/business/Product"
        _logger.info(f"📤 [MISA RAW REQUEST] Code: {code}")

        session = self._get_retry_session()
        res = session.post(url, headers=headers, json=payload, timeout=30)
        
        _logger.info(f"📥 [MISA RESPONSE] Status: {res.status_code} | Body: {res.text}")

        res_json = res.json()
        if not res_json.get("Success"):
            err_msg = res_json.get("UserMessage")
            val_info = res_json.get("ValidateInfo", [])
            if val_info:
                err_msg = ", ".join([v.get("ErrorMessage", "") for v in val_info])
            raise Exception(f"MISA Refused: {err_msg}")

        misa_id = self._parse_misa_id(res_json, code, headers)
        
        if not misa_id:
             raise Exception("MISA báo thành công nhưng không trả ID.")

        # --- TẠO SẢN PHẨM Ở ODOO ---
        try:
            # Tìm category POS theo MISA ID (đã import ở module pos_category_import_json)
            pos_categ = False
            if cat_id:
                pos_categ = self.env['pos.category'].sudo().search([('x_misa_id', '=', int(cat_id))], limit=1)

            # Tìm Unit
            uom_id = False
            if unit_name:
                found_uom = self.env['uom.uom'].sudo().search([('name', '=', unit_name)], limit=1)
                if found_uom:
                    uom_id = found_uom.id

            # Chuẩn bị values
            vals = {
                'name': name,
                'list_price': price,
                'standard_price': price_pu,
                'type': 'consu' if str(product_type).lower() == 'goods' else 'service',
                'is_storable': True if str(product_type).lower() == 'goods' else False,
                'available_in_pos': True,
            }
            if description:
                vals['description'] = description

            # Tìm và gán thuế theo phần trăm
            if tax_percent:
                tax = self.env['account.tax'].sudo().search([
                    ('amount', '=', float(tax_percent)),
                    ('type_tax_use', '=', 'sale')
                ], limit=1)
                if tax:
                    vals['taxes_id'] = [(6, 0, [tax.id])]

            if pos_categ:
                vals['pos_categ_ids'] = [(6, 0, [pos_categ.id])]
            
            if uom_id:
                vals['uom_id'] = uom_id
                vals['uom_po_id'] = uom_id

            # Check tồn tại
            existing_prod = self.env['product.template'].sudo().search([('default_code', '=', code)], limit=1)
            
            if not existing_prod:
                vals['default_code'] = code
                new_prod = self.env['product.template'].sudo().create(vals)
                _logger.info("Đã tạo sản phẩm Odoo: %s (ID: %s) từ API MISA", new_prod.name, new_prod.id)
            else:
                existing_prod.sudo().write(vals)
                _logger.info("Đã cập nhật sản phẩm Odoo: %s (ID: %s) từ API MISA", existing_prod.name, existing_prod.id)

        except Exception as e:
            _logger.error("Lỗi khi tạo sản phẩm Odoo từ API MISA: %s", str(e))
            # Không raise lỗi để tránh ảnh hưởng response MISA ID nếu MISA tạo thành công rồi

        return misa_id

    def _get_product_code_by_misa_id(self, headers, misa_id):
        """Best-effort lookup ProductCode from MISA Product ID."""
        url = "https://amisapp.misa.vn/crm/g2/api/business/Product/FormDataNew/Product/45/4"
        payload = {"ID": str(misa_id)}
        try:
            res = self._get_retry_session().post(
                url, headers=headers, json=payload, timeout=20)
            data = res.json()
            if not data.get("Success"):
                return None

            raw = data.get("Data") or {}
            if isinstance(raw, dict):
                current = (
                    raw.get("CurrentData")
                    or raw.get("FormData")
                    or raw.get("Data")
                    or raw
                )
                if isinstance(current, dict):
                    return current.get("ProductCode")
        except Exception as e:
            _logger.warning("Cannot fetch product code for MISA ID %s: %s", misa_id, e)
        return None

    def _sync_product_description_to_odoo(self, misa_id, description, headers=None):
        """Sync MISA product Description to Odoo product.template.description."""
        try:
            ProductTemplate = self.env['product.template'].sudo()
            product = ProductTemplate.browse()

            if 'x_misa_id' in ProductTemplate._fields:
                product = ProductTemplate.search([
                    '|',
                    ('x_misa_id', '=', str(misa_id)),
                    ('x_misa_id', '=', misa_id),
                ], limit=1)

            if not product:
                if headers is None:
                    misa_config = self.env['misa.config']
                    token = self._fetch_login_crm_token()
                    headers = misa_config.get_crm_header(token)
                    headers.update({"LayoutCode": "product", "X-Misa-Language": "vi-VN"})
                code = self._get_product_code_by_misa_id(headers, misa_id)
                if code:
                    product = ProductTemplate.search([
                        ('default_code', '=', code),
                    ], limit=1)

            if product:
                product.write({'description': description or ""})
                return True

            _logger.warning(
                "Cannot sync Description to Odoo: product not found for MISA ID %s",
                misa_id,
            )
        except Exception as e:
            _logger.error("Odoo description sync failed for MISA ID %s: %s", misa_id, e)
        return False

    def update_product_field_misa(self, misa_id, field_type, new_value, old_value):
        """
        Cập nhật từng trường (name hoặc code) lên MISA CRM
        field_type: 'name' hoặc 'code'
        """
        if not misa_id:
            return False

        misa_config = self.env['misa.config']
        token = self._fetch_login_crm_token()
        if not token:
            _logger.error("Lỗi Token MISA khi cập nhật sản phẩm")
            return False

        headers = misa_config.get_crm_header(token)
        headers.update({
            "LayoutCode": "product", 
            "X-Misa-Language": "vi-VN"
        })

        if field_type == 'name':
            payload = misa_config.get_misa_update_product_name_payload(misa_id, new_value, old_value)
        elif field_type == 'code':
            payload = misa_config.get_misa_update_product_code_payload(misa_id, new_value, old_value)
        elif field_type in ('Description', 'description'):
            payload = misa_config.get_misa_update_product_description_payload(misa_id, new_value, old_value)
        else:
            return False

        url = "https://amisapp.misa.vn/crm/g2/api/business/product"
        
        session = self._get_retry_session()
        try:
            res = session.put(url, headers=headers, json=payload, timeout=20)
            res_json = res.json()
            if res.ok and res_json.get("Success"):
                _logger.info("✅ Đã cập nhật %s cho MISA ID %s", field_type, misa_id)
                if field_type in ('Description', 'description'):
                    self._sync_product_description_to_odoo(
                        misa_id, new_value, headers=headers)
                return True
            else:
                _logger.warning("⚠️ Lỗi MISA khi cập nhật %s: %s", field_type, res.text)
                return False
        except Exception as e:
            _logger.error("❌ Exception MISA update %s: %s", field_type, e)
            return False

    # =========================================================================
    # API SEARCH PRODUCT BY NAME
    # =========================================================================
    def search_product_by_name(self, name=None, code=None, limit=20):
        import uuid
        
        if not name and not code:
            raise Exception("Cần truyền ít nhất 'name' hoặc 'code' để tìm kiếm")
        
        misa_config = self.env['misa.config']
        token = self._fetch_login_crm_token()
        if not token:
            raise Exception("Lỗi Token MISA")

        headers = misa_config.get_crm_header(token)
        headers.update({"LayoutCode": "product", "X-Misa-Language": "vi-VN"})

        # Sử dụng API g1 thay vì g2
        url = "https://amisapp.misa.vn/crm/g1/api/business/Product/Grid"
        
        filters = []
        
        if name:
            filters.append({
                "Value": name.strip(),
                "IsDefaultFilter": False,
                "IsCustomField": False,
                "IsRelatedField": False,
                "ModuleRelated": "",
                "FromFilterCustom": False,
                "ValueDisplayText": "",
                "isValueDateNumber": False,
                "IsSearchModule": False,
                "ConfigDisplayRelatedField": "",
                "ConfigSubDisplayRelatedField": "",
                "ConfigSearchField": [],
                "ConfigUrlCbx": "",
                "FilterObjects": [],
                "dataOperator": [],
                "IsProductCategory": False,
                "SelectedDataList": [],
                "IsCustomTypeDecimalDigits": False,
                "IsFromFormula": False,
                "Operator": 1,
                "Addition": 1,
                "Property": "ProductName",
                "InputType": 1,
                "FieldType": 0,
                "FieldName": "ProductName",
                "OperatorBeforeDetectChanges": 1,
                "InputTypeOrigin": 1,
                "DisplayField": "Tên hàng hóa",
                "DisplayOperator": "Chứa",
                "DisplayValue": name.strip(),
                "ValueOrigin": name.strip()
            })
        
        if code:
            filters.append({
                "Value": code.strip(),
                "IsDefaultFilter": False,
                "IsCustomField": False,
                "IsRelatedField": False,
                "ModuleRelated": "",
                "FromFilterCustom": False,
                "ValueDisplayText": "",
                "isValueDateNumber": False,
                "IsSearchModule": False,
                "ConfigDisplayRelatedField": "",
                "ConfigSubDisplayRelatedField": "",
                "ConfigSearchField": [],
                "ConfigUrlCbx": "",
                "FilterObjects": [],
                "dataOperator": [],
                "IsProductCategory": False,
                "SelectedDataList": [],
                "IsCustomTypeDecimalDigits": False,
                "IsFromFormula": False,
                "Operator": 1,
                "Addition": 1,
                "Property": "ProductCode",
                "InputType": 1,
                "FieldType": 0,
                "FieldName": "ProductCode",
                "OperatorBeforeDetectChanges": 1,
                "InputTypeOrigin": 1,
                "DisplayField": "Mã hàng hóa",
                "DisplayOperator": "Chứa",
                "DisplayValue": code.strip(),
                "ValueOrigin": code.strip()
            })
        
        payload = {
            "Columns": "SUQsUHJvZHVjdENvZGUsUHJvZHVjdE5hbWUsUHJvZHVjdENhdGVnb3J5SUQsUHJvZHVjdENhdGVnb3J5SURUZXh0LFVzYWdlVW5pdElELFVzYWdlVW5pdElEVGV4dCxVbml0UHJpY2UsVGF4SUQsVGF4SURUZXh0LERlZmF1bHRTdG9ja0lELERlZmF1bHRTdG9ja0lEVGV4dCxGb3JtTGF5b3V0SUQsRm9ybUxheW91dElEVGV4dCxPd25lcklELE93bmVySURUZXh0LElzU3lzdGVtLEF2YXRhcg==",
            "Sorts": [{"SortBy": "ModifiedDate", "Type": 0, "SortDirection": 1}],
            "Start": 0,
            "Page": 1,
            "PageSize": limit,
            "Filters": filters,
            "Formula": "",
            "LayoutCode": "Product",
            "DefaultTotal": True,
            "IsMappingData": False,
            "MappingValueObject": {},
            "IsApproved": False,
            "CustomPagingData": {},
            "IsUsedELTS": True,
            "ListGmailPage": [],
            "ListFacebookPage": {},
            "IsListPaging": True,
            "IsGetCache": True,
            "IsCheckInactive": False,
            "IsConverted": False,
            "SessionID": str(uuid.uuid4()),
            "LayoutCodeCheckPermission": "Product",
            "AISearchKeyword": ""
        }

        _logger.info(f"🔎 [MISA SEARCH] Tìm kiếm sản phẩm với tên: '{name}'")

        session = self._get_retry_session()
        try:
            res = session.post(url, headers=headers, json=payload, timeout=30)
            
            _logger.info(f"📥 [MISA RESPONSE] Staus: {res.status_code} | Body: {res.text}")

            
            res_json = res.json()
            
            if not res_json.get("Success"):
                err_msg = res_json.get("UserMessage") or f"Response: {res.text[:200]}"
                raise Exception(f"MISA Search Failed: {err_msg}")
            
            products = res_json.get("Data", []) or []
            
            result = []
            for p in products:
                result.append({
                    "misa_id": p.get("ID") or p.get("ProductID"),
                    "code": p.get("ProductCode"),
                    "name": p.get("ProductName"),
                    "price": p.get("UnitPrice") or 0,
                    "cost": p.get("PurchasedPrice") or 0,
                    "unit": p.get("UsageUnitIDText"),
                    "category": p.get("ProductCategoryIDText"),
                    "tax": p.get("TaxIDText"),
                    "type": p.get("ProductPropertiesIDText"),
                    "active": p.get("Active", True),
                })
            
            return result

        except Exception as e:
            _logger.exception(f"❌ Search error: {e}")
            raise e

    def _get_empty_serial_row(self, sort_order):
        """Hàm tạo dòng rỗng cho bảng quy cách"""
        return {
            "SortOrder": sort_order, "TableName": "product_detail_serial_type",
            "DisplayName": None, "IsAllowDupplicate": None, "ID": None,
            "MISAEntityState": 1, "AsyncID": "", "OwnerID": "", "PromotionMasterRowID": "",
            "PromotionRowID": "", "ProductSetID": "", "ProductSetMasterID": "",
            "ProductInSetMasterID": "", "IsSetProduct": "", "IsChildProduct": "",
            "ProductIDInSet": "", "ExcludeCurrentRecord": "", "ExchangeID": 0,
            "IsExchangeProduct": None, "ExchangePoint": 0,
            "TotalAmountBasedUPriceAndDATax": False, "AmountBasedOnPriceAfterTax": False
        }
    # =========================================================================
    # API SEARCH PURCHASE VOUCHER (CHỨNG TỪ NHẬP KHO MUA HÀNG)
    # =========================================================================
    def search_purchase_voucher(self, journal_memo, limit=20):
        """
        Tìm kiếm chứng từ nhập kho mua hàng trong MISA (actapp) theo diễn giải (journal_memo).
        Hỗ trợ tìm nhiều mã phân cách bởi dấu phẩy (eg: "DH1, DH2").

        Sử dụng API pu_list/paging_filter_v2 với view=40 để lấy chứng từ nhập kho (reftype 302)
        với đầy đủ thông tin: refno_finance, posted_date, paid_status, in_outward_refno, v.v.
        """
        if not journal_memo:
            raise Exception("Cần truyền 'journal_memo' để tìm kiếm")
            
        # 1. Lấy token
        access_token = self._get_misa_token()
        
        # 2. Config Header
        misa_config = self.env['misa.config']
        headers = misa_config.get_default_headers(access_token)
        
        # 3. Dùng pu_list với view=40 (chứng từ nhập kho mua hàng - reftype 302)
        url = "https://actapp.misa.vn/g2/api/pu/v1/pu_list/paging_filter_v2"
        
        # Xử lý input: split theo dấu phẩy
        search_terms = [s.strip() for s in journal_memo.split(',') if s.strip()]
        
        if not search_terms:
            return []

        # Helper function để gọi API cho 1 giá trị
        from datetime import datetime, timedelta
        
        # Date range: 1 năm gần đây
        date_to = datetime.utcnow()
        date_from = date_to - timedelta(days=365)
        
        session = self._get_retry_session()
        all_results = []
        seen_refids = set()

        for val in search_terms:
            _logger.info(f"🔎 [MISA PURCHASE VOUCHER SEARCH] Tìm kiếm term: '{val}'")
            
            payload = {
                "sort": "[{\"property\":3654,\"desc\":true,\"data_type\":3,\"operand\":1},{\"property\":3972,\"desc\":true,\"data_type\":3,\"operand\":1},{\"property\":4018,\"desc\":true,\"data_type\":1,\"operand\":1}]",
                # Date range filter (bắt buộc)
                "filter": [
                    {
                        "property": 3654,
                        "value": date_from.strftime("%Y-%m-%dT%H:%M:%S.00Z"),
                        "operator": 10,  # >=
                        "operand": 1,
                        "data_type": 3
                    },
                    {
                        "property": 3654,
                        "value": date_to.strftime("%Y-%m-%dT%H:%M:%S.00Z"),
                        "operator": 12,  # <=
                        "operand": 1,
                        "data_type": 3
                    }
                ],
                # Custom filter cho text search (parent-children structure)
                "customFilter": [{
                    "property": 4018,
                    "value": val,
                    "operator": 1,  # Equals (SO SÁNH BẰNG ĐỂ CHÍNH XÁC)
                    "operand": 1,
                    "data_type": 1,
                    "childrens": [
                        {"property": 2189, "value": val, "operator": 1, "operand": 2, "data_type": 1},
                        {"property": 57, "value": val, "operator": 1, "operand": 2, "data_type": 1},
                        {"property": 2656, "value": val, "operator": 1, "operand": 2, "data_type": 1},
                        {"property": 4029, "value": val, "operator": 1, "operand": 2}
                    ]
                }],
                "pageIndex": 1,
                "pageSize": int(limit),
                "view": 40,  # View cho chứng từ nhập kho mua hàng (reftype 302)
                "useSp": False, 
                "loadMode": 2,
                "summaryColumns": [5080, 5730, 5128, 5059]
            }
            
            try:
                res = session.post(url, headers=headers, json=payload, timeout=30)
                if res.status_code != 200:
                    _logger.error(f"❌ MISA Purchase Voucher Search HTTP {res.status_code}: {res.text}")
                    continue # Skip lỗi mạng của 1 item để chạy tiếp item khác
                    
                data = res.json()
                if not data.get("Success"):
                    _logger.warning(f"⚠️ MISA Refused for term '{val}': {data}")
                    continue
                    
                page_data = data.get("Data", {}).get("PageData", [])
                
                # Merge into results
                for item in page_data:
                    refid = item.get("refid")
                    if refid and refid not in seen_refids:
                        seen_refids.add(refid)
                        all_results.append(item)
                        
            except Exception as e:
                _logger.exception(f"❌ Search Purchase Voucher Error for term '{val}': {e}")
                # Không raise e để tiếp tục loop các term khác
        
        _logger.info(f"✅ [MISA PURCHASE VOUCHER SEARCH] Tổng tìm thấy {len(all_results)} chứng từ cho {len(search_terms)} keywords")
        return all_results
    
    # =========================================================================
    # 5. API CREATE SHIPPING ROUTE (TUYẾN VẬN CHUYỂN)
    # =========================================================================
    def _generate_shipping_route_code(self, headers):
        """
        Gọi API GenerateNumber để lấy mã ShippingRouteCode tự động từ MISA.
        
        Returns:
            str: Mã tuyến vận chuyển (e.g., "TVC0000002")
        """
        url = "https://amisapp.misa.vn/crm/g1/api/business/ShippingRoute/GenerateNumber/ShippingRoute/ShippingRouteCode/142"
        
        # Dùng session thường - KHÔNG retry vì sẽ dùng fallback nếu fail
        session = requests.Session()
        try:
            res = session.get(url, headers=headers, timeout=2)  # Giảm timeout xuống 2s
            res.raise_for_status()
            data = res.json()
            
            _logger.info(f"📥 [MISA] GenerateNumber Response: {data}")
            
            if data.get('Success') and data.get('Data'):
                generated_code = data.get('Data')
                _logger.info(f"✅ [MISA] Generated ShippingRouteCode: {generated_code}")
                return generated_code
            
            _logger.warning(f"⚠️ [MISA] GenerateNumber failed: {data}")
            return None
            
        except Exception as e:
            _logger.warning(f"⚠️ [MISA] GenerateNumber error (using fallback): {e}")
            return None

    def create_shipping_route_misa(self, code, name, owner_id=59):
        """
        Tạo tuyến vận chuyển mới trên MISA CRM.
        
        Args:
            code (str): Mã tuyến backup (sẽ dùng nếu GenerateNumber fail)
            name (str): Tên tuyến (thường dùng SO name)
            owner_id (int): MISA User ID (default 59)
            
        Returns:
            int/str: MISA ID của tuyến vừa tạo
        """
        from datetime import datetime
        
        misa_config = self.env['misa.config']
        token = self._fetch_login_crm_token()
        if not token:
            raise Exception("Lỗi Token MISA")

        headers = misa_config.get_crm_header(token)
        
        # 1. Gọi GenerateNumber để lấy mã ShippingRouteCode hợp lệ
        generated_code = self._generate_shipping_route_code(headers)
        
        if generated_code:
            shipping_route_code = generated_code
        else:
            # Fallback: Dùng code gốc trực tiếp (mã phiếu OUT)
            shipping_route_code = code
            _logger.info(f"⚠️ [MISA] GenerateNumber failed, using original code: {shipping_route_code}")
        
        # 2. API endpoint
        url = "https://amisapp.misa.vn/crm/g1/api/business/ShippingRoute"
        
        # 3. Build payload theo đúng format capture từ MISA browser
        # StartDate format: UTC với Z suffix
        current_date_utc = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.000Z")
        
        payload = {
            "ShippingRouteCode": shipping_route_code,
            "ShippingRouteName": name,
            "StatusID": "3",  # 3 = Đã hoàn thành
            "OwnerID": owner_id,
            "StartDate": current_date_utc,
            "WarehouseEmployeeID": owner_id,
            "EndDate": None,
            "MISAEntityState": 1,  # 1 = Insert (tạo mới)
            "FormLayoutID": 142,
            "FormLayoutIDText": "Mẫu tiêu chuẩn",
            "LayoutCode": "ShippingRoute",
            "ActiveLayoutCode": "ShippingRoute",
            "Fields": [
                {
                    "ID": 11409,
                    "FieldName": "ShippingRouteCode",
                    "DisplayText": "Mã tuyến",
                    "Value": shipping_route_code,
                    "TypeControl": 10,
                    "MaxLength": 100,
                    "DecimalLength": 2,
                    "IsRequired": True,
                    "IsNotZero": False,
                    "IsUnique": True,
                    "IsValidateFormat": False,
                    "CustomRoundDigit": 2,
                    "IsAutoCreateSequenceAfterSave": False,
                    "IsOnlyNumeric": False,
                    "IsCustomField": False
                },
                {
                    "ID": 11411,
                    "FieldName": "OwnerID",
                    "DisplayText": "Người thực hiện",
                    "Value": owner_id,
                    "TypeControl": 5,
                    "MaxLength": 255,
                    "DecimalLength": 2,
                    "IsRequired": False,
                    "IsNotZero": False,
                    "IsUnique": False,
                    "IsValidateFormat": False,
                    "CustomRoundDigit": 2,
                    "IsAutoCreateSequenceAfterSave": False,
                    "IsOnlyNumeric": False,
                    "IsCustomField": False
                },
                {
                    "FieldName": "OwnerIDText",
                    "DisplayText": "Người thực hiện",
                    "Value": "",
                    "TypeControl": 1,
                    "MaxLength": 255
                },
                {
                    "ID": 11413,
                    "FieldName": "StartDate",
                    "DisplayText": "Ngày bắt đầu",
                    "Value": current_date_utc,
                    "TypeControl": 7,
                    "MaxLength": 255,
                    "DecimalLength": 2,
                    "IsRequired": False,
                    "IsNotZero": False,
                    "IsUnique": False,
                    "IsValidateFormat": False,
                    "CustomRoundDigit": 2,
                    "IsAutoCreateSequenceAfterSave": False,
                    "IsOnlyNumeric": False,
                    "IsCustomField": False
                },
                {
                    "ID": 11415,
                    "FieldName": "StatusID",
                    "DisplayText": "Tình trạng",
                    "Value": "3",
                    "TypeControl": 5,
                    "MaxLength": 255,
                    "DecimalLength": 2,
                    "IsRequired": False,
                    "IsNotZero": False,
                    "IsUnique": False,
                    "IsValidateFormat": False,
                    "CustomRoundDigit": 2,
                    "IsAutoCreateSequenceAfterSave": False,
                    "IsOnlyNumeric": False,
                    "IsCustomField": False
                },
                {
                    "FieldName": "StatusIDText",
                    "DisplayText": "Tình trạng",
                    "Value": "Đã hoàn thành",
                    "TypeControl": 1,
                    "MaxLength": 255
                },
                {
                    "ID": 11410,
                    "FieldName": "ShippingRouteName",
                    "DisplayText": "Tên tuyến",
                    "Value": name,
                    "TypeControl": 1,
                    "MaxLength": 255,
                    "DecimalLength": 2,
                    "IsRequired": True,
                    "IsNotZero": False,
                    "IsUnique": False,
                    "IsValidateFormat": False,
                    "CustomRoundDigit": 2,
                    "IsAutoCreateSequenceAfterSave": False,
                    "IsOnlyNumeric": False,
                    "IsCustomField": False
                },
                {
                    "ID": 11412,
                    "FieldName": "WarehouseEmployeeID",
                    "DisplayText": "Nhân viên kho",
                    "Value": owner_id,
                    "TypeControl": 5,
                    "MaxLength": 255,
                    "DecimalLength": 2,
                    "IsRequired": False,
                    "IsNotZero": False,
                    "IsUnique": False,
                    "IsValidateFormat": False,
                    "CustomRoundDigit": 2,
                    "IsAutoCreateSequenceAfterSave": False,
                    "IsOnlyNumeric": False,
                    "IsCustomField": False
                },
                {
                    "FieldName": "WarehouseEmployeeIDText",
                    "DisplayText": "Nhân viên kho",
                    "Value": "",
                    "TypeControl": 1,
                    "MaxLength": 255
                },
                {
                    "ID": 11414,
                    "FieldName": "EndDate",
                    "DisplayText": "Ngày kết thúc",
                    "Value": None,
                    "TypeControl": 7,
                    "MaxLength": 255,
                    "DecimalLength": 2,
                    "IsRequired": False,
                    "IsNotZero": False,
                    "IsUnique": False,
                    "IsValidateFormat": False,
                    "CustomRoundDigit": 2,
                    "IsAutoCreateSequenceAfterSave": False,
                    "IsOnlyNumeric": False,
                    "IsCustomField": False
                },
                {
                    "FieldName": "FormLayoutID",
                    "Value": 142,
                    "TypeControl": 14
                },
                {
                    "FieldName": "FormLayoutIDText",
                    "Value": "Mẫu tiêu chuẩn",
                    "TypeControl": 1
                },
                {
                    "FieldName": "PersonInChargeID",
                    "TypeControl": 9
                },
                {
                    "FieldName": "PersonInChargeIDText",
                    "TypeControl": 1
                }
            ]
        }
        
        _logger.info(f"🚀 [MISA] Creating Shipping Route: Code={shipping_route_code}, Name={name}")
        _logger.debug(f"📤 [MISA] Payload: {json.dumps(payload, ensure_ascii=False)}")
        
        session = self._get_retry_session()
        try:
            res = session.post(url, headers=headers, json=payload, timeout=30)
            res.raise_for_status()
            data = res.json()
            
            _logger.info(f"📥 [MISA] Shipping Route Response: {data}")

            if data.get('Success') and data.get('Data'):
                res_data = data.get('Data')
                
                # Parse ID từ response
                if isinstance(res_data, dict):
                    found_id = res_data.get('ID') or res_data.get('ShippingRouteID')
                    if found_id:
                        _logger.info(f"✅ [MISA] Shipping Route created: ID={found_id}")
                        return found_id
                    
                    _logger.warning(f"⚠️ [MISA] Response Data (Dict) but no ID found: {res_data}")
                    raise Exception(f"MISA Response missing ID: {json.dumps(res_data, ensure_ascii=False)}")

                # Nếu Data là primitive (int/str), return trực tiếp
                if isinstance(res_data, (int, str)):
                    _logger.info(f"✅ [MISA] Shipping Route created: ID={res_data}")
                    return res_data
            
            # Xử lý lỗi
            error_msg = data.get('UserMessage') or data.get('ValidateInfo')
            if not error_msg:
                error_msg = json.dumps(data, ensure_ascii=False)
            raise Exception(f"MISA Create Shipping Route Failed: {error_msg}")
            
        except Exception as e:
            _logger.error(f"❌ [MISA] Failed to create shipping route: {e}")
            raise e


    def update_sale_order_shipping_route(self, misa_sale_order_id, shipping_route_id, shipping_route_name=""):
        """
        Cập nhật ShippingRouteID vào Sale Order trên MISA CRM.
        Sử dụng API /Delivery/SaveDelivery
        
        Args:
            misa_sale_order_id (int/str): MISA Sale Order ID
            shipping_route_id (int/str): MISA Shipping Route ID vừa tạo
            shipping_route_name (str): Tên tuyến vận chuyển (để hiển thị)
            
        Returns:
            bool: True nếu thành công
        """
        misa_config = self.env['misa.config']
        token = self._fetch_login_crm_token()
        if not token:
            raise Exception("Lỗi Token MISA")

        headers = misa_config.get_crm_header(token)
        
        # API endpoint đúng - /Delivery/SaveDelivery
        url = "https://amisapp.misa.vn/crm/g1/api/business/Delivery/SaveDelivery"
        
        payload = {
            "ID": str(misa_sale_order_id),
            "ShippingRouteID": str(shipping_route_id),
            "ShippingRouteIDText": shipping_route_name,
            "WarehouseUserID": None,
            "WarehouseUserIDText": None,
            "DeliveryUserID": None,
            "DeliveryUserIDText": None,
            "EstimatedDeliveryDate": None,
            "Description": ""
        }
        
        _logger.info(f"🔄 [MISA] Updating Sale Order {misa_sale_order_id} with ShippingRouteID={shipping_route_id}")
        _logger.debug(f"📤 [MISA] Payload: {json.dumps(payload, ensure_ascii=False)}")
        
        session = self._get_retry_session()
        try:
            res = session.post(url, headers=headers, json=payload, timeout=30)
            res.raise_for_status()
            data = res.json()
            
            _logger.info(f"📥 [MISA] SaveDelivery Response: {data}")

            if data.get('Success'):
                _logger.info(f"✅ [MISA] Sale Order {misa_sale_order_id} updated with ShippingRouteID={shipping_route_id}")
                return True
            
            # Xử lý lỗi
            error_msg = data.get('UserMessage') or data.get('ValidateInfo')
            if not error_msg:
                error_msg = json.dumps(data, ensure_ascii=False)
            _logger.error(f"❌ [MISA] SaveDelivery Failed: {error_msg}")
            return False
            
        except Exception as e:
            _logger.error(f"❌ [MISA] Failed to save delivery: {e}")
            return False
