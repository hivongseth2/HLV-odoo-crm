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
        
        if not name:
            return []
        
        candidates = self.env['product.template'].search([
            ('id', '!=', product.id),
            ('active', '=', True)
        ])
        
        lines = []
        
        for cand in candidates:
            score = 0
            reasons = []
            cand_sku = cand.default_code or ""
            cand_name = cand.name or ""
            
            # 1. SKU Check
            if sku and cand_sku:
                if sku == cand_sku:
                    score = 100
                    reasons.append("Trùng mã SKU")
                elif sku in cand_sku or cand_sku in sku:
                    score = 70
                    reasons.append(f"SKU tương tự")
            
            # 2. Name Similarity (Simple and effective)
            if name and cand_name and score < 100:
                similarity = difflib.SequenceMatcher(None, name.lower(), cand_name.lower()).ratio()
                if similarity > 0.7:  # Increased threshold to reduce noise
                    score = max(score, int(similarity * 100))
                    reasons.append(f"Tên giống {int(similarity * 100)}%")
            
            # Add to candidates if score >= 70
            if score >= 70:
                lines.append((0, 0, {
                    'candidate_product_id': cand.id,
                    'score': score,
                    'reason': ", ".join(reasons) if reasons else "Tương tự"
                }))
        
        # Sort by score desc
        lines.sort(key=lambda x: x[2]['score'], reverse=True)
        
        # CRITICAL: Limit to top 15 to avoid AI overload
        return lines[:15]

    def action_batch_ai_verify(self):
        """Use AI to verify all duplicate candidates at once"""
        self.ensure_one()
        
        if not self.duplicate_line_ids:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {'title': 'Thông báo', 'message': 'Không có sản phẩm nào để kiểm tra', 'type': 'warning'}
            }
        
        checked_count = 0
        for line in self.duplicate_line_ids:
            result = self.product_id.compare_products_with_ai(line.candidate_product_id)
            
            if "error" not in result:
                is_dup = result.get('is_duplicate', False)
                reason = result.get('reason', '')
                confidence = result.get('confidence', 0)
                
                new_reason = f"🤖 ({confidence}%) {reason}"
                
                vals = {
                    'reason': new_reason,
                    'ai_verdict': 'duplicate' if is_dup else 'different'
                }
                if not is_dup and confidence > 80:
                    vals['score'] = 0
                elif is_dup and confidence > 80:
                    vals['score'] = 99
                    
                line.write(vals)
                checked_count += 1
        
        # Reload the wizard to show updated results
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'product.duplicate.wizard',
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
            'context': {'message': f'✅ Đã kiểm tra {checked_count} sản phẩm bằng AI'}
        }

    def action_archive_selected(self):
        """Archive all products marked as duplicates by AI"""
        self.ensure_one()
        
        # Get lines marked as duplicate by AI
        to_archive = self.duplicate_line_ids.filtered(lambda l: l.ai_verdict == 'duplicate')
        
        if not to_archive:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {'title': 'Thông báo', 'message': 'Không có sản phẩm nào được đánh dấu TRÙNG bởi AI', 'type': 'warning'}
            }
        
        # Archive all candidate products
        products_to_archive = to_archive.mapped('candidate_product_id')
        products_to_archive.action_archive()
        
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _("Hoàn thành"),
                'message': _("Đã lưu trữ %d sản phẩm trùng lặp") % len(products_to_archive),
                'type': 'success',
                'sticky': False,
            }
        }

class ProductDuplicateLine(models.TransientModel):
    _name = 'product.duplicate.line'
    _description = 'Duplicate Candidate Line'
    _order = 'score desc'

    wizard_id = fields.Many2one('product.duplicate.wizard')
    candidate_product_id = fields.Many2one('product.template', string="Sản phẩm trùng tiềm năng")
    score = fields.Integer(string="Độ trùng khớp (%)")
    reason = fields.Char(string="Lý do")
    ai_verdict = fields.Selection([
        ('not_checked', 'Chưa kiểm tra'),
        ('duplicate', 'AI: TRÙNG'),
        ('different', 'AI: KHÁC'),
    ], string="Kết quả AI", default='not_checked')
    
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
