import re

# Read file
with open('custom_addons/zalo_chat_integration/models/zalo_chat_conversation.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find line with _get_or_create_partner
start_idx = None
for i, line in enumerate(lines):
    if 'def _get_or_create_partner' in line:
        start_idx = i
        break

if start_idx is None:
    print("Method not found")
    exit(1)

# Find end of method (next def or end of file)
end_idx = len(lines)
for i in range(start_idx + 1, len(lines)):
    if lines[i].strip().startswith('def ') and not lines[i].strip().startswith('def _'):
        end_idx = i
        break
    if lines[i].startswith('    def ') or (lines[i].strip() and not lines[i].startswith(' ')):
        end_idx = i
        break

# New method code
new_method = '''    def _get_or_create_partner(self, zalo_user_id, user_info):
        """
        Get or create partner for Zalo user
        Uses full API response including shared_info
        Downloads and saves avatar image
        """
        Partner = self.env['res.partner']
        
        # Search existing partner
        partner = Partner.search([('zalo_user_id', '=', zalo_user_id)], limit=1)
        
        if not partner:
            # Create new partner
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
            
            partner = Partner.create(partner_vals)
            _logger.info(f'Created partner for Zalo user: {name} (ID: {zalo_user_id})')
        
        return partner
    
    def _download_avatar(self, url):
        """
        Download avatar image from URL and return base64 encoded data
        """
        try:
            import requests
            import base64
            
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

'''

# Replace lines
new_lines = lines[:start_idx] + [new_method] + lines[end_idx:]

# Write back
with open('custom_addons/zalo_chat_integration/models/zalo_chat_conversation.py', 'w', encoding='utf-8') as f:
    f.writelines(new_lines)

print(f"Replaced lines {start_idx} to {end_idx}")
print("Success!")
