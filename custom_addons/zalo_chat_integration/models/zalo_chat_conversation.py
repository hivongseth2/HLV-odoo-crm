# -*- coding: utf-8 -*-
from odoo import models, fields, api, _, tools
from odoo.exceptions import UserError
import logging
import json
import subprocess
import os
import re
from datetime import datetime
import unicodedata
from markupsafe import Markup

_logger = logging.getLogger(__name__)


class ZaloChatConversation(models.Model):
    _name = 'zalo.chat.conversation'
    _description = 'Hội thoại Zalo Chat'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'last_message_date desc, id desc'
    
    name = fields.Char(
        string='Hội thoại',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('New'),
    )
    
    zalo_user_id = fields.Char(
        string='Zalo User ID',
        required=True,
        copy=False,
        tracking=True,
        help='ID người dùng Zalo',
    )
    
    zalo_user_name = fields.Char(
        string='Tên người dùng',
        tracking=True,
        help='Tên hiển thị của người dùng Zalo',
    )
    
    zalo_avatar = fields.Char(
        string='Avatar URL',
        help='URL avatar của người dùng Zalo',
    )
    
    partner_id = fields.Many2one(
        'res.partner',
        string='Liên hệ',
        tracking=True,
        help='Liên hệ Odoo được liên kết với người dùng Zalo này',
    )


    assistant_summary_html = fields.Html(
        string='Tóm tắt hội thoại (AI)',
        sanitize=False,
        help='Tóm tắt ngắn gọn cho sale, KHÔNG gửi cho khách.',
    )

    assistant_product_suggestions_html = fields.Html(
        string='Gợi ý sản phẩm & tồn kho (AI)',
        sanitize=False,
        help='Gợi ý top 3 sản phẩm (MISA) + tồn kho theo kho Odoo.',
    )

    assistant_last_run = fields.Datetime(
        string='Lần cập nhật gần nhất',
        readonly=True,
    )
    
    message_ids = fields.One2many(
        'zalo.chat.message',
        'conversation_id',
        string='Tin nhắn',
    )
    
    state = fields.Selection([
        ('open', 'Đang mở'),
        ('closed', 'Đã đóng'),
        ('archived', 'Đã lưu trữ'),
    ], string='Trạng thái', default='open', required=True, tracking=True,
       help='Trạng thái của hội thoại')
    
    last_message_date = fields.Datetime(
        string='Tin nhắn cuối',
        compute='_compute_last_message_date',
        store=True,
        help='Thời gian tin nhắn cuối cùng',
    )
    
    unread_count = fields.Integer(
        string='Chưa đọc',
        compute='_compute_unread_count',
        help='Số tin nhắn chưa đọc',
    )
    
    discuss_channel_id = fields.Many2one(
        'discuss.channel',
        string='Kênh Chat',
        help='Kênh Discuss được liên kết để hiển thị live chat',
        readonly=True,
    )
    
    @api.depends('message_ids.sent_date')
    def _compute_last_message_date(self):
        for conversation in self:
            if conversation.message_ids:
                conversation.last_message_date = max(
                    conversation.message_ids.mapped('sent_date')
                )
            else:
                conversation.last_message_date = False
    
    @api.depends('message_ids.is_read', 'message_ids.direction')
    def _compute_unread_count(self):
        for conversation in self:
            conversation.unread_count = len(
                conversation.message_ids.filtered(
                    lambda m: m.direction == 'inbound' and not m.is_read
                )
            )
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                # Generate sequence
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'zalo.chat.conversation'
                ) or _('New')
        
        conversations = super(ZaloChatConversation, self).create(vals_list)
        
        for conversation in conversations:
            # Auto-link partner if exists
            if not conversation.partner_id and conversation.zalo_user_id:
                partner = self.env['res.partner'].search([
                    ('zalo_user_id', '=', conversation.zalo_user_id)
                ], limit=1)
                if partner:
                    conversation.partner_id = partner
        
        return conversations

    
    def action_close(self):
        self.write({'state': 'closed'})
    
    def action_reopen(self):
        self.write({'state': 'open'})

    def action_update_assistant(self):
        """Run AI assistant: summarize + tag + suggest products + check stock.
        Output is stored in conversation fields (internal only).
        """
        self.ensure_one()

        # Find config with GPT API key
        config = self.env['zalo.oa.config'].sudo().search([('active', '=', True)], limit=1)
        if not config or not config.gpt_api_key:
            raise UserError(_('Vui lòng cấu hình GPT API Key trong Zalo OA.'))

        # Build chat content (last 50 messages)
        messages = self.message_ids.sorted(key=lambda m: m.sent_date)[-50:]
        if not messages:
            raise UserError(_('Không có tin nhắn để phân tích.'))

        content_lines = []
        for msg in messages:
            sender = "Khách" if msg.direction == 'inbound' else "NV"
            content = msg.content or "[File/Image]"
            content_lines.append(f"{sender}: {content}")
        chat_content = "\n".join(content_lines)

        # 1) Summarize + Extract products + Tag suggestions
        prompt = [
            {"role": "system", "content": """Bạn là trợ lý sales nội bộ. Hãy đọc hội thoại và trả về JSON theo format:
{
  \"summary_html\": \"<ul>...</ul>\",
  \"key_info\": {
    \"products\": [\"tên/mã\"],
    \"brands\": [\"Bosch\"],
    \"needs\": [\"Hỏi giá\", \"Mua hàng\"],
    \"role\": \"Khách hàng\" | \"NCC\"
  },
  \"tags\": [\"Khách hàng\", \"Bosch\", \"Hỏi giá\"]
}

YÊU CẦU:
- summary_html: HTML bullet list ngắn gọn (3-6 dòng).
- role: suy luận theo nội dung (nếu họ chào hàng/đề xuất cung ứng → NCC; nếu hỏi giá/mua hàng → Khách hàng).
- products: trích xuất tên/mã sản phẩm khách đề cập (tối đa 5).
- Chỉ trả JSON, không kèm markdown.
"""},
            {"role": "user", "content": chat_content}
        ]

        try:
            ai_raw = config._get_gpt_response(prompt, json_mode=True)
            data = json.loads(ai_raw)
        except Exception as e:
            _logger.error(f"Assistant summarize error: {e}")
            raise UserError(_(f"Lỗi phân tích hội thoại: {str(e)}"))

        summary_html = data.get('summary_html') or ''
        tags = data.get('tags') or []
        key_info = data.get('key_info') or {}
        product_queries = key_info.get('products') or []

        # Update partner summary/tags
        if self.partner_id:
            # Update partner summary field directly
            if summary_html:
                self.partner_id.zalo_summary_html = summary_html
            self.partner_id.zalo_last_assistant_run = fields.Datetime.now()

        # 2) Product suggestions via MISA + stock by warehouse
        # Use last inbound timestamp as a hint for timeline
        last_inbound = None
        try:
            last_inbound_msg = next((m for m in reversed(messages) if m.direction == 'inbound'), None)
            last_inbound = last_inbound_msg.sent_date if last_inbound_msg else None
        except Exception:
            last_inbound = None

        suggestions_html = self._build_product_suggestions_html(product_queries, chat_content)
        if suggestions_html:
            self.assistant_product_suggestions_html = suggestions_html

        self.assistant_last_run = fields.Datetime.now()

        # Post internal note to Discuss (sale-facing, NOT sent to customer)
        try:
            channel = self._get_active_livechat_channel()
            if channel:
                note_html = "<div>"
                if last_inbound:
                    note_html += f"<p><b>⏱ Giai đoạn</b>: {fields.Datetime.to_string(last_inbound)}</p>"
                if summary_html:
                    note_html += f"<p><b>📝 Tóm tắt (AI)</b></p>{summary_html}"

                # Build card payload for Discuss UI
                card_items = []
                # Use product_queries for list, rebuild display from alias/MISA quickly
                for q in (product_queries or [])[:3]:
                    prod = self._find_product_by_alias(q)
                    if prod:
                        stock_lines = self._get_stock_by_warehouse(prod.default_code or prod.name)
                        card_items.append({
                            'name': prod.name,
                            'code': prod.default_code or '',
                            'price': f"{prod.list_price:,.0f}",
                            'unit': prod.uom_id.name,
                            'stock': stock_lines,
                        })
                        continue
                    misa_candidates = self._misa_search_products(q)
                    if misa_candidates:
                        best = self._pick_best_misa_candidate(q, misa_candidates, chat_content) or misa_candidates[0]
                        card_items.append({
                            'name': best.get('name',''),
                            'code': best.get('code',''),
                            'price': f"{best.get('price', '-')}",
                            'unit': best.get('unit',''),
                            'stock': self._get_stock_by_warehouse(best.get('code') or best.get('name')),
                        })

                if card_items:
                    payload = {
                        'phase': fields.Datetime.to_string(last_inbound) if last_inbound else '',
                        'items': card_items,
                    }
                    payload_json = tools.html_escape(json.dumps(payload, ensure_ascii=False))
                    note_html += (
                        "<div class='zalo-assistant-card' data-json=\"" + payload_json + "\"></div>"
                    )
                elif suggestions_html:
                    note_html += f"<p><b>📦 Gợi ý sản phẩm &amp; tồn kho</b></p>{suggestions_html}"

                note_html += "</div>"
                channel.with_context(skip_zalo_sync=True).message_post(
                    body=Markup(note_html),
                    message_type='comment',
                    subtype_xmlid='mail.mt_note'
                )
        except Exception as e:
            _logger.error(f"Failed to post assistant note to Discuss: {e}")
        return True

    def _build_product_suggestions_html(self, product_queries, chat_content):
        """Return HTML with top 3 suggestions from MISA + stock per warehouse."""
        if not product_queries:
            return "<p>⚠️ Không tìm thấy sản phẩm trong hội thoại.</p>"

        # Use only top 3 queries to reduce noise
        queries = product_queries[:3]

        html_lines = ["<div>", "<p><b>Gợi ý sản phẩm (Top 3)</b></p>"]

        for q in queries:
            # 1) Alias match in Odoo
            alias_product = self._find_product_by_alias(q)
            if alias_product:
                stock_lines = self._get_stock_by_warehouse(alias_product.default_code or alias_product.name)
                price = alias_product.list_price
                price_str = f"{price:,.0f}" if isinstance(price, (int, float)) else str(price or '-')
                html_lines.append(
                    "<div style='margin-bottom:8px;'>"
                    f"<div><b>{alias_product.name}</b> — <code>{alias_product.default_code or ''}</code></div>"
                    f"<div>Giá: <b>{price_str}</b> | ĐVT: {alias_product.uom_id.name}</div>"
                    f"<div>Tồn kho: {stock_lines}</div>"
                    "</div>"
                )
                continue

            # 2) Fallback to MISA
            misa_candidates = self._misa_search_products(q)
            if not misa_candidates:
                html_lines.append(f"<p>⚠️ Không tìm thấy trong MISA: <b>{q}</b></p>")
                continue

            best = self._pick_best_misa_candidate(q, misa_candidates, chat_content) or misa_candidates[0]
            stock_lines = self._get_stock_by_warehouse(best.get('code') or best.get('name'))
            price = best.get('price')
            price_str = f"{price:,.0f}" if isinstance(price, (int, float)) else str(price or '-')

            html_lines.append(
                "<div style='margin-bottom:8px;'>"
                f"<div><b>{best.get('name','')}</b> — <code>{best.get('code','')}</code></div>"
                f"<div>Giá: <b>{price_str}</b> | ĐVT: {best.get('unit','')}</div>"
                f"<div>Tồn kho: {stock_lines}</div>"
                "</div>"
            )

        html_lines.append("</div>")
        return "".join(html_lines)

    def _misa_search_products(self, keyword):
        """Call local misa_search.py and return product list."""
        if not keyword:
            return []
        try:
            # Default: use bundled script inside module (can be overridden by system param)
            module_dir = os.path.dirname(os.path.dirname(__file__))
            default_script = os.path.join(module_dir, 'scripts', 'misa_search.py')
            script_path = self.env['ir.config_parameter'].sudo().get_param(
                'zalo_chat_integration.misa_search_path',
                default_script
            )
            python_bin = self.env['ir.config_parameter'].sudo().get_param(
                'zalo_chat_integration.python_bin',
                '/usr/bin/python3'
            )
            cmd = [python_bin, script_path, str(keyword)]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode != 0:
                _logger.error(f"MISA search failed: {res.stderr}")
                return []
            data = json.loads(res.stdout)
            if data.get('status') != 'success':
                return []
            return data.get('data', {}).get('products', [])
        except Exception as e:
            _logger.error(f"MISA search error: {e}")
            return []

    def _pick_best_misa_candidate(self, query, candidates, chat_context):
        """Heuristic: exact code match > name contains query > first."""
        q = (query or '').strip().lower()
        if not q:
            return candidates[0] if candidates else None

        # Exact code match
        for c in candidates:
            code = (c.get('code') or '').lower()
            if code == q:
                return c

        # Name contains query
        for c in candidates:
            name = (c.get('name') or '').lower()
            if q in name:
                return c

        return candidates[0] if candidates else None

    def _find_product_by_alias(self, query):
        """Find product.template by alias table (normalized)."""
        if not query:
            return None
        normalized = self._normalize_text(query)
        Alias = self.env['product.alias'].sudo()
        alias = Alias.search([
            ('normalized_alias', '=', normalized),
            ('active', '=', True)
        ], limit=1)
        if alias and alias.product_id:
            return alias.product_id
        return None

    def _normalize_text(self, text):
        text = (text or '').strip().lower()
        text = unicodedata.normalize('NFKD', text)
        text = ''.join([c for c in text if not unicodedata.combining(c)])
        return text

    def _get_stock_by_warehouse(self, code_or_name):
        """Return stock string by warehouse for a product.
        Match by default_code first, fallback by name ilike.
        """
        Product = self.env['product.product'].sudo()
        product = Product.search([
            ('default_code', '=', code_or_name)
        ], limit=1)
        if not product:
            product = Product.search([
                ('name', 'ilike', code_or_name)
            ], limit=1)

        if not product:
            return '<span class="text-muted">Không có trong Odoo</span>'

        whs = self.env['stock.warehouse'].sudo().search([])
        if not whs:
            return '<span class="text-muted">Không có kho</span>'

        parts = []
        for wh in whs:
            # Compute available qty in each warehouse by context
            qty = product.with_context(warehouse=wh.id).qty_available
            parts.append(f"{wh.code or wh.name}: <b>{qty}</b>")

        return ' | '.join(parts)
    
    def action_create_evaluation(self):
        """Create a new evaluation record for this conversation"""
        self.ensure_one()
        
        # Get chat content from stored messages
        messages = self.message_ids.sorted(key=lambda m: m.sent_date)
        content_lines = []
        for msg in messages:
            sender = "Khách" if msg.direction == 'inbound' else "NV"
            content = msg.content or "[File/Image]"
            content_lines.append(f"{sender} ({msg.sent_date}): {content}")
            
        chat_content = "\n".join(content_lines)
        
        channel = self._get_active_livechat_channel()
        
        evaluation = self.env['zalo.chat.evaluation'].create({
            'partner_id': self.partner_id.id,
            'conversation_id': self.id,
            'chat_content': chat_content,
        })
        
        return {
            'type': 'ir.actions.act_window',
            'name': 'Đánh giá hội thoại',
            'res_model': 'zalo.chat.evaluation',
            'res_id': evaluation.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_send_message(self):
        """Open wizard to send message"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Gửi tin nhắn Zalo',
            'res_model': 'send.zalo.chat.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_conversation_id': self.id,
                'default_recipient_id': self.zalo_user_id,
            },
        }
    
    def action_open_chat(self):
        """Open Live Chat session for this conversation"""
        self.ensure_one()
        
        if not self.partner_id:
             return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Lỗi',
                    'message': 'Không tìm thấy Partner liên kết với hội thoại này. Vui lòng chờ tin nhắn đầu tiên để hệ thống tự tạo.',
                    'type': 'danger',
                }
            }
            
        # Search for existing Live Chat session
        # Logic: discuss.channel type='livechat', member=self.partner_id
        domain = [
            ('channel_type', '=', 'livechat'),
            ('channel_member_ids.partner_id', '=', self.partner_id.id)
        ]
        # Sort by updated desc to get latest session
        channel = self.env['discuss.channel'].sudo().search(domain, order='write_date desc', limit=1)
        
        if channel:
            return {
                'type': 'ir.actions.client',
                'tag': 'mail.action_discuss',
                'params': {
                    'active_id': channel.id,
                }
            }
            
        # If no session found
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Chưa có phiên chat',
                'message': 'Chưa có phiên Live Chat nào cho khách hàng này. Phiên chat sẽ tự động tạo khi có tin nhắn mới từ khách hàng.',
                'type': 'warning',
            }
        }
    
    @api.model
    def action_open_all_zalo_chats(self):
        """
        Open list of Live Chat sessions linked to active Zalo OAs.
        If no OA config, redirect to configuration.
        """
        configs = self.env['zalo.oa.config'].sudo().search([('active', '=', True)])
        
        if not configs:
            # Check if action exists before returning
            action = self.env.ref('zalo_chat_integration.action_zalo_oa_config', raise_if_not_found=False)
            if action:
                return action.read()[0]
            return False
        
        livechat_ids = []
        for config in configs:
            # Ensure livechat channel exists
            lc = config._get_or_create_livechat_channel()
            livechat_ids.append(lc.id)
            
        return {
            'type': 'ir.actions.act_window',
            'name': 'Kênh Zalo OA',
            'res_model': 'im_livechat.channel',
            'view_mode': 'kanban,form',
            'domain': [('id', 'in', livechat_ids)],
            'help': """
                <p class="o_view_nocontent_smiling_face">
                    Chưa có kênh Zalo OA nào được cấu hình Live Chat.
                </p>
                <p>
                    Vui lòng vào Cấu hình Zalo OA để thiết lập.
                </p>
            """
        }


    def _get_active_livechat_channel(self):
        """Helper to find the associated livechat channel"""
        self.ensure_one()
        if not self.partner_id:
            return None
            
        domain = [
            ('channel_type', '=', 'livechat'),
            ('channel_member_ids.partner_id', '=', self.partner_id.id)
        ]
        # Sort by updated desc to get latest session
        return self.env['discuss.channel'].sudo().search(domain, order='write_date desc', limit=1)

    def action_gpt_summarize(self):
        """Proxy to channel action"""
        channel = self._get_active_livechat_channel()
        if not channel:
             raise UserError(_("Chưa tìm thấy phiên Live Chat nào."))
        return channel.action_gpt_summarize()
        
    def action_gpt_create_quote(self):
        """Proxy to channel action"""
        channel = self._get_active_livechat_channel()
        if not channel:
             raise UserError(_("Chưa tìm thấy phiên Live Chat nào."))
        return channel.action_gpt_create_quote()
