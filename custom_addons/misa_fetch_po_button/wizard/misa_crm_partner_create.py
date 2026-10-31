# -*- coding: utf-8 -*-
"""Hộp thoại "Tạo khách từ MISA CRM": gõ MST / tên → tìm khách trên CRM → tạo liên hệ Odoo.

Trước khi tạo luôn kiểm Odoo đã có khách chưa: trùng mã khách CRM hoặc MST thì CHẶN (chỉ cho mở
khách đã có), chỉ trùng tên thì cảnh báo — CRM có nhiều khách cùng tên khác mã là chuyện thật.
Tạo bằng quyền của người dùng (menu chỉ hiện cho nhóm "Contact Creation"), không sudo.
"""
import json

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from ..utils.text_match import same_name, tax_code_key

NAME_CANDIDATE_LIMIT = 50


class MisaCrmPartnerCreate(models.TransientModel):
    _name = "misa.crm.partner.create"
    _description = "Tạo khách từ MISA CRM"

    keyword = fields.Char(string="MST hoặc tên khách")
    line_ids = fields.One2many("misa.crm.partner.create.line", "wizard_id", string="Khách trên CRM")
    searched = fields.Boolean()

    def action_search(self):
        self.ensure_one()
        keyword = (self.keyword or "").strip()
        if not keyword:
            raise UserError(_("Nhập MST hoặc tên khách để tìm."))
        # sudo chỉ để đọc token / cấu hình CRM; tạo liên hệ vẫn bằng quyền người dùng.
        accounts = self.env["misa.api.utils"].sudo().crm_search_accounts(keyword[:100])
        Line = self.env["misa.crm.partner.create.line"]
        self.line_ids.unlink()
        self.write({
            "searched": True,
            "line_ids": [fields.Command.create(Line._values_from_account(a)) for a in accounts],
        })
        return self._reopen()

    def _reopen(self):
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "name": _("Tạo khách từ MISA CRM"),
        }


