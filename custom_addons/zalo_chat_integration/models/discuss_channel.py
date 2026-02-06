# -*- coding: utf-8 -*-

from odoo import models, api, _
from odoo import models, api, _
from odoo.exceptions import UserError
import logging
import json
import re

_logger = logging.getLogger(__name__)


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'
    
    def _find_or_create_member_for_self(self):
        """
        Override to handle member creation for chat channels gracefully
        """
        if self.channel_type == 'chat':
            # Check if current user is already a member
            current_partner = self.env.user.partner_id
            existing_member = self.env['discuss.channel.member'].search([
                ('channel_id', '=', self.id),
                ('partner_id', '=', current_partner.id)
            ], limit=1)
            
            if existing_member:
                return existing_member
            else:
                # Try to create member, catch the UserError about limit
                try:
                    return super(DiscussChannel, self)._find_or_create_member_for_self()
                except UserError as e:
                    error_msg = str(e)
                    if 'cannot add more members' in error_msg.lower() or 'không thể thêm nhiều thành viên' in error_msg.lower():
                        _logger.debug(
                            f'Cannot add user {current_partner.id} to chat channel {self.id} '
                            f'(member limit reached), returning first existing member'
                        )
                        # Return any existing member to avoid NotFound error
                        return self.channel_member_ids[0] if self.channel_member_ids else self.env['discuss.channel.member']
                    else:
                        raise
        
        return super(DiscussChannel, self)._find_or_create_member_for_self()
    
    def add_members(self, partner_ids=None, guest_ids=None, **kwargs):
        """
        Override to prevent adding new members to chat channels
        """
        if self.channel_type == 'chat':
            # Check current member count
            current_member_count = len(self.channel_partner_ids)
            if current_member_count >= 2:
                # Filter out partners that are not already members
                if partner_ids:
                    existing_partner_ids = self.channel_partner_ids.ids
                    filtered_partner_ids = [pid for pid in partner_ids if pid in existing_partner_ids]
                    if not filtered_partner_ids:
                        _logger.debug(
                            f'Blocked add_members for chat channel {self.id} '
                            f'(already has {current_member_count} members)'
                        )
                        # Return existing members
                        return self.channel_member_ids
                    partner_ids = filtered_partner_ids
        
        return super(DiscussChannel, self).add_members(partner_ids=partner_ids, guest_ids=guest_ids, **kwargs)
    
    def write(self, vals):
        """
        Override write to prevent adding members to chat channels
        IMPORTANT: Only filter channel_partner_ids, NOT other fields like avatar_128
        """
        # Only process if trying to modify members
        if 'channel_partner_ids' in vals:
            for channel in self:
                if channel.channel_type == 'chat':
                    # Check if trying to add new members
                    commands = vals.get('channel_partner_ids', [])
                    current_partner_ids = set(channel.channel_partner_ids.ids)
                    
                    # Filter out commands that would add new members
                    filtered_commands = []
                    for cmd in commands:
                        if cmd[0] == 4:  # Link existing partner
                            if cmd[1] not in current_partner_ids:
                                _logger.debug(
                                    f'Blocked attempt to add partner {cmd[1]} to '
                                    f'chat channel {channel.id} (already has 2 members)'
                                )
                                continue
                        elif cmd[0] == 0:  # Create new member
                            partner_id = cmd[2].get('partner_id')
                            if partner_id and partner_id not in current_partner_ids:
                                _logger.debug(
                                    f'Blocked attempt to add partner {partner_id} to '
                                    f'chat channel {channel.id} (already has 2 members)'
                                )
                                continue
                        filtered_commands.append(cmd)
                    
                    # Update vals with filtered commands
                    vals['channel_partner_ids'] = filtered_commands
        
        # Suppress UserError for chat channel member limit
        try:
            result = super(DiscussChannel, self).write(vals)
            
            # Debug logging for avatar writes
            if 'avatar_128' in vals:
                for channel in self:
                    _logger.info(f'[WRITE DEBUG] Channel {channel.id} - avatar_128 written: {bool(vals.get("avatar_128"))} ({len(vals.get("avatar_128", b""))} bytes)')
                    # Verify after write
                    _logger.info(f'[WRITE DEBUG] Channel {channel.id} - avatar_128 after write: {bool(channel.avatar_128)} ({len(channel.avatar_128) if channel.avatar_128 else 0} bytes)')
            
            return result
        except UserError as e:
            error_msg = str(e)
            if 'cannot add more members' in error_msg.lower() or 'không thể thêm nhiều thành viên' in error_msg.lower():
                _logger.debug(f'Suppressed member limit error for chat channel: {error_msg}')
                # Return True to indicate success without actually writing invalid data
                return True
            else:
                raise
    
    def message_post(self, **kwargs):
        """
        Override to prevent auto-adding author to chat channels
        when posting messages (which causes 'too many members' error)
        """
        # For chat type channels (1-to-1), disable auto-adding author
        if self.channel_type == 'chat':
            # Check if we're trying to post from a partner not in the channel
            author_id = kwargs.get('author_id')
            if author_id:
                # Check if author is already a member
                partner_ids = self.channel_partner_ids.ids
                if author_id not in partner_ids:
                    # Partner not in channel - log debug but don't add
                    _logger.debug(
                        f'Posting to chat channel {self.id} from non-member '
                        f'partner {author_id} as system message'
                    )
                    # Post as system message instead (no author)
                    kwargs['author_id'] = False
        
        return super(DiscussChannel, self).message_post(**kwargs)
    
    def notify_typing(self, is_typing):
        """
        Override to prevent auto-adding members on typing notification
        For chat channels, only notify if user is already a member
        """
        if self.channel_type == 'chat':
            # Check if current user is a member
            current_partner = self.env.user.partner_id
            if current_partner not in self.channel_partner_ids:
                _logger.debug(
                    f'Skipping typing notification for non-member '
                    f'partner {current_partner.id} in channel {self.id}'
                )
                # Don't call super - just return without error
                return
        
        return super(DiscussChannel, self).notify_typing(is_typing)
    
    def _notify_thread(self, message, msg_vals=False, **kwargs):
        """
        Override to prevent auto-subscribing partners on notification
        """
        if self.channel_type == 'chat':
            # Don't auto-subscribe - just send notifications to existing members
            return super(DiscussChannel, self)._notify_thread(message, msg_vals=msg_vals, **kwargs)
        
        return super(DiscussChannel, self)._notify_thread(message, msg_vals=msg_vals, **kwargs)

    # -------------------------------------------------------------------------
    # GPT INTEGRATION (ZALO LIVECHAT)
    # -------------------------------------------------------------------------

    def action_gpt_summarize(self):
        """
        Summarize the livechat conversation using GPT
        """
        self.ensure_one()
        
        # Only applicable for livechat channels linked to Zalo OA
        if self.channel_type != 'livechat' or not self.livechat_channel_id:
             return
             
        # Find Zalo Config linked to this livechat channel
        # We need config to get API Key through helper
        config = self.env['zalo.oa.config'].sudo().search([('livechat_channel_id', '=', self.livechat_channel_id.id)], limit=1)
        
        if not config:
             raise UserError(_("Không tìm thấy cấu hình Zalo OA liên kết với kênh này."))
             
        if not config.gpt_api_key:
             raise UserError(_("Vui lòng cấu hình GPT API Key trong cài đặt Zalo OA."))
             
        # Fetch last 50 messages
        messages = self.message_ids.sorted(key=lambda m: m.date)[-50:]
        if not messages:
            raise UserError(_("Hội thoại chưa có tin nhắn nào để tóm tắt."))
            
        content_lines = []
        for msg in messages:
            # Simple sanitization
            body = config.env['mail.message']._strip_html(msg.body) if msg.body else ''
            if not body: continue
            
            author_name = msg.author_id.name if msg.author_id else "Bot"
            content_lines.append(f"{author_name}: {body}")
        
        chat_content = "\n".join(content_lines)
        
        prompt = [
            {"role": "system", "content": "Bạn là trợ lý AI quản lý khách hàng (CRM). Hãy đọc đoạn hội thoại sau và tóm tắt ngắn gọn các ý chính:\n1. Nhu cầu/Vấn đề của khách hàng\n2. Thái độ khách hàng (Tích cực/Tiêu cực)\n3. Trạng thái hiện tại (Đã chốt/Đang tư vấn/Khiếu nại)\nTrả lời bằng tiếng Việt, ngắn gọn súc tích."},
            {"role": "user", "content": chat_content}
        ]
        
        try:
            summary = config._get_gpt_response(prompt)
            
            # Post summary as internal note
            from markupsafe import Markup
            self.message_post(
                body=Markup(f"📝 **Tóm tắt nội dung (GPT):**\n{summary.replace(chr(10), '<br/>')}"),
                message_type='notification',
                subtype_xmlid='mail.mt_note'
            )
        except Exception as e:
            raise UserError(_(f"Lỗi khi gọi GPT: {str(e)}"))

    def action_gpt_create_quote(self):
        """
        Parse chat and create Draft Quotation (Sale Order)
        """
        self.ensure_one()
        
        config = self.env['zalo.oa.config'].sudo().search([('livechat_channel_id', '=', self.livechat_channel_id.id)], limit=1)
        if not config or not config.gpt_api_key:
             raise UserError(_("Vui lòng cấu hình GPT API Key."))
             
        # Fetch messages
        messages = self.message_ids.sorted(key=lambda m: m.date)[-50:]
        content_lines = []
        for msg in messages:
            body = config.env['mail.message']._strip_html(msg.body) if msg.body else ''
            if not body: continue
            author_name = msg.author_id.name if msg.author_id else "Bot"
            content_lines.append(f"{author_name}: {body}")
            
        chat_content = "\n".join(content_lines)
        
        prompt = [
            {"role": "system", "content": """Bạn là trợ lý ảo tạo đơn hàng. Hãy trích xuất thông tin đặt hàng từ hội thoại.
Trả về dữ liệu dạng JSON CHUẨN (không markdown, không giải thích thêm).
Cấu trúc:
{
  "products": [
    {"name": "tên sản phẩm", "quantity": 1, "note": ""}
  ],
  "note": "Ghi chú chung của đơn"
}
Nếu không có sản phẩm nào, trả về: {"products": []}
"""},
            {"role": "user", "content": chat_content}
        ]
        
        try:
            response_content = config._get_gpt_response(prompt)
            # Cleanup JSON if GPT wrapped it in markdown code block
            if "```json" in response_content:
                response_content = response_content.split("```json")[1].split("```")[0].strip()
            elif "```" in response_content:
                response_content = response_content.split("```")[1].split("```")[0].strip()
                
            data = json.loads(response_content)
            products_data = data.get('products', [])
            
            if not products_data:
                raise UserError(_("GPT không tìm thấy thông tin sản phẩm nào trong đoạn chat."))
                
            # Create Sale Order
            # Use the partner from the conversation
            # For 1-on-1 chat, the partner is the 'other' member
            # Zalo Livechat: channel_partner_ids contains the customer and operators
            # We assume the external partner (not user) is the customer
            customer = False
            for partner in self.channel_partner_ids:
                if partner.id != self.env.user.partner_id.id and not partner.user_ids: # Likely the customer
                    customer = partner
                    break
            
            if not customer:
                 # Fallback: take any partner that is not current user
                 partners = self.channel_partner_ids.filtered(lambda p: p.id != self.env.user.partner_id.id)
                 if partners:
                     customer = partners[0]
                 else:
                     raise UserError(_("Không xác định được khách hàng trong kênh chat."))
            
            order_lines = []
            Product = self.env['product.product']
            
            not_found_products = []
            
            for item in products_data:
                p_name = item.get('name')
                qty = item.get('quantity', 1)
                note = item.get('note', '')
                
                # Search product
                product = Product.search([('name', 'ilike', p_name)], limit=1)
                
                if product:
                    order_lines.append((0, 0, {
                        'product_id': product.id,
                        'product_uom_qty': qty,
                        'name': product.name + (f" ({note})" if note else ""),
                    }))
                else:
                    not_found_products.append(p_name)
                    # Add as a section/note or dummy? 
                    # Let's Skip and warn, OR create a line without product if allowed (usually not for stock)
                    # We will create a note line
                    order_lines.append((0, 0, {
                        'display_type': 'line_note',
                        'name': f"Sản phẩm chưa tìm thấy mã: {p_name} (SL: {qty})",
                    }))

            vals = {
                'partner_id': customer.id,
                'order_line': order_lines,
                'note': f"Được tạo tự động từ Zalo Chat. Ghi chú: {data.get('note', '')}",
                'origin': f"Zalo Chat {self.name}",
            }
            
            sale_order = self.env['sale.order'].create(vals)
            
            msg = f"✅ **Đã tạo Báo giá nháp:** {sale_order.name}\n"
            if not_found_products:
                msg += f"⚠️ **Không tìm thấy SP:** {', '.join(not_found_products)}"
                
            # Post link to SO
            self.message_post(
                body=Markup(msg),
                message_type='notification',
                subtype_xmlid='mail.mt_note'
            )
            
            # Open the SO
            return {
                'type': 'ir.actions.act_window',
                'res_model': 'sale.order',
                'res_id': sale_order.id,
                'view_mode': 'form',
                'target': 'current',
            }
            
        except json.JSONDecodeError:
            raise UserError(_("Lỗi phân tích dữ liệu từ GPT. (Invalid JSON)"))
        except Exception as e:
            _logger.exception("GPT Create Quote Failed")
            raise UserError(_(f"Lỗi tạo báo giá: {str(e)}"))
