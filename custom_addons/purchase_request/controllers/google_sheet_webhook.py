import json
import logging
import requests
import uuid
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

class PurchaseRequestSheetWebhook(http.Controller):

    @http.route('/hlv_zalo/webhook/purchase_request_from_sheet', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def purchase_request_from_sheet(self, **kwargs):
        try:
            try:
                data = json.loads(request.httprequest.data)
            except Exception:
                data = kwargs

            _logger.info("Webhook tạo PR nhận dữ liệu: %s", data)

            id_sale = data.get('id_sale') or data.get('id_don_mua')
            nv_yeu_cau = data.get('nv_yeu_cau', '').strip()
            
            # Các trường bổ sung từ Sheet
            sheet_id = data.get('id', '')
            quy_trinh = data.get('quy_trinh', '')
            ngay_tao = data.get('ngay_tao', '')
            nguoi_duyet = data.get('nguoi_duyet', '')
            id_manager = data.get('id_manager', '')
            don_dich = data.get('don_dich', '')

            if not id_sale:
                return request.make_response(
                    json.dumps({'status': 'error', 'message': 'Missing id_sale / id_don_mua'}),
                    headers=[('Content-Type', 'application/json')], status=400)

            env = request.env
            misa_utils = env['misa.api.utils'].sudo()
            misa_config = env['misa.config'].sudo()
            odoo_utils = env['odoo.utils'].sudo()

            try:
                crm_token = misa_utils._fetch_login_crm_token()
                sale_headers = misa_config.get_crm_header(crm_token)
            except Exception as e:
                return request.make_response(
                    json.dumps({'status': 'error', 'message': f'Cannot connect to MISA CRM: {e}'}),
                    headers=[('Content-Type', 'application/json')], status=500)

            # 1. TÌM KIẾM ĐƠN BÁN TRONG MISA CRM ĐỂ LẤY ID
            orders_url = "https://amisapp.misa.vn/crm/g2/api/business/SaleOrder/Grid"
            search_payload = {
                "Columns": "SUQsU2FsZU9yZGVyTm8sU2FsZU9yZGVyTmFtZQ==",
                "Filters": [
                    {
                        "Addition": 1,
                        "InputType": 1,
                        "IsFromFormula": True,
                        "Operator": 1,
                        "Property": "SaleOrderNo",
                        "Text": id_sale,
                        "Value": id_sale
                    }
                ],
                "Formula": "( 1 )",
                "Start": 0,
                "Page": 1,
                "PageSize": 10,
                "DefaultTotal": False,
                "IsUsedELTS": True,
                "SessionID": str(uuid.uuid4())
            }
            
            response = requests.post(orders_url, headers=sale_headers, json=search_payload, timeout=30)
            response.raise_for_status()
            res_data = response.json().get("Data", [])
            
            if not res_data:
                return request.make_response(
                    json.dumps({'status': 'error', 'message': f'Not found Sale Order {id_sale} in MISA CRM'}),
                    headers=[('Content-Type', 'application/json')], status=404)
            
            misa_order_id = res_data[0].get("ID")
            
            # 2. LẤY CHI TIẾT SẢN PHẨM TRONG ĐƠN BÁN
            order_detail_url = "https://amisapp.misa.vn/crm/g2/api/business/SaleOrder/DataSubPaging"
            payload_detail = misa_config.get_crm_sale_order_detail_payload(misa_order_id)
            product_lines = misa_utils.get_list_product_by_order_crm(order_detail_url, sale_headers, payload_detail)
            
            if not product_lines:
                return request.make_response(
                    json.dumps({'status': 'error', 'message': f'Sale Order {id_sale} has no products'}),
                    headers=[('Content-Type', 'application/json')], status=400)

            # 3. TẠO YÊU CẦU MUA HÀNG (PURCHASE REQUEST)
            PRModel = env['purchase.request'].sudo()
            PRLineModel = env['purchase.request.line'].sudo()
            
            user = env.user
            if nv_yeu_cau:
                domain = [('x_studio_misa_saler_code', '=', nv_yeu_cau)] if 'x_studio_misa_saler_code' in env['res.users']._fields else [('name', 'ilike', nv_yeu_cau)]
                found_user = env['res.users'].sudo().search(domain, limit=1)
                if found_user:
                    user = found_user

            desc_lines = [
                "Tạo tự động từ Google Sheet.",
                f"Mã Đơn Bán MISA: {id_sale}"
            ]
            if sheet_id: desc_lines.append(f"ID Sheet: {sheet_id}")
            if quy_trinh: desc_lines.append(f"Quy trình: {quy_trinh}")
            if ngay_tao: desc_lines.append(f"Ngày tạo: {ngay_tao}")
            if nv_yeu_cau: desc_lines.append(f"Nhân viên yêu cầu: {nv_yeu_cau}")
            if nguoi_duyet: desc_lines.append(f"Người duyệt: {nguoi_duyet}")
            if id_manager: desc_lines.append(f"ID Manager: {id_manager}")
            if don_dich: desc_lines.append(f"Đơn đích: {don_dich}")

            pr_vals = {
                'requested_by': user.id,
                'origin': id_sale,
                'description': "\n".join(desc_lines),
            }
            if 'x_studio_misa_saler_code' in PRModel._fields:
                pr_vals['x_studio_misa_saler_code'] = nv_yeu_cau
                
            purchase_request = PRModel.create(pr_vals)
            
            for line in product_lines:
                product_code = line.get("ProductIDText")
                description = line.get("Description") or product_code
                qty = float(line.get("Amount", 1) or 0.0)
                uom_name = (line.get("UnitIDText") or "Cái").strip()
                
                if not product_code:
                    continue
                    
                product = odoo_utils._get_or_create_product(
                    code=product_code,
                    name=description,
                    unit_name=uom_name,
                    product_type="consu",
                    purchase_ok=True,
                    sale_ok=True
                )
                
                PRLineModel.create({
                    'request_id': purchase_request.id,
                    'product_id': product.id,
                    'name': description,
                    'product_qty': qty,
                    'product_uom_id': product.uom_id.id if product.uom_id else False,
                })

            return request.make_response(
                json.dumps({
                    'status': 'success',
                    'message': 'OK',
                    'pr_name': purchase_request.name,
                    'pr_id': purchase_request.id
                }),
                headers=[('Content-Type', 'application/json')]
            )

        except Exception as e:
            _logger.exception("Lỗi Webhook tạo Purchase Request")
            return request.make_response(
                json.dumps({'status': 'error', 'message': str(e)}),
                headers=[('Content-Type', 'application/json')],
                status=500
            )
