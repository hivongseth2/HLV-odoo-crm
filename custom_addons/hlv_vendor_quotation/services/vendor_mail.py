# -*- coding: utf-8 -*-
"""Gửi email cho NCC từ trang /hoi-gia-ncc (hộp thông tin NCC): cùng nội dung tin Zalo soạn sẵn,
sale sửa được trước khi gửi.

Gửi bằng mail.mail của Odoo (máy chủ mail ra đã cấu hình), không đăng vào khung trao đổi của
báo giá — khung đó NCC cũng thấy. Ghi lại một dòng nội bộ trên link NCC để biết đã gửi gì, cho ai.
"""

from markupsafe import escape

from odoo.exceptions import UserError
from odoo.tools import plaintext2html

from ..models.vendor_quote_utils import parse_email_list

SUBJECT_MAX = 200
BODY_MAX = 10000
MAX_RECIPIENTS = 10


def mail_defaults(quote, sale_code=""):
    """Giá trị điền sẵn cho hộp gửi email: {to, cc, subject, suggestions}.

    to: email NCC (công ty, không có thì người liên hệ đầu tiên có email); cc: email sale hỏi giá
    (danh bạ sale) để sale nhận bản sao; suggestions: mọi email của NCC để bấm thêm.
    """
    partner = (quote.access_id.partner_id or quote.partner_id).commercial_partner_id
    emails = [e for e in [partner.email] + partner.child_ids.filtered("active").mapped("email") if e]
    contact = quote.env["hlv.vendor.sale.contact"]._for_code(sale_code or quote.inquiry_id.sale_code) or {}
    company = quote.company_id or quote.env.company
    return {
        "to": emails[0] if emails else "",
        "cc": contact.get("email", ""),
        "subject": f"{company.name} – yêu cầu báo giá {quote.name}",
        "suggestions": list(dict.fromkeys(e.strip().lower() for e in emails)),
    }


def send_vendor_mail(quote, to, cc, subject, body, sale_code=""):
    """Gửi một email cho NCC của báo giá. Sai dữ liệu → UserError (thông điệp cho sale).

    Trả {"state": "sent" | "outgoing", "to": [...]} — "outgoing" là đã xếp hàng đợi máy chủ mail
    gửi (gửi ngay không được thì cron mail của Odoo gửi lại).
    """
    recipients, bad_to = parse_email_list(to)
    copies, bad_cc = parse_email_list(cc)
    if bad_to or bad_cc:
        raise UserError("Email không hợp lệ: " + ", ".join(bad_to + bad_cc))
    if not recipients:
        raise UserError("Nhập email NCC cần gửi tới.")
    if len(recipients) + len(copies) > MAX_RECIPIENTS:
        raise UserError(f"Gửi tối đa {MAX_RECIPIENTS} địa chỉ một lần.")
    subject = (subject or "").strip()[:SUBJECT_MAX]
    body = (body or "").strip()[:BODY_MAX]
    if not subject or not body:
        raise UserError("Email cần có tiêu đề và nội dung.")

    env = quote.env
    company = quote.company_id or env.company
    contact = env["hlv.vendor.sale.contact"]._for_code(sale_code or quote.inquiry_id.sale_code) or {}
    email_from = company.email_formatted or env.user.email_formatted
    mail = env["mail.mail"].sudo().create({
        "subject": subject,
        "body_html": plaintext2html(body),
        "email_from": email_from,
        # NCC bấm trả lời là về thẳng sale hỏi giá (nếu danh bạ sale có email).
        "reply_to": contact.get("email") or email_from,
        "email_to": ", ".join(recipients),
        "email_cc": ", ".join(copies),
        # Không gắn model/res_id của báo giá: thư sẽ thành một tin trên báo giá, lẫn vào khung trao đổi.
        "auto_delete": False,
    })
    mail.send(raise_exception=False)
    if mail.state == "exception":
        raise UserError("Máy chủ mail không gửi được: " + (mail.failure_reason or "không rõ lý do") +
                        ". Kiểm tra cấu hình máy chủ mail ra (Thiết lập → Kỹ thuật → Máy chủ mail ra).")
    if quote.access_id:
        quote.access_id.sudo().message_post(
            body=escape("Đã gửi email \"{}\" ({}) tới {}{}.").format(
                subject, quote.name, ", ".join(recipients), f" — CC {', '.join(copies)}" if copies else ""),
            subtype_xmlid="mail.mt_note",
        )
    return {"state": mail.state, "to": recipients}
