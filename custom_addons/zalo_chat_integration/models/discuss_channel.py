from odoo import models, api, _, tools
from odoo.exceptions import UserError
import logging
import json
import re
from markupsafe import Markup

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
        
        Also intercept outbound messages to send via Zalo API
        """
        # _logger.info(f'[ZALO DEBUG] discuss.channel.message_post called for channel {self.id}, type={self.channel_type}')
        
        # SLASH COMMAND INTERCEPTION (Check FIRST to prevent sending to customer)
        message_body = kwargs.get('body', '')
        if message_body and message_body.strip().lower() == '/baogia':
             _logger.info(f'[ZALO SLASH] Detected /baogia command. Executing Logic...')
             
             # 1. Post command to Odoo Chat (Internal Note or Comment? Keep as comment so user sees it)
             # But explicitly SKIP Zalo Sync for this message
             ctx = dict(self.env.context)
             ctx['skip_zalo_sync'] = True
             res = super(DiscussChannel, self.with_context(ctx)).message_post(**kwargs)
             
             # 2. Trigger AI Actions
             try:
                 # Create Quote
                 self.action_gpt_create_quote()
                 
                 # UPDATE SUMMARY (New Request)
                 self.action_gpt_update_customer_profile()
                 
             except Exception as e:
                 _logger.error(f"Error executing /baogia: {e}")
                 self.message_post(body=f"⚠️ Lỗi: {str(e)}", message_type='notification', subtype_xmlid='mail.mt_note')
             
             return res

        # SLASH COMMAND /checkton
        if message_body and message_body.strip().lower() == '/checkton':
             _logger.info(f'[ZALO SLASH] Detected /checkton command. Executing Logic...')
             
             # 1. Post command to Odoo Chat (SKIP Zalo Sync)
             ctx = dict(self.env.context)
             ctx['skip_zalo_sync'] = True
             res = super(DiscussChannel, self.with_context(ctx)).message_post(**kwargs)
             
             # 2. Trigger AI Stock Check
             try:
                 self.action_gpt_check_stock()
             except Exception as e:
                 _logger.error(f"Error executing /checkton: {e}")
                 self.message_post(body=f"⚠️ Lỗi: {str(e)}", message_type='notification', subtype_xmlid='mail.mt_note')
             
             return res

        # For chat type channels (1-to-1), disable auto-adding author
        if self.channel_type == 'chat':
            # Check if we're trying to post from a partner not in the channel
            author_id = kwargs.get('author_id')
            if author_id:
                # Check if author is already a member
                partner_ids = self.channel_partner_ids.ids
                if author_id not in partner_ids:
                    # Partner not in channel - log debug but don't add
                    # _logger.debug(f'Posting to chat channel {self.id} from non-member {author_id} as system message')
                    # Post as system message instead (no author)
                    kwargs['author_id'] = False
        
        # INTERCEPT OUTBOUND MESSAGES (Re-implementation for Odoo 18)
        try:
            # Check context to avoid recursion
            if not self.env.context.get('skip_zalo_sync'):
                
                # Check if Live Chat Channel linked to Zalo
                if self.channel_type == 'livechat' and self.livechat_channel_id:
                    # _logger.info(f'[ZALO DEBUG] Channel {self.id} is livechat, linked to {self.livechat_channel_id.id}')
                    
                    oa_config = self.env['zalo.oa.config'].sudo().search([
                        ('livechat_channel_id', '=', self.livechat_channel_id.id)
                    ], limit=1)
                    
                    if oa_config:
                        # _logger.info(f'[ZALO DEBUG] Found OA Config {oa_config.oa_name} for channel {self.id}')
                        
                        # Filtering: Only send 'comment' messages, SKIP 'notification'
                        message_type = kwargs.get('message_type', 'comment')
                        if message_type != 'comment':
                            # _logger.info(f'[ZALO DEBUG] Skipping outbound message type: {message_type}')
                            return super(DiscussChannel, self).message_post(**kwargs)

                        # Filtering: Block specific system keywords if any leaked as comment
                        if message_body and ('Đã tạo báo giá' in str(message_body) or '🤖 AI:' in str(message_body)):
                             _logger.info(f'[ZALO DEBUG] Skipping System/AI notification')
                             return super(DiscussChannel, self).message_post(**kwargs)
                             
                        # author_id might be in kwargs or from context
                        author_id = kwargs.get('author_id') or self.env.user.partner_id.id
                        
                        if message_body:
                            # Find Zalo Conversation
                            target_partner = False
                            for partner in self.channel_partner_ids:
                                if partner.id != author_id:
                                    target_partner = partner
                                    break
                            
                            if target_partner:
                                conv = self.env['zalo.chat.conversation'].sudo().search([
                                    ('partner_id', '=', target_partner.id)
                                ], limit=1)
                                
                                if conv:
                                    plain_text = tools.html2plaintext(message_body)
                                    if plain_text and plain_text.strip():
                                        # DEDUPLICATION CHECK: Prevent double-send from UI
                                        last_sent = self.env['zalo.chat.message'].sudo().search([
                                            ('conversation_id', '=', conv.id),
                                            ('direction', '=', 'outbound'),
                                            ('content', '=', plain_text),
                                            ('create_date', '>=', fields.Datetime.now() - datetime.timedelta(seconds=2))
                                        ], limit=1)
                                        
                                        if last_sent:
                                             _logger.warning(f'[ZALO OUTBOUND] Duplicate send detected for {conv.id}, skipping.')
                                             return super(DiscussChannel, self).message_post(**kwargs)

                                        zalo_message = self.env['zalo.chat.message'].sudo().create({
                                            'conversation_id': conv.id,
                                            'direction': 'outbound',
                                            'message_type': 'text',
                                            'content': plain_text,
                                            'state': 'draft',
                                        })
                                        
                                        _logger.info(f'[ZALO OUTBOUND] Sending message {zalo_message.id} to {target_partner.name}')
                                        zalo_message.action_send()
                                        
                                        # IMPORTANT: Prevent double-sending if super check isn't enough?
                                        # Currently we just call action_send() which calls API.
                                        # We do NOT return here, we let super() create the Odoo message.
                                    else:
                                        pass
                                else:
                                    _logger.warning(f'[ZALO DEBUG] No Zalo conversation found for partner {target_partner.name}')
                            else:
                                _logger.warning(f'[ZALO DEBUG] Could not identify target partner in channel {self.id}')
                    else:
                        pass
                        # No OA Config

        except Exception as e:
            _logger.error(f'[ZALO ERROR] Error in message_post intercept: {str(e)}', exc_info=True)

        return super(DiscussChannel, self).message_post(**kwargs)

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
            body = tools.html2plaintext(msg.body) if msg.body else ''
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


    def _find_product_by_name_smart(self, product_name, chat_context, config):
        """
        Smart product search using Odoo Search + GPT Disambiguation (Enhanced)
        """
        Product = self.env['product.product']
        
        # 1. Broad search in Odoo (NO LIMIT - send all to AI for disambiguation)
        candidates = Product.search([
            '|', ('name', 'ilike', product_name), ('default_code', 'ilike', product_name)
        ])
        
        if not candidates:
            return None
            
        if len(candidates) == 1:
            return candidates[0]
            
        # 2. Too many results, use GPT to disambiguate
        # Prepare rich candidate list
        candidate_list = []
        for p in candidates:
            info = (
                f"- ID: {p.id}\n"
                f"  Name: {p.name}\n"
                f"  Code: {p.default_code or 'N/A'}\n"
                f"  Category: {p.categ_id.name}\n"
                f"  Price: {p.lst_price:,.0f}\n"
                f"  Type: {p.type}\n"
                f"  Stock: {p.qty_available}"
            )
            candidate_list.append(info)
            
        candidates_str = "\n".join(candidate_list)
        
        prompt = [
            {"role": "system", "content": """You are an expert Sales Assistant. Your job is to select the EXACT product ID from a list of candidates that matches the user's intent.