class MisaCrmPartnerCreateLine(models.TransientModel):
    _name = "misa.crm.partner.create.line"
    _description = "Khách trên MISA CRM"

    wizard_id = fields.Many2one("misa.crm.partner.create", required=True, ondelete="cascade")
    account_json = fields.Text(help="Nguyên dòng Account của CRM, dùng lại khi tạo.")
    account_number = fields.Char(string="Mã khách CRM")
    account_name = fields.Char(string="Tên trên CRM")
    tax_code = fields.Char(string="MST")
    phone = fields.Char(string="Điện thoại")
    address = fields.Char(string="Địa chỉ")
    owner = fields.Char(string="Sale phụ trách")
    crm_inactive = fields.Boolean(string="Ngừng theo dõi trên CRM")
    state = fields.Selection([
        ("exists", "Đã có trong Odoo"),
        ("same_name", "Có khách trùng tên"),
        ("new", "Chưa có"),
    ], string="Odoo", required=True, default="new")
    existing_partner_id = fields.Many2one("res.partner", string="Khách Odoo đã có")
    match_reason = fields.Char(string="Lý do trùng")
    same_name_partner_ids = fields.Many2many("res.partner", string="Khách Odoo cùng tên")

    @api.model
    def _values_from_account(self, account):
        address = ", ".join(filter(None, [
            (account.get("BillingAddress") or "").strip(),
            (account.get("BillingProvinceIDText") or "").strip(),
        ]))
        vals = {
            "account_json": json.dumps(account, ensure_ascii=False),
            "account_number": (account.get("AccountNumber") or "").strip(),
            "account_name": (account.get("AccountName") or "").strip(),
            "tax_code": (account.get("TaxCode") or "").strip(),
            "phone": (account.get("OfficeTel") or "").strip(),
            "address": address,
            "owner": account.get("OwnerIDText") or "",
            "crm_inactive": bool(account.get("Inactive")),
        }
        vals.update(self._odoo_match(account))
        return vals

    @api.model
    def _odoo_match(self, account):
        """Odoo đã có khách này chưa: {state, existing_partner_id, match_reason, same_name_partner_ids}."""
        existing, reason = self._find_existing_partner(account)
        if existing:
            return {"state": "exists", "existing_partner_id": existing.id, "match_reason": reason,
                    "same_name_partner_ids": [fields.Command.clear()]}
        namesakes = self._same_name_partners(account.get("AccountName"))
        return {
            "state": "same_name" if namesakes else "new",
            "existing_partner_id": False,
            "match_reason": _("Trùng tên") if namesakes else False,
            "same_name_partner_ids": [fields.Command.set(namesakes.ids)],
        }

    @api.model
    def _find_existing_partner(self, account):
        """(khách gốc trùng mã khách CRM hoặc MST, lý do) — cả khách đã lưu trữ, vì tạo thêm là trùng.
        Không có → (res.partner rỗng, "")."""
        Partner = self.env["res.partner"].with_context(active_test=False)
        code = (account.get("AccountNumber") or "").strip()
        if code:
            # Mã khách lưu ở ref hoặc company_registry (cùng chỗ đồng bộ CRM ghi). =ilike để khỏi phân
            # biệt hoa thường; "_" trong mã là ký tự đại diện nên lọc lại bằng so khớp đúng.
            found = Partner.search([
                ("parent_id", "=", False), "|", ("ref", "=ilike", code), ("company_registry", "=ilike", code),
            ], order="active desc, id asc").filtered(
                lambda p: code.upper() in ((p.ref or "").strip().upper(), (p.company_registry or "").strip().upper()))
            if found:
                return found[:1], _("Trùng mã khách CRM %s", code)
        vat = tax_code_key(account.get("TaxCode"))
        if vat:
            found = Partner.search([("vat", "=ilike", vat)], order="active desc, id asc").filtered(
                lambda p: tax_code_key(p.vat) == vat)
            if found:
                return found[:1].commercial_partner_id, _("Trùng MST %s", vat)
        return Partner.browse(), ""

    @api.model
    def _same_name_partners(self, name):
        """Khách gốc trong Odoo cùng tên (bỏ qua hoa thường, dấu cách). ilike không bỏ dấu nên tên
        lệch dấu tiếng Việt sẽ không bắt được — chỉ là cảnh báo, chấp nhận."""
        name = (name or "").strip()
        if not name:
            return self.env["res.partner"]
        candidates = self.env["res.partner"].search(
            [("parent_id", "=", False), ("name", "ilike", name)], limit=NAME_CANDIDATE_LIMIT)
        return candidates.filtered(lambda p: same_name(p.name, name))

    def action_create_partner(self):
        self.ensure_one()
        account = json.loads(self.account_json or "{}")
        # Kiểm lại ngay lúc tạo: từ lúc tìm tới lúc bấm, người khác (hoặc webhook MISA) có thể đã tạo.
        existing, reason = self._find_existing_partner(account)
        if existing:
            raise UserError(_("Không tạo: Odoo đã có khách %(name)s (%(reason)s).",
                              name=existing.display_name, reason=reason))
        if not (account.get("AccountName") or "").strip():
            raise UserError(_("Khách trên CRM không có tên."))
        Partner = self.env["res.partner"]
        # Dùng chung ánh xạ Account → liên hệ với đồng bộ CRM; truyền liên hệ rỗng để lấy đủ mọi trường.
        vals = self.env["misa.crm.contact.sync.run"]._values_from_crm_account(account, Partner)
        partner = Partner.create(vals)
        partner.message_post(body=Markup(_("Tạo từ khách MISA CRM <b>%(code)s</b> (ID %(crm_id)s)."))
                             % {"code": account.get("AccountNumber") or "", "crm_id": account.get("ID") or ""})
        return self._open_partner(partner)

    def action_open_existing(self):
        self.ensure_one()
        return self._open_partner(self.existing_partner_id)

    def _open_partner(self, partner):
        return {
            "type": "ir.actions.act_window",
            "res_model": "res.partner",
            "res_id": partner.id,
            "view_mode": "form",
            "target": "current",
        }
