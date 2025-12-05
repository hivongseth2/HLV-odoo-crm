from odoo import http
from odoo.http import request
import json

class MisaController(http.Controller):

    @http.route('/api/misa/create_product', type='json', auth='user', methods=['POST'])
    def create_product(self, product_id):
        """
        API tạo sản phẩm MISA.
        Body JSON: {"product_id": 123}
        """
        try:
            misa_utils = request.env['misa.api.utils']
            misa_id = misa_utils.create_product_misa_api(product_id)
            return {
                "status": "success",
                "message": "Tạo thành công",
                "misa_id": misa_id
            }
        except Exception as e:
            return {
                "status": "error",
                "message": str(e)
            }