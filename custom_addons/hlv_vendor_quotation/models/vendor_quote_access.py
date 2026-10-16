# -*- coding: utf-8 -*-
import hmac
import secrets

from odoo import _, api, fields, models
from odoo.osv import expression
from odoo.tools import str2bool

from .vendor_quote_utils import is_login_locked, next_failed_count, session_fingerprint

# Bỏ I, L, O, 0, 1: NCC hay gõ mật khẩu trên điện thoại và nhầm các ký tự này.
PASSWORD_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
PASSWORD_LENGTH = 6
# Mã ngắn trong link gửi NCC (/bao-gia/k7mx3qp9tz): link dài 32 ký tự trông như link lừa đảo, NCC ngại bấm.
# 10 ký tự trong 31 ký tự (chữ thường + số, bỏ i l o 0 1 dễ nhầm) ≈ 8·10^14 mã — đoán trúng link của
# một NCC nào đó vẫn là không thể dù có vài nghìn NCC. Mã dài cũ (access_token) vẫn mở được: NCC đã
# lưu link cũ không bị chặn.
SHORT_CODE_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
SHORT_CODE_LENGTH = 10
MAX_LOGIN_ATTEMPTS = 5
LOCK_MINUTES = 15
PORTAL_ROUTE = "/bao-gia"
# Đoạn đường dẫn tab "Đơn mua hàng" trên trang NCC: <link NCC>/don-mua/<id đơn>.
PORTAL_ORDERS = "don-mua"
# Trang quản lý của sale (controllers/sale_page.py); ?ncc=<id> mở sẵn NCC đó.
SALE_PAGE_ROUTE = "/hoi-gia-ncc"
# Bật trong Cài đặt → Mua hàng → Hỏi giá NCC. Mặc định tắt: tin Zalo gửi link kèm mật khẩu
# trong cùng một tin nên mật khẩu gần như không chặn thêm được ai, chỉ làm NCC mất công nhập.
REQUIRE_PASSWORD_PARAM = "hlv_vendor_quotation.require_password"


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
    # Không đặt default: thêm field lúc nâng cấp thì Odoo gọi default MỘT lần rồi gán cùng một mã cho mọi
    # link cũ (trùng mã). Link mới: sinh trong create(); link cũ: migrations/18.0.3.49.0.
    short_code = fields.Char(
        string="Mã link ngắn", readonly=True, copy=False, index=True,
        help="Mã trong link gửi NCC. Link dài cũ (Mã link) vẫn mở được.",
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
        ("short_code_uniq", "unique(short_code)", "Mã link ngắn bị trùng, hãy tạo lại link."),
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

    def _portal_path(self):
        """Đường dẫn trang NCC (không domain), dùng mã ngắn; bản ghi chưa có mã ngắn thì mã dài."""
        self.ensure_one()
        return f"{PORTAL_ROUTE}/{self.short_code or self.access_token}"

    def _portal_paths(self):
        """Mọi đường dẫn gốc mở được trang NCC này (mã ngắn + mã dài cũ) — để kiểm link quay về."""
        self.ensure_one()
        return {f"{PORTAL_ROUTE}/{code}" for code in (self.short_code, self.access_token) if code}

    @api.depends("access_token", "short_code", "partner_id")
    def _compute_urls(self):
        for rec in self:
            base = rec.get_base_url()
            rec.portal_url = f"{base}{rec._portal_path()}"
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
            vals.setdefault("short_code", self._new_short_code())
        return super().create(vals_list)

    @api.model
    def _new_token(self):
        return secrets.token_urlsafe(24)

    @api.model
    def _new_short_code(self):
        """Mã ngắn chưa NCC nào dùng (thử lại khi trùng — hiếm tới mức gần như không xảy ra)."""
        while True:
            code = "".join(secrets.choice(SHORT_CODE_ALPHABET) for _i in range(SHORT_CODE_LENGTH))
            if not self.sudo().with_context(active_test=False).search_count([("short_code", "=", code)]):
                return code

    @api.model
    def _find_by_code(self, code):
        """Link NCC theo mã trong URL: mã ngắn (link mới) hoặc mã dài (link cũ NCC đã lưu). Không có → rỗng."""
        if not code:
            return self.browse()
        return self.search(["|", ("short_code", "=", code), ("access_token", "=", code)], limit=1)

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
            # Đổi cả mã ngắn: thu hồi link là thu hồi cả hai dạng.
            rec.write({"access_token": self._new_token(), "short_code": self._new_short_code()})
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

    def _vendor_purchase_orders(self):
        """Đơn mua đã xác nhận sinh ra từ các báo giá của NCC này (xem hlv.vendor.quote)."""
        self.ensure_one()
        return self.quote_ids._vendor_purchase_orders()

    @api.model
    def _password_required(self):
        """NCC có phải nhập mật khẩu khi mở link không (Cài đặt, mặc định không)."""
        return str2bool(self.env["ir.config_parameter"].sudo().get_param(REQUIRE_PASSWORD_PARAM, "False"))

    def _shown_password(self):
        """Mật khẩu để sale gửi NCC — rỗng khi đang tắt mật khẩu (khỏi gửi thứ không dùng)."""
        self.ensure_one()
        return (self.password or "") if self._password_required() else ""

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
