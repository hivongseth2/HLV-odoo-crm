from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError


class StockMove(models.Model):
    _inherit = 'stock.move'
    
    production_operation_id = fields.Many2one(
        'production.operation',
        string='Production Operation',
        readonly=True,
        help="Production operation that generated this stock move"
    )


class ProductionOperation(models.Model):
    _name = 'production.operation'
    _description = 'Production Assembly/Disassembly Operation'
    _order = 'date desc, id desc'
    _rec_name = 'name'

    name = fields.Char(
        string='Operation Number',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New')
    )
    
    date = fields.Datetime(
        string='Date',
        required=True,
        default=fields.Datetime.now,
        readonly=True,
        states={'draft': [('readonly', False)]}
    )
    
    operation_type = fields.Selection([
        ('assembly', 'Sản xuất'),
        ('disassembly', 'Tháo gỡ')
    ], string='Loại hoạt động', required=True, default='assembly',
       readonly=True, states={'draft': [('readonly', False)]})
    
    main_product_id = fields.Many2one(
        'product.product',
        string='Main Product',
        required=True,
        domain=[('type', 'in', ['product', 'consu'])],
        readonly=True,
        states={'draft': [('readonly', False)]},
        help="Product to be produced (assembly) or disassembled",
        tracking=True
    )
    
    main_product_qty = fields.Float(
        string='Quantity',
        required=True,
        default=1.0,
        readonly=True,
        states={'draft': [('readonly', False)]},
        help="Quantity to produce or disassemble"
    )
    
    main_product_uom_id = fields.Many2one(
        'uom.uom',
        string='Unit of Measure',
        related='main_product_id.uom_id',
        readonly=True
    )
    
    destination_location_id = fields.Many2one(
        'stock.location',
        string='Destination Location',
        required=True,
        domain=[('usage', '=', 'internal')],
        readonly=True,
        states={'draft': [('readonly', False)]},
        help="Location where finished product will be stored (assembly) or where main product is taken from (disassembly)"
    )
    
    source_location_id = fields.Many2one(
        'stock.location',
        string='Vị trí nguồn',
        domain=[('usage', '=', 'internal')],
        readonly=True,
        states={'draft': [('readonly', False)]},
        help='Vị trí lấy sản phẩm cần tháo gỡ (chỉ dùng cho tháo gỡ)'
    )
    
    # Computed field for filtering source locations with stock
    available_source_location_ids = fields.Many2many(
        'stock.location',
        compute='_compute_available_source_locations',
        string='Vị trí nguồn có sẵn'
    )
    
    component_line_ids = fields.One2many(
        'production.operation.line',
        'operation_id',
        string='Components',
        readonly=True,
        states={'draft': [('readonly', False)]}
    )
    
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('done', 'Hoàn thành'),
        ('cancel', 'Đã hủy')
    ], string='Trạng thái', default='draft', readonly=True)
    
    move_ids = fields.One2many(
        'stock.move',
        'production_operation_id',
        string='Stock Moves',
        readonly=True
    )
    
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company
    )
    
    notes = fields.Text(string='Notes')

    @api.model
    def create(self, vals):
        if vals.get('name', _('New')) == _('New'):
            vals['name'] = self.env['ir.sequence'].next_by_code('production.operation') or _('New')
        return super().create(vals)

    @api.depends('main_product_id', 'operation_type')
    def _compute_available_source_locations(self):
        """Compute available source locations based on product stock and user access"""
        for record in self:
            if record.operation_type == 'disassembly' and record.main_product_id:
                # Get locations with stock for this product that user can access
                warehouse_config = self.env['warehouse.access.config']
                locations = warehouse_config.get_locations_with_stock(record.main_product_id.id)
                record.available_source_location_ids = locations
            else:
                record.available_source_location_ids = False

    @api.onchange('main_product_id')
    def _onchange_main_product_id(self):
        if self.main_product_id:
            # Set default destination location to stock location if not set
            if not self.destination_location_id:
                stock_location = self.env['stock.location'].search([
                    ('usage', '=', 'internal'),
                    ('company_id', '=', self.company_id.id)
                ], limit=1)
                if stock_location:
                    self.destination_location_id = stock_location.id
            
            # Clear source location when product changes
            self.source_location_id = False

    def action_process_operation(self):
        """Process the assembly or disassembly operation"""
        self.ensure_one()
        
        if self.state != 'draft':
            raise UserError(_('Only draft operations can be processed.'))
        
        if not self.component_line_ids:
            raise UserError(_('Please add at least one component line.'))
        
        # Validate component quantities
        for line in self.component_line_ids:
            if line.qty <= 0:
                raise UserError(_('Component quantities must be positive.'))
        
        # Get virtual production location (id=15)
        virtual_location = self.env['stock.location'].browse(15)
        if not virtual_location.exists():
            raise UserError(_('Virtual Production Location (ID=15) not found. Please check your stock configuration.'))
        
        moves_to_create = []
        
        if self.operation_type == 'assembly':
            moves_to_create = self._prepare_assembly_moves(virtual_location)
        else:  # disassembly
            moves_to_create = self._prepare_disassembly_moves(virtual_location)
        
        # Create and process moves
        moves = self.env['stock.move'].create(moves_to_create)
        moves._action_confirm()
        moves._action_assign()
        
        # Process moves directly without picking - simpler approach
        for move in moves:
            # Ensure move is assigned
            if move.state not in ('assigned', 'partially_available'):
                move._action_assign()
            
            # Create move lines if they don't exist
            if not move.move_line_ids:
                move_line_vals = {
                    'move_id': move.id,
                    'product_id': move.product_id.id,
                    'product_uom_id': move.product_uom.id,
                    'location_id': move.location_id.id,
                    'location_dest_id': move.location_dest_id.id,
                    'company_id': move.company_id.id,
                    'qty_done': move.product_uom_qty,
                }
                self.env['stock.move.line'].create(move_line_vals)
            else:
                # Set qty_done on existing move lines
                for move_line in move.move_line_ids:
                    move_line.qty_done = move.product_uom_qty
            
            # Complete the move
            move._action_done()
        
        self.state = 'done'
        
        return True

    def _prepare_assembly_moves(self, virtual_location):
        """Prepare stock moves for assembly operation"""
        moves = []
        
        # Step 1: Move components from their locations to virtual location
        for line in self.component_line_ids:
            moves.append({
                'name': f'{self.name} - {line.product_id.name}',
                'product_id': line.product_id.id,
                'product_uom_qty': line.qty,
                'product_uom': line.product_uom_id.id,
                'location_id': line.source_location_id.id,
                'location_dest_id': virtual_location.id,
                'production_operation_id': self.id,
                'company_id': self.company_id.id,
                'date': self.date,
            })
        
        # Step 2: Move finished product from virtual location to destination
        moves.append({
            'name': f'{self.name} - {self.main_product_id.name} (Finished)',
            'product_id': self.main_product_id.id,
            'product_uom_qty': self.main_product_qty,
            'product_uom': self.main_product_uom_id.id,
            'location_id': virtual_location.id,
            'location_dest_id': self.destination_location_id.id,
            'production_operation_id': self.id,
            'company_id': self.company_id.id,
            'date': self.date,
        })
        
        return moves

    def _prepare_disassembly_moves(self, virtual_location):
        """Prepare stock moves for disassembly operation"""
        moves = []
        
        # Validate source location for disassembly
        if not self.source_location_id:
            raise UserError(_('Please select a source location for disassembly operation.'))
        
        # Step 1: Move main product from source to virtual location
        moves.append({
            'name': f'{self.name} - {self.main_product_id.name} (To Disassemble)',
            'product_id': self.main_product_id.id,
            'product_uom_qty': self.main_product_qty,
            'product_uom': self.main_product_uom_id.id,
            'location_id': self.source_location_id.id,  # Use dedicated source location
            'location_dest_id': virtual_location.id,
            'production_operation_id': self.id,
            'company_id': self.company_id.id,
            'date': self.date,
        })
        
        # Step 2: Move components from virtual location to their destinations
        for line in self.component_line_ids:
            moves.append({
                'name': f'{self.name} - {line.product_id.name} (Component)',
                'product_id': line.product_id.id,
                'product_uom_qty': line.qty,
                'product_uom': line.product_uom_id.id,
                'location_id': virtual_location.id,
                'location_dest_id': line.source_location_id.id,  # In disassembly, this is destination
                'production_operation_id': self.id,
                'company_id': self.company_id.id,
                'date': self.date,
            })
        
        return moves

    def action_cancel(self):
        """Cancel the operation"""
        self.ensure_one()
        
        if self.state == 'done':
            raise UserError(_('Cannot cancel a completed operation.'))
        
        # Cancel related stock moves
        cancelled_moves = self.move_ids.filtered(lambda m: m.state not in ('done', 'cancel'))
        cancelled_moves._action_cancel()
        
        self.state = 'cancel'
        
        return True

    def action_set_to_draft(self):
        """Reset to draft state"""
        self.ensure_one()
        
        if self.state == 'done':
            raise UserError(_('Cannot reset a completed operation to draft.'))
        
        self.state = 'draft'
        return True

    @api.constrains('main_product_qty')
    def _check_main_product_qty(self):
        for record in self:
            if record.main_product_qty <= 0:
                raise ValidationError(_('Main product quantity must be positive.'))

    @api.constrains('component_line_ids')
    def _check_component_lines(self):
        for record in self:
            if record.state == 'draft' and not record.component_line_ids:
                continue  # Allow empty components in draft state
            
            # Check for duplicate products in components
            products = record.component_line_ids.mapped('product_id')
            if len(products) != len(record.component_line_ids):
                raise ValidationError(_('Duplicate products are not allowed in component lines.'))