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
            category_id = kwargs.get('category_id', None)
            price_pu = kwargs.get('price_pu', 0)

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
                product_type=p_type,
                category_id=category_id,
                 price_pu=price_pu,
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
        API tìm kiếm sản phẩm MISA theo tên hoặc mã sản phẩm.
        
        Body mẫu (JSON):
        {
            "jsonrpc": "2.0",
            "params": {
                "name": "Tên sản phẩm cần tìm",
                "code": "Mã sản phẩm cần tìm",
                "limit": 20
            }
        }
        
        Lưu ý:
        - Có thể truyền "name" hoặc "code" hoặc cả 2
        - Nếu truyền cả 2, sẽ tìm theo điều kiện AND (cả tên và mã đều khớp)
        
        Response:
        {
            "status": "success",
            "message": "Tìm thấy N sản phẩm",
            "data": {
                "total": N,
                "products": [
                    {
                        "misa_id": "...",
                        "code": "SP001",
                        "name": "Tên sản phẩm",
                        "price": 100000,
                        "unit": "Cái",
                        "category": "Hàng hóa",
                        "tax": "10%",
                        "type": "Hàng hóa",
                        "active": true
                    },
                    ...
                ]
            }
        }
        """
        try:
            # 1. Lấy tham số
            name = kwargs.get('name')
            code = kwargs.get('code')
            limit = kwargs.get('limit', 20)

            # Validate cơ bản - cần ít nhất 1 trong 2: name hoặc code
            if not name and not code:
                return {
                    "status": "error", 
                    "message": "Thiếu thông tin bắt buộc: cần truyền 'name' hoặc 'code' (hoặc cả 2)"
                }

            # 2. Gọi logic xử lý (Dùng sudo để bypass quyền)
            misa_utils = request.env['misa.api.utils'].sudo()
            
            products = misa_utils.search_product_by_name(
                name=name, 
                code=code,
                limit=int(limit)
            )

            # 3. Trả về kết quả
            return {
                "status": "success",
                "message": f"Tìm thấy {len(products)} sản phẩm",
                "data": {
                    "total": len(products),
                    "products": products
                }
            }

        except Exception as e:
            _logger.exception("API MISA Search Error")
            return {
                "status": "error",
                "message": str(e)
            }
            
    @http.route('/api/misa/purchase/search', type='json', auth='public', methods=['POST'], csrf=False)
    def api_search_purchase_misa(self, **kwargs):
        """
        API tìm kiếm chứng từ mua hàng MISA (actapp) theo diễn giải.
        
        Body mẫu (JSON):
        {
            "jsonrpc": "2.0",
            "params": {
                "journal_memo": "DH1255...",
                "limit": 20
            }
        }
        
        Response:
        {
            "status": "success",
            "message": "Tìm thấy N chứng từ",
            "data": [ ... ]
        }
        """
        try:
            journal_memo = kwargs.get('journal_memo')
            limit = kwargs.get('limit', 20)
            
            if not journal_memo:
                return {
                    "status": "error",
                    "message": "Thiếu tham số 'journal_memo'"
                }
                
            misa_utils = request.env['misa.api.utils'].sudo()
            result = misa_utils.search_purchase_voucher(journal_memo, limit)
            
            return {
                "status": "success",
                "message": f"Tìm thấy {len(result)} chứng từ",
                "data": result
            }
            
        except Exception as e:
            _logger.exception("API MISA Purchase Search Error")
            return {
                "status": "error",
                "message": str(e)
            }

    @http.route('/api/misa/product/export', type='json', auth='user', methods=['POST'], csrf=False)
    def api_export_products_misa(self, **kwargs):
        """
        API xuất tất cả sản phẩm từ MISA CRM ra file Excel.
        
        Body mẫu (JSON):
        {
            "jsonrpc": "2.0",
            "params": {}
        }
        
        Response:
        {
            "status": "success",
            "message": "Xuất thành công N sản phẩm",
            "data": {
                "file_base64": "...",
                "file_name": "misa_products_20231219.xlsx",
                "total_products": N,
                "total_categories": M
            }
        }
        """
        try:
            from odoo.addons.misa_fetch_po_button.utils.misa_product_export import MisaProductExporter
            from datetime import datetime
            import base64
            
            exporter = MisaProductExporter(request.env)
            
            # Lấy dữ liệu
            products = exporter.fetch_all_products()
            categories = exporter.fetch_all_categories()
            
            # Xuất Excel
            excel_content = exporter.export_all_products_to_excel()
            
            file_name = f"misa_products_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            
            return {
                "status": "success",
                "message": f"Xuất thành công {len(products)} sản phẩm và {len(categories)} danh mục",
                "data": {
                    "file_base64": base64.b64encode(excel_content).decode('utf-8'),
                    "file_name": file_name,
                    "total_products": len(products),
                    "total_categories": len(categories)
                }
            }
            
        except Exception as e:
            _logger.exception("API MISA Export Error")
            return {
                "status": "error",
                "message": str(e)
            }

    @http.route('/api/misa/product/export/download', type='http', auth='user', methods=['GET'], csrf=False)
    def api_download_products_misa(self, **kwargs):
        """
        API tải trực tiếp file Excel sản phẩm MISA.
        
        URL: /api/misa/product/export/download
        Method: GET
        
        Response: File Excel download
        """
        try:
            from odoo.addons.misa_fetch_po_button.utils.misa_product_export import MisaProductExporter
            from datetime import datetime
            
            exporter = MisaProductExporter(request.env)
            excel_content = exporter.export_all_products_to_excel()
            
            file_name = f"misa_products_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
            
            return request.make_response(
                excel_content,
                headers=[
                    ('Content-Type', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                    ('Content-Disposition', f'attachment; filename="{file_name}"'),
                ]
            )
            
        except Exception as e:
            _logger.exception("API MISA Export Download Error")
            return request.make_response(
                f"Error: {str(e)}",
                headers=[('Content-Type', 'text/plain')],
                status=500
            )
