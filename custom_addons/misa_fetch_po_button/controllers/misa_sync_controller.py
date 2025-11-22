# -*- coding: utf-8 -*-
import logging
import json
from odoo import http
from odoo.http import request, Response

_logger = logging.getLogger(__name__)


class MisaSyncController(http.Controller):
    """
    Controller for updating MISA sync status from external automation app

    === ENDPOINT ===
    URL: https://your-odoo-domain.com/api/misa/sync/update
    Method: POST
    Content-Type: application/json
    Header: X-API-Key: <your-api-key>

    === REQUEST BODY ===
    {
        "order_name": "SO00123",
        "sync_status": true
    }

    === RESPONSE ===
    {
        "success": true,
        "message": "MISA sync status updated successfully",
        "order_id": 12345
    }

    === BẢO MẬT ===
    - Endpoint sử dụng API key từ System Parameters 'odoo-secret-key'
    - Cần cung cấp X-API-Key header để xác thực
    """

    @http.route('/api/misa/sync/update', type='http', auth='public', methods=['POST'], csrf=False, cors='*')
    def update_misa_sync_status(self, **kwargs):
        """
        Cập nhật trạng thái MISA sync cho đơn hàng

        :param kwargs: Dữ liệu từ request body
        :return: JSON response với kết quả
        """

        try:
            # Parse JSON data từ request body
            try:
                data = json.loads(request.httprequest.data.decode('utf-8'))
            except (json.JSONDecodeError, AttributeError, UnicodeDecodeError) as e:
                _logger.warning("MISA Sync API - Invalid JSON in request body: %s", str(e))
                return Response(
                    json.dumps({'success': False, 'error': 'Invalid JSON format'}),
                    content_type='application/json',
                    status=400
                )

            # Kiểm tra API key từ System Parameters
            api_key_param = request.env['ir.config_parameter'].sudo().get_param('odoo-secret-key')

            if not api_key_param:
                _logger.error("MISA Sync API - No API key configured in System Parameters")
                return Response(
                    json.dumps({'success': False, 'error': 'API key not configured in Odoo'}),
                    content_type='application/json',
                    status=500
                )

            # Lấy API key từ header
            request_api_key = request.httprequest.headers.get('X-API-Key')

            if not request_api_key:
                _logger.warning("MISA Sync API - Missing API key in request header")
                return Response(
                    json.dumps({'success': False, 'error': 'Missing API key. Please provide X-API-Key header.'}),
                    content_type='application/json',
                    status=401
                )

            if request_api_key != api_key_param:
                _logger.warning("MISA Sync API - Invalid API key provided")
                return Response(
                    json.dumps({'success': False, 'error': 'Invalid API key'}),
                    content_type='application/json',
                    status=403
                )

            _logger.debug("MISA Sync API - API key validated successfully")

            # Validate required fields
            required_fields = ['order_name', 'sync_status']
            missing_fields = [field for field in required_fields if field not in data]

            if missing_fields:
                _logger.warning("MISA Sync API - Missing required fields: %s", missing_fields)
                return Response(
                    json.dumps({'success': False, 'error': f'Missing required fields: {", ".join(missing_fields)}'}),
                    content_type='application/json',
                    status=400
                )

            order_name = data.get('order_name', '').strip()
            sync_status = data.get('sync_status', False)

            if not order_name:
                return Response(
                    json.dumps({'success': False, 'error': 'order_name cannot be empty'}),
                    content_type='application/json',
                    status=400
                )

            # Tìm đơn hàng trong Odoo
            # Ưu tiên tìm theo Sale Order name trước
            sale_order = request.env['sale.order'].sudo().search([('name', '=', order_name)], limit=1)

            if not sale_order:
                # Nếu không tìm thấy SO, tìm theo Stock Picking name
                picking = request.env['stock.picking'].sudo().search([('name', '=', order_name)], limit=1)
                if picking:
                    # Tìm SO liên kết với picking này
                    if picking.sale_id:
                        sale_order = picking.sale_id
                    else:
                        # Tìm SO qua picking's move lines
                        for move in picking.move_ids_without_package:
                            if move.sale_line_id and move.sale_line_id.order_id:
                                sale_order = move.sale_line_id.order_id
                                break

            if not sale_order:
                _logger.warning("MISA Sync API - Order not found: %s", order_name)
                return Response(
                    json.dumps({'success': False, 'error': f'Order not found: {order_name}'}),
                    content_type='application/json',
                    status=404
                )

            # Kiểm tra trường x_studio_misa_sav có tồn tại không
            if not hasattr(sale_order, 'x_studio_misa_sav'):
                _logger.error("MISA Sync API - Field x_studio_misa_sav not found on sale.order")
                return Response(
                    json.dumps({'success': False, 'error': 'MISA sync field not available'}),
                    content_type='application/json',
                    status=500
                )

            # Cập nhật trạng thái MISA sync
            current_status = getattr(sale_order, 'x_studio_misa_sav', False)

            # Chỉ cập nhật nếu trạng thái mới khác với trạng thái hiện tại
            if current_status != bool(sync_status):
                sale_order.sudo().write({'x_studio_misa_sav': bool(sync_status)})
                _logger.info("MISA Sync API - Updated MISA sync status for order %s: %s -> %s",
                           order_name, current_status, bool(sync_status))

                # Ghi chú trên đơn hàng
                action = "Enabled" if bool(sync_status) else "Disabled"
                sale_order.sudo().message_post(
                    body=f"MISA sync status updated via API: {action}"
                )
            else:
                _logger.info("MISA Sync API - No status change needed for order %s: %s",
                           order_name, current_status)

            response_data = {
                'success': True,
                'message': 'MISA sync status updated successfully',
                'order_id': sale_order.id,
                'order_name': sale_order.name,
                'sync_status': getattr(sale_order, 'x_studio_misa_sav', False)
            }

            return Response(
                json.dumps(response_data),
                content_type='application/json',
                status=200
            )

        except Exception as e:
            _logger.exception("Error updating MISA sync status: %s", e)
            return Response(
                json.dumps({'success': False, 'error': str(e)}),
                content_type='application/json',
                status=500
            )

    @http.route('/api/misa/sync/status', type='http', auth='public', methods=['GET'], csrf=False, cors='*')
    def get_misa_sync_status(self, **kwargs):
        """
        Lấy trạng thái MISA sync của đơn hàng (dùng để test)

        Query parameters:
        - order_name: Tên đơn hàng

        :return: JSON response với trạng thái hiện tại
        """

        try:
            # Kiểm tra API key
            api_key_param = request.env['ir.config_parameter'].sudo().get_param('odoo-secret-key')

            if not api_key_param:
                return Response(
                    json.dumps({'success': False, 'error': 'API key not configured in Odoo'}),
                    content_type='application/json',
                    status=500
                )

            request_api_key = request.httprequest.headers.get('X-API-Key')

            if not request_api_key or request_api_key != api_key_param:
                return Response(
                    json.dumps({'success': False, 'error': 'Invalid or missing API key'}),
                    content_type='application/json',
                    status=401
                )

            # Lấy order_name từ query parameter
            order_name = request.httprequest.args.get('order_name', '').strip()

            if not order_name:
                return Response(
                    json.dumps({'success': False, 'error': 'order_name parameter is required'}),
                    content_type='application/json',
                    status=400
                )

            # Tìm đơn hàng
            sale_order = request.env['sale.order'].sudo().search([('name', '=', order_name)], limit=1)

            if not sale_order:
                # Thử tìm qua picking
                picking = request.env['stock.picking'].sudo().search([('name', '=', order_name)], limit=1)
                if picking and picking.sale_id:
                    sale_order = picking.sale_id
                elif picking:
                    for move in picking.move_ids_without_package:
                        if move.sale_line_id and move.sale_line_id.order_id:
                            sale_order = move.sale_line_id.order_id
                            break

            if not sale_order:
                return Response(
                    json.dumps({'success': False, 'error': f'Order not found: {order_name}'}),
                    content_type='application/json',
                    status=404
                )

            response_data = {
                'success': True,
                'order_id': sale_order.id,
                'order_name': sale_order.name,
                'sync_status': getattr(sale_order, 'x_studio_misa_sav', False),
                'message': 'Status retrieved successfully'
            }

            return Response(
                json.dumps(response_data),
                content_type='application/json',
                status=200
            )

        except Exception as e:
            _logger.exception("Error getting MISA sync status: %s", e)
            return Response(
                json.dumps({'success': False, 'error': str(e)}),
                content_type='application/json',
                status=500
            )