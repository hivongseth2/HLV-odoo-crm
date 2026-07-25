# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestWarehouseAccess(TransactionCase):
    
    def setUp(self):
        super(TestWarehouseAccess, self).setUp()
        
        # Create test users
        self.user1 = self.env['res.users'].create({
            'name': 'Test User 1',
            'login': 'testuser1',
            'email': 'testuser1@example.com',
            'groups_id': [(6, 0, [self.env.ref('stock.group_stock_user').id])]
        })
        
        self.user2 = self.env['res.users'].create({
            'name': 'Test User 2', 
            'login': 'testuser2',
            'email': 'testuser2@example.com',
            'groups_id': [(6, 0, [self.env.ref('stock.group_stock_user').id])]
        })
        
        # Create test locations
        self.location1 = self.env['stock.location'].create({
            'name': 'Test Location 1',
            'usage': 'internal',
        })
        
        self.location2 = self.env['stock.location'].create({
            'name': 'Test Location 2',
            'usage': 'internal',
        })
        
        # Create test warehouse
        self.warehouse = self.env['stock.warehouse'].create({
            'name': 'Test Warehouse',
            'code': 'TW',
        })
        
        # Create test product
        self.product = self.env['product.product'].create({
            'name': 'Test Product',
            'type': 'consu',
        })
        
    def test_warehouse_access_config_creation(self):
        """Test warehouse access config creation"""
        config = self.env['warehouse.access.config'].create({
            'user_id': self.user1.id,
            'location_ids': [(6, 0, [self.location1.id])],
            'warehouse_ids': [(6, 0, [self.warehouse.id])],
        })
        
        self.assertEqual(config.user_id, self.user1)
        self.assertIn(self.location1, config.location_ids)
        self.assertIn(self.warehouse, config.warehouse_ids)
        
    def test_user_unique_constraint(self):
        """Test that each user can only have one config"""
        # Create first config
        self.env['warehouse.access.config'].create({
            'user_id': self.user1.id,
            'location_ids': [(6, 0, [self.location1.id])],
        })
        
        # Try to create second config for same user - should fail
        with self.assertRaises(ValidationError):
            self.env['warehouse.access.config'].create({
                'user_id': self.user1.id,
                'location_ids': [(6, 0, [self.location2.id])],
            })
            
    def test_location_filtering_with_access_control(self):
        """Test location filtering with warehouse access control"""
        # Create warehouse access config for user1
        self.env['warehouse.access.config'].create({
            'user_id': self.user1.id,
            'location_ids': [(6, 0, [self.location1.id])],
        })
        
        # Create stock for product in location1
        self.env['stock.quant'].create({
            'product_id': self.product.id,
            'location_id': self.location1.id,
            'quantity': 10.0,
        })
        
        # Create production operation line as user1
        operation = self.env['production.operation'].create({
            'operation_type': 'assembly',
            'main_product_id': self.product.id,
            'main_product_qty': 1.0,
        })
        
        line = self.env['production.operation.line'].with_user(self.user1).create({
            'operation_id': operation.id,
            'product_id': self.product.id,
            'qty': 1.0,
        })
        
        # Check that available locations include location1
        available_locations = line.available_location_ids
        self.assertIn(self.location1, available_locations)
        
    def test_disassembly_source_location_filtering(self):
        """Test source location filtering for disassembly operations"""
        # Create stock for product in location1
        self.env['stock.quant'].create({
            'product_id': self.product.id,
            'location_id': self.location1.id,
            'quantity': 10.0,
        })
        
        # Create disassembly operation
        operation = self.env['production.operation'].create({
            'operation_type': 'disassembly',
            'main_product_id': self.product.id,
            'main_product_qty': 1.0,
        })
        
        # Check that available source locations include location1
        available_locations = operation.available_source_location_ids
        self.assertIn(self.location1, available_locations)
        
        # Set source location
        operation.source_location_id = self.location1.id
        self.assertEqual(operation.source_location_id, self.location1)