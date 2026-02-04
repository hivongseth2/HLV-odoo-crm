# -*- coding: utf-8 -*-

import requests
import json
import logging
from datetime import datetime, timedelta
from odoo import api, fields, models, _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class ZaloOAConfig(models.Model):
    _name = 'zalo.oa.config'
    _description = 'Zalo Official Account Configuration'
    _rec_name = 'oa_name'

    oa_name = fields.Char(
        string='OA Name',
        default='Zalo Official Account',
        required=True,
    )
    app_id = fields.Char(
        string='App ID',
        required=True,
        help='Zalo App ID from developer portal',
    )
    secret_key = fields.Char(
        string='Secret Key',
        required=True,
        help='Zalo App Secret Key',
    )
    access_token = fields.Char(
        string='Access Token',
        readonly=True,
        help='OAuth2 access token',
    )
    refresh_token = fields.Char(
        string='Refresh Token',
        readonly=True,
        help='OAuth2 refresh token',
    )
    token_expiry = fields.Datetime(
        string='Token Expiry',
        readonly=True,
    )
    active = fields.Boolean(
        string='Active',
        default=True,
    )
    
    _sql_constraints = [
        ('app_id_unique', 'UNIQUE(app_id)', 'An app with this ID already exists!'),
    ]

    def action_authorize(self):
        """Open OAuth2 authorization URL"""
        self.ensure_one()
        
        if not self.app_id:
            raise UserError(_('Please enter App ID first!'))
        
        # Construct authorization URL
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        redirect_uri = f"{base_url}/zalo/oauth/callback"
        
        auth_url = (
            f"https://oauth.zaloapp.com/v4/oa/permission"
            f"?app_id={self.app_id}"
            f"&redirect_uri={redirect_uri}"
        )
        
        return {
            'type': 'ir.actions.act_url',
            'url': auth_url,
            'target': 'new',
        }

    def exchange_code_for_token(self, code):
        """
        Exchange authorization code for access token
        
        :param code: Authorization code from OAuth2 callback
        """
        self.ensure_one()
        
        try:
            url = 'https://oauth.zaloapp.com/v4/oa/access_token'
            
            data = {
                'app_id': self.app_id,
                'code': code,
                'grant_type': 'authorization_code',
            }
            
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'secret_key': self.secret_key,
            }
            
            response = requests.post(url, data=data, headers=headers, timeout=30)
            
            if response.status_code != 200:
                raise UserError(
                    _('Failed to get access token: %s') % response.text
                )
            
            result = response.json()
            
            if 'access_token' not in result:
                raise UserError(
                    _('No access token in response: %s') % json.dumps(result)
                )
            
            # Calculate expiry time
            expires_in = int(result.get('expires_in', 86400))  # Default 24h, convert to int
            expiry_time = datetime.now() + timedelta(seconds=expires_in)
            
            self.write({
                'access_token': result['access_token'],
                'refresh_token': result.get('refresh_token', ''),
                'token_expiry': expiry_time,
            })
            
            _logger.info(f'Successfully obtained Zalo access token for app {self.app_id}')
            
            return True
            
        except Exception as e:
            error_msg = str(e)
            _logger.error(f'Error exchanging code for token: {error_msg}')
            raise UserError(_('Failed to authorize: %s') % error_msg)

    def refresh_access_token(self):
        """Refresh the access token using refresh token"""
        self.ensure_one()
        
        if not self.refresh_token:
            raise UserError(_('No refresh token available. Please authorize again.'))
        
        try:
            url = 'https://oauth.zaloapp.com/v4/oa/access_token'
            
            data = {
                'app_id': self.app_id,
                'refresh_token': self.refresh_token,
                'grant_type': 'refresh_token',
            }
            
            headers = {
                'Content-Type': 'application/x-www-form-urlencoded',
                'secret_key': self.secret_key,
            }
            
            response = requests.post(url, data=data, headers=headers, timeout=30)
            
            if response.status_code != 200:
                raise UserError(
                    _('Failed to refresh token: %s') % response.text
                )
            
            result = response.json()
            
            if 'access_token' not in result:
                raise UserError(
                    _('No access token in response: %s') % json.dumps(result)
                )
            
            # Calculate expiry time
            expires_in = int(result.get('expires_in', 86400))  # Convert to int
            expiry_time = datetime.now() + timedelta(seconds=expires_in)
            
            self.write({
                'access_token': result['access_token'],
                'refresh_token': result.get('refresh_token', self.refresh_token),
                'token_expiry': expiry_time,
            })
            
            _logger.info(f'Successfully refreshed Zalo access token for app {self.app_id}')
            
            return True
            
        except Exception as e:
            error_msg = str(e)
            _logger.error(f'Error refreshing token: {error_msg}')
            raise UserError(_('Failed to refresh token: %s') % error_msg)

    def _check_token_validity(self):
        """Check if token is still valid, refresh if needed"""
        self.ensure_one()
        
        if not self.access_token:
            raise UserError(_('No access token. Please authorize first.'))
        
        # Check if token is expired or will expire in next 5 minutes
        if self.token_expiry:
            now = datetime.now()
            expiry = fields.Datetime.from_string(self.token_expiry)
            
            if expiry <= now + timedelta(minutes=5):
                _logger.info('Access token expired or expiring soon, refreshing...')
                self.refresh_access_token()
        
        return self.access_token

    @api.model
    def get_active_config(self):
        """Get the active Zalo OA configuration"""
        config = self.search([('active', '=', True)], limit=1)
        if not config:
            raise UserError(
                _('No active Zalo OA configuration found. Please configure Zalo OA first.')
            )
        return config
