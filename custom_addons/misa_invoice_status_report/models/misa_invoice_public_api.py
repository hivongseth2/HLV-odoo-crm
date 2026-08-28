import hashlib

from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.osv import expression

from .stock_picking import MISA_INVOICE_RECONCILE_GROUP, MISA_INVOICE_STATE_LABELS

# API cho trang public /misa_sale_status (misa_invoice_public_controller) — đăng ký/xác thực mã
# sale, danh sách phiếu + action (kiểm tra/ngoại lệ/gắn mã đề nghị) scope theo đúng 1 mã sale,
# và tra cứu 1 phiếu/phiếu anh em (dùng chung cho cả nội bộ lẫn public). Tách khỏi
# stock_picking.py (đã quá lớn) — mọi method ở đây chỉ VALIDATE quyền rồi gọi lại các method
# "thật" (vẫn ở stock_picking.py hoặc các file khác), không tự cài thêm logic đối soát nào.
#
# Mỗi sale theo dõi + tự thao tác (gắn mã đề nghị thủ công, đánh dấu ngoại lệ) trên các phiếu
# của MÌNH mà không cần vào backend Odoo. Route auth='user' — bắt buộc đăng nhập Odoo thật,
# danh tính "tôi là sale nào" lấy từ CHÍNH tài khoản đang đăng nhập
# (res.users.x_misa_saler_codes của self.env.user, xem get_misa_invoice_saler_code_registry) —
# KHÔNG còn dùng chung 1 mật khẩu cho mọi sale như trước (đã bỏ, vì lộ hết mã sale của người
# khác cho bất kỳ ai biết mật khẩu).


