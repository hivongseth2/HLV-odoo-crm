# -*- coding: utf-8 -*-
import logging
from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class StockPickingBarcode(models.Model):
    """Extension of stock.picking with server-side barcode scanning validation."""
    _inherit = 'stock.picking'

    def _get_barcode_config(self):
        """Return config dict for frontend."""
        ICP = self.env['ir.config_parameter'].sudo()
        return {
            'auto_focus': ICP.get_param('hlv_barcode_custom.auto_focus', 'True') == 'True',
            'sound_success': ICP.get_param('hlv_barcode_custom.sound_success', 'True') == 'True',
            'sound_error': ICP.get_param('hlv_barcode_custom.sound_error', 'True') == 'True',
            'strict_delivery': ICP.get_param('hlv_barcode_custom.strict_delivery', 'True') == 'True',
            'decimal_step': float(ICP.get_param('hlv_barcode_custom.decimal_step', '0.1')),
            'camera_enabled': ICP.get_param('hlv_barcode_custom.camera_enabled', 'True') == 'True',
        }

    @api.model
    def get_barcode_picking_types(self):
        """Get all active picking types for the barcode menu, grouped by warehouse."""
        types = self.env['stock.picking.type'].search([
            ('code', 'in', ['incoming', 'outgoing', 'internal']),
            ('active', '=', True),
        ], order='warehouse_id asc, sequence asc')
        warehouses = {}
        for pt in types:
            wh_id = pt.warehouse_id.id or 0
            wh_name = pt.warehouse_id.name or 'Khác'
            if wh_id not in warehouses:
                warehouses[wh_id] = {
                    'warehouse_id': wh_id,
                    'warehouse_name': wh_name,
                    'picking_types': [],
                }
            # Count ready pickings
            count = self.search_count([
                ('picking_type_id', '=', pt.id),
                ('state', 'in', ['assigned', 'confirmed', 'waiting']),
            ])
            warehouses[wh_id]['picking_types'].append({
                'id': pt.id,
                'name': pt.name,
                'code': pt.code,
                'count': count,
                'warehouse_id': wh_id,
                'warehouse_name': wh_name,
                'scan_source': pt.barcode_scan_source or 'no',
                'scan_dest': pt.barcode_scan_dest or 'no',
                'require_product_scan': pt.barcode_require_product_scan,
            })
        return list(warehouses.values())

    @api.model
    def get_barcode_pickings(self, picking_type_id=None, picking_type_code=None):
        """Get list of pickings ready for barcode scanning."""
        domain = [('state', 'in', ['assigned', 'confirmed', 'waiting'])]
        if picking_type_id:
            domain.append(('picking_type_id', '=', picking_type_id))
        elif picking_type_code:
            domain.append(('picking_type_code', '=', picking_type_code))

        pickings = self.search(domain, order='scheduled_date asc, id asc', limit=100)
        result = []
        for p in pickings:
            result.append({
                'id': p.id,
                'name': p.name,
                'origin': p.origin or '',
                'partner_name': p.partner_id.name or '',
                'picking_type_code': p.picking_type_code,
                'picking_type_name': p.picking_type_id.name or '',
                'state': p.state,
                'state_label': dict(p._fields['state'].selection).get(p.state, p.state),
                'scheduled_date': fields.Datetime.to_string(p.scheduled_date) if p.scheduled_date else '',
                'location_id': p.location_id.id,
                'location_name': p.location_id.complete_name or p.location_id.name,
                'location_dest_id': p.location_dest_id.id,
                'location_dest_name': p.location_dest_id.complete_name or p.location_dest_id.name,
                'move_count': len(p.move_ids),
                'has_packages': bool(p.move_line_ids.filtered(lambda ml: ml.package_id)),
                'priority': p.priority or '0',
                'user_name': p.user_id.name or '',
            })
        return result

    def get_picking_detail(self):
        """Get detailed picking data with move lines for barcode scanning."""
        self.ensure_one()
        pt = self.picking_type_id
        # Determine scan config
        scan_source = pt.barcode_scan_source or 'no'
        scan_dest = pt.barcode_scan_dest or 'no'
        require_product_scan = pt.barcode_require_product_scan

        # Check if source location is transit (Inter-warehouse transit)
        source_is_transit = self.location_id.usage == 'transit'

        # For internal transfers from transit → override scan_source to 'no'
        if self.picking_type_code == 'internal' and source_is_transit:
            scan_source = 'no'

        lines = []
        for move in self.move_ids.filtered(lambda m: m.state not in ('done', 'cancel')):
            # Check if product is a BOM Kit component
            bom_info = self._get_bom_kit_info(move.product_id)

            # Get sub-locations from move_line_ids (detailed bin/shelf locations)
            move_lines_data = []
            for sml in move.move_line_ids:
                move_lines_data.append({
                    'id': sml.id,
                    'location_id': sml.location_id.id,
                    'location_name': sml.location_id.complete_name or sml.location_id.name,
                    'location_dest_id': sml.location_dest_id.id,
                    'location_dest_name': sml.location_dest_id.complete_name or sml.location_dest_id.name,
                    'quantity': sml.quantity,
                    'lot_name': sml.lot_id.name if sml.lot_id else '',
                    'package_name': sml.package_id.name if sml.package_id else '',
                })

            # Use move_line source/dest for display (sub-location detail)
            display_location = move.location_id.complete_name or move.location_id.name
            display_location_dest = move.location_dest_id.complete_name or move.location_dest_id.name
            if move.move_line_ids:
                first_sml = move.move_line_ids[0]
                display_location = first_sml.location_id.complete_name or first_sml.location_id.name
                display_location_dest = first_sml.location_dest_id.complete_name or first_sml.location_dest_id.name

            lines.append({
                'move_id': move.id,
                'product_id': move.product_id.id,
                'product_name': move.product_id.display_name,
                'product_barcode': move.product_id.barcode or '',
                'product_default_code': move.product_id.default_code or '',
                'product_image': True if move.product_id.image_128 else False,
                'demand': move.product_uom_qty - move.quantity,
                # Always start from 0 in scanning UI - actual DB qty tracked separately
                'quantity_done': 0,
                'quantity_done_db': move.quantity,
                'uom_name': move.product_uom.name,
                'uom_rounding': move.product_uom.rounding,
                'is_decimal': move.product_uom.rounding < 1.0,
                'location_id': move.location_id.id,
                'location_name': display_location,
                'location_dest_id': move.location_dest_id.id,
                'location_dest_name': display_location_dest,
                'move_lines': move_lines_data,
                'lot_ids': [{'id': lot.id, 'name': lot.name} for lot in move.lot_ids],
                'bom_kit_name': bom_info.get('kit_name', ''),
                'bom_kit_product': bom_info.get('kit_product', ''),
                'is_bom_component': bom_info.get('is_component', False),
                'source_scanned': False,
                'dest_scanned': False,
            })
        return {
            'id': self.id,
            'name': self.name,
            'origin': self.origin or '',
            'partner_name': self.partner_id.name or '',
            'picking_type_code': self.picking_type_code,
            'picking_type_name': pt.name or '',
            'state': self.state,
            'priority': self.priority or '0',
            'location_id': self.location_id.id,
            'location_name': self.location_id.complete_name or self.location_id.name,
            'location_dest_id': self.location_dest_id.id,
            'location_dest_name': self.location_dest_id.complete_name or self.location_dest_id.name,
            'source_is_transit': source_is_transit,
            'lines': lines,
            'config': self._get_barcode_config(),
            'scan_config': {
                'scan_source': scan_source,
                'scan_dest': scan_dest,
                'require_product_scan': require_product_scan,
            },
        }

    def _get_bom_kit_info(self, product):
        """Check if product is a component of a BOM Kit."""
        self.ensure_one()
        try:
            BomLine = self.env['mrp.bom.line']
            bom_lines = BomLine.search([
                ('product_id', '=', product.id),
                ('bom_id.type', '=', 'phantom'),
            ], limit=1)
            if bom_lines:
                kit_bom = bom_lines.bom_id
                kit_product = kit_bom.product_tmpl_id
                return {
                    'is_component': True,
                    'kit_name': kit_bom.display_name or kit_product.name,
                    'kit_product': kit_product.name,
                }
        except Exception:
            pass
        return {'is_component': False, 'kit_name': '', 'kit_product': ''}

    @api.model
    def scan_barcode_on_picking(self, picking_id, barcode, location_barcode=None):
        """
        Server-side barcode scan handler.
        Validates product, quantity, and location in real-time.
        Returns result dict with status and data.
        """
        picking = self.browse(picking_id)
        if not picking.exists():
            return {'status': 'error', 'message': _('Phiếu không tồn tại.')}

        if picking.state not in ('assigned', 'confirmed', 'waiting'):
            return {'status': 'error', 'message': _('Phiếu ở trạng thái không hợp lệ: %s') % picking.state}

        # Check if barcode is a location
        location = self.env['stock.location'].search([('barcode', '=', barcode)], limit=1)
        if location:
            return {
                'status': 'location',
                'location_id': location.id,
                'location_name': location.complete_name or location.name,
                'location_barcode': location.barcode,
                'location_usage': location.usage,
            }

        # Try to find product by barcode or default_code
        product = self._find_product_by_barcode(barcode)
        if not product:
            # Check if it's a package barcode (for internal transfers)
            package = self.env['stock.quant.package'].search([('name', '=', barcode)], limit=1)
            if package and picking.picking_type_code == 'internal':
                return self._handle_package_scan(picking, package)
            return {'status': 'not_found', 'barcode': barcode, 'message': _('Không tìm thấy sản phẩm với mã: %s') % barcode}

        # Dispatch by picking type
        if picking.picking_type_code == 'outgoing':
            return self._handle_delivery_scan(picking, product, location_barcode)
        elif picking.picking_type_code == 'incoming':
            return self._handle_receipt_scan(picking, product)
        elif picking.picking_type_code == 'internal':
            return self._handle_internal_scan(picking, product)
        else:
            return self._handle_generic_scan(picking, product)

    @api.model
    def _find_product_by_barcode(self, barcode):
        """Find product by barcode, default_code, or packaging barcode."""
        Product = self.env['product.product']
        product = Product.search([('barcode', '=', barcode)], limit=1)
        if not product:
            product = Product.search([('default_code', '=', barcode)], limit=1)
        if not product:
            packaging = self.env['product.packaging'].search([('barcode', '=', barcode)], limit=1)
            if packaging:
                product = packaging.product_id
        return product

    def _handle_delivery_scan(self, picking, product, location_barcode=None):
        """
        Handle scanning for Delivery Orders / Outgoing Pickings.
        Rules:
        1. Product must be in the picking's move lines
        2. Cannot exceed demand quantity
        3. Must have stock at the source location
        """
        picking.ensure_one()
        config = picking._get_barcode_config()

        # Rule 1: Product must be in picking
        matching_moves = picking.move_ids.filtered(
            lambda m: m.product_id.id == product.id and m.state not in ('done', 'cancel')
        )
        if not matching_moves:
            return {
                'status': 'error',
                'error_type': 'not_in_picking',
                'message': _('Sản phẩm [%s] %s KHÔNG có trong phiếu này!') % (product.default_code or product.barcode, product.name),
            }

        # Find the best move line to increment
        target_move = None
        for move in matching_moves:
            remaining = move.product_uom_qty - move.quantity
            if remaining > 0:
                target_move = move
                break

        if not target_move:
            # Rule 2: All moves are fully done
            if config.get('strict_delivery', True):
                return {
                    'status': 'error',
                    'error_type': 'over_demand',
                    'message': _('Sản phẩm [%s] %s đã đủ số lượng yêu cầu! Không thể quét thêm.') % (
                        product.default_code or product.barcode, product.name),
                }

        if target_move:
            # Rule 3: Check stock at source location
            source_location = target_move.location_id
            if location_barcode:
                scan_location = self.env['stock.location'].search([('barcode', '=', location_barcode)], limit=1)
                if scan_location:
                    source_location = scan_location

            available_qty = self._get_available_qty(product, source_location)
            already_scanned = target_move.quantity
            remaining_demand = target_move.product_uom_qty - already_scanned

            if available_qty <= 0:
                return {
                    'status': 'error',
                    'error_type': 'no_stock',
                    'message': _('Vị trí [%s] KHÔNG có tồn kho sản phẩm [%s] %s!') % (
                        source_location.complete_name or source_location.name,
                        product.default_code or '', product.name),
                }

            if available_qty < 1.0 and target_move.product_uom.rounding >= 1.0:
                return {
                    'status': 'error',
                    'error_type': 'insufficient_stock',
                    'message': _('Vị trí [%s] không đủ số lượng sản phẩm [%s] %s. Tồn: %.2f') % (
                        source_location.complete_name or source_location.name,
                        product.default_code or '', product.name, available_qty),
                }

            # Increment quantity
            increment = min(1.0, remaining_demand)
            new_qty = already_scanned + increment
            target_move.write({'quantity': new_qty})

            return {
                'status': 'success',
                'move_id': target_move.id,
                'product_id': product.id,
                'product_name': product.display_name,
                'product_barcode': product.barcode or product.default_code or '',
                'demand': target_move.product_uom_qty,
                'quantity_done': new_qty,
                'remaining': target_move.product_uom_qty - new_qty,
                'uom_name': target_move.product_uom.name,
                'location_name': source_location.complete_name or source_location.name,
                'message': _('✓ %s: %.1f / %.1f %s') % (product.name, new_qty, target_move.product_uom_qty, target_move.product_uom.name),
            }

        return {'status': 'error', 'message': _('Không tìm thấy dòng phù hợp để cập nhật.')}

    def _handle_receipt_scan(self, picking, product):
        """Handle scanning for Receipts / Incoming Pickings."""
        picking.ensure_one()

        # Find matching move or create new line
        matching_moves = picking.move_ids.filtered(
            lambda m: m.product_id.id == product.id and m.state not in ('done', 'cancel')
        )

        if matching_moves:
            target_move = matching_moves[0]
            new_qty = target_move.quantity + 1.0
            target_move.write({'quantity': new_qty})
            return {
                'status': 'success',
                'move_id': target_move.id,
                'product_id': product.id,
                'product_name': product.display_name,
                'product_barcode': product.barcode or product.default_code or '',
                'demand': target_move.product_uom_qty,
                'quantity_done': new_qty,
                'remaining': max(0, target_move.product_uom_qty - new_qty),
                'uom_name': target_move.product_uom.name,
                'location_dest_name': picking.location_dest_id.complete_name or picking.location_dest_id.name,
                'message': _('✓ Nhập: %s → %.1f %s') % (product.name, new_qty, target_move.product_uom.name),
            }
        else:
            # Product not in original picking - still allow for receipts
            return {
                'status': 'warning',
                'message': _('Sản phẩm %s không có trong phiếu nhập. Vui lòng thêm thủ công nếu cần.') % product.name,
                'product_id': product.id,
                'product_name': product.display_name,
            }

    def _handle_internal_scan(self, picking, product):
        """Handle scanning for Internal Transfers."""
        picking.ensure_one()

        matching_moves = picking.move_ids.filtered(
            lambda m: m.product_id.id == product.id and m.state not in ('done', 'cancel')
        )

        if matching_moves:
            target_move = matching_moves[0]
            # Check available stock at source
            available_qty = self._get_available_qty(product, target_move.location_id)
            if available_qty <= 0:
                return {
                    'status': 'error',
                    'error_type': 'no_stock',
                    'message': _('Vị trí nguồn [%s] KHÔNG có tồn kho sản phẩm %s!') % (
                        target_move.location_id.complete_name or target_move.location_id.name, product.name),
                }

            new_qty = target_move.quantity + 1.0
            target_move.write({'quantity': new_qty})
            return {
                'status': 'success',
                'move_id': target_move.id,
                'product_id': product.id,
                'product_name': product.display_name,
                'product_barcode': product.barcode or product.default_code or '',
                'demand': target_move.product_uom_qty,
                'quantity_done': new_qty,
                'remaining': max(0, target_move.product_uom_qty - new_qty),
                'uom_name': target_move.product_uom.name,
                'message': _('✓ Chuyển: %s → %.1f %s') % (product.name, new_qty, target_move.product_uom.name),
            }
        else:
            return {
                'status': 'warning',
                'message': _('Sản phẩm %s không có trong phiếu chuyển.') % product.name,
                'product_id': product.id,
                'product_name': product.display_name,
            }

    def _handle_generic_scan(self, picking, product):
        """Fallback handler for other picking types."""
        return self._handle_receipt_scan(picking, product)

    def _handle_package_scan(self, picking, package):
        """
        Handle package barcode scan for internal transfers.
        Adds all products inside the package to the transfer.
        """
        picking.ensure_one()
        quants = self.env['stock.quant'].search([
            ('package_id', '=', package.id),
            ('quantity', '>', 0),
        ])
        if not quants:
            return {
                'status': 'error',
                'message': _('Kiện hàng [%s] không có sản phẩm nào bên trong.') % package.name,
            }

        results = []
        for quant in quants:
            product = quant.product_id
            qty = quant.quantity
            # Find or create move for this product
            matching_moves = picking.move_ids.filtered(
                lambda m: m.product_id.id == product.id and m.state not in ('done', 'cancel')
            )
            if matching_moves:
                target_move = matching_moves[0]
                new_qty = target_move.quantity + qty
                target_move.write({'quantity': new_qty})
                results.append({
                    'move_id': target_move.id,
                    'product_id': product.id,
                    'product_name': product.display_name,
                    'quantity_added': qty,
                    'quantity_done': new_qty,
                })

        return {
            'status': 'package_success',
            'package_name': package.name,
            'products_count': len(results),
            'products': results,
            'message': _('✓ Kiện [%s]: Đã thêm %d sản phẩm vào phiếu chuyển.') % (package.name, len(results)),
        }

    def _get_available_qty(self, product, location):
        """Get real-time available quantity at a location (including child locations)."""
        quants = self.env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id', 'child_of', location.id),
        ])
        return sum(quants.mapped('quantity')) - sum(quants.mapped('reserved_quantity'))

    @api.model
    def update_move_quantity(self, move_id, new_quantity):
        """Update quantity done on a specific move. Used for manual quantity input."""
        move = self.env['stock.move'].browse(move_id)
        if not move.exists():
            return {'status': 'error', 'message': _('Dòng không tồn tại.')}

        picking = move.picking_id
        config = picking._get_barcode_config()

        # Validation for delivery
        if picking.picking_type_code == 'outgoing' and config.get('strict_delivery', True):
            if new_quantity > move.product_uom_qty:
                return {
                    'status': 'error',
                    'error_type': 'over_demand',
                    'message': _('Không được vượt quá số lượng yêu cầu: %.2f %s') % (
                        move.product_uom_qty, move.product_uom.name),
                }
            # Check stock
            available = self._get_available_qty(move.product_id, move.location_id)
            if new_quantity > available + move.quantity:
                return {
                    'status': 'error',
                    'error_type': 'insufficient_stock',
                    'message': _('Không đủ tồn kho. Có sẵn: %.2f %s') % (available, move.product_uom.name),
                }

        move.write({'quantity': new_quantity})
        return {
            'status': 'success',
            'move_id': move.id,
            'product_id': move.product_id.id,
            'quantity_done': new_quantity,
            'demand': move.product_uom_qty,
            'message': _('✓ Cập nhật: %s → %.2f %s') % (move.product_id.name, new_quantity, move.product_uom.name),
        }

    @api.model
    def find_picking_by_barcode(self, barcode):
        """
        Find a picking by its name (reference number).
        This is the main entry point: user scans a picking barcode → system opens it.
        """
        picking = self.search([
            ('name', '=', barcode),
            ('state', 'in', ['assigned', 'confirmed', 'waiting']),
        ], limit=1)
        if not picking:
            # Try partial match (e.g. user scans without prefix)
            picking = self.search([
                ('name', 'ilike', barcode),
                ('state', 'in', ['assigned', 'confirmed', 'waiting']),
            ], limit=1)
        if picking:
            return {
                'status': 'found',
                'picking_id': picking.id,
                'picking_name': picking.name,
                'picking_type_name': picking.picking_type_id.name or '',
                'picking_type_code': picking.picking_type_code,
            }
        return {'status': 'not_found'}

    @api.model
    def scan_barcode_global(self, barcode):
        """
        Global scan from home screen.
        Priority: 1) Find picking by name  2) Find product for stock info
        """
        # 1. Try to find a picking
        picking_result = self.find_picking_by_barcode(barcode)
        if picking_result.get('status') == 'found':
            picking_result['scan_type'] = 'picking'
            return picking_result

        # 2. Try to find a product for stock lookup
        product = self._find_product_by_barcode(barcode)
        if product:
            return {
                'status': 'found',
                'scan_type': 'product',
                'barcode': barcode,
            }

        return {
            'status': 'not_found',
            'message': _('Không tìm thấy phiếu hoặc sản phẩm với mã: %s') % barcode,
        }

    @api.model
    def search_product_global(self, barcode):
        """
        Global product search - shows stock info across all locations.
        Called when scanning outside a picking context.
        """
        product = self._find_product_by_barcode(barcode)
        if not product:
            return {'status': 'not_found', 'message': _('Không tìm thấy sản phẩm với mã: %s') % barcode}

        # Get stock by location
        quants = self.env['stock.quant'].search([
            ('product_id', '=', product.id),
            ('location_id.usage', '=', 'internal'),
            ('quantity', '!=', 0),
        ])

        locations = []
        total_qty = 0.0
        for quant in quants:
            loc_qty = quant.quantity
            reserved = quant.reserved_quantity
            total_qty += loc_qty
            locations.append({
                'location_id': quant.location_id.id,
                'location_name': quant.location_id.complete_name or quant.location_id.name,
                'quantity': loc_qty,
                'reserved': reserved,
                'available': loc_qty - reserved,
            })

        # BOM Kit info
        bom_info = self.env['stock.picking']._get_bom_kit_info(product) if product else {}

        return {
            'status': 'found',
            'product': {
                'id': product.id,
                'name': product.display_name,
                'default_code': product.default_code or '',
                'barcode': product.barcode or '',
                'uom_name': product.uom_id.name,
                'has_image': bool(product.image_128),
                'total_qty': total_qty,
                'bom_kit_name': bom_info.get('kit_name', ''),
                'is_bom_component': bom_info.get('is_component', False),
            },
            'locations': locations,
        }
