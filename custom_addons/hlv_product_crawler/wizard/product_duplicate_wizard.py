from odoo import models, fields, api, _
import difflib
import re

class ProductDuplicateWizard(models.TransientModel):
    _name = 'product.duplicate.wizard'
    _description = 'Find Potential Duplicate Products'

    product_id = fields.Many2one('product.template', string="Sản phẩm gốc", required=True, readonly=True)
    duplicate_line_ids = fields.One2many('product.duplicate.line', 'wizard_id', string="Sản phẩm trùng lặp tiềm năng")

    @api.model
    def default_get(self, fields_list):
        res = super().default_get(fields_list)
        active_id = self.env.context.get('active_id')
        if active_id:
            res['product_id'] = active_id
            # Auto-calculate on open
            lines = self._find_duplicates(active_id)
            res['duplicate_line_ids'] = lines
        return res

    def _find_duplicates(self, product_id):
        product = self.env['product.template'].browse(product_id)
        name = product.name or ""
        sku = product.default_code or ""
        
        candidates = self.env['product.template'].search([
            ('id', '!=', product.id),
            ('active', '=', True)
        ])
        
        # Helper to extract technical specs as complete tokens
        def extract_specs(text):
            text = text.lower()
            tokens = set()
            
            # Pattern 1: Complete fastener spec (M5x15, M10x20, M5, M10)
            # Matches: M + digits + optional(x + digits)
            tokens.update(re.findall(r'm\d+(?:x\d+)?', text))
            
            # Pattern 2: Standalone dimensions (50mm, 100mm)
            tokens.update(re.findall(r'\d+mm', text))
            
            # Pattern 3: Standalone NxM ONLY if NOT preceded by M
            # Use negative lookbehind to avoid matching the "5x15" in "M5x15"
            standalone_dims = re.findall(r'(?<!m)\b(\d+x\d+)\b', text)
            tokens.update(standalone_dims)
            
            return tokens

        product_specs = extract_specs(name)
        lines = []

        for cand in candidates:
            score = 0
            reasons = []
            
            # 1. SKU Check (Highest Priority)
            cand_sku = cand.default_code or ""
            if sku and cand_sku:
                if sku == cand_sku:
                    score = 100
                    reasons.append("Trùng mã SKU")
                elif sku in cand_sku or cand_sku in sku:
                    score += 50
                    reasons.append(f"Mã SKU gần giống ({sku} vs {cand_sku})")
            
            # 2. SPEC-FIRST PATH: Check if technical specs match EXACTLY
            # This bypasses name similarity requirement for technical products
            cand_name = cand.name or ""
            cand_specs = extract_specs(cand_name)
            
            if product_specs and cand_specs and product_specs == cand_specs:
                # Exact spec match! These are likely same product variant
                spec_score = 85  # High confidence but not 100 (SKU is 100)
                if spec_score > score:
                    score = spec_score
                    reasons.append(f"Trùng thông số kỹ thuật: {product_specs}")
            
            # 3. FUZZY NAME PATH: Traditional text similarity
            # This catches duplicates with typos or slightly different naming
            if name and cand_name:
                similarity = difflib.SequenceMatcher(None, name.lower(), cand_name.lower()).ratio()
                if similarity > 0.8:
                    s_score = int(similarity * 100)
                    
                    # Check for spec conflicts
                    if product_specs and cand_specs:
                        if product_specs != cand_specs:
                            # Names similar but specs differ (e.g., M5x15 vs M5x10)
                            if not (product_specs.issubset(cand_specs) or cand_specs.issubset(product_specs)):
                                # Not a subset relationship → Conflicting specs
                                s_score -= 60
                                reasons.append(f"Thông số kỹ thuật khác ({product_specs} vs {cand_specs})")
                        # If specs match, we already handled it in Path 2 above
                    
                    # Only update score if name-based score is better
                    if s_score > score:
                        score = s_score
                        reasons.append(f"Tên giống nhau {s_score}%")
            
            if score >= 60:  # Threshold
                lines.append((0, 0, {
                    'candidate_product_id': cand.id,
                    'score': score,
                    'reason': ", ".join(reasons)
                }))
        
        # Sort by score desc
        lines.sort(key=lambda x: x[2]['score'], reverse=True)
        return lines

class ProductDuplicateLine(models.TransientModel):
    _name = 'product.duplicate.line'
    _description = 'Duplicate Candidate Line'
    _order = 'score desc'

    wizard_id = fields.Many2one('product.duplicate.wizard')
    candidate_product_id = fields.Many2one('product.template', string="Sản phẩm trùng tiềm năng")
    score = fields.Integer(string="Độ trùng khớp (%)")
    reason = fields.Char(string="Lý do")
    
    def action_view_product(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'product.template',
            'view_mode': 'form',
            'res_id': self.candidate_product_id.id,
            'target': 'current',
        }

    def action_copy_specs_from_candidate(self):
        """Copy specs from this candidate to the wizard's product"""
        self.ensure_one()
        source = self.candidate_product_id
        target = self.wizard_id.product_id
        
        target.write({
            'crawled_specs_raw': source.crawled_specs_raw,
            'crawled_specs_analyzed': source.crawled_specs_analyzed,
        })
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Thành công"),
                'message': _("Đã sao chép thông số từ %s sang %s") % (source.name, target.name),
                'type': 'success',
                'sticky': False,
            }
        }

    def action_archive_wizard_product(self):
        """Archive the product being checked (wizard's product) because it is a duplicate"""
        self.ensure_one()
        target = self.wizard_id.product_id
        target.action_archive()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Đã lưu trữ"),
                'message': _("Đã lưu trữ sản phẩm trùng lặp: %s") % target.name,
                'type': 'warning',
                'sticky': False,
            }
        }

    def action_ai_verify_duplicate(self):
        """Call AI to verify if this candidate is a true duplicate"""
        self.ensure_one()
        source = self.candidate_product_id
        target = self.wizard_id.product_id
        
        result = target.compare_products_with_ai(source)
        
        if "error" in result:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {'title': 'Lỗi AI', 'message': result['error'], 'type': 'danger'}
            }
            
        is_dup = result.get('is_duplicate', False)
        reason = result.get('reason', '')
        confidence = result.get('confidence', 0)
        
        new_reason = f"🤖 AI: {'TRÙNG' if is_dup else 'KHÁC'} ({confidence}%) - {reason}"
        
        # Update score/reason based on AI
        vals = {'reason': new_reason}
        if not is_dup and confidence > 80:
            vals['score'] = 0 # Mark as definitely not duplicate
        elif is_dup and confidence > 80:
            vals['score'] = 99 # Mark as highly likely
            
        self.write(vals)
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Kết quả AI"),
                'message': reason,
                'type': 'success' if is_dup else 'warning',
                'sticky': False,
            }
        }
