"""Tìm tin nhắn đơn bán theo từ khoá / alias / thời gian, và đánh dấu đã đọc theo bộ lọc.

Dùng cho drawer "Tin nhắn mới từ saler" (trang điều phối) và ô tìm trong panel Thông
báo của /sale_plan. Mọi điều kiện là AND: mọi từ trong ô tìm, mọi alias đã chọn, và
khoảng thời gian.

Lọc hai tầng: domain SQL lọc thô (unaccent nên rộng hơn ý người gõ), rồi Python kiểm
lại đúng dấu / đủ alias — xem message_search_utils.py.
"""

import logging
import re
from datetime import datetime, timedelta

import pytz

from odoo import api, fields, models
from odoo.osv import expression

from .delivery_planner_messages import (
    _SKIP_MSG_RE,
    _message_plain_text,
    _normalize_mention_alias,
    _split_public_author_prefix,
)
from .message_period_utils import local_days_to_utc_range, message_period_bounds
from .message_search_utils import (
    matches_words,
    mentions_all_aliases,
    needs_exact_check,
    split_search_words,
)

_logger = logging.getLogger(__name__)

# Trần số tin quét cho một lần bấm tìm / "Tải thêm" khi phải kiểm lại bằng Python —
# từ ngắn có dấu ("dạ") qua unaccent khớp rất nhiều tin thô.
_SEARCH_SCAN_CAP = 2000
_SEARCH_BATCH = 200
# Trần cho "đánh dấu đã đọc theo bộ lọc" (chỉ duyệt khi cần kiểm lại bằng Python).
_MARK_SCAN_CAP = 20000