Rules:
1. Analyze the 'Chat Context' to understand what the user wants (e.g., specific variant, combo, or accessory).
   - If user asks for "Combo", select the product with Category 'Combo' or similar name.
   - If user asks for specific model (e.g. FPD3), prefer the main product over accessories, unless context implies otherwise.
2. Check 'Code' and 'Name' closely.
3. If multiple similar products exist, prefer the one with positive Stock if context is ambiguous.
4. Return ONLY the ID number (integer). If uncertain/none match, return 0.
"""},
            {"role": "user", "content": f"""
User Request Item: '{product_name}'
Chat Context:
'''
{chat_context}
'''

Candidates:
{candidates_str}

Select ID:"""}
        ]
        
        try:
            response = config._get_gpt_response(prompt)
            # Cleanup non-digit characters just in case
            import re
            cleaned_id = re.sub(r'\D', '', response)
            if cleaned_id:
                selected_id = int(cleaned_id)
                if selected_id == 0:
                    return None
                return candidates.filtered(lambda p: p.id == selected_id)
        except Exception as e:
            _logger.warning(f"Smart search GPT error: {e}")
            
        # Fallback: return the first result
        return candidates[0]

    def _execute_command_baogia(self, **kwargs):
        """
        Slash command /baogia to trigger GPT Quote Creation
        """
        self.action_gpt_create_quote()
        self.action_gpt_update_customer_profile()
        return True

    def action_gpt_check_stock(self):
        """
        AI infers product from chat and checks stock
        """
        self.ensure_one()
        
        config = self.env['zalo.oa.config'].sudo().search([('livechat_channel_id', '=', self.livechat_channel_id.id)], limit=1)
        if not config or not config.gpt_api_key:
             raise UserError(_("Vui lòng cấu hình GPT API Key."))
             
        # Fetch last 30 messages
        messages = self.message_ids.sorted(key=lambda m: m.date)[-30:]
        content_lines = []
        for msg in messages:
            body = tools.html2plaintext(msg.body) if msg.body else ''
            if not body: continue
            
            # Skip system commands
            if body.startswith('/'): continue
            
            prefix = "Me" if msg.author_id == self.env.user.partner_id else "Customer"
            content_lines.append(f"{prefix}: {body}")
            
        chat_content = "\n".join(content_lines)
        
        prompt = [
            {"role": "system", "content": """Bạn là trợ lý kho hàng. Đọc đoạn hội thoại và xác định sản phẩm khách hàng đang hỏi tồn kho GẦN NHẤT.
