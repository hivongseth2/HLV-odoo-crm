import requests
import logging
from odoo import models
import re
from dateutil import parser as dtparser
from requests.utils import dict_from_cookiejar
from http.cookiejar import Cookie
_logger = logging.getLogger(__name__)

class MisaApiUtils(models.AbstractModel):
    _name = 'misa.api.utils'
    _description = 'MISA API Utilities'
    
    def get_or_create_combo_product(self, combo_data, children_data, env=None, sale_headers=None):
        """
        Tạo/cập nhật combo product với cơ chế đúng theo model combo.product
        """
        env = env or self.env
        Product = env['product.product']
        ProductTmpl = env['product.template']
        ComboProduct = env['combo.product']
        OdooUtils = env['odoo.utils']

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

        # === Helper: GHI VÀO TEMPLATE ===
        def _write_combo_children(target_tmpl, children_list, parent_qty_in_order=1.0):
            """
            Ghi thông tin sản phẩm con vào combo.product
            target_tmpl: record product.template
            children_list: [{ProductIDText, Amount, UnitIDText, Price, ...}]
            parent_qty_in_order: số lượng combo cha trong đơn hàng (để tính lại base qty)
            """
            if not target_tmpl or not children_list:
                return

            # 1) Xóa sạch các dòng cũ
            old_lines = ComboProduct.search([('product_template_id', '=', target_tmpl.id)])
            if old_lines:
                old_lines.sudo().unlink()
                _logger.info("🗑️ Đã xóa %d dòng combo.product cũ của %s", len(old_lines), target_tmpl.display_name)

            # 2) Loại bỏ trùng lặp: gom theo ProductIDText, giữ lại item đầu tiên
            seen_codes = set()
            unique_children = []
            for ch in children_list:
                c_code = (ch.get('ProductIDText') or '').strip()
                if c_code and c_code not in seen_codes:
                    seen_codes.add(c_code)
                    unique_children.append(ch)
            
            if len(unique_children) < len(children_list):
                _logger.info("🔧 Đã loại bỏ %d dòng con trùng lặp", len(children_list) - len(unique_children))

            created = 0
            for ch in unique_children:
                c_code = (ch.get('ProductIDText') or '').strip()
                if not c_code:
                    continue
                
                c_name = (ch.get('Description') or c_code).strip()
                c_uom_name = (ch.get('UnitIDText') or 'Cái').strip()
                c_qty_raw = float(ch.get('Amount') or 1.0)
                c_price = float(ch.get('Price') or 0.0)
                
                # 🔧 FIX: Tính lại số lượng base (MISA trả về Amount đã nhân với qty đơn hàng)
                # Ví dụ: combo cha qty=3, con base=0.1 → MISA trả Amount=0.3
                # Ta cần chia ngược lại: 0.3 / 3 = 0.1
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
                            product_type='product', 
                            purchase_ok=True, 
                            sale_ok=True
                        )
                    except Exception as e:
                        _logger.error("❌ Không tạo được sản phẩm con %s: %s", c_code, e)
                        continue

                if not c_prod:
                    _logger.warning("⚠️ Bỏ qua sản phẩm con %s (không tạo được)", c_code)
                    continue

                # 2) Tạo dòng combo.product theo đúng schema
                try:
                    ComboProduct.sudo().create({
                        'product_template_id': target_tmpl.id,
                        'product_id': c_prod.id,
                        'product_quantity': c_qty,
                        'price': c_price,
                        # uom_id là related field nên không cần set
                    })
                    created += 1
                    _logger.info("✅ Thêm sản phẩm con: %s (qty=%s) vào combo %s", 
                            c_code, c_qty, target_tmpl.display_name)
                except Exception as e:
                    _logger.error("❌ Lỗi tạo combo.product cho %s: %s", c_code, e)

            _logger.info("✅ Đã tạo %s dòng combo.product cho combo %s", created, target_tmpl.display_name)

        # === Lấy/tạo combo cha ===
        combo_prod = Product.search([('default_code', '=', combo_code)], limit=1)
        
        if combo_prod:
            # Sản phẩm đã tồn tại
            tmpl = combo_prod.product_tmpl_id
            
            # Đảm bảo tick is_combo + cập nhật UoM nếu cần
            update_vals = {}
            if not getattr(tmpl, 'is_combo', False):
                update_vals['is_combo'] = True
            
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

            # Nếu thiếu con -> tự fetch từ API
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

            # 🔥 LUÔN GHI CHILDREN VÀO TEMPLATE (cập nhật mỗi lần sync)
            _write_combo_children(tmpl, children_data or [], qty_divider)
            _logger.info("✅ Đã cập nhật children cho combo đã tồn tại: %s", combo_code)
            return combo_prod

        # === Chưa có -> tạo mới ===
        _logger.info("🆕 Tạo mới combo product: %s", combo_code)
        
        vals = {
            'name': combo_name or combo_code,
            'default_code': combo_code,
            'type': 'service',  # Combo thường là service
            'sale_ok': True,
            'purchase_ok': False,
            'is_combo': True,
        }
        
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

        # Ghi children vào template
        _write_combo_children(tmpl, children_data or [], qty_divider)
        
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
        response = requests.post(url, headers=headers, json=payload)
        _logger.info("Response text: %s", response.text)
        if response.status_code == 401:
            _logger.warning("🔁 Token hết hạn, đang đăng nhập lại...")
            new_token = self._get_misa_token()
            _logger.info("🔑 Đăng nhập thành công, token mới: %s", new_token)
            headers["Authorization"] = f"Bearer {new_token}"
            response = requests.post(url, headers=headers, json=payload)
        return response

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
        và mã vận đơn (OtherSysOrderCode, DeliveryOrderNumber)
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

                return {"owner_code": None, "sale_order_date": None, "misa_delivery": None, "shipping_contact": None}
                # return {"owner_code": None, "sale_order_date": None, "misa_delivery": None, "other_sys_order_code": None, "delivery_order_number": None, "shipping_contact": None}
            data = resp.json() if resp.content else {}
        except Exception as ex:
            _logger.exception("Lỗi gọi FormDataNew SaleOrder (ID=%s): %s", sale_order_id, ex)
            return {"owner_code": None, "sale_order_date": None, "misa_delivery": None, "shipping_contact": None}
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
        # other_sys_order_code = (cd.get("OtherSysOrderCode") or "").strip() or None
        # delivery_order_number = (cd.get("DeliveryOrderNumber") or "").strip() or None

        # Lấy tên người nhận hàng từ ShippingContactIDText
        shipping_contact = (cd.get("ShippingContactIDText") or "").strip() or None

        # Trả về kết quả dạng dict
        return {
            "owner_code": owner_code,
            "sale_order_date": sale_date,
            "misa_delivery": misa_delivery,
            "shipping_contact": shipping_contact
        }
        # return {
        #     "owner_code": owner_code,
        #     "sale_order_date": sale_date,
        #     "misa_delivery": misa_delivery,
        #     "other_sys_order_code": other_sys_order_code,
        #     "delivery_order_number": delivery_order_number,
        #     "shipping_contact": shipping_contact
        # }    
    


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
        """
        session = requests.Session()
        all_products = []
        page = 1
        page_size = 20  # MISA cố định
        max_pages = 100  # Giới hạn an toàn
        total_expected = None  # Sẽ được set từ response đầu tiên
        
        while page <= max_pages:
            # Cập nhật payload cho trang hiện tại
            current_payload = payload.copy()
            current_payload['Page'] = page
            current_payload['Start'] = (page - 1) * page_size
            
            try:
                _logger.info("📄 Fetching MISA products: Page %d (Start=%d)", page, current_payload['Start'])
                
                response = session.post(api_url, headers=header, json=current_payload)
                
                if response.status_code != 200:
                    _logger.error("❌ API call failed at page %d: %s - %s", 
                                page, response.status_code, response.text)
                    break
                
                data = response.json()
                
                if not data.get("Success", True):
                    _logger.warning("⚠️ MISA returned Success=False at page %d: %s", 
                                page, data.get("Message"))
                    break
                
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
                
            except requests.exceptions.RequestException as e:
                _logger.exception("❌ Request error at page %d: %s", page, e)
                break
            except Exception as e:
                _logger.exception("❌ Unexpected error at page %d: %s", page, e)
                break
        
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



