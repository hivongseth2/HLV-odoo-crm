# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import UserError
from odoo.osv import expression

from ..services.loyalty_misa_payment_utils import PAID_STATE_SELECTION

# API cho tab "Điểm đổi thưởng" trên trang /misa_sale_status: sale tự xác nhận (và — nếu bật
# trong Cài đặt — hủy / sửa / tính lại) điểm đổi thưởng đang chờ của CHÍNH đơn mình. Mọi hàm
# đều nhận saler_code và xác thực lại bằng đúng hàm của trang
# (stock.picking._misa_invoice_validate_public_saler_code): controller gọi bằng sudo, nên đây là
# chốt chặn duy nhất giữa sale này và điểm của sale khác.

# 2 công tắc trong Cài đặt > Khách hàng thân thiết. Tắt (mặc định) thì sale chỉ xác nhận được.
SALE_ALLOW_CANCEL_PARAM = 'hlv_loyalty_misa_payment.sale_allow_cancel'
SALE_ALLOW_EDIT_PARAM = 'hlv_loyalty_misa_payment.sale_allow_edit'

# Mỗi phiếu kho tốn 2-4 lệnh gọi MISA khi xác nhận — chặn số phiếu mỗi lần bấm để request không
# chạy quá thời gian chờ của Odoo.sh.
SALE_CONFIRM_MAX_PICKINGS = 20