Quy tắc:
1. Chỉ trả về TÊN SẢN PHẨM (hoặc Mã) mà khách đang quan tâm nhất.
2. Nếu khách hỏi nhiều món, ưu tiên món hỏi sau cùng.
3. Nếu không tìm thấy thông tin sản phẩm nào, trả về "NULL".
4. Không giải thích, chỉ trả về tên sản phẩm."""},
            {"role": "user", "content": chat_content}
        ]
        
        try:
            product_query = config._get_gpt_response(prompt)
            product_query = product_query.strip().strip('"').strip("'")
            
            if product_query == "NULL" or not product_query:
                self.message_post(body="🤖 AI: Không tìm thấy tên sản phẩm nào trong đoạn chat gần đây để kiểm tra tồn kho.", message_type='notification', subtype_xmlid='mail.mt_note')
                return
                
            # Smart search using explicit method
            product = self._find_product_by_name_smart(product_query, chat_content, config)
            
            if product:
                # Get Stock Info
                qty_available = product.qty_available
                virtual_available = product.virtual_available
                
                # Format currency
                price = "{:,.0f}".format(product.lst_price)
                
                msg = f"""📦 **Kiểm tra tồn kho: {product.name}**
- Mã: {product.default_code}
- Giá niêm yết: {price} đ
- Tồn thực tế: **{qty_available}**
- Dự kiến (sau khi giữ hàng): {virtual_available}
"""
                self.message_post(body=Markup(msg), message_type='notification', subtype_xmlid='mail.mt_note')
            else:
                 self.message_post(body=f"🤖 AI: Đã tìm kiếm '{product_query}' nhưng không thấy sản phẩm nào khớp trong hệ thống.", message_type='notification', subtype_xmlid='mail.mt_note')

        except Exception as e:
            _logger.error(f"Stock Check Error: {e}")
            self.message_post(body=f"⚠️ Lỗi kiểm tra tồn: {str(e)}", message_type='notification', subtype_xmlid='mail.mt_note')

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
            body = tools.html2plaintext(msg.body) if msg.body else ''
            if not body: continue
            
            # Timestamp (Local time approx or UTC, GPT handles relative)
            ts = msg.date.strftime('%Y-%m-%d %H:%M:%S')
            
            # Distinguish System/Bot messages vs User messages
            # IMPORTANT: Detect "Quote Created" messages even if they have an author
            is_quote_notification = 'Đã tạo báo giá' in body or 'AI Tạo Báo Giá' in body
            
            if is_quote_notification:
                 prefix = "SYSTEM_LOG"
            elif msg.author_id:
                prefix = f"User ({msg.author_id.name})"
            else:
                prefix = "SYSTEM_LOG"
                
            content_lines.append(f"[{ts}] {prefix}: {body}")
            
        chat_content = "\n".join(content_lines)
        
        prompt = [
            {"role": "system", "content": """Bạn là trợ lý ảo tạo đơn hàng (Sale Order Creator). 