class DeliveryPlannerServiceMessageSearch(models.AbstractModel):
    _inherit = 'hlv.delivery.planner.service'

    @api.model
    def _plan_message_user_tz(self):
        try:
            return pytz.timezone(self.env.context.get('tz') or self.env.user.tz or 'Asia/Ho_Chi_Minh')
        except Exception:
            return pytz.UTC

    @api.model
    def _plan_message_period_domain(self, period='', date_from='', date_to=''):
        """Domain lọc mail.message.date theo lựa chọn "Thời gian"; [] nếu không lọc."""
        tz = self._plan_message_user_tz()
        today = datetime.now(pytz.UTC).astimezone(tz).date()
        from_day, to_day = message_period_bounds(period or '', today, date_from, date_to)
        start_utc, end_utc = local_days_to_utc_range(from_day, to_day, tz)
        domain = []
        if start_utc:
            domain.append(('date', '>=', fields.Datetime.to_string(start_utc)))
        if end_utc:
            domain.append(('date', '<', fields.Datetime.to_string(end_utc)))
        return domain

    @api.model
    def _plan_message_search_domain(self, words=None, aliases=None, days=365, unread_only=False,
                                    period='', date_from='', date_to=''):
        """Domain SQL (lọc thô) chung cho tìm kiếm và "đánh dấu đã đọc theo bộ lọc".

        - words: MỖI từ phải khớp nội dung tin, tên người gửi, hoặc mã đơn / tên khách.
        - aliases: tin phải nhắc ĐỦ mọi alias (backend render mention thành
          <strong class="sale-plan-mention">@alias</strong>).
        - period/date_from/date_to: khoảng thời gian (message_period_bounds). Có khoảng
          thời gian thì bỏ mốc trần `days` — ngày tự chọn có thể cũ hơn 1 năm.
        - unread_only: chỉ đơn user hiện tại chưa đọc. Trạng thái đọc lưu theo ĐƠN
          (hlv.sale.plan.message) nên mọi tin trong đơn đó đều coi là chưa đọc.
        """
        domain = [
            ('model', '=', 'sale.order'),
            ('message_type', 'in', ('comment', 'email')),
        ]
        period_domain = self._plan_message_period_domain(period, date_from, date_to)
        domain += period_domain
        days = int(days or 0)
        if days > 0 and not period_domain:
            floor_dt = fields.Datetime.now() - timedelta(days=days)
            domain.append(('date', '>=', fields.Datetime.to_string(floor_dt)))

        if unread_only:
            unread_so_ids = self.env['hlv.sale.plan.message'].sudo().search([
                ('user_id', '=', self.env.uid),
                ('is_read', '=', False),
            ]).mapped('sale_order_id').ids
            # Không có đơn chưa đọc → chặn bằng res_id in [0] cho ra tập rỗng.
            domain.append(('res_id', 'in', unread_so_ids or [0]))

        for alias in aliases or []:
            domain.append(('body', 'ilike', '@%s' % alias))

        for word in words or []:
            term_domain = [[('body', 'ilike', word)], [('author_id.name', 'ilike', word)]]
            # Gõ mã đơn / tên khách: đổi sang res_id để không phải ilike toàn bộ body.
            orders = self.env['sale.order'].sudo().search(
                ['|', ('name', 'ilike', word), ('partner_id.name', 'ilike', word)],
                limit=500,
            )
            if orders:
                term_domain.append([('res_id', 'in', orders.ids)])
            domain = expression.AND([domain, expression.OR(term_domain)])

        return domain

    @api.model
    def _normalize_plan_message_filters(self, search='', aliases=None):
        aliases = [_normalize_mention_alias(alias) for alias in (aliases or [])]
        return split_search_words(search), list(dict.fromkeys(a for a in aliases if a))

    @api.model
    def _plan_message_orders(self, records):
        """{sale_order_id: (mã đơn, tên khách)} cho một lô tin."""
        so_ids = list({rec.res_id for rec in records if rec.res_id})
        return {
            order.id: (order.name or '', order.partner_id.name or '')
            for order in self.env['sale.order'].sudo().browse(so_ids).exists()
        }

    @api.model
    def _plan_message_text(self, rec):
        """(plain text, người gửi hiển thị) của một tin."""
        plain = _message_plain_text(rec.body or '')
        if not plain and rec.body:
            # html2plaintext trả rỗng với vài dạng HTML → bóc thẻ thủ công, nếu không
            # tin sẽ bị coi là rỗng và biến mất khỏi kết quả.
            plain = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', rec.body or '')).strip()
        author, clean_body = _split_public_author_prefix(rec.body or '', plain)
        if not author:
            author = rec.author_id.name if rec.author_id else (rec.email_from or '')
        return plain, author, clean_body

    @api.model
    def _plan_message_passes(self, plain, author, rec, order_info, words, aliases):
        """Kiểm lại đúng dấu / đủ alias cho tin đã qua lọc thô SQL."""
        if not mentions_all_aliases(plain, aliases):
            return False
        so_name, partner_name = order_info
        return matches_words(words, [plain, author, rec.author_id.name, so_name, partner_name])

    @api.model
    def search_plan_messages(self, search='', aliases=None, limit=50, offset=0, days=365, unread_only=False,
                             period='', date_from='', date_to=''):
        """Tìm trên TOÀN BỘ tin nhắn của đơn bán (mail.message).

        Khác với hlv.sale.plan.message (mỗi đơn 1 dòng, chỉ giữ tin CUỐI), hàm này
        quét từng tin một nên tìm được cả tin cũ trong cùng một đơn.

        Quét theo lô cho tới khi đủ `limit` tin khớp hoặc chạm trần quét; next_offset
        đếm theo số tin ĐÃ QUÉT (không phải số tin trả về) để trang sau không trùng/sót.
        """
        words, aliases = self._normalize_plan_message_filters(search, aliases)
        if not words and not aliases and not unread_only and not period:
            return {'messages': [], 'has_more': False, 'next_offset': 0}

        limit = max(1, min(int(limit or 50), 200))
        offset = max(0, int(offset or 0))
        domain = self._plan_message_search_domain(
            words=words, aliases=aliases, days=days, unread_only=unread_only,
            period=period, date_from=date_from, date_to=date_to,
        )
        exact = needs_exact_check(words, aliases)
        user_tz = self._plan_message_user_tz()
        Message = self.env['mail.message'].sudo()

        result = []
        stats = {'empty': 0, 'system': 0, 'inexact': 0}
        cursor = offset
        has_more = True
        while len(result) < limit and cursor - offset < max(_SEARCH_SCAN_CAP, limit):
            batch_start = cursor
            batch = Message.search(domain, order='date desc, id desc', limit=_SEARCH_BATCH, offset=cursor)
            orders = self._plan_message_orders(batch)
            read_rows = self.env['hlv.sale.plan.message'].sudo().search_read(
                [('user_id', '=', self.env.uid), ('sale_order_id', 'in', list(orders))],
                ['sale_order_id', 'is_read'],
            )
            read_by_so = {r['sale_order_id'][0]: r['is_read'] for r in read_rows if r.get('sale_order_id')}
            for rec in batch:
                cursor += 1
                row = self._plan_message_row(rec, orders, read_by_so, words, aliases, exact, user_tz, stats)
                if row:
                    result.append(row)
                    if len(result) >= limit:
                        break
            if len(batch) < _SEARCH_BATCH and cursor == batch_start + len(batch):
                has_more = False
                break

        if not result and cursor > offset:
            _logger.info(
                'search_plan_messages: quét %s tin nhưng không giữ lại tin nào (%s) — words=%r aliases=%r',
                cursor - offset, stats, words, aliases,
            )
        return {
            'messages': result,
            'has_more': has_more,
            'next_offset': cursor,
            # Số liệu để soi nhanh khi kết quả rỗng bất thường (FE log ra console).
            'scanned': cursor - offset,
            'dropped_empty': stats['empty'],
            'dropped_system': stats['system'],
            'dropped_inexact': stats['inexact'],
        }

    @api.model
    def _plan_message_row(self, rec, orders, read_by_so, words, aliases, exact, user_tz, stats):
        """Dòng kết quả cho một tin, hoặc None nếu tin bị loại (stats ghi lý do)."""
        plain, author, clean_body = self._plan_message_text(rec)
        attachment_count = len(rec.attachment_ids)
        if not plain and not attachment_count:
            stats['empty'] += 1
            return None
        # Log hệ thống không bao giờ chứa @mention, nên khi đang lọc alias thì không
        # chạy bộ lọc này — tránh nuốt nhầm tin thật.
        if not aliases and plain and _SKIP_MSG_RE.search(plain):
            stats['system'] += 1
            return None
        order_info = orders.get(rec.res_id, ('', ''))
        if exact and not self._plan_message_passes(plain, author, rec, order_info, words, aliases):
            stats['inexact'] += 1
            return None
        local_dt = rec.date.replace(tzinfo=pytz.UTC).astimezone(user_tz) if rec.date else None
        return {
            'message_id': rec.id,
            'sale_order_id': rec.res_id,
            'so_name': order_info[0],
            'author': author or '',
            'date': local_dt.strftime('%d/%m %H:%M') if local_dt else '',
            'date_full': local_dt.strftime('%d/%m/%Y %H:%M') if local_dt else '',
            'preview': clean_body[:400],
            'attachment_count': attachment_count,
            'is_read': bool(read_by_so.get(rec.res_id, True)),
        }

    @api.model
    def _plan_message_matching_so_ids(self, domain, words, aliases, max_orders):
        """Đơn có tin khớp bộ lọc; trả (so_ids, truncated)."""
        Message = self.env['mail.message'].sudo()
        if not needs_exact_check(words, aliases):
            groups = Message._read_group(domain, groupby=['res_id'], limit=max_orders + 1)
            so_ids = [res_id for (res_id,) in groups if res_id]
            return so_ids[:max_orders], len(so_ids) > max_orders

        so_ids = []
        matched = set()
        for start in range(0, _MARK_SCAN_CAP, _SEARCH_BATCH):
            batch = Message.search(domain, order='id desc', limit=_SEARCH_BATCH, offset=start)
            orders = self._plan_message_orders(batch)
            for rec in batch:
                if not rec.res_id or rec.res_id in matched:
                    continue  # đơn đã khớp thì khỏi kiểm thêm tin của nó
                plain, author, _clean = self._plan_message_text(rec)
                if self._plan_message_passes(plain, author, rec, orders.get(rec.res_id, ('', '')), words, aliases):
                    matched.add(rec.res_id)
                    so_ids.append(rec.res_id)
            if len(so_ids) > max_orders:
                return so_ids[:max_orders], True
            if len(batch) < _SEARCH_BATCH:
                return so_ids, False
        return so_ids, True  # chạm trần quét — bấm lại để chạy tiếp

    @api.model
    def mark_plan_messages_read(self, search='', aliases=None, days=365, max_orders=5000, unread_only=False,
                                period='', date_from='', date_to=''):
        """Đánh dấu đã đọc MỌI đơn có tin khớp bộ lọc hiện tại của drawer.

        Phủ cả tin chưa kéo về màn hình, cùng luật khớp với search_plan_messages.
        Trạng thái đã đọc lưu theo ĐƠN (hlv.sale.plan.message, mỗi user 1 dòng / đơn)
        nên đánh dấu ở đây là đánh dấu cả đơn — không đánh dấu riêng 1 tin được.
        """
        words, aliases = self._normalize_plan_message_filters(search, aliases)
        if not words and not aliases and not unread_only and not period:
            return {'marked': 0, 'sale_order_ids': [], 'truncated': False}

        domain = self._plan_message_search_domain(
            words=words, aliases=aliases, days=days, unread_only=unread_only,
            period=period, date_from=date_from, date_to=date_to,
        )
        max_orders = max(1, min(int(max_orders or 5000), 20000))
        so_ids, truncated = self._plan_message_matching_so_ids(domain, words, aliases, max_orders)
        if not so_ids:
            return {'marked': 0, 'sale_order_ids': [], 'truncated': truncated}

        notifications = self.env['hlv.sale.plan.message'].sudo().search([
            ('user_id', '=', self.env.uid),
            ('sale_order_id', 'in', so_ids),
            ('is_read', '=', False),
        ])
        marked_so_ids = notifications.mapped('sale_order_id').ids
        if notifications:
            notifications.write({'is_read': True})
        return {
            'marked': len(notifications),
            'sale_order_ids': marked_so_ids,
            'truncated': truncated,
        }
