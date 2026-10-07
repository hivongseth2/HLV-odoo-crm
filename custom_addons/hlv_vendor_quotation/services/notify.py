# -*- coding: utf-8 -*-
"""Đăng chatter cho các việc NCC làm trên trang công khai, chỉ báo người trong công ty.

Không đăng kiểu "comment" (mt_comment): mọi follower nhận thông báo, mà follower thường có
cả đối tác bên ngoài — Odoo tự cho NCC theo dõi đơn mua của chính họ. Kết quả là gửi email
ra ngoài (và lỗi "Invalid email address" khi NCC không có email). Thay vào đó đăng ghi chú
nội bộ và gọi tên đích danh các follower là user nội bộ.
"""


def internal_followers(record):
    """Partner của các follower là user nội bộ (không phải portal / đối tác bên ngoài)."""
    return record.sudo().message_follower_ids.partner_id.filtered(
        lambda partner: partner.user_ids.filtered(lambda user: not user.share)
    )


def post_internal(record, body, author=None):
    """Ghi chú nội bộ lên record, thông báo cho follower nội bộ. author: res.partner (VD NCC).

    mail_create_nosubscribe: Odoo mặc định cho tác giả theo dõi record khi đăng — NCC đăng từ
    trang công khai sẽ thành follower YCMH / phiếu và về sau nhận email mọi bình luận.
    """
    record.with_context(mail_create_nosubscribe=True).message_post(
        body=body,
        author_id=author.id if author else None,
        message_type="comment",
        subtype_xmlid="mail.mt_note",
        partner_ids=internal_followers(record).ids,
    )
