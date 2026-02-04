# -*- coding: utf-8 -*-

import json
import hmac
import hashlib
import logging
import requests
import base64
from odoo import http, fields, _
from odoo.http import request
from markupsafe import Markup

_logger = logging.getLogger(__name__)


class ZaloFileProxyController(http.Controller):
    """Proxy controller for Zalo file downloads to avoid 403 errors"""
    
    @http.route('/zalo/proxy/file', type='http', auth='user', methods=['GET'])
    def proxy_file_download(self, url=None, msg_id=None, **kwargs):
        """
        Proxy file download from Zalo to avoid CORS/403 issues
        """
        if not url:
            return request.make_response('Missing URL parameter', status=400)
        
        try:
            # Fetch file from Zalo URL
            _logger.info(f'Proxying file download from: {url}')
            response = requests.get(url, timeout=30, stream=True)
            
            if response.status_code != 200:
                _logger.error(f'Failed to fetch file from Zalo: {response.status_code}')
                return request.make_response(
                    f'Failed to download file: {response.status_code}',
                    status=response.status_code
                )
            
            # Get filename from URL or use default
            filename = url.split('/')[-1] or 'zalo_file'
            
            # Return file response
            return request.make_response(
                response.content,
                headers=[
                    ('Content-Type', response.headers.get('Content-Type', 'application/octet-stream')),
                    ('Content-Disposition', f'attachment; filename="{filename}"'),
                    ('Content-Length', len(response.content)),
                ]
            )
        
        except Exception as e:
            _logger.error(f'Error proxying file download: {str(e)}', exc_info=True)
            return request.make_response(
                f'Error downloading file: {str(e)}',
                status=500
            )
    
    @http.route('/zalo/upload/file', type='json', auth='user', methods=['POST'])
    def upload_file_to_zalo(self, file_content=None, filename=None, **kwargs):
        """
        Upload file to Zalo and return upload URL
        
        API Doc: https://developers.zalo.me/docs/official-account/tin-nhan/quan-ly-tin-nhan/upload-file
        """
        try:
            if not file_content:
                return {'error': 'Missing file content'}
            
            # Get Zalo config
            config = request.env['zalo.oa.config'].sudo().get_active_config()
            access_token = config._check_token_validity()
            
            # Decode base64 file content
            file_data = base64.b64decode(file_content)
            
            # Upload to Zalo
            url = 'https://openapi.zalo.me/v2.0/oa/upload/file'
            
            files = {
                'file': (filename or 'file', file_data)
            }
            
            headers = {
                'access_token': access_token
            }
            
            _logger.info(f'Uploading file to Zalo: {filename}')
            
            response = requests.post(url, headers=headers, files=files, timeout=30)
            
            if response.status_code != 200:
                error_msg = f'Zalo upload API error {response.status_code}: {response.text}'
                _logger.error(error_msg)
                return {'error': error_msg}
            
            result = response.json()
            
            if result.get('error') != 0:
                error_msg = f'Zalo API error {result.get("error")}: {result.get("message")}'
                _logger.error(error_msg)
                return {'error': error_msg}
            
            # Return attachment ID from Zalo
            attachment_id = result.get('data', {}).get('attachment_id')
            
            _logger.info(f'File uploaded to Zalo successfully: {attachment_id}')
            
            return {
                'success': True,
                'attachment_id': attachment_id,
                'data': result.get('data')
            }
        
        except Exception as e:
            error_msg = f'Error uploading file: {str(e)}'
            _logger.error(error_msg, exc_info=True)
            return {'error': error_msg}
    
    @http.route('/zalo/upload/image', type='json', auth='user', methods=['POST'])
    def upload_image_to_zalo(self, image_content=None, filename=None, **kwargs):
        """
        Upload image to Zalo and return upload URL
        
        API Doc: https://developers.zalo.me/docs/official-account/tin-nhan/quan-ly-tin-nhan/upload-hinh-anh
        """
        try:
            if not image_content:
                return {'error': 'Missing image content'}
            
            # Get Zalo config  
            config = request.env['zalo.oa.config'].sudo().get_active_config()
            access_token = config._check_token_validity()
            
            # Decode base64 image content
            image_data = base64.b64decode(image_content)
            
            # Upload to Zalo
            url = 'https://openapi.zalo.me/v2.0/oa/upload/image'
            
            files = {
                'file': (filename or 'image.jpg', image_data)
            }
            
            headers = {
                'access_token': access_token
            }
            
            _logger.info(f'Uploading image to Zalo: {filename}')
            
            response = requests.post(url, headers=headers, files=files, timeout=30)
            
            if response.status_code != 200:
                error_msg = f'Zalo upload API error {response.status_code}: {response.text}'
                _logger.error(error_msg)
                return {'error': error_msg}
            
            result = response.json()
            
            if result.get('error') != 0:
                error_msg = f'Zalo API error {result.get("error")}: {result.get("message")}'
                _logger.error(error_msg)
                return {'error': error_msg}
            
            # Return attachment ID from Zalo
            attachment_id = result.get('data', {}).get('attachment_id')
            
            _logger.info(f'Image uploaded to Zalo successfully: {attachment_id}')
            
            return {
                'success': True,
                'attachment_id': attachment_id,
                'data': result.get('data')
            }
        
        except Exception as e:
            error_msg = f'Error uploading image: {str(e)}'
            _logger.error(error_msg, exc_info=True)
            return {'error': error_msg}
