# -*- coding: utf-8 -*-

from odoo.tests.common import TransactionCase
from odoo.exceptions import UserError


class TestProductionOperation(TransactionCase):

    def setUp(self):
        super(TestProductionOperation, self).setUp()
        
        # Create test products
        self.product_final = self.env['product.product'].create({
            'name': 'Final Product Test',
            'type': 'consu',
            'categ_id': self.env.ref('product.product_category_all').id,
        })
        
        self.product_component1 = self.env['product.product'].create({
            'name': 'Component 1 Test',
            'type': 'consu',
            'categ_id': self.env.ref('product.product_category_all').id,
        })
        
        self.product_component2 = self.env['product.product'].create({
            'name': 'Component 2 Test',
            'type': 'consu',
            'categ_id': self.env.ref('product.product_category_all').id,
        })
        
        # Create test locations
        self.location_stock = self.env.ref('stock.stock_location_stock')
        self.location_production = self.env.ref('stock.location_production')
        
        # Create initial stock for components
        self.env['stock.quant'].create({
            'product_id': self.product_component1.id,
            'location_id': self.location_stock.id,
            'quantity': 100.0,
        })
        
        self.env['stock.quant'].create({
            'product_id': self.product_component2.id,
            'location_id': self.location_stock.id,
            'quantity': 50.0,
        })

    def test_create_assembly_operation(self):
        """Test creating an assembly operation"""
        operation = self.env['production.operation'].create({
            'operation_type': 'assembly',
            'main_product_id': self.product_final.id,
            'main_product_qty': 10.0,
            'destination_location_id': self.location_stock.id,
        })
        
        self.assertEqual(operation.state, 'draft')
        self.assertEqual(operation.operation_type, 'assembly')
        self.assertTrue(operation.name.startswith('PA'))

    def test_create_disassembly_operation(self):
        """Test creating a disassembly operation"""
        # First create stock for final product
        self.env['stock.quant'].create({
            'product_id': self.product_final.id,
            'location_id': self.location_stock.id,
            'quantity': 20.0,
        })
        
        operation = self.env['production.operation'].create({
            'operation_type': 'disassembly',
            'main_product_id': self.product_final.id,
            'main_product_qty': 5.0,
            'destination_location_id': self.location_stock.id,
        })
        
        self.assertEqual(operation.state, 'draft')
        self.assertEqual(operation.operation_type, 'disassembly')

    def test_assembly_process(self):
        """Test the assembly process with components"""
        operation = self.env['production.operation'].create({
            'operation_type': 'assembly',
            'main_product_id': self.product_final.id,
            'main_product_qty': 5.0,
            'destination_location_id': self.location_stock.id,
        })
        
        # Add component lines
        self.env['production.operation.line'].create({
            'operation_id': operation.id,
            'product_id': self.product_component1.id,
            'qty': 10.0,
            'source_location_id': self.location_stock.id,
        })
        
        self.env['production.operation.line'].create({
            'operation_id': operation.id,
            'product_id': self.product_component2.id,
            'qty': 5.0,
            'source_location_id': self.location_stock.id,
        })
        
        # Process the operation
        operation.action_process_operation()
        
        self.assertEqual(operation.state, 'done')
        self.assertTrue(len(operation.move_ids) > 0)

    def test_disassembly_process(self):
        """Test the disassembly process"""
        # Create stock for final product
        self.env['stock.quant'].create({
            'product_id': self.product_final.id,
            'location_id': self.location_stock.id,
            'quantity': 10.0,
        })
        
        operation = self.env['production.operation'].create({
            'operation_type': 'disassembly',
            'main_product_id': self.product_final.id,
            'main_product_qty': 2.0,
            'destination_location_id': self.location_stock.id,
        })
        
        # Add component lines (what we get from disassembly)
        self.env['production.operation.line'].create({
            'operation_id': operation.id,
            'product_id': self.product_component1.id,
            'qty': 4.0,
            'source_location_id': self.location_stock.id,
        })
        
        # Process the operation
        operation.action_process_operation()
        
        self.assertEqual(operation.state, 'done')
        self.assertTrue(len(operation.move_ids) > 0)

    def test_cancel_operation(self):
        """Test canceling an operation"""
        operation = self.env['production.operation'].create({
            'operation_type': 'assembly',
            'main_product_id': self.product_final.id,
            'main_product_qty': 1.0,
            'destination_location_id': self.location_stock.id,
        })
        
        operation.action_cancel()
        self.assertEqual(operation.state, 'cancel')

    def test_set_to_draft(self):
        """Test setting canceled operation back to draft"""
        operation = self.env['production.operation'].create({
            'operation_type': 'assembly',
            'main_product_id': self.product_final.id,
            'main_product_qty': 1.0,
            'destination_location_id': self.location_stock.id,
        })
        
        operation.action_cancel()
        operation.action_set_to_draft()
        self.assertEqual(operation.state, 'draft')

    def test_component_line_available_qty(self):
        """Test available quantity calculation in component lines"""
        operation = self.env['production.operation'].create({
            'operation_type': 'assembly',
            'main_product_id': self.product_final.id,
            'main_product_qty': 1.0,
            'destination_location_id': self.location_stock.id,
        })
        
        line = self.env['production.operation.line'].create({
            'operation_id': operation.id,
            'product_id': self.product_component1.id,
            'qty': 5.0,
            'source_location_id': self.location_stock.id,
        })
        
        # Check available quantity is calculated
        self.assertEqual(line.available_qty, 100.0)  # From setUp stock