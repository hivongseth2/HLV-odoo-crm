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
    
    # New Fields
    alias = fields.Char(string='Alias (Display Name)', help="User-friendly name for this Zalo OA")
    unique_room_id = fields.Char(string='Unique Room ID', compute='_compute_unique_room_id', store=True, readonly=True)
    
    _sql_constraints = [
        ('unique_room_id_uniq', 'unique(unique_room_id)', 'This Zalo OA Room (App ID + OA Name) already exists!'),
    ]

    @api.depends('app_id', 'oa_name')
    def _compute_unique_room_id(self):
        for record in self:
            if record.app_id and record.oa_name:
                record.unique_room_id = f"{record.app_id}_{record.oa_name.replace(' ', '_')}"
            else:
                record.unique_room_id = False

    active = fields.Boolean(
        string='Active',
        default=True,
    )
    
    # Live Chat Channel for Zalo Integration
    livechat_channel_id = fields.Many2one(
        'im_livechat.channel',
        string='Live Chat Channel',
        readonly=True,
        help='Odoo Live Chat channel linked to this Zalo OA',
    )
    
    # GPT Configuration
    gpt_api_key = fields.Char(string='GPT API Key', help='OpenAI API Key provided by user')
    gpt_model = fields.Selection([
        ('gpt-4o', 'GPT-4o'),
        ('gpt-4-turbo', 'GPT-4 Turbo'),
        ('gpt-4', 'GPT-4'),
        ('gpt-3.5-turbo', 'GPT-3.5 Turbo'),
    ], string='GPT Model', default='gpt-4o')

    def _get_gpt_response(self, messages, temperature=0.7, json_mode=False):
        """Helper to call OpenAI API"""
        self.ensure_one()
        if not self.gpt_api_key:
            raise UserError(_("Vui lòng cấu hình GPT API Key trong cài đặt Zalo OA."))
            
        headers = {
            'Authorization': f'Bearer {self.gpt_api_key}',
            'Content-Type': 'application/json',
        }
        data = {
            'model': self.gpt_model or 'gpt-4o',
            'messages': messages,
            'temperature': temperature,
        }
        
        if json_mode:
            data['response_format'] = {'type': 'json_object'}
        
        try:
            # Increased timeout for image analysis which takes longer
            response = requests.post('https://api.openai.com/v1/chat/completions', headers=headers, json=data, timeout=60)
            if response.status_code != 200:
                error_detail = response.text
                _logger.error(f"GPT API Error: {error_detail}")
                raise UserError(_(f"Lỗi kết nối GPT: {response.status_code} - {error_detail}"))
                
            result = response.json()
            return result['choices'][0]['message']['content']
        except Exception as e:
            _logger.error(f"GPT Call Failed: {str(e)}")
            raise UserError(_(f"Không thể gọi GPT: {str(e)}"))

    def _get_embedding(self, text):
        """Generate embedding for text using OpenAI"""
        self.ensure_one()
        if not self.gpt_api_key:
            raise UserError(_("Vui lòng cấu hình GPT API Key."))
            
        headers = {
            'Authorization': f'Bearer {self.gpt_api_key}',
            'Content-Type': 'application/json',
        }
        data = {
            'input': text,
            'model': 'text-embedding-3-small', 
        }
        
        try:
            response = requests.post('https://api.openai.com/v1/embeddings', headers=headers, json=data, timeout=30)
            if response.status_code != 200:
                 raise UserError(f"Embedding API Error: {response.text}")
            
            result = response.json()
            return result['data'][0]['embedding']
        except Exception as e:
            _logger.error(f"Embedding Failed: {e}")
            raise UserError(f"Lỗi tạo Embedding: {str(e)}")

    def search_vector(self, query_text, model_name, limit=10, min_score=0.4):
        """
        Search for records by semantic similarity.
        Returns list of tuples: (res_id, score)
        """
        import numpy as np
        
        # 1. Generate query embedding
        query_vec = np.array(self._get_embedding(query_text))
        
        # 2. Fetch target embeddings
        # TODO: Optimize by caching or using a real vector DB if data grows large.
        # For now, fetching all embeddings for the model is acceptable for small-medium datasets (<10k products).
        vectors = self.env['zalo.vector.store'].sudo().search([('res_model', '=', model_name)])
        
        if not vectors:
            return []
            
        results = []
        for v in vectors:
            if not v.embedding: continue
            
            doc_vec = v.get_embedding_numpy()
            if doc_vec is None: continue
            
            # cosine similarity
            # dot product of normalized vectors (assuming OpenAI embeddings are normalized, which they usually are)
            # If unsure, we can normalize: 
            # score = np.dot(query_vec, doc_vec) / (np.linalg.norm(query_vec) * np.linalg.norm(doc_vec))
            # OpenAI 'text-embedding-3-small' are normalized, so dot product is sufficient.
            score = np.dot(query_vec, doc_vec)
            
            if score >= min_score:
                results.append((v.res_id, score))
                
        # Sort by score desc
        results.sort(key=lambda x: x[1], reverse=True)
        
        return results[:limit]

    def action_update_all_vectors(self):
        """Manually trigger vector update for all products"""
        self.ensure_one()
        # This can be slow, so ideally it should be a background job.
        products = self.env['product.product'].search([])
        count = 0
        skipped = 0
        for p in products:
            # Check if vector already exists to avoid re-embedding everything (costly)
            # Or trust _update_vector to handle logic? 
            # _update_vector currently unconditionally calls OpenAI. 
            # Let's check if vector exists first to save money/time, 
            # or maybe we WANT to force update. 
            # Let's assume this button is "Force Update All" or "Sync Missing".
            # For now, let's just do it. 
            try:
                # Optimized: only update if missing or content changed?
                # For simplicity, we just call _update_vector.
                # But to avoid timeout, maybe we should use queue_job if available, which it isn't standard.
                # Let's limit to 100 for safety in foreground.
                if count >= 100:
                     self.env.user.notify_warning(message="Đã đạt giới hạn 100 sản phẩm test. Vui lòng chạy lại nếu muốn tiếp tục.")
                     break
                
                # Check if exists
                exists = self.env['zalo.vector.store'].sudo().search_count([('res_model', '=', 'product.product'), ('res_id', '=', p.id)])
                if not exists:
                    p._update_vector()
                    count += 1
                else:
                    skipped += 1
            except Exception as e:
                _logger.error(f"Failed to update vector for {p.name}: {e}")
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Cập nhật Vector"),
                'message': f"Đã cập nhật mới {count} sản phẩm. (Bỏ qua {skipped} đã có)",
                'type': 'success',
                'sticky': False,
            }
        }

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
    
    def _get_or_create_livechat_channel(self):
        """Get or create the Live Chat channel"""
        self.ensure_one()
        
        if not self.livechat_channel_id:
            _logger.info(f'[ZALO LIVECHAT] Creating Live Chat channel for OA: {self.oa_name}')
            
            # Create im_livechat.channel
            # Add current user as operator
            channel = self.env['im_livechat.channel'].create({
                'name': f'Zalo OA - {self.oa_name or self.app_id}',
                'default_message': f'Hỗ trợ khách hàng qua Zalo OA: {self.oa_name}',
                'user_ids': [(4, self.env.user.id)],
            })
            
            self.livechat_channel_id = channel.id
            _logger.info(f'[ZALO LIVECHAT] Created Live Chat channel id={channel.id}')
        
        return self.livechat_channel_id
    
    def action_open_livechat_config(self):
        """Open the Live Chat channel configuration"""
        self.ensure_one()
        channel = self._get_or_create_livechat_channel()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Live Chat Configuration',
            'res_model': 'im_livechat.channel',
            'res_id': channel.id,
            'view_mode': 'form',
            'target': 'current',
        }
