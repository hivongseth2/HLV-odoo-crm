# controllers/misa_controller.py
from odoo import http
from odoo.http import request
import json
import logging

_logger = logging.getLogger(__name__)

class MisaController(http.Controller):

    @http.route('/api/misa/create-product', type='json', auth='public', methods=['POST'], csrf=False)
    def create_product_api(self, **kwargs):
        """
        API tạo sản phẩm sang MISA.
        Endpoint: /api/misa/create-product
        Method: POST
        Body (JSON):
        {
            "jsonrpc": "2.0",
            "params": {
                "product_id": 123
            }
        }
        """
        try:
            # 1. Lấy tham số từ body
            product_id = kwargs.get('product_id')
            
            if not product_id:
                return {
                    "status": "error",
                    "message": "Thiếu tham số 'product_id'"
                }

            # 2. Gọi hàm logic trong Model (Dùng sudo() để bỏ qua quyền nếu gọi public)
            # Hàm này nằm trong file misa_api_utils.py mà ta đã viết
            misa_utils = request.env['misa.api.utils'].sudo()
            misa_id = misa_utils.create_product_misa(int(product_id))

            # 3. Trả về kết quả thành công
            return {
                "status": "success",
                "message": "Đã đồng bộ thành công sang MISA",
                "data": {
                    "odoo_product_id": product_id,
                    "misa_crm_id": misa_id
                }
            }

        except Exception as e:
            _logger.exception("Lỗi API MISA Controller")
            # Trả về lỗi
            return {
                "status": "error",
                "message": str(e)
            }