Nhiệm vụ: Trích xuất sản phẩm khách muốn mua TỪ CÁC TIN NHẮN MỚI NHẤT chưa được xử lý.

QUY TẮC XỬ LÝ LỊCH SỬ (QUAN TRỌNG):
1. Dựa vào thời gian (Timestamp). Tìm mốc "SYSTEM_LOG: Đã tạo báo giá..." gần nhất.
2. CHỈ TRÍCH XUẤT yêu cầu MỚI sau mốc đó.

QUY TẮC GIÁ & SẢN PHẨM:
1. Trích xuất chính xác Tên sản phẩm, Số lượng.
2. QUAN TRỌNG: Nếu trong hội thoại có NHẮC ĐẾN GIÁ (ví dụ: "giá 50k nhé", "chốt 3tr", "bán cho em giá cũ 120k"), BẮT BUỘC phải lấy giá đó vào `price_unit`.
3. Nếu không nhắc giá hoặc chỉ hỏi giá -> để `price_unit` = 0 (để hệ thống tự lấy bảng giá).

CẤU TRÚC JSON TRẢ VỀ:
{
  "products": [
    {"name": "tên sản phẩm", "quantity": 1, "price_unit": 0, "note": ""}
  ],
  "note": "Ghi chú chung (đặc biệt là về giá nếu có deal)"
}
Nếu không có yêu cầu mới: {"products": []}
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
                # Post a ephemeral notification or just log
                self.message_post(body="🤖 AI: Không tìm thấy yêu cầu mua hàng mới nào cần tạo báo giá (Các yêu cầu cũ đã được xử lý).", message_type='notification', subtype_xmlid='mail.mt_note')
                return
                
            customer = False
            for partner in self.channel_partner_ids:
                if partner.id != self.env.user.partner_id.id and not partner.user_ids: # Likely the customer
                    customer = partner
                    break
            
            if not customer:
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
                price_unit = item.get('price_unit', 0)
                
                # Use Smart Search
                product = self._find_product_by_name_smart(p_name, chat_content, config)
                
                if product:
                    line_vals = {
                        'product_id': product.id,
                        'product_uom_qty': qty,
                        'name': product.name + (f" ({note})" if note else ""),
                    }
                    # Apply custom price if detected
                    if price_unit > 0:
                        line_vals['price_unit'] = price_unit
                        
                    order_lines.append((0, 0, line_vals))
                else:
                    not_found_products.append(p_name)
                    order_lines.append((0, 0, {
                        'display_type': 'line_note',
                        'name': f"Sản phẩm chưa tìm thấy mã: {p_name} (SL: {qty}) - Giá: {price_unit if price_unit > 0 else 'Theo bảng giá'}",
                    }))

            vals = {
                'partner_id': customer.id,
                'order_line': order_lines,
                'note': f"Được tạo tự động từ Zalo Chat. Ghi chú: {data.get('note', '')}",
                'origin': f"Zalo Chat {self.name}",
            }
            
            sale_order = self.env['sale.order'].create(vals)
            
            # Post as plain notification
            link = Markup(f'<a href="#" data-oe-model="sale.order" data-oe-id="{sale_order.id}">{sale_order.name}</a>')
            self.message_post(
                body=Markup(f"✅ Đã tạo báo giá: {link}<br/>(Ghi chú: {data.get('note', 'Không')})"),
                message_type='notification',
                subtype_xmlid='mail.mt_note'
            )
            
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
