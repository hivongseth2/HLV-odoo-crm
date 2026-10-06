# -*- coding: utf-8 -*-
import hmac
import secrets

from odoo import _, api, fields, models
from odoo.osv import expression

from .vendor_quote_utils import is_login_locked, next_failed_count, session_fingerprint

# Bỏ I, L, O, 0, 1: NCC hay gõ mật khẩu trên điện thoại và nhầm các ký tự này.
PASSWORD_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
PASSWORD_LENGTH = 6
MAX_LOGIN_ATTEMPTS = 5
LOCK_MINUTES = 15
PORTAL_ROUTE = "/bao-gia"
# Trang quản lý của sale (controllers/sale_page.py); ?ncc=<id> mở sẵn NCC đó.
SALE_PAGE_ROUTE = "/hoi-gia-ncc"


class VendorQuoteAccess(models.Model):
    """Một NCC trong luồng báo giá.

    Hai mặt: link công khai cố định cho NCC (hiện mọi yêu cầu báo giá gửi NCC đó), và
    link quản lý nội bộ cho sale — trang /hoi-gia-ncc mở sẵn NCC này.
    """

    _name = "hlv.vendor.quote.access"
    _description = "Link báo giá nhà cung cấp"
    _inherit = ["mail.thread"]
    _rec_name = "partner_id"
    _order = "partner_id"

    partner_id = fields.Many2one(
        "res.partner",
        string="Nhà cung cấp",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )
    access_token = fields.Char(
        string="Mã link",
        required=True,
        readonly=True,
        copy=False,
        index=True,
        default=lambda self: self._new_token(),
    )
    password = fields.Char(
        string="Mật khẩu",
        required=True,
        copy=False,
        default=lambda self: self._new_password(),
    )
    active = fields.Boolean(string="Hoạt động", default=True, tracking=True)
    portal_url = fields.Char(string="Link báo giá", compute="_compute_urls")
    manage_url = fields.Char(string="Link quản lý (nội bộ)", compute="_compute_urls")
    quote_ids = fields.One2many("hlv.vendor.quote", "access_id", string="Yêu cầu báo giá")
    open_quote_count = fields.Integer(
        string="Chờ NCC báo giá", compute="_compute_quote_counts"
    )
    quoted_quote_count = fields.Integer(
        string="NCC đã báo giá", compute="_compute_quote_counts"
    )
    last_login_date = fields.Datetime(string="Đăng nhập gần nhất", readonly=True)
    failed_login_count = fields.Integer(string="Số lần sai mật khẩu", readonly=True)
    last_failed_login_date = fields.Datetime(string="Sai mật khẩu gần nhất", readonly=True)

    _sql_constraints = [
        ("partner_uniq", "unique(partner_id)", "Mỗi nhà cung cấp chỉ có một link báo giá."),
        ("token_uniq", "unique(access_token)", "Mã link bị trùng, hãy tạo lại link."),
    ]

    @api.model
    def _vendor_partner_domain(self):
        """Ai được coi là NCC trên trang hỏi giá — nơi DUY NHẤT định nghĩa điều này.

        Công ty gốc (hlv_partner_type = root_company: không có cha, là công ty) có xếp hạng
        NCC hoặc gắn phân loại "Nhà cung cấp" (hlv_contact_refine, code "vendor"). Nhiều NCC
        cũ chưa từng có đơn mua trong Odoo nên supplier_rank = 0 — chỉ phân loại mới bắt
        được họ. Liên hệ con / cá nhân bị loại vì sale chọn nhầm người liên hệ sẽ ra hai
        link báo giá cho cùng một công ty.
        Cộng thêm NCC đã từng nhận yêu cầu báo giá, để báo giá cũ không mất NCC khi phân loại
        của họ bị đổi.
        """
        quoted_ids = self.with_context(active_test=False).search([]).partner_id.ids
        return expression.OR([
            [
                ("hlv_partner_type", "=", "root_company"),
                "|", ("supplier_rank", ">", 0), ("hlv_filter_tag_ids.code", "=", "vendor"),
            ],
            [("id", "in", quoted_ids)],
        ])

    @api.model
    def _vendor_search_domain(self, term):
        """NCC khớp chữ gõ theo tên, mã liên hệ hoặc MST. term rỗng → mọi NCC."""
        domain = self._vendor_partner_domain()
        if not term:
            return domain
        return expression.AND([domain, [
            "|", "|", ("name", "ilike", term), ("ref", "ilike", term), ("vat", "ilike", term),
        ]])

    @api.depends("access_token", "partner_id")
    def _compute_urls(self):
        for rec in self:
            base = rec.get_base_url()
            rec.portal_url = f"{base}{PORTAL_ROUTE}/{rec.access_token}"
            rec.manage_url = f"{base}{SALE_PAGE_ROUTE}?ncc={rec.partner_id.id}" if rec.partner_id else False

    @api.depends("quote_ids.state")
    def _compute_quote_counts(self):
        for rec in self:
            states = rec.quote_ids.mapped("state")
            rec.open_quote_count = states.count("sent")
            rec.quoted_quote_count = states.count("quoted")

    @api.model_create_multi
    def create(self, vals_list):
        # Link gắn với công ty NCC, không với từng liên hệ — sale chọn nhầm tên người liên
        # hệ vẫn ra đúng một link cho cả công ty.
        Partner = self.env["res.partner"]
        for vals in vals_list:
            if vals.get("partner_id"):
                vals["partner_id"] = Partner.browse(vals["partner_id"]).commercial_partner_id.id
        return super().create(vals_list)

    @api.model
    def _new_token(self):
        return secrets.token_urlsafe(24)

    @api.model
    def _new_password(self):
        return "".join(secrets.choice(PASSWORD_ALPHABET) for _i in range(PASSWORD_LENGTH))

    @api.model
    def _get_for_partner(self, partner):
        """Link của công ty NCC (commercial partner) — mọi liên hệ của cùng công ty dùng chung."""
        vendor = partner.commercial_partner_id
        access = self.with_context(active_test=False).search([("partner_id", "=", vendor.id)], limit=1)
        if not access:
            return self.create({"partner_id": vendor.id})
        if not access.active:
            access.active = True
        return access

    def action_regenerate_token(self):
        for rec in self:
            rec.access_token = self._new_token()
            rec.message_post(body=_("Đã tạo link mới — link cũ không còn dùng được."))

    def action_regenerate_password(self):
        for rec in self:
            rec.write({"password": self._new_password(), "failed_login_count": 0})
            rec.message_post(body=_("Đã đổi mật khẩu — NCC phải đăng nhập lại."))

    def action_unlock(self):
        self.write({"failed_login_count": 0, "last_failed_login_date": False})

    def action_new_quote(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Yêu cầu báo giá mới"),
            "res_model": "hlv.vendor.quote",
            "view_mode": "form",
            "target": "current",
            "context": {"default_partner_id": self.partner_id.id},
        }

    def action_view_quotes(self):
        self.ensure_one()
        action = self.env["ir.actions.act_window"]._for_xml_id(
            "hlv_vendor_quotation.action_vendor_quote"
        )
        action["domain"] = [("access_id", "=", self.id)]
        action["context"] = {"default_partner_id": self.partner_id.id}
        return action

    def _session_key(self):
        self.ensure_one()
        return session_fingerprint(self.access_token, self.password)

    def _is_locked(self):
        self.ensure_one()
        return is_login_locked(
            self.failed_login_count,
            self.last_failed_login_date,
            fields.Datetime.now(),
            MAX_LOGIN_ATTEMPTS,
            LOCK_MINUTES,
        )

    def _vendor_login(self, password):
        """Kiểm mật khẩu NCC nhập ở link công khai. Trả "ok", "wrong" hoặc "locked"."""
        self.ensure_one()
        if self._is_locked():
            return "locked"
        # Mật khẩu chỉ gồm chữ in hoa + số; NCC gõ chữ thường trên điện thoại vẫn cho qua.
        typed = (password or "").strip().upper().encode("utf-8")
        if hmac.compare_digest(typed, (self.password or "").encode("utf-8")):
            self.write({"failed_login_count": 0, "last_login_date": fields.Datetime.now()})
            return "ok"
        now = fields.Datetime.now()
        self.write({
            "failed_login_count": next_failed_count(
                self.failed_login_count, self.last_failed_login_date, now, LOCK_MINUTES
            ),
            "last_failed_login_date": now,
        })
        return "locked" if self._is_locked() else "wrong"
