# Copyright 2025 Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from odoo.tests.common import TransactionCase


class TestApiNamespace(TransactionCase):
    """Test API Namespace functionality."""
    
    def setUp(self):
        """Set up test data."""
        super().setUp()
        self.namespace_model = self.env['api.namespace']
        self.user_model = self.env['res.users']
        
        # Create test user
        self.test_user = self.user_model.create({
            'name': 'Test API User',
            'login': 'test_api_user',
            'email': 'test@example.com'
        })
        
        # Create test namespace
        self.test_namespace = self.namespace_model.create({
            'name': 'test_namespace',
            'description': 'Test Namespace',
            'user_ids': [(4, self.test_user.id)]
        })
    
    def test_namespace_creation(self):
        """Test namespace creation with token generation."""
        self.assertTrue(self.test_namespace.token)
        self.assertEqual(len(self.test_namespace.token), 36)  # UUID format
    
    def test_namespace_name_normalization(self):
        """Test that namespace names are normalized."""
        namespace = self.namespace_model.create({
            'name': 'Test Namespace With Spaces',
            'description': 'Test'
        })
        # Name should be URL-safe
        self.assertNotIn(' ', namespace.name)
        self.assertEqual(namespace.name.lower(), namespace.name)
    
    def test_token_reset(self):
        """Test token reset functionality."""
        old_token = self.test_namespace.token
        self.test_namespace.reset_token()
        self.assertNotEqual(old_token, self.test_namespace.token)
        self.assertTrue(self.test_namespace.token)
    
    def test_spec_url_generation(self):
        """Test OpenAPI specification URL generation."""
        self.test_namespace._compute_spec_url()
        self.assertIn('/api/v1/', self.test_namespace.spec_url)
        self.assertIn(self.test_namespace.name, self.test_namespace.spec_url)
        self.assertIn(self.test_namespace.token, self.test_namespace.spec_url)
