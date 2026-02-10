from odoo import models, api, _, tools
from odoo.exceptions import UserError
import logging
import json
import re

_logger = logging.getLogger(__name__)


class DiscussChannel(models.Model):
    _inherit = 'discuss.channel'

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

    def _extract_chat_content_with_images(self, limit=50):
        """
        Extract chat content including images for GPT-4 Vision
        Returns a list of message objects for GPT API
        """
        messages = self.message_ids.sorted(key=lambda m: m.date)[-limit:]
        gpt_messages = []
        
        for msg in messages:
            body = tools.html2plaintext(msg.body) if msg.body else ''
            
            # Determine role and prefix
            role = "user"
            prefix = "User"
            if msg.author_id == self.env.user.partner_id:
                role = "user" # Treat operator as user for context, or system? Better as user but identified
                prefix = "Me (Operator)"
            elif not msg.author_id:
                role = "system" # System notifications
                prefix = "System"
            else:
                 prefix = f"Customer ({msg.author_id.name})"
            
            # Extract content (Text + Images)
            content_parts = []
            
            # 1. Text Content
            if body:
                content_parts.append({"type": "text", "text": f"[{msg.date}] {prefix}: {body}"})
                
            # 2. Image Attachments (HTML img tags or attachments)
            # Check for image attachments in the message
            if msg.attachment_ids:
                for attachment in msg.attachment_ids:
                    if attachment.mimetype.startswith('image/'):
                        # Construct public URL if possible, or use internal
                        pass
            
            # Check for Zalo image URLs embedded in body (from our webhook handler)
            # Our webhook handler adds: <img src="..." ... />
            if msg.body and '<img' in msg.body:
                import re
                img_urls = re.findall(r'src="([^"]+)"', msg.body)
                for url in img_urls:
                    if url.startswith('http'):
                        content_parts.append({
                            "type": "image_url", 
                            "image_url": {"url": url}
                        })
            
            if content_parts:
                gpt_messages.append({"role": role, "content": content_parts})
                
        return gpt_messages
