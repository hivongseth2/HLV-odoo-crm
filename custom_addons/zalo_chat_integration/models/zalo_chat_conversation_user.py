# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import logging
import requests
import base64
from psycopg2.errors import UniqueViolation

_logger = logging.getLogger(__name__)

class ZaloChatConversation(models.Model):
    _inherit = 'zalo.chat.conversation'

    @api.model
    def _find_or_create_conversation(self, zalo_user_id, user_info=None):
        """
        Find existing conversation or create new one for Zalo user
        Auto-fetch user info from Zalo API if not provided
        """
        conversation = self.search([('zalo_user_id', '=', zalo_user_id)], limit=1)
        
        if not conversation:
            # Fetch user info from Zalo if not provided
            if not user_info:
                _logger.info(f'Fetching user info from Zalo API for new user {zalo_user_id}')
                user_info = self._fetch_zalo_user_info(zalo_user_id)
            
            # Create new conversation
            vals = {
                'zalo_user_id': zalo_user_id,
                'zalo_user_name': user_info.get('display_name') or user_info.get('user_alias') or 'Zalo User',
                'zalo_avatar': user_info.get('avatar'),
                'state': 'open',
            }
            
            # Auto-create partner if we have useful info
            if user_info.get('display_name') or user_info.get('user_alias'):
                partner = self._get_or_create_partner(zalo_user_id, user_info)
                vals['partner_id'] = partner.id
            
            conversation = self.create(vals)
            _logger.info(f'Created new Zalo conversation for user {zalo_user_id}: {vals.get("zalo_user_name")}')
        else:
            _logger.debug(f'Found existing conversation for Zalo user {zalo_user_id}')
        
        return conversation
    
    def _fetch_zalo_user_info(self, zalo_user_id):
        """
        Fetch user information from Zalo API
        Returns dict with display_name, user_name, avatar
        """
        try:
            config = self.env['zalo.oa.config'].get_active_config()
            access_token = config._check_token_validity()
            
            url = 'https://openapi.zalo.me/v3.0/oa/user/detail'
            headers = {
                'access_token': access_token,
                'Content-Type': 'application/json',
            }
            
            payload = {
                'user_id': zalo_user_id,
            }
            
            response = requests.post(url, json=payload, headers=headers, timeout=10)
            result = response.json()
            
            if result.get('error') == 0:
                data = result.get('data', {})
                _logger.info(f'Fetched Zalo user info for {zalo_user_id}: {data.get("display_name")}')
                return data
            else:
                _logger.warning(f'Failed to fetch Zalo user info: {result.get("message")}')
                return {}
        
        except Exception as e:
            _logger.error(f'Error fetching Zalo user info: {str(e)}', exc_info=True)
            return {}
    
    def _get_or_create_partner(self, zalo_user_id, user_info):
        """
        Get or create partner for Zalo user
        Uses full API response including shared_info
        Downloads and saves avatar image
        """
        Partner = self.env['res.partner']
        
        # Search existing partner
        partner = Partner.search([('zalo_user_id', '=', zalo_user_id)], limit=1)
        
        if partner:
            return partner
        
        # Prepare partner values
        name = user_info.get('display_name') or user_info.get('user_alias') or f'Zalo User {zalo_user_id[-4:]}'
        partner_vals = {
            'name': name,
            'zalo_user_id': zalo_user_id,
        }
        
        # Get shared_info if available
        shared_info = user_info.get('shared_info', {})
        
        # Add phone from shared_info or user_id_by_app
        phone = shared_info.get('phone') or user_info.get('user_id_by_app')
        if phone and str(phone) != '0':
            partner_vals['phone'] = str(phone)
        
        # Add address info if available
        if shared_info.get('address'):
            partner_vals['street'] = shared_info.get('address')
        
        if shared_info.get('city'):
            partner_vals['city'] = shared_info.get('city')
        
        # Download and save avatar
        avatar_url = user_info.get('avatar')
        if not avatar_url and user_info.get('avatars'):
            # Try to get from avatars dict (prefer 240px)
            avatars = user_info.get('avatars', {})
            avatar_url = avatars.get('240') or avatars.get('120')
        
        if avatar_url:
            avatar_data = self._download_avatar(avatar_url)
            if avatar_data:
                partner_vals['image_1920'] = avatar_data
        
        try:
            partner = Partner.create(partner_vals)
            _logger.info(f'Created partner for Zalo user: {name} (ID: {zalo_user_id})')
        except Exception as e:
            # Handle race condition - another process created the partner
            if 'unique' in str(e).lower() or 'duplicate' in str(e).lower():
                self.env.cr.rollback()
                partner = Partner.search([('zalo_user_id', '=', zalo_user_id)], limit=1)
                if partner:
                    _logger.info(f'Found existing partner after UniqueViolation: {partner.name}')
                    return partner
            raise
        
        return partner
    
    def _download_avatar(self, url):
        """
        Download avatar image from URL and return base64 encoded data
        """
        try:
            response = requests.get(url, timeout=10)
            if response.status_code == 200:
                # Encode to base64
                avatar_base64 = base64.b64encode(response.content)
                _logger.info(f'Downloaded avatar from {url}')
                return avatar_base64
            else:
                _logger.warning(f'Failed to download avatar: HTTP {response.status_code}')
                return None
        
        except Exception as e:
            _logger.error(f'Error downloading avatar: {str(e)}')
            return None
