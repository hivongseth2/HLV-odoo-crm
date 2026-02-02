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

        for cand in candidates:
            score = 0
            reasons = []
            
            # 1. SKU Check
            cand_sku = cand.default_code or ""
            if sku and cand_sku:
                if sku == cand_sku:
                    score = 100
                    reasons.append("Trùng mã SKU")
                elif sku in cand_sku or cand_sku in sku:
                    score += 50
                    reasons.append(f"Mã SKU gần giống ({sku} vs {cand_sku})")
            
            # 2. Name Fuzzy Match
            cand_name = cand.name or ""
            if name and cand_name:
                similarity = difflib.SequenceMatcher(None, name.lower(), cand_name.lower()).ratio()
                if similarity > 0.8:
                    s_score = int(similarity * 100)
                    
                    # 3. Spec Token Check
                    cand_specs = extract_specs(cand_name)
                    
                    # Only penalize if BOTH have specs AND they share NO common specs
                    # OR if they have conflicting specs?
                    # Safer: If they have specs, and the sets are disjoint or conflicting?
                    # Let's say: if they share common "types" (like both have an Mx token) but the values differ?
                    # Simple approach: If sets form a mismatch?
                    
                    # Case 1: M5x15 (m5, 5x15) vs M5x10 (m5, 5x10). Common: m5. Diff: 5x15 vs 5x10.
                    # If there is ANY difference in spec tokens, it's suspicious? 
                    # No, "M5x15" vs "M5" (generic). "M5x15" has {m5, 5x15}, "M5" has {m5}.
                    # Subset is fine.
                    
                    if product_specs and cand_specs:
                        # Check for CONFLICTS
                        # Conflict = same pattern type but different value?
                        # Hard to classify patterns dynamically.
                        
                        # Let's try: If the Intersection is Empty? No, M5 matches.
                        # If Symmetric Difference contains "Dimension" looking things?
                        
                        # Let's go back to strict equality but ONLY for the extracted specs?
                        # M5x15 (m5, 5x15) vs M5x10 (m5, 5x10).
                        # product_specs - cand_specs = {5x15}
                        # cand_specs - product_specs = {5x10}
                        # Mismatch!
                        
                        # SS304 M5x15 (m5, 5x15) vs 912 M5x15 (m5, 5x15).
                        # product_specs == cand_specs. Match!
                        
                        if product_specs != cand_specs:
                             # Check if one is subset of another?
                             # e.g. "Bolts M5" ({m5}) vs "Bolts M5x15" ({m5, 5x15})
                             # If we are looking for duplicates, usually we want exact spec match.
                             # But "M5" is likely a Category name, not a Product.
                             # If user is deduplicating Products, they should generally have full specs.
                             
                             if product_specs.issubset(cand_specs) or cand_specs.issubset(product_specs):
                                 # Subset is acceptable (one is more specific) -> No penalty?
                                 # Or maybe small penalty? Let's accept it for now.
                                 pass 
                             else:
                                 # Significant mismatch
                                 s_score -= 60
                                 reasons.append(f"Thông số kỹ thuật khác ({product_specs} vs {cand_specs})")
                        else:
                             reasons.append(f"Tên giống nhau {s_score}%")
                    else:
                        # No specs detected in one or both -> Rely purely on text fuzzy
                        reasons.append(f"Tên giống nhau {s_score}%")

                    if s_score > 0:
                        score = max(score, s_score)
            
            if score >= 60: # Threshold
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