class HlvLoyaltyHistorySaleConfirm(models.Model):
    _inherit = 'hlv.loyalty.history'

    @api.model
    def _sale_public_code(self, saler_code):
        """Mã sale đã xác thực quyền; False = "Tất cả" (chỉ nhóm Đối soát XHD)."""
        return self.env['stock.picking']._misa_invoice_validate_public_saler_code(saler_code)

    @api.model
    def _sale_public_domain(self, code):
        """Điểm đổi thưởng đang chờ xác nhận thuộc mã sale này.

        "Của sale nào" lấy theo mã sale MISA của phiếu kho (misa_invoice_saler_code, lấy từ đơn
        bán) — cùng cách mọi tab khác của trang chia phiếu cho sale, để sale thấy điểm của đúng
        những phiếu họ đang đối soát."""
        domain = [
            ('transaction_type', '=', 'earn'),
            ('point_type', '=', 'exchange'),
            ('state', '=', 'pending'),
            ('picking_id', '!=', False),
        ]
        if code:
            domain.append(('picking_id.misa_invoice_saler_code', '=ilike', code))
        return domain

    @api.model
    def _sale_public_options(self):
        params = self.env['ir.config_parameter'].sudo()
        return {
            'allow_cancel': bool(params.get_param(SALE_ALLOW_CANCEL_PARAM)),
            'allow_edit': bool(params.get_param(SALE_ALLOW_EDIT_PARAM)),
        }

    @api.model
    def _sale_public_records(self, saler_code, history_ids):
        """Các bản ghi được chọn, sau khi chắc chắn TẤT CẢ thuộc mã sale này và còn chờ xác nhận.

        Lệch dù 1 bản ghi là báo lỗi cả lượt chứ không lặng lẽ bỏ qua: hoặc trang đang hiện dữ
        liệu cũ (người khác vừa xử lý), hoặc có ai gửi id ngoài phạm vi — cả 2 đều phải biết."""
        ids = [int(history_id) for history_id in (history_ids or [])]
        if not ids:
            raise UserError('Chưa chọn điểm nào.')
        records = self.search(expression.AND([
            self._sale_public_domain(self._sale_public_code(saler_code)), [('id', 'in', ids)],
        ]))
        if len(records) != len(set(ids)):
            raise UserError(
                'Có điểm không còn chờ xác nhận hoặc không thuộc mã sale đang xem '
                '(có thể vừa được người khác xử lý) — bấm Làm mới rồi thử lại.'
            )
        return records

    @api.model
    def _sale_public_require(self, option, label):
        if not self._sale_public_options()[option]:
            raise UserError('Chức năng %s điểm trên trang sale đang tắt trong Cài đặt Loyalty.' % label)

    @staticmethod
    def _sale_public_search_domain(search):
        term = (search or '').strip()
        if not term:
            return []
        return expression.OR([
            [('partner_id.name', 'ilike', term)], [('account_id.display_name', 'ilike', term)],
            [('sale_order_id.name', 'ilike', term)], [('picking_id.name', 'ilike', term)],
            [('misa_invoice_no', 'ilike', term)],
        ])

    def _sale_public_row(self, paid_labels):
        self.ensure_one()
        return {
            'id': self.id,
            'date': fields.Datetime.context_timestamp(self, self.date).date().isoformat() if self.date else '',
            'partner': self.partner_id.name or '',
            'account': self.account_id.display_name or '',
            'order': self.sale_order_id.name or '',
            'picking': self.picking_id.name or '',
            'saler_code': self.picking_id.misa_invoice_saler_code or '',
            'points': self.point_amount,
            'description': self.description or '',
            'invoice_no': self.misa_invoice_no or '',
            'paid_state': self.misa_paid_state or '',
            'paid_label': paid_labels.get(self.misa_paid_state, 'Chưa tra'),
        }

    @api.model
    def get_sale_public_pending_points(self, saler_code, search=False, limit=50, offset=0):
        """Trang điểm chờ xác nhận của mã sale. Tình trạng thu tiền trong mỗi hàng chỉ là kết quả
        lần tra trước (để nhìn), lúc bấm xác nhận luôn tra lại MISA — xem action_sale_public_confirm."""
        domain = expression.AND([
            self._sale_public_domain(self._sale_public_code(saler_code)),
            self._sale_public_search_domain(search),
        ])
        records = self.search(domain, limit=limit, offset=offset, order='date desc, id desc')
        paid_labels = dict(PAID_STATE_SELECTION)
        totals = self._read_group(domain, [], ['__count', 'point_amount:sum'])[0]
        return {
            'rows': [record._sale_public_row(paid_labels) for record in records],
            'total': totals[0],
            'total_points': totals[1] or 0,
            **self._sale_public_options(),
        }

    @api.model
    def action_sale_public_check_paid(self, saler_code, history_id):
        """Tra lại MISA cho 1 dòng (nút "Tra MISA") — chỉ xem, không xác nhận gì."""
        record = self._sale_public_records(saler_code, [history_id])
        report = self.get_misa_payment_status(record.id)
        return {
            'paid_state': report.get('summary_state') or '',
            'label': report.get('error') or report.get('summary_label') or report.get('message') or '',
            'invoice_no': report.get('invoice_no') or '',
        }

    @api.model
    def action_sale_public_confirm(self, saler_code, history_ids):
        """Xác nhận các điểm đã chọn, CHỈ những điểm mà MISA báo đã thu đủ tiền ngay lúc bấm.

        Không tin misa_paid_state đã lưu (có thể là ảnh chụp từ hôm trước): sale tự duyệt điểm
        cho khách của mình nên điều kiện "đã thu tiền" phải là số liệu sống. Tra theo phiếu kho,
        không theo từng bản ghi — các tài khoản cùng phiếu dùng chung 1 hóa đơn, tra 1 lần là đủ.
        Phiếu chưa thu đủ / tra lỗi thì để nguyên, báo lý do; các phiếu khác vẫn được xác nhận.
        """
        records = self._sale_public_records(saler_code, history_ids)
        pickings = records.picking_id
        if len(pickings) > SALE_CONFIRM_MAX_PICKINGS:
            raise UserError(
                'Mỗi lần chỉ xác nhận tối đa %s phiếu kho (mỗi phiếu phải tra MISA) — đang chọn %s.'
                % (SALE_CONFIRM_MAX_PICKINGS, len(pickings))
            )

        to_confirm = self.browse()
        skipped = []
        for picking in pickings:
            group = records.filtered(lambda record: record.picking_id == picking)
            report = self.get_misa_payment_status(group[0].id)
            for other in group[1:]:
                other._misa_payment_store(report)
            if report.get('error') or report.get('summary_state') != 'paid':
                skipped.append({
                    'picking': picking.name,
                    'reason': report.get('error') or report.get('summary_label') or 'Chưa thu đủ tiền',
                })
                continue
            to_confirm |= group

        to_confirm.action_confirm()
        return {
            'confirmed': len(to_confirm),
            'confirmed_points': sum(to_confirm.mapped('point_amount')),
            'skipped': skipped,
        }

    def _sale_public_note(self, text):
        """Nối vết thao tác vào mô tả — model không có chatter (cùng cách _revoke_and_notify)."""
        for record in self:
            record.description = '%s [%s]' % (record.description or '', text)

    @staticmethod
    def _sale_public_reason(reason):
        reason = (reason or '').strip()
        if not reason:
            raise UserError('Vui lòng ghi lý do.')
        return reason

    @api.model
    def action_sale_public_cancel(self, saler_code, history_ids, reason):
        self._sale_public_require('allow_cancel', 'hủy')
        reason = self._sale_public_reason(reason)
        records = self._sale_public_records(saler_code, history_ids)
        records._sale_public_note('Hủy bởi %s trên trang sale: %s' % (self.env.user.name, reason))
        records.action_cancel()
        return {'cancelled': len(records)}

    @api.model
    def action_sale_public_edit(self, saler_code, history_id, point_amount, reason):
        self._sale_public_require('allow_edit', 'sửa')
        reason = self._sale_public_reason(reason)
        try:
            new_amount = int(point_amount)
        except (TypeError, ValueError):
            raise UserError('Số điểm phải là số nguyên.')
        if new_amount <= 0:
            raise UserError('Số điểm phải lớn hơn 0 — muốn bỏ hẳn thì dùng Hủy.')
        record = self._sale_public_records(saler_code, [history_id])
        old_amount = record.point_amount
        record._sale_public_note('Sửa %s → %s bởi %s trên trang sale: %s' % (
            old_amount, new_amount, self.env.user.name, reason,
        ))
        record.point_amount = new_amount
        return {'points': new_amount}

    @api.model
    def action_sale_public_recalculate(self, saler_code, history_id):
        """Tính lại theo đơn bán hiện tại (như nút "Tính lại điểm" ở backend) — cùng công tắc với
        Sửa vì cũng đổi số điểm."""
        self._sale_public_require('allow_edit', 'tính lại')
        record = self._sale_public_records(saler_code, [history_id])
        record.action_recalculate_points()
        return {'points': record.point_amount}