class StockPickingMisaInvoicePublicApi(models.Model):
    _inherit = 'stock.picking'

    @api.model
    def get_misa_invoice_saler_code_registry(self):
        """Mã sale MISA mà CHÍNH tài khoản đang đăng nhập (self.env.user) được cấu hình xem —
        1 tài khoản có thể có nhiều mã (VD trưởng nhóm quản lý nhiều sale), nhưng TUYỆT ĐỐI
        không gộp mã của user khác vào đây (khác hẳn thiết kế mật khẩu-chung trước đây) — nếu
        không, bất kỳ ai đăng nhập được cũng thấy hết mã sale của toàn bộ công ty.

        NGOẠI LỆ: tài khoản thuộc nhóm "Đối soát XHD" (MISA_INVOICE_RECONCILE_GROUP) được xem
        TẤT CẢ mã đã đăng ký — để có thể chủ động chọn xem/lấy link riêng cho từng sale (VD
        đối chiếu thay khi sale nghỉ phép, hoặc gửi link trực tiếp cho từng người) — vẫn CHỈ
        nhóm này, không mở rộng cho ai khác."""
        if self.env.user.has_group(MISA_INVOICE_RECONCILE_GROUP):
            users = self.env['res.users'].sudo().search([('x_misa_saler_codes', '!=', False)])
            codes = []
            seen = set()
            for user in users:
                for part in (user.x_misa_saler_codes or '').split(','):
                    code = part.strip()
                    if code and code.upper() not in seen:
                        seen.add(code.upper())
                        codes.append(code)
            return sorted(codes)
        codes = []
        seen = set()
        for part in (self.env.user.x_misa_saler_codes or '').split(','):
            code = part.strip()
            if code and code.upper() not in seen:
                seen.add(code.upper())
                codes.append(code)
        return sorted(codes)

    def _misa_invoice_saler_code_token(self, code):
        """Token dùng để đưa vào URL link riêng (/misa_sale_status?t=<token>) thay vì để mã
        sale ở dạng dễ đọc/dễ đoán (VD "NV001") ngay trên URL — CHỈ để tránh lộ/đoán được mã
        khi nhìn link, KHÔNG PHẢI cơ chế xác thực (xác thực THẬT vẫn luôn dựa vào session Odoo
        đang đăng nhập + x_misa_saler_codes, xem _misa_invoice_validate_public_saler_code —
        token này chỉ giúp resolve về đúng mã, không tự cấp thêm quyền gì). Băm nhẹ (sha256,
        cắt ngắn) với salt lấy từ database.uuid (secret sẵn có của Odoo, không cần lưu thêm
        bảng ánh xạ nào) — cùng 1 mã LUÔN ra cùng 1 token, để link cũ vẫn dùng lại được."""
        secret = self.env['ir.config_parameter'].sudo().get_param('database.uuid') or 'misa-invoice-status-report'
        raw = (code or '').strip().upper() + '|' + secret
        return hashlib.sha256(raw.encode('utf-8')).hexdigest()[:16]

    @api.model
    def get_misa_invoice_saler_code_registry_with_tokens(self):
        """Như get_misa_invoice_saler_code_registry() nhưng kèm token URL cho từng mã — dùng
        cho trang public /misa_sale_status (JS tự resolve ?t=<token> về đúng mã, và dựng link
        "Copy link" mà không hiện mã thật trên URL)."""
        return [
            {'code': code, 'token': self._misa_invoice_saler_code_token(code)}
            for code in self.get_misa_invoice_saler_code_registry()
        ]

    def _misa_invoice_validate_public_saler_code(self, saler_code):
        code = (saler_code or '').strip()
        if not code:
            raise UserError("Vui lòng chọn mã sale của bạn.")
        registry = {c.upper() for c in self.get_misa_invoice_saler_code_registry()}
        if code.upper() not in registry:
            raise UserError("Mã sale không hợp lệ, vui lòng chọn lại.")
        return code

    def _misa_invoice_public_multi_request_order_ids(self, base_domain):
        """Tìm các đơn bán 'xuất HĐ nhiều đợt' (>= 2 đề nghị/phiếu đại diện KHÁC NHAU cùng
        xuất HĐ cho 1 đơn) trong phạm vi base_domain — cùng logic multi_request của
        _misa_invoice_order_row (dashboard nội bộ), nhưng tính trên toàn bộ phiếu khớp
        base_domain thay vì theo trang đang xem, để lọc picking-level cho đúng."""
        Picking = self.sudo()
        pickings = Picking.search(base_domain)
        by_order = {}
        for picking in pickings:
            for order in picking.misa_invoice_sale_order_ids:
                by_order.setdefault(order.id, self.browse())
                by_order[order.id] |= picking
        multi_ids = []
        for order_id, order_pickings in by_order.items():
            invoiced = order_pickings.filtered(lambda p: p.misa_invoice_state == 'invoiced')
            representatives = {(p.misa_invoice_master_picking_id or p).id for p in invoiced}
            if len(representatives) > 1:
                multi_ids.append(order_id)
        return multi_ids

    def _misa_invoice_public_list_state_domain(self, state=False, states=None):
        """Domain phần trạng thái/ngoại lệ cho get_misa_invoice_public_list — tách riêng để
        export (export_misa_invoice_public_list_excel) tái dùng được ĐÚNG cùng 1 logic, không
        xây domain lệch với danh sách đang xem.

        states (list): multi-select mới (checkbox) — mỗi lựa chọn OR với nhau. 'exception' là
        ngoại lệ (bất kể misa_invoice_state); các key còn lại ('missing'/'requested'/
        'invoiced'/'not_checked') là ĐÚNG trạng thái đó VÀ chưa ngoại lệ (ngoại lệ chỉ hiện
        qua lựa chọn 'exception' riêng, không lẫn vào state khác — giữ đúng hành vi cũ).

        state (str): kiểu chọn 1 CŨ, vẫn giữ cho nơi gọi khác chưa đổi qua multi-select. Bỏ
        qua nếu states có giá trị."""
        states = [s for s in (states or []) if s]
        if states:
            sub_domains = []
            for key in states:
                if key == 'exception':
                    sub_domains.append([('misa_invoice_exception', '=', True)])
                else:
                    sub_domains.append([('misa_invoice_state', '=', key), ('misa_invoice_exception', '=', False)])
            return expression.OR(sub_domains)
        if state == 'exception':
            return [('misa_invoice_exception', '=', True)]
        if state in ('missing', 'requested', 'invoiced', 'not_checked'):
            return [('misa_invoice_state', '=', state), ('misa_invoice_exception', '=', False)]
        if state == 'all':
            return []
        return [('misa_invoice_state', '!=', 'invoiced'), ('misa_invoice_exception', '=', False)]

    @api.model
    def get_misa_invoice_public_list(
        self, saler_code, search=False, state=False, states=None, date_from=False, date_to=False,
        multi_order_group=False, multi_request=False, limit=50, offset=0,
    ):
        """Danh sách phiếu xuất kho của ĐÚNG 1 mã sale cho trang public, lọc thêm được theo
        khoảng NGÀY XUẤT KHO (date_from/date_to) và theo trạng thái cụ thể — xem
        _misa_invoice_public_list_state_domain cho ý nghĩa từng lựa chọn/kiểu 'states' multi-select.
        multi_order_group=True: chỉ phiếu thuộc nhóm gộp chung nhiều đơn bán (1 đề nghị HĐ
        cho >=2 đơn). multi_request=True: chỉ phiếu của đơn bán đã xuất HĐ qua >=2 đề nghị
        khác nhau (giao/xuất nhiều đợt) — 2 case khác nhau, xem field misa_invoice_multi_order_group.
        search theo cả tên phiếu LẪN tên đơn bán liên quan. counts (cho donut/badge) luôn tính
        trên TOÀN BỘ phạm vi ngày đang lọc, không bị ảnh hưởng bởi state/search hiện tại — để
        số liệu tổng quan luôn nhất quán dù đang xem tab nào."""
        Picking = self.sudo()
        code = self._misa_invoice_validate_public_saler_code(saler_code)
        base_domain = Picking._misa_invoice_dashboard_base_domain(date_from, date_to) + [
            ('misa_invoice_saler_code', '=', code),
        ]
        domain = list(base_domain) + Picking._misa_invoice_public_list_state_domain(state, states)
        if search:
            domain += [
                '|', '|', ('name', 'ilike', search), ('misa_invoice_sale_order_ids.name', 'ilike', search),
                ('misa_invoice_root_partner_id.display_name', 'ilike', search),
            ]
        if multi_order_group:
            domain.append(('misa_invoice_multi_order_group', '=', True))
        if multi_request:
            multi_request_order_ids = Picking._misa_invoice_public_multi_request_order_ids(base_domain)
            domain.append(('misa_invoice_sale_order_ids', 'in', multi_request_order_ids))

        total = Picking.search_count(domain)
        pickings = Picking.search(domain, order='date_done desc', limit=limit, offset=offset)
        today = fields.Date.context_today(self)

        state_groups = Picking.read_group(base_domain, ['id'], ['misa_invoice_state'])
        state_counts = {row['misa_invoice_state']: row['misa_invoice_state_count'] for row in state_groups}
        exception_count = Picking.search_count(base_domain + [('misa_invoice_exception', '=', True)])

        return {
            'rows': [Picking._misa_invoice_picking_to_row(p, today) for p in pickings],
            'total': total,
            'counts': {
                'missing': state_counts.get('missing', 0),
                'requested': state_counts.get('requested', 0),
                'invoiced': state_counts.get('invoiced', 0),
                'exception': exception_count,
            },
        }

    @api.model
    def get_misa_invoice_public_daily_stats(self, saler_code, date_from=False, date_to=False, weekly=False):
        """Số liệu 'theo ngày' (tiền xuất kho vs tiền đã xuất HĐ) cho trang public, scope theo
        đúng 1 mã sale — tái dùng thẳng get_misa_invoice_daily_stats (dashboard nội bộ) sau khi
        xác thực mã sale, tránh viết lại logic gộp theo ngày/tuần."""
        code = self._misa_invoice_validate_public_saler_code(saler_code)
        return self.sudo().get_misa_invoice_daily_stats(
            date_from=date_from, date_to=date_to, saler_code=code, weekly=weekly,
        )

    @api.model
    def get_misa_invoice_public_reconciliation_totals(self, saler_code, date_from=False, date_to=False):
        """Số liệu đối chiếu tổng (xem get_misa_invoice_reconciliation_totals) scope theo
        đúng 1 mã sale cho trang public."""
        code = self._misa_invoice_validate_public_saler_code(saler_code)
        return self.sudo().get_misa_invoice_reconciliation_totals(
            date_from=date_from, date_to=date_to, saler_code=code,
        )

    @api.model
    def action_public_check(self, picking_ids, saler_code):
        code = self._misa_invoice_validate_public_saler_code(saler_code)
        pickings = self.sudo().browse(picking_ids or []).exists().filtered(
            lambda p: p.misa_invoice_saler_code == code
        )
        if not pickings:
            return []
        return self._misa_invoice_check_batch(pickings)

    @api.model
    def action_public_mark_exception(self, picking_ids, saler_code, reason):
        code = self._misa_invoice_validate_public_saler_code(saler_code)
        reason = (reason or '').strip()
        if not reason:
            raise UserError("Vui lòng nhập lý do.")
        pickings = self.sudo().browse(picking_ids or []).exists().filtered(
            lambda p: p.misa_invoice_saler_code == code
        )
        if not pickings:
            raise UserError("Không tìm thấy phiếu phù hợp với mã sale của bạn.")
        pickings._misa_invoice_apply_exception(reason, source_note='trang public — mã sale %s' % code)
        return {'count': len(pickings)}

    @api.model
    def action_public_unmark_exception(self, picking_ids, saler_code):
        code = self._misa_invoice_validate_public_saler_code(saler_code)
        pickings = self.sudo().browse(picking_ids or []).exists().filtered(
            lambda p: p.misa_invoice_saler_code == code
        )
        if pickings:
            pickings.action_unmark_misa_invoice_exception()
        return {'count': len(pickings)}

    @api.model
    def action_public_manual_link(self, picking_id, saler_code, refno):
        code = self._misa_invoice_validate_public_saler_code(saler_code)
        picking = self.sudo().browse(picking_id).exists()
        if not picking or picking.misa_invoice_saler_code != code:
            raise UserError("Không tìm thấy phiếu phù hợp với mã sale của bạn.")
        return picking.action_apply_manual_invoice_link(refno, source_note='trang public — mã sale %s' % code)

    @api.model
    def get_misa_invoice_public_order_list(
        self, saler_code, search=False, state=False, partial_coverage_only=False, mismatch_only=False,
        states=None, date_from=False, date_to=False, limit=20, offset=0,
    ):
        """Danh sách ĐƠN BÁN (xem get_misa_invoice_order_list) scope theo đúng 1 mã sale cho
        trang public — tab 'Đơn hàng' của /misa_sale_status."""
        code = self._misa_invoice_validate_public_saler_code(saler_code)
        return self.sudo().get_misa_invoice_order_list(
            limit=limit, offset=offset, search=search, state=state, saler_code=code,
            partial_coverage_only=partial_coverage_only, mismatch_only=mismatch_only, states=states,
            date_from=date_from, date_to=date_to,
        )

    @api.model
    def get_misa_invoice_picking_row(self, picking_id):
        """Lấy dữ liệu 1 phiếu theo đúng format `_misa_invoice_picking_to_row` — dùng để mở
        drawer chi tiết từ 1 id (VD bấm vào link phiếu gốc/phiếu đi kèm trong drawer khác),
        thay vì phải điều hướng sang form Odoo."""
        picking = self.sudo().browse(picking_id)
        if not picking.exists():
            return False
        today = fields.Date.context_today(self)
        return self._misa_invoice_picking_to_row(picking, today)

    def _misa_invoice_picking_siblings(self, picking):
        """Các phiếu xuất kho KHÁC cùng (các) đơn bán liên quan tới phiếu này — dùng khi 1 đơn
        được giao/xuất kho NHIỀU ĐỢT (nhiều phiếu riêng biệt). Khác với
        misa_invoice_master_picking_id/covered (gộp theo 1 ĐỀ NGHỊ xuất HĐ trên MISA) — đây
        là gộp theo ĐƠN BÁN, để người xem thấy hết các đợt xuất khác của cùng đơn dù chúng
        không chung đề nghị xuất HĐ nào cả."""
        if not picking.misa_invoice_sale_order_ids:
            return []
        siblings = self.sudo().search([
            ('misa_invoice_sale_order_ids', 'in', picking.misa_invoice_sale_order_ids.ids),
            ('id', '!=', picking.id),
            ('picking_type_id.code', '=', 'outgoing'),
        ], order='date_done desc')
        return [
            {
                'id': s.id, 'name': s.name,
                'state': s.misa_invoice_state,
                'state_label': MISA_INVOICE_STATE_LABELS.get(s.misa_invoice_state, s.misa_invoice_state),
                'date_done': fields.Date.to_string(s.date_done.date()) if s.date_done else '',
            }
            for s in siblings
        ]

    @api.model
    def get_misa_invoice_picking_siblings(self, picking_id):
        picking = self.sudo().browse(picking_id)
        if not picking.exists():
            return []
        return self._misa_invoice_picking_siblings(picking)

    @api.model
    def get_misa_invoice_public_picking_row(self, picking_id, saler_code):
        code = self._misa_invoice_validate_public_saler_code(saler_code)
        picking = self.sudo().browse(picking_id).exists()
        if not picking or picking.misa_invoice_saler_code != code:
            return False
        today = fields.Date.context_today(self)
        return self._misa_invoice_picking_to_row(picking, today)

    @api.model
    def get_misa_invoice_public_picking_siblings(self, picking_id, saler_code):
        code = self._misa_invoice_validate_public_saler_code(saler_code)
        picking = self.sudo().browse(picking_id).exists()
        if not picking or picking.misa_invoice_saler_code != code:
            return []
        return self._misa_invoice_picking_siblings(picking)
