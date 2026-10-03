# -*- coding: utf-8 -*-
"""Sửa sản phẩm trên Odoo -> tự cập nhật hàng tương ứng trên MISA CRM.

Bật / tắt ở Cài đặt > Tồn kho > MISA CRM (System Parameter misa.crm.auto_sync_product).

Cố ý:
- Chỉ đẩy khi NGƯỜI DÙNG sửa (env không phải sudo). Các luồng tự động MISA -> Odoo ghi
  sản phẩm bằng sudo; đẩy ngược lên là vòng lặp, và làm chậm cả lô import.
- Gọi MISA SAU KHI Odoo commit (postcommit): Odoo lưu lỗi thì MISA không bị đụng.
- Kết quả (được / hỏng) ghi lên chatter sản phẩm: lỗi xảy ra sau khi form đã lưu xong,
  không còn cách nào bật thông báo cho người bấm Lưu.
"""
import logging

from odoo import SUPERUSER_ID, api, fields, models

_logger = logging.getLogger(__name__)

SYNC_PARAM = 'misa.crm.auto_sync_product'
# Trường Odoo -> tên trường của misa.api.utils.update_product_field_misa.
SYNCED_FIELDS = {'name': 'name', 'default_code': 'code'}
FIELD_LABELS = {'name': 'tên', 'default_code': 'mã'}


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    misa_product_id = fields.Char(
        string="MISA ID", copy=False, readonly=True,
        help="ID hàng tương ứng trên MISA CRM, nhớ lại sau lần đồng bộ đầu để khỏi tra theo mã.",
    )

    def write(self, vals):
        changes = self._misa_changes_to_push(vals)
        res = super().write(vals)
        if changes:
            self._schedule_misa_push(changes)
        return res

    def _misa_changes_to_push(self, vals):
        """Chụp giá trị cũ TRƯỚC khi ghi, cho các trường MISA quan tâm.

        Trả: list ``(id, mã cũ, misa_id, {trường: giá trị cũ})``; rỗng khi tắt đồng bộ,
        khi ghi bằng sudo, hoặc vals không đụng tên / mã.
        """
        touched = [field for field in SYNCED_FIELDS if field in vals]
        if not touched or self.env.su or self.env.context.get('misa_skip_crm_sync'):
            return []
        if not self.env['ir.config_parameter'].sudo().get_param(SYNC_PARAM):
            return []
        return [
            (rec.id, (rec.default_code or '').strip(), rec.misa_product_id,
             {field: rec[field] or '' for field in touched})
            for rec in self
        ]

    def _schedule_misa_push(self, changes):
        """Đẩy lên MISA sau khi transaction này commit, bằng cursor riêng.

        Một lần bấm Lưu có thể ghi sản phẩm nhiều lần (onchange, module khác ghi thêm).
        Gộp theo sản phẩm, giữ giá trị cũ ĐẦU TIÊN của mỗi trường — đó mới là thứ MISA
        đang có — và chỉ đăng ký một callback cho cả transaction.
        """
        postcommit = self.env.cr.postcommit
        pending = postcommit.data.get(SYNC_PARAM)
        if pending is None:
            pending = postcommit.data[SYNC_PARAM] = {}
            registry, uid = self.env.registry, self.env.uid

            def _push():
                with registry.cursor() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {'misa_skip_crm_sync': True})
                    env['product.template'].browse([])._push_changes_to_misa(
                        [(tid, *rest) for tid, rest in pending.items()], uid)

            postcommit.add(_push)

        for template_id, old_code, misa_id, old_values in changes:
            first = pending.setdefault(template_id, [old_code, misa_id, {}])
            for field, value in old_values.items():
                first[2].setdefault(field, value)

    def _push_changes_to_misa(self, changes, author_uid):
        """Đẩy từng sản phẩm, ghi kết quả lên chatter. Không bao giờ raise (đã sau commit)."""
        misa = self.env['misa.api.utils']
        author = self.env['res.users'].browse(author_uid).partner_id
        for template_id, old_code, misa_id, old_values in changes:
            product = self.browse(template_id).exists()
            if not product:
                continue
            new_values = {field: product[field] or '' for field in old_values}
            diff = {field: (old_values[field], new_values[field])
                    for field in old_values if old_values[field] != new_values[field]}
            if not diff:
                continue
            code_on_misa, pushed_misa_id = False, misa_id
            try:
                note, code_on_misa, pushed_misa_id = product._push_one_to_misa(misa, old_code, misa_id, diff)
            except Exception as error:
                _logger.exception("MISA_PRODUCT_SYNC lỗi khi đẩy sản phẩm %s", template_id)
                note = "Chưa cập nhật được MISA: %s" % error
            product.message_post(body=note, author_id=author.id or None,
                                 message_type='comment', subtype_xmlid='mail.mt_note')
            if 'default_code' in diff:
                # Mã đã đổi trên Odoo rồi; MISA nhận hay không cũng phải để lại dấu vết.
                self.env['misa.product.code.history'].record(
                    diff['default_code'][0], diff['default_code'][1], 'odoo',
                    actor=author.name, product_tmpl=product, misa_id=pushed_misa_id,
                    misa_updated=code_on_misa, odoo_updated=True,
                    note=None if code_on_misa else note,
                )

    def _push_one_to_misa(self, misa, old_code, misa_id, diff):
        """Đẩy thay đổi của MỘT sản phẩm.

        Trả ``(ghi chú chatter, mã đã đổi trên MISA hay chưa, MISA ID)``.
        """
        self.ensure_one()
        if not misa_id:
            found = misa._find_exact_crm_product_by_code(old_code) if old_code else None
            if not found:
                return ("Chưa cập nhật MISA: không thấy mã %s trên MISA CRM." % (old_code or '(trống)'),
                        False, None)
            misa_id = str(found.get('misa_id'))
            self.write({'misa_product_id': misa_id})

        if 'default_code' in diff:
            new_code = diff['default_code'][1].strip()
            taken = misa._find_exact_crm_product_by_code(new_code) if new_code else None
            if not new_code or (taken and str(taken.get('misa_id')) != misa_id):
                # Bỏ cả lượt: đổi tên mà giữ mã cũ cũng là lệch, thà báo để người sửa quyết.
                return ("Chưa cập nhật MISA: mã mới %s %s." %
                        (new_code or '(trống)', "đã thuộc hàng khác trên MISA" if new_code else "bị bỏ trống"),
                        False, misa_id)

        done, failed, code_on_misa = [], [], False
        for field, (old, new) in diff.items():
            ok = misa.update_product_field_misa(misa_id, SYNCED_FIELDS[field], new.strip(), old)
            (done if ok else failed).append("%s «%s» → «%s»" % (FIELD_LABELS[field], old, new))
            code_on_misa = code_on_misa or (ok and field == 'default_code')
        _logger.info("MISA_PRODUCT_SYNC MISA ID %s: được %s, hỏng %s", misa_id, done, failed)
        parts = []
        if done:
            parts.append("Đã cập nhật MISA (ID %s): %s." % (misa_id, "; ".join(done)))
        if failed:
            parts.append("MISA KHÔNG nhận: %s — sửa tay trên MISA." % "; ".join(failed))
        return " ".join(parts), code_on_misa, misa_id
