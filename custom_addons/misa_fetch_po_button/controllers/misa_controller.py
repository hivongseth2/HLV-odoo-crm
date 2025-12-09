from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)

class MisaController(http.Controller):

    @http.route('/api/misa/product/create', type='json', auth='public', methods=['POST'], csrf=False)
    def api_create_product_misa(self, **kwargs):
        """
        API tạo sản phẩm MISA từ params truyền vào.
        
        Body mẫu (JSON):
        {
            "jsonrpc": "2.0",
            "params": {
                "code": "SP_API_001",
                "name": "Sản phẩm test API",
                "price": 500000,
                "tax": 8,
                "unit": "Hộp",
                "category": "Hàng hóa",
                "type": "goods"
            }
        }
        """
        try:
            # 1. Lấy tham số
            code = kwargs.get('code')
            name = kwargs.get('name')
            price = kwargs.get('price', 0)
            tax = kwargs.get('tax', 10)          # Mặc định 10%
            unit = kwargs.get('unit', 'Cái')     # Mặc định Cái
            category = kwargs.get('category', 'Hàng hóa')
            p_type = kwargs.get('type', 'goods') # goods hoặc service

            # Validate cơ bản
            if not code or not name:
                return {
                    "status": "error", 
                    "message": "Thiếu thông tin bắt buộc: code, name"
                }

            # 2. Gọi logic xử lý (Dùng sudo để bypass quyền)
            misa_utils = request.env['misa.api.utils'].sudo()
            
            misa_id = misa_utils.create_product_misa_raw(
                code=code, 
                name=name, 
                price=price, 
                tax_percent=tax, 
                unit_name=unit, 
                category_name=category,
                product_type=p_type
            )

            # 3. Trả về kết quả
            return {
                "status": "success",
                "message": "Tạo thành công",
                "data": {
                    "misa_id": misa_id,
                    "code": code
                }
            }

        except Exception as e:
            _logger.exception("API MISA Error")
            return {
                "status": "error",
                "message": str(e)
            }

    @http.route('/api/misa/product/search', type='json', auth='public', methods=['POST'], csrf=False)
    def api_search_product_misa(self, **kwargs):
        """
        API tìm kiếm sản phẩm MISA và trả về Full Detail.
        Body:
        {
            "name": "Búa"
        }
        """
        try:
            name = kwargs.get('name')
            if not name:
                return {"status": "error", "message": "Thiếu tham số 'name'"}

            misa_utils = request.env['misa.api.utils'].sudo()
            data = misa_utils.search_product_misa_raw(name)
            
            if not data:
                return {"status": "error", "message": "Không tìm thấy sản phẩm"}

            return {
                "status": "success",
                "data": data
            }

        except Exception as e:
            _logger.exception("API Search MISA Error")
            return {
                "status": "error",
                "message": str(e)
            }