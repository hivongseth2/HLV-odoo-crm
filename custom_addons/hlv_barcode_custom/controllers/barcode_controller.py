# -*- coding: utf-8 -*-
import logging
from odoo import http, _
from odoo.http import request

_logger = logging.getLogger(__name__)


class BarcodeCustomController(http.Controller):
    """JSON-RPC routes for barcode scanning operations."""

    @http.route('/hlv_barcode_custom/get_config', type='json', auth='user')
    def get_config(self):
        """Get barcode configuration for frontend."""
        ICP = request.env['ir.config_parameter'].sudo()
        return {
            'auto_focus': ICP.get_param('hlv_barcode_custom.auto_focus', 'True') == 'True',
            'sound_success': ICP.get_param('hlv_barcode_custom.sound_success', 'True') == 'True',
            'sound_error': ICP.get_param('hlv_barcode_custom.sound_error', 'True') == 'True',
            'strict_delivery': ICP.get_param('hlv_barcode_custom.strict_delivery', 'True') == 'True',
            'decimal_step': float(ICP.get_param('hlv_barcode_custom.decimal_step', '0.1')),
            'camera_enabled': ICP.get_param('hlv_barcode_custom.camera_enabled', 'True') == 'True',
        }

    @http.route('/hlv_barcode_custom/scan', type='json', auth='user')
    def scan_barcode(self, picking_id, barcode, location_barcode=None):
        """Main barcode scan endpoint - server-side validation."""
        return request.env['stock.picking'].scan_barcode_on_picking(
            picking_id, barcode, location_barcode
        )

    @http.route('/hlv_barcode_custom/search_product', type='json', auth='user')
    def search_product(self, barcode):
        """Global product search endpoint."""
        return request.env['stock.picking'].search_product_global(barcode)

    @http.route('/hlv_barcode_custom/scan_global', type='json', auth='user')
    def scan_global(self, barcode):
        """Global scan from home: find picking or product."""
        return request.env['stock.picking'].scan_barcode_global(barcode)

    @http.route('/hlv_barcode_custom/get_picking_types', type='json', auth='user')
    def get_picking_types(self):
        """Get operation types for menu."""
        return request.env['stock.picking'].get_barcode_picking_types()

    @http.route('/hlv_barcode_custom/get_pickings', type='json', auth='user')
    def get_pickings(self, picking_type_id=None, picking_type_code=None):
        """Get pickings list for barcode interface."""
        return request.env['stock.picking'].get_barcode_pickings(
            picking_type_id=picking_type_id,
            picking_type_code=picking_type_code,
        )

    @http.route('/hlv_barcode_custom/get_picking_detail', type='json', auth='user')
    def get_picking_detail(self, picking_id):
        """Get detailed picking data."""
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists():
            return {'status': 'error', 'message': _('Phiếu không tồn tại.')}
        return picking.get_picking_detail()

    @http.route('/hlv_barcode_custom/update_quantity', type='json', auth='user')
    def update_quantity(self, move_id, quantity):
        """Update quantity on a move line."""
        return request.env['stock.picking'].update_move_quantity(move_id, quantity)

    @http.route('/hlv_barcode_custom/validate_picking', type='json', auth='user')
    def validate_picking(self, picking_id):
        """Validate / confirm a picking after scanning."""
        picking = request.env['stock.picking'].browse(picking_id)
        if not picking.exists():
            return {'status': 'error', 'message': _('Phiếu không tồn tại.')}
        try:
            picking.button_validate()
            return {'status': 'success', 'message': _('✓ Phiếu %s đã được xác nhận thành công!') % picking.name}
        except Exception as e:
            return {'status': 'error', 'message': str(e)}

    @http.route('/hlv_barcode_custom/get_product_image', type='http', auth='user')
    def get_product_image(self, product_id):
        """Serve product image."""
        product = request.env['product.product'].browse(int(product_id))
        if product.exists() and product.image_128:
            return request.make_response(
                product.image_128,
                headers=[
                    ('Content-Type', 'image/png'),
                    ('Cache-Control', 'public, max-age=3600'),
                ],
            )
        # Return transparent 1x1 pixel
        import base64
        pixel = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==')
        return request.make_response(pixel, headers=[('Content-Type', 'image/png')])
