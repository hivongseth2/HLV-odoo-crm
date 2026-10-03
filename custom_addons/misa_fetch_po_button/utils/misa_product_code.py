# -*- coding: utf-8 -*-
"""Đổi mã hàng ở CẢ MISA CRM lẫn Odoo, có lịch sử truy vết.

Một chỗ duy nhất cho mọi lệnh đổi mã chủ động (trợ lý Claude, API ngoài): đổi mã chỉ
một bên là hai hệ thống lệch khoá nối, đơn / phiếu sau đó không khớp mã.
"""
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class ProductCodeNotFound(Exception):
    """Mã cũ không có trên MISA (hoặc MISA ID không khớp)."""


class ProductCodeTaken(Exception):
    """Mã mới đã thuộc một hàng khác (trên MISA hoặc Odoo)."""


class MisaProductCode(models.AbstractModel):
    _inherit = 'misa.api.utils'

    def change_product_code(self, old_code, new_code, source, actor=None, expected_misa_id=None):
        """Đổi mã ``old_code`` -> ``new_code`` trên MISA rồi trên Odoo, ghi lịch sử.

        Nhận: source = 'agent' | 'api' (xem misa.product.code.history); actor = người đổi;
            expected_misa_id = MISA ID bên gọi tin là của mã cũ (lệch -> từ chối).
        Trả: ``{'misa_id', 'product_tmpl', 'odoo_updated', 'note'}``.
        Raise (KHÔNG đổi gì ở cả hai bên) khi: thiếu mã; mã cũ không có trên MISA; MISA ID
            lệch; mã mới đã thuộc hàng khác trên MISA hoặc trên Odoo; MISA từ chối.
        Biên: MISA đổi được mà Odoo không có / không ghi được -> KHÔNG raise (MISA đã đổi
            rồi, raise là mất dấu); trả odoo_updated False và lịch sử ghi rõ lý do.
        """
        old_code = (old_code or '').strip()
        new_code = (new_code or '').strip()
        if not old_code or not new_code:
            raise Exception("Thiếu mã cũ hoặc mã mới")
        if old_code == new_code:
            raise Exception("Mã mới trùng mã cũ")

        # Cùng khoá với lệnh tạo hàng: không để ai vừa tạo hàng mang đúng mã mới này.
        self.lock_product_creation()
        current = self._find_exact_crm_product_by_code(old_code)
        if not current:
            raise ProductCodeNotFound(f"Không có mã {old_code} trên MISA CRM")
        misa_id = str(current.get('misa_id'))
        if expected_misa_id and str(expected_misa_id) != misa_id:
            raise ProductCodeNotFound(f"Mã {old_code} trên MISA là ID {misa_id}, không phải {expected_misa_id}")
        taken = self._find_exact_crm_product_by_code(new_code)
        if taken and str(taken.get('misa_id')) != misa_id:
            raise ProductCodeTaken(f"Mã {new_code} đã thuộc hàng khác trên MISA (ID {taken.get('misa_id')})")

        Variant = self.env['product.product'].sudo().with_context(active_test=False)
        variant = Variant.search([('default_code', '=', old_code)], limit=1)
        clash = Variant.search([('default_code', '=', new_code)], limit=1)
        if clash and clash != variant:
            raise ProductCodeTaken(f"Mã {new_code} đã thuộc sản phẩm Odoo khác: {clash.display_name}")

        if not self.update_product_field_misa(misa_id, 'code', new_code, current.get('code') or old_code):
            raise Exception(f"MISA không nhận đổi mã {old_code} -> {new_code}")

        odoo_updated, note = False, None
        if not variant:
            note = f"Odoo không có sản phẩm mã {old_code}: chỉ đổi trên MISA."
        else:
            try:
                with self.env.cr.savepoint():
                    # misa_skip_crm_sync: MISA vừa đổi rồi, không đẩy ngược lên lần nữa.
                    variant.with_context(misa_skip_crm_sync=True).write({'default_code': new_code})
                odoo_updated = True
            except Exception as error:
                _logger.exception("Đổi mã Odoo %s -> %s lỗi", old_code, new_code)
                note = f"Đã đổi trên MISA nhưng Odoo lỗi: {error} — sửa tay mã Odoo."

        template = variant.product_tmpl_id if variant else False
        self.env['misa.product.code.history'].record(
            old_code, new_code, source, actor=actor, product_tmpl=template, misa_id=misa_id,
            misa_updated=True, odoo_updated=odoo_updated, note=note,
        )
        if template:
            template.message_post(
                body="Đổi mã %s → %s trên MISA%s (qua %s%s)." % (
                    old_code, new_code, " và Odoo" if odoo_updated else "", source,
                    ", " + actor if actor else ""),
                message_type='comment', subtype_xmlid='mail.mt_note',
            )
        _logger.info("MISA_CODE_CHANGE %s -> %s (MISA %s, odoo=%s, qua %s, %s)",
                     old_code, new_code, misa_id, odoo_updated, source, actor)
        return {'misa_id': misa_id, 'product_tmpl': template, 'odoo_updated': odoo_updated, 'note': note}
