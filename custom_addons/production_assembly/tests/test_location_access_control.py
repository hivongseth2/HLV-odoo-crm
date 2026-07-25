# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestLocationAccessControl(TransactionCase):
    
    def setUp(self):
        super(TestLocationAccessControl, self).setUp()
        
        # Create test user
        self.test_user = self.env['res.users'].create({
            'name': 'Test User',
            'login': 'testuser',
            'email': 'testuser@example.com',
            'groups_id': [(6, 0, [self.env.ref('stock.group_stock_user').id])]
        })
        
        # Create test locations
        self.location_allowed = self.env['stock.location'].create({
            'name': 'Allowed Location',
            'usage': 'internal',
        })
        
        self.location_forbidden = self.env['stock.location'].create({
            'name': 'Forbidden Location',
            'usage': 'internal',
        })
        
        # Create warehouse access config - only allow access to location_allowed
        self.warehouse_config = self.env['warehouse.access.config'].create({
            'user_id': self.test_user.id,
            'location_ids': [(6, 0, [self.location_allowed.id])],
        })
        
        # Create test product
        self.product = self.env['product.product'].create({
            'name': 'Test Product',
            'type': 'consu',
        })
        
        # Create stock in both locations
        self.env['stock.quant'].create({
            'product_id': self.product.id,
            'location_id': self.location_allowed.id,
            'quantity': 10.0,
        })
        
        self.env['stock.quant'].create({
            'product_id': self.product.id,
            'location_id': self.location_forbidden.id,
            'quantity': 5.0,
        })
        
    def test_assembly_destination_access_control(self):
        """Test that user cannot select forbidden destination location for assembly"""
        # Create assembly operation as test user
        operation = self.env['production.operation'].with_user(self.test_user).create({
            'operation_type': 'assembly',
            'main_product_id': self.product.id,
            'main_product_qty': 1.0,
        })
        
        # Should be able to set allowed location
        operation.destination_location_id = self.location_allowed.id
        
        # Should not be able to set forbidden location
        with self.assertRaises(ValidationError):
            operation.destination_location_id = self.location_forbidden.id
            
    def test_disassembly_source_access_control(self):
        """Test that user cannot select forbidden source location for disassembly"""
        # Create disassembly operation as test user
        operation = self.env['production.operation'].with_user(self.test_user).create({
            'operation_type': 'disassembly',
            'main_product_id': self.product.id,
            'main_product_qty': 1.0,
        })
        
        # Should be able to set allowed location
        operation.source_location_id = self.location_allowed.id
        
        # Should not be able to set forbidden location
        with self.assertRaises(ValidationError):
            operation.source_location_id = self.location_forbidden.id
            
    def test_component_line_access_control(self):
        """Test that user cannot select forbidden location in component lines"""
        # Create operation
        operation = self.env['production.operation'].with_user(self.test_user).create({
            'operation_type': 'assembly',
            'main_product_id': self.product.id,
            'main_product_qty': 1.0,
            'destination_location_id': self.location_allowed.id,
        })
        
        # Create component line
        line = self.env['production.operation.line'].with_user(self.test_user).create({
            'operation_id': operation.id,
            'product_id': self.product.id,
            'qty': 1.0,
        })
        
        # Should be able to set allowed location
        line.source_location_id = self.location_allowed.id
        
        # Should not be able to set forbidden location
        with self.assertRaises(ValidationError):
            line.source_location_id = self.location_forbidden.id
            
    def test_available_locations_filtering(self):
        """Test that available locations are filtered based on access control"""
        # Create assembly operation
        operation = self.env['production.operation'].with_user(self.test_user).create({
            'operation_type': 'assembly',
            'main_product_id': self.product.id,
            'main_product_qty': 1.0,
        })
        
        # Check available destination locations
        available_destinations = operation.available_destination_location_ids
        self.assertIn(self.location_allowed, available_destinations)
        self.assertNotIn(self.location_forbidden, available_destinations)
        
        # Create disassembly operation
        operation_disassembly = self.env['production.operation'].with_user(self.test_user).create({
            'operation_type': 'disassembly',
            'main_product_id': self.product.id,
            'main_product_qty': 1.0,
        })
        
        # Check available source locations (should only show locations with stock AND access)
        available_sources = operation_disassembly.available_source_location_ids
        self.assertIn(self.location_allowed, available_sources)
        self.assertNotIn(self.location_forbidden, available_sources)  # Has stock but no access
        
    def test_admin_user_access(self):
        """Test that admin users have access to all locations"""
        admin_user = self.env.ref('base.user_admin')
        
        # Create operation as admin
        operation = self.env['production.operation'].with_user(admin_user).create({
            'operation_type': 'assembly',
            'main_product_id': self.product.id,
            'main_product_qty': 1.0,
        })
        
        # Admin should have access to all locations
        available_destinations = operation.available_destination_location_ids
        self.assertIn(self.location_allowed, available_destinations)
        self.assertIn(self.location_forbidden, available_destinations)