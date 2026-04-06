# Copyright 2025 Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import json
from unittest.mock import patch

from odoo.tests import common, tagged
from odoo.tests.common import HttpCase


@tagged('post_install', '-at_install')
class TestApiControllers(HttpCase):
    """Test API Controllers functionality."""
    
    def setUp(self):
        """Set up test data."""
        super().setUp()
        
        # Create test user with API token
        self.test_user = self.env['res.users'].create({
            'name': 'API Test User',
            'login': 'api_test',
            'email': 'api_test@example.com',
        })
        self.api_token = self.test_user.api_token
        
        # Create test namespace
        self.namespace = self.env['api.namespace'].create({
            'name': 'test_api',
            'description': 'Test API',
            'user_ids': [(4, self.test_user.id)]
        })
        
        # Create API access for res.partner
        self.partner_model = self.env['ir.model'].search([
            ('model', '=', 'res.partner')
        ], limit=1)
        
        self.api_access = self.env['api.access'].create({
            'namespace_id': self.namespace.id,
            'model_id': self.partner_model.id,
            'api_create': True,
            'api_read': True,
            'api_update': True,
            'api_delete': True,
            'api_public_methods': True,
        })
        
        # Prepare auth header
        auth_string = base64.b64encode(self.api_token.encode()).decode()
        self.headers = {
            'Authorization': f'Basic {auth_string}',
            'Content-Type': 'application/json'
        }
    
    def test_api_authentication(self):
        """Test API authentication with token."""
        # Test with valid token
        response = self.url_open(
            f'/api/v1/{self.namespace.name}/res.partner',
            headers=self.headers
        )
        self.assertNotEqual(response.status_code, 401)
        
        # Test with invalid token
        invalid_auth = base64.b64encode(b'invalid_token').decode()
        invalid_headers = {
            'Authorization': f'Basic {invalid_auth}',
            'Content-Type': 'application/json'
        }
        response = self.url_open(
            f'/api/v1/{self.namespace.name}/res.partner',
            headers=invalid_headers
        )
        self.assertEqual(response.status_code, 401)
    
    def test_crud_operations(self):
        """Test CRUD operations through API."""
        base_url = f'/api/v1/{self.namespace.name}/res.partner'
        
        # CREATE
        create_data = {
            'name': 'Test Partner API',
            'email': 'test_partner@example.com'
        }
        response = self.url_open(
            base_url,
            headers=self.headers,
            data=json.dumps(create_data).encode(),
        )
        self.assertEqual(response.status_code, 201)
        result = json.loads(response.content)
        partner_id = result.get('id')
        self.assertTrue(partner_id)
        
        # READ ONE
        response = self.url_open(
            f'{base_url}/{partner_id}',
            headers=self.headers
        )
        self.assertEqual(response.status_code, 200)
        result = json.loads(response.content)
        self.assertEqual(result.get('name'), 'Test Partner API')
        
        # UPDATE
        update_data = {
            'name': 'Updated Partner API'
        }
        response = self.url_open(
            f'{base_url}/{partner_id}',
            headers=self.headers,
            data=json.dumps(update_data).encode(),
        )
        self.assertEqual(response.status_code, 204)
        
        # Verify update
        partner = self.env['res.partner'].browse(partner_id)
        self.assertEqual(partner.name, 'Updated Partner API')
        
        # DELETE
        response = self.url_open(
            f'{base_url}/{partner_id}',
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 204)
        
        # Verify deletion
        partner = self.env['res.partner'].search([('id', '=', partner_id)])
        self.assertFalse(partner.exists())
    
    def test_openapi_spec_download(self):
        """Test OpenAPI specification download."""
        response = self.url_open(
            f'/api/v1/{self.namespace.name}/swagger.json?token={self.namespace.token}'
        )
        self.assertEqual(response.status_code, 200)
        
        spec = json.loads(response.content)
        self.assertEqual(spec.get('swagger'), '2.0')
        self.assertIn('paths', spec)
        self.assertIn('definitions', spec)
