from odoo import models, fields, api, _
import difflib

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
        
        lines = []
        for cand in candidates:
            score = 0
            reasons = []
            
            # 1. SKU Check (Exact or Contain)
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
                # Basic SequenceMatcher
                similarity = difflib.SequenceMatcher(None, name.lower(), cand_name.lower()).ratio()
                if similarity > 0.8:
                    s_score = int(similarity * 100)
                    score = max(score, s_score) # Take max to verify
                    reasons.append(f"Tên giống nhau {s_score}%")
            
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
