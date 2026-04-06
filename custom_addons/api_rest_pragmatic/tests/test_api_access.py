# Copyright 2025 Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase
from odoo.exceptions import ValidationError


class TestApiAccess(TransactionCase):
    """Test API Access configuration."""
    
    def setUp(self):
        """Set up test data."""
        super().setUp()
        self.access_model = self.env['api.access']
        self.namespace_model = self.env['api.namespace']
        
        # Create test namespace
        self.namespace = self.namespace_model.create({
            'name': 'test_access',
            'description': 'Test Access Namespace'
        })
        
        # Get partner model
        self.partner_model = self.env['ir.model'].search([
            ('model', '=', 'res.partner')
        ], limit=1)
    
    def test_access_creation(self):
        """Test API access creation."""
        access = self.access_model.create({
            'namespace_id': self.namespace.id,
            'model_id': self.partner_model.id,
            'api_create': True,
            'api_read': True,
            'api_update': True,
            'api_delete': False,
        })
        
        self.assertEqual(access.model, 'res.partner')
        self.assertTrue(access.api_create)
        self.assertTrue(access.api_read)
        self.assertTrue(access.api_update)
        self.assertFalse(access.api_delete)
    
    def test_access_requires_at_least_one_method(self):
        """Test that access configuration requires at least one method enabled."""
        with self.assertRaises(ValidationError):
            self.access_model.create({
                'namespace_id': self.namespace.id,
                'model_id': self.partner_model.id,
                'api_create': False,
                'api_read': False,
                'api_update': False,
                'api_delete': False,
                'api_public_methods': False,
            })
    
    def test_public_methods_validation(self):
        """Test public methods whitelist validation."""
        access = self.access_model.create({
            'namespace_id': self.namespace.id,
            'model_id': self.partner_model.id,
            'api_read': True,
            'api_public_methods': True,
            'public_methods': 'search\nname_get'
        })
        
        # Should not raise error for valid public methods
        access._check_public_methods()
        
        # Should raise error for private method in public list
        with self.assertRaises(ValidationError):
            access.write({'public_methods': '_compute_name'})
    
    def test_private_methods_validation(self):
        """Test private methods whitelist validation."""
        access = self.access_model.create({
            'namespace_id': self.namespace.id,
            'model_id': self.partner_model.id,
            'api_read': True,
            'private_methods': '_compute_display_name'
        })
        
        # Should not raise error for valid private methods
        access._check_private_methods()
        
        # Should raise error for public method in private list
        with self.assertRaises(ValidationError):
            access.write({'private_methods': 'search'})
    
    def test_unique_model_per_namespace(self):
        """Test that only one access configuration per model per namespace is allowed."""
        self.access_model.create({
            'namespace_id': self.namespace.id,
            'model_id': self.partner_model.id,
            'api_read': True,
        })
        
        # Should raise error for duplicate
        with self.assertRaises(Exception):  # SQL constraint error
            self.access_model.create({
                'namespace_id': self.namespace.id,
                'model_id': self.partner_model.id,
                'api_read': True,
            })
