from odoo import models, fields, api, _
from odoo.exceptions import ValidationError


class ProductionOperationLine(models.Model):
    _name = 'production.operation.line'
    _description = 'Production Operation Component Line'
    _order = 'operation_id, sequence, id'

    operation_id = fields.Many2one(
        'production.operation',
        string='Operation',
        required=True,
        ondelete='cascade'
    )
    
    sequence = fields.Integer(string='Sequence', default=10)
    
    product_id = fields.Many2one(
        'product.product',
        string='Component Product',
        required=True,
        domain=[('type', 'in', ['product', 'consu'])]
    )
    
    qty = fields.Float(
        string='Quantity',
        required=True,
        default=1.0
    )
    
    product_uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        related='product_id.uom_id',
        readonly=True
    )
    
    source_location_id = fields.Many2one(
        'stock.location',
        string='Source/Destination Location',
        required=True,
        domain="[('usage', '=', 'internal'), ('id', 'in', available_location_ids)]",
        help="For Assembly: Location where component is taken from. For Disassembly: Location where component will be placed."
    )
    
    # Computed field for available locations
    available_location_ids = fields.Many2many(
        'stock.location',
        compute='_compute_available_location_ids',
        string='Available Locations',
        store=False
    )
    
    # Related fields for easier access
    operation_type = fields.Selection(
        related='operation_id.operation_type',
        string='Operation Type',
        readonly=True
    )
    
    state = fields.Selection(
        related='operation_id.state',
        string='Status',
        readonly=True
    )
    
    company_id = fields.Many2one(
        related='operation_id.company_id',
        string='Company',
        readonly=True
    )
    
    # Computed fields for display
    available_qty = fields.Float(
        string='Available Qty',
        compute='_compute_available_qty',
        help="Available quantity in source location (for assembly operations)"
    )
    
    def _compute_available_location_ids(self):
        """Compute available locations based on operation type and user access"""
        warehouse_config = self.env['warehouse.access.config']
        
        for line in self:
            if line.operation_type == 'assembly' and line.product_id:
                # For assembly: only show locations where the product has stock and user has access
                locations = warehouse_config.get_locations_with_stock(line.product_id.id, self.env.user.id)
                line.available_location_ids = locations
            elif line.operation_type == 'disassembly':
                # For disassembly: show accessible internal locations
                accessible_locations = warehouse_config.get_accessible_locations(self.env.user.id)
                line.available_location_ids = accessible_locations
            else:
                # Return empty recordset for other cases
                line.available_location_ids = self.env['stock.location']

    @api.depends('product_id', 'source_location_id', 'operation_type')
    def _compute_available_qty(self):
        for line in self:
            if line.operation_type == 'assembly' and line.product_id and line.source_location_id:
                # Get available quantity for assembly operations
                quants = self.env['stock.quant'].search([
                    ('product_id', '=', line.product_id.id),
                    ('location_id', '=', line.source_location_id.id),
                    ('company_id', '=', line.company_id.id)
                ])
                line.available_qty = sum(quants.mapped('quantity'))
            else:
                line.available_qty = 0.0
    
    @api.onchange('product_id', 'operation_type')
    def _onchange_product_id(self):
        # Force recompute available locations when product or operation type changes
        self._compute_available_location_ids()
        
        if self.product_id:
            # Clear current location selection
            self.source_location_id = False
            
            # For assembly operations, try to find a location with stock that user can access
            if self.operation_type == 'assembly':
                warehouse_config = self.env['warehouse.access.config']
                locations = warehouse_config.get_locations_with_stock(self.product_id.id, self.env.user.id)
                if locations:
                    self.source_location_id = locations[0].id
            else:
                # For disassembly, set default to first accessible internal location
                warehouse_config = self.env['warehouse.access.config']
                accessible_locations = warehouse_config.get_accessible_locations(self.env.user.id)
                if accessible_locations:
                    self.source_location_id = accessible_locations[0].id

    @api.constrains('qty')
    def _check_qty(self):
        for line in self:
            if line.qty <= 0:
                raise ValidationError(_('Component quantity must be positive.'))
    
    @api.constrains('source_location_id')
    def _check_location_access(self):
        """Check if user has access to selected location"""
        for line in self:
            if line.source_location_id:
                warehouse_config = self.env['warehouse.access.config']
                accessible_locations = warehouse_config.get_accessible_locations(self.env.user.id)
                
                if line.source_location_id not in accessible_locations:
                    raise ValidationError(_('Bạn không có quyền truy cập vào vị trí đã chọn: %s') % line.source_location_id.display_name)

    @api.constrains('product_id', 'operation_id')
    def _check_product_unique(self):
        for line in self:
            if line.operation_id:
                # Check for duplicate products in the same operation
                duplicate_lines = self.search([
                    ('operation_id', '=', line.operation_id.id),
                    ('product_id', '=', line.product_id.id),
                    ('id', '!=', line.id)
                ])
                if duplicate_lines:
                    raise ValidationError(_('Product "%s" is already used in this operation. Please use different products or combine quantities.') % line.product_id.name)

    def name_get(self):
        result = []
        for line in self:
            name = f"{line.product_id.name} - {line.qty} {line.product_uom_id.name}"
            result.append((line.id, name))
        return result