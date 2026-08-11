import base64
import io
import json
import logging
from collections import defaultdict
from datetime import date, datetime, time as dt_time, timedelta

import xlsxwriter
from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError

_logger = logging.getLogger(__name__)

MISA_INVOICE_STATE_LABELS = {
    'not_checked': 'Chưa kiểm tra',
    'missing': 'Chưa có đề nghị xuất HĐ',
    'requested': 'Đã đề nghị, chờ HĐ',
    'invoiced': 'Đã xuất hóa đơn',
}

# Giới hạn số phiếu xử lý mỗi lần chạy cron, tránh gọi MISA API quá nhiều cùng lúc.
MISA_INVOICE_SCAN_BATCH_SIZE = 50

# Mốc ngày mặc định bắt đầu đối soát nếu chưa cấu hình (có thể đổi trên dashboard).
MISA_INVOICE_CUTOFF_PARAM = 'misa_invoice_status_report.cutoff_date'
MISA_INVOICE_CUTOFF_DEFAULT = '2026-05-01'
MISA_INVOICE_RECONCILE_GROUP = 'misa_invoice_status_report.group_misa_invoice_reconciliation'

# Sai số cho phép khi so tiền hóa đơn MISA với tiền thực xuất trên phiếu kho (làm tròn).
MISA_INVOICE_AMOUNT_TOLERANCE = 1.0

MISA_INVOICE_UNASSIGNED_SALER = 'Chưa gán mã sale'

# Số ngày nới rộng biên trước ngày xuất kho sớm nhất trong lô khi tải map đề nghị xuất HĐ —
# vì đề nghị/hóa đơn thường được lập TRỄ hơn ngày xuất kho (đúng lý do có báo cáo này).
MISA_INVOICE_MAP_LOOKBACK_DAYS = 60

MISA_ORDER_STATE_LABELS = {
    'not_checked': 'Chưa kiểm tra',
    'missing': 'Chưa có đề nghị xuất HĐ',
    'requested': 'Đã đề nghị, chờ HĐ',
    'partial': 'Một phần đã xuất HĐ',
    'invoiced': 'Đã xuất hóa đơn',
}

# Đơn Shopee dùng luồng hóa đơn điện tử "meInvoice" riêng của amis_callback (model
# meinvoice.invoice), không đi qua sa_invoice_request như MISA — trạng thái lấy thẳng từ
# field `state` của meinvoice.invoice (draft/submitted/rejected/accepted), + 'missing' tự
# thêm khi đơn Shopee chưa có bản ghi hóa đơn nào (hoặc tất cả đã bị hủy).
MISA_SHOPEE_INVOICE_STATE_LABELS = {
    'missing': 'Chưa có HĐĐT',
    'draft': 'Nháp, chưa phát hành',
    'submitted': 'Đã gửi, chờ CQT duyệt',
    'rejected': 'Bị từ chối',
    'accepted': 'Đã phát hành',
}


class StockPickingMisaInvoiceStatus(models.Model):
    _inherit = 'stock.picking'

    misa_invoice_state = fields.Selection(
        [
            ('not_checked', 'Chưa kiểm tra'),
            ('missing', 'Chưa có đề nghị xuất HĐ'),
            ('requested', 'Đã đề nghị, chờ HĐ'),
            ('invoiced', 'Đã xuất hóa đơn'),
        ],
        string='Tình trạng xuất HĐ MISA',
        default='not_checked',
        copy=False,
        index=True,
    )
    misa_invoice_last_checked = fields.Datetime(string='MISA kiểm tra lúc', copy=False)
    misa_invoice_request_refid = fields.Char(string='MISA Request RefID', copy=False)
    misa_invoice_no = fields.Char(string='Số hóa đơn MISA', copy=False)
    misa_invoice_date = fields.Date(string='Ngày hóa đơn MISA', copy=False)
    misa_invoice_amount = fields.Float(string='Tiền hóa đơn MISA', copy=False)

    # Đối soát tự động tra MISA bằng refno = TÊN PHIẾU. Nếu sale quên ghi đúng số phiếu xuất
    # kho lúc tạo đề nghị xuất HĐ trên MISA, MISA tự sinh 1 mã đề nghị khác (VD "DN00123")
    # không khớp tên phiếu — tự động sẽ không bao giờ tìm ra. Field này cho gắn tay đúng mã
    # đề nghị đó (qua wizard misa.invoice.manual.link.wizard), sau đó MỌI lần kiểm tra (thủ
    # công lẫn cron) sẽ ưu tiên tra theo mã này thay vì theo tên phiếu — xem
    # action_check_misa_invoice_status.
    misa_invoice_manual_refno = fields.Char(string='Mã đề nghị MISA (gắn tay)', copy=False)

    # MISA cho phép 1 "đề nghị xuất HĐ" (dùng refno của 1 phiếu làm đại diện) gộp chung cho
    # nhiều phiếu xuất kho khác, liệt kê trong journal_memo — các phiếu "ăn theo" đó KHÔNG tự
    # có đề nghị riêng. misa_invoice_master_picking_id trỏ NGƯỢC về phiếu đại diện (chỉ set ở
    # phiếu ăn theo); misa_invoice_covered_picking_ids là chiều ngược lại, tự có trên phiếu
    # đại diện nhờ Odoo suy ra từ field Many2one trên — không cần lưu thêm gì khác.
    misa_invoice_master_picking_id = fields.Many2one(
        'stock.picking', string='Phiếu xuất kho gốc (gộp chung đề nghị HĐ)', copy=False, index=True,
    )
    misa_invoice_covered_picking_ids = fields.One2many(
        'stock.picking', 'misa_invoice_master_picking_id',
        string='Các phiếu xuất kho đi kèm (gộp chung HĐ)',
    )
    # True nếu đề nghị/hóa đơn của NHÓM này (gốc + các phiếu ăn theo) gộp chung cho từ 2 đơn
    # bán trở lên — VD 1 đề nghị xuất HĐ gộp giao hàng của DH1 và DH2 làm 1. Dùng để lọc/audit
    # riêng case này, khác với case "1 đơn bán được xuất hóa đơn qua nhiều đề nghị khác nhau"
    # (xem get_misa_invoice_order_list's multi_request).
    misa_invoice_multi_order_group = fields.Boolean(
        string='Gộp chung nhiều đơn bán', compute='_compute_misa_invoice_multi_order_group', store=True,
    )
    # Tên TẤT CẢ đơn bán trong cả nhóm (gốc + các phiếu ăn theo) — không lưu (store=False) vì
    # chỉ để đọc hiển thị cho biết cụ thể gộp với đơn nào, không cần search/group theo field
    # này (đã có domain riêng qua misa_invoice_multi_order_group).
    misa_invoice_group_order_names = fields.Char(
        string='Đơn bán trong nhóm gộp', compute='_compute_misa_invoice_multi_order_group',
    )

    # 1 phiếu xuất kho có thể gộp nhiều đơn bán (MISA trả "order_code": "DH1, DH2"
    # cho cùng 1 refno), và 1 đơn bán có thể được xuất bởi nhiều phiếu (giao nhiều đợt)
    # => quan hệ nhiều-nhiều, không thể rút gọn về 1 đơn duy nhất.
    misa_invoice_sale_order_ids = fields.Many2many(
        'sale.order', 'misa_invoice_picking_sale_order_rel', 'picking_id', 'order_id',
        string='Đơn bán liên quan',
        compute='_compute_misa_invoice_sale_order_ids', store=True,
    )
    # Lấy từ sale.order.x_studio_misa_saler_code (field Studio, đã có sẵn trên hệ thống).
    misa_invoice_saler_code = fields.Char(
        string='Mã sale MISA', compute='_compute_misa_invoice_saler_code', store=True, index=True,
    )
    # So tiền hóa đơn MISA với tiền thực xuất trên phiếu (field Studio x_studio_tng_tin_sau_thu).
    misa_invoice_amount_diff = fields.Float(
        string='Chênh lệch tiền (Odoo - MISA)', compute='_compute_misa_invoice_amount_mismatch', store=True,
    )
    misa_invoice_amount_mismatch = fields.Boolean(
        string='Lệch tiền so với MISA', compute='_compute_misa_invoice_amount_mismatch', store=True,
    )

    misa_invoice_exception = fields.Boolean(string='Ngoại lệ (chấp nhận chờ xuất HĐ)', copy=False)
    misa_invoice_exception_reason = fields.Text(string='Lý do ngoại lệ', copy=False)
    misa_invoice_exception_by_id = fields.Many2one('res.users', string='Người đánh dấu', copy=False)
    misa_invoice_exception_date = fields.Datetime(string='Ngày đánh dấu', copy=False)

    # Đơn Shopee dùng luồng hóa đơn meInvoice riêng (amis_callback) — loại khỏi đối soát MISA này.
    misa_invoice_is_shopee = fields.Boolean(
        string='Thuộc đơn Shopee', compute='_compute_misa_invoice_is_shopee', store=True,
    )

    # Khách hàng ở cấp công ty gốc (commercial_partner_id của đơn bán) — dùng để thống kê/nhóm
    # "Theo khách hàng", tránh bị tách lẻ theo từng chi nhánh/địa chỉ giao hàng cụ thể.
    misa_invoice_root_partner_id = fields.Many2one(
        'res.partner', string='Khách hàng (công ty gốc)',
        compute='_compute_misa_invoice_root_partner_id', store=True,
    )

    @api.depends('move_ids_without_package.sale_line_id.order_id', 'origin', 'picking_type_id.code')
    def _compute_misa_invoice_sale_order_ids(self):
        SaleOrder = self.env['sale.order']
        for picking in self:
            # Chỉ gắn quan hệ với đơn bán ở PHIẾU XUẤT KHO CUỐI (outgoing) — kho dùng giao
            # hàng nhiều bước (pick/pack/out) thì các bước trung gian (pick, pack) cũng có
            # move trỏ về cùng sale_line_id, nếu không loại ra sẽ bị lẫn vào "phiếu liên
            # quan" của đơn bán dù chúng không phải phiếu xuất kho thật sự cần đối soát HĐ.
            if picking.picking_type_code != 'outgoing':
                picking.misa_invoice_sale_order_ids = False
                continue
            orders = picking.move_ids_without_package.mapped('sale_line_id.order_id')
            if not orders and picking.origin:
                names = [name.strip() for name in picking.origin.split(',') if name.strip()]
                if names:
                    orders = SaleOrder.search([('name', 'in', names)])
            picking.misa_invoice_sale_order_ids = orders

    @api.depends('misa_invoice_sale_order_ids.x_studio_misa_saler_code')
    def _compute_misa_invoice_saler_code(self):
        for picking in self:
            code = False
            for order in picking.misa_invoice_sale_order_ids:
                value = getattr(order, 'x_studio_misa_saler_code', False)
                if value:
                    code = value
                    break
            picking.misa_invoice_saler_code = code

    @api.depends('misa_invoice_sale_order_ids.shopee_order_ref')
    def _compute_misa_invoice_is_shopee(self):
        for picking in self:
            picking.misa_invoice_is_shopee = any(
                getattr(order, 'shopee_order_ref', False) for order in picking.misa_invoice_sale_order_ids
            )

    @api.depends(
        'misa_invoice_sale_order_ids.partner_id.commercial_partner_id',
        'partner_id.commercial_partner_id',
    )
    def _compute_misa_invoice_root_partner_id(self):
        for picking in self:
            order = picking.misa_invoice_sale_order_ids[:1]
            source_partner = order.partner_id if order else picking.partner_id
            picking.misa_invoice_root_partner_id = source_partner.commercial_partner_id

    @api.depends(
        'misa_invoice_sale_order_ids',
        'misa_invoice_master_picking_id.misa_invoice_sale_order_ids',
        'misa_invoice_covered_picking_ids.misa_invoice_sale_order_ids',
    )
    def _compute_misa_invoice_multi_order_group(self):
        for picking in self:
            group = picking.misa_invoice_master_picking_id or picking
            group_pickings = group | group.misa_invoice_covered_picking_ids
            orders = group_pickings.mapped('misa_invoice_sale_order_ids')
            picking.misa_invoice_multi_order_group = len(orders) > 1
            picking.misa_invoice_group_order_names = ', '.join(orders.mapped('name'))

    @api.depends(
        'misa_invoice_state', 'misa_invoice_amount', 'x_studio_tng_tin_sau_thu',
        'misa_invoice_master_picking_id', 'misa_invoice_covered_picking_ids.x_studio_tng_tin_sau_thu',
    )
    def _compute_misa_invoice_amount_mismatch(self):
        for picking in self:
            actual_amount = getattr(picking, 'x_studio_tng_tin_sau_thu', False) or 0.0
            if picking.misa_invoice_master_picking_id:
                # Phiếu "ăn theo" 1 đề nghị gộp chung — không tự so tiền ở đây (tiền hóa đơn
                # đầy đủ được lưu ở phiếu gốc), xem đối chiếu tại misa_invoice_master_picking_id.
                picking.misa_invoice_amount_diff = 0.0
                picking.misa_invoice_amount_mismatch = False
            elif picking.misa_invoice_state == 'invoiced' and (actual_amount or picking.misa_invoice_covered_picking_ids):
                # Nếu có phiếu đi kèm gộp chung đề nghị, so theo TỔNG tiền thực xuất của cả
                # nhóm với tiền hóa đơn (đã lưu đầy đủ ở phiếu gốc) — so từng phiếu riêng lẻ
                # với tổng tiền hóa đơn gộp sẽ luôn báo lệch sai.
                group_actual = actual_amount + sum(
                    picking.misa_invoice_covered_picking_ids.mapped('x_studio_tng_tin_sau_thu')
                )
                diff = group_actual - (picking.misa_invoice_amount or 0.0)
                picking.misa_invoice_amount_diff = diff
                picking.misa_invoice_amount_mismatch = abs(diff) > MISA_INVOICE_AMOUNT_TOLERANCE
            else:
                picking.misa_invoice_amount_diff = 0.0
                picking.misa_invoice_amount_mismatch = False

    def action_check_misa_invoice_status(self, request_map=None):
        """Gọi MISA kiểm tra tình trạng xuất hóa đơn cho các phiếu đang chọn.
        Dùng chung cho nút thủ công (form/list), cron quét định kỳ, và vòng lặp
        hiện tiến trình trên dashboard. Trả về kết quả từng phiếu để hiển thị ngay
        (không bắt buộc caller nào phải dùng).

        request_map=None: tra từng phiếu bằng 1 API call riêng (phù hợp kiểm tra lẻ 1 phiếu).
        request_map=<dict từ get_invoice_request_map()>: tra trong map đã tải sẵn — dùng khi
        kiểm tra theo lô, vừa đỡ gọi API lặp lại vừa xử lý được trường hợp 1 đề nghị xuất
        hóa đơn đại diện cho nhiều phiếu (xem _misa_invoice_check_batch)."""
        misa_utils = self.env['misa.api.utils']
        results = []
        # Phiếu gốc của 1 nhóm gộp chung có thể KHÔNG nằm trong lô đang kiểm tra này (VD chỉ
        # có phiếu "ăn theo" được chọn/lọt vào lô quét) — nếu không chủ động kiểm tra luôn nó
        # ở đây, phiếu gốc sẽ bị "treo" ở trạng thái cũ (thường là "missing") cho tới khi tự
        # nó lọt vào 1 lượt quét khác, gây ra nghịch lý "phiếu ăn theo đã xuất HĐ nhưng phiếu
        # gốc lại chưa" dù cùng 1 đề nghị.
        extra_masters_to_check = self.browse()
        # Tra theo mã đơn hàng chỉ là NGƯỜI DÙNG SUY LUẬN (order code không phải khóa join
        # đáng tin cậy như refno=tên phiếu) — nếu 1 đơn có NHIỀU phiếu xuất kho cùng "missing"
        # trong đợt kiểm tra này, chỉ cho phiếu ĐẦU TIÊN nhận đề nghị tìm được qua mã đơn đó,
        # tránh mỗi phiếu tưởng nhầm mình đã xuất HĐ full tiền của cùng 1 đề nghị (double-count).
        claimed_order_refnos = {}
        for picking in self:
            if picking.picking_type_code != 'outgoing':
                continue
            # Ưu tiên mã đề nghị gắn tay (nếu có) — xem misa_invoice_manual_refno.
            refno = picking.misa_invoice_manual_refno or picking.name
            try:
                if request_map is not None:
                    status = misa_utils.get_invoice_status_from_map(refno, request_map)
                else:
                    status = misa_utils.get_invoice_status_for_refno(refno)
            except Exception as e:
                _logger.exception(
                    "❌ [MISA INVOICE STATUS] Lỗi kiểm tra phiếu %s (refno=%s): %s", picking.name, refno, e
                )
                picking.message_post(
                    body=Markup("<b>Kiểm tra hóa đơn MISA thất bại:</b><br/>%s") % str(e)
                )
                results.append({'id': picking.id, 'name': picking.name, 'error': str(e)})
                continue

            # Tra theo tên phiếu không ra đề nghị nào — trước khi kết luận "chưa có đề nghị",
            # thử lại bằng mã ĐƠN HÀNG (DH...) liên quan: sale nhiều khi tạo đề nghị xuất HĐ
            # trên MISA bằng mã đơn thay vì mã phiếu xuất kho nội bộ. Bỏ qua bước này nếu đã
            # gắn mã đề nghị thủ công (người dùng đã xác định chính xác refno cần dùng).
            if status['state'] == 'missing' and not picking.misa_invoice_manual_refno:
                for order_name in picking.misa_invoice_sale_order_ids.mapped('name'):
                    if not order_name or order_name == refno or order_name in claimed_order_refnos:
                        continue
                    try:
                        if request_map is not None:
                            order_status = misa_utils.get_invoice_status_from_map(order_name, request_map)
                        else:
                            order_status = misa_utils.get_invoice_status_for_refno(order_name)
                    except Exception:
                        _logger.exception(
                            "❌ [MISA INVOICE STATUS] Lỗi thử lại theo mã đơn %s cho phiếu %s",
                            order_name, picking.name,
                        )
                        continue
                    if order_status['state'] != 'missing':
                        status = order_status
                        refno = order_name
                        claimed_order_refnos[order_name] = picking
                        break

            # MISA cho phép 1 đề nghị (refno của phiếu ĐẠI DIỆN) gộp chung nhiều phiếu khác
            # (liệt kê trong journal_memo) — nếu refno thật của đề nghị khác tên phiếu đang
            # kiểm tra, đây là phiếu "ăn theo": trỏ về phiếu gốc và KHÔNG lưu tiền hóa đơn ở
            # đây nữa (đã lưu đầy đủ ở phiếu gốc) để tránh cộng dồn trùng tiền trong dashboard.
            master_refno = status.get('master_refno')
            master_picking = self.browse()
            # So với refno vừa dùng để tra (không phải luôn là tên phiếu — có thể là mã đề
            # nghị gắn tay) — nếu trùng nghĩa là đề nghị này chính là của phiếu đang xét,
            # không cần tìm phiếu gốc nào khác.
            if master_refno and master_refno != refno:
                master_picking = self.sudo().search([('name', '=', master_refno)], limit=1)
                if (
                    master_picking and master_picking.id not in self._ids
                    and master_picking.misa_invoice_state != 'invoiced'
                ):
                    extra_masters_to_check |= master_picking

            vals = {
                'misa_invoice_state': status['state'],
                'misa_invoice_last_checked': fields.Datetime.now(),
                'misa_invoice_request_refid': status.get('request_refid') or False,
                'misa_invoice_no': status.get('invoice_no') or False,
                'misa_invoice_amount': 0.0 if master_picking else (status.get('invoice_amount') or 0.0),
                'misa_invoice_master_picking_id': master_picking.id if master_picking else False,
            }
            invoice_date = status.get('invoice_date')
            if invoice_date:
                try:
                    vals['misa_invoice_date'] = fields.Date.to_date(invoice_date)
                except Exception:
                    _logger.warning("Không parse được ngày hóa đơn MISA: %s", invoice_date)

            old_state = picking.misa_invoice_state
            old_master_id = picking.misa_invoice_master_picking_id.id
            picking.write(vals)

            if old_state != status['state']:
                picking.message_post(
                    body=Markup("<b>Tình trạng xuất hóa đơn MISA:</b> %s → %s") % (
                        MISA_INVOICE_STATE_LABELS.get(old_state, old_state),
                        MISA_INVOICE_STATE_LABELS.get(status['state'], status['state']),
                    )
                )
            if master_picking and old_master_id != master_picking.id:
                master_link = Markup('<a href="#" data-oe-model="stock.picking" data-oe-id="%d">%s</a>') % (
                    master_picking.id, master_picking.name
                )
                picking_link = Markup('<a href="#" data-oe-model="stock.picking" data-oe-id="%d">%s</a>') % (
                    picking.id, picking.name
                )
                picking.message_post(
                    body=Markup(
                        "<b>🔗 Xuất hóa đơn gộp chung:</b> đề nghị xuất HĐ của phiếu này nằm trong "
                        "phiếu gốc %s (xem chi tiết hóa đơn tại đó)."
                    ) % master_link
                )
                master_picking.message_post(
                    body=Markup(
                        "<b>🔗 Xuất hóa đơn gộp chung:</b> đề nghị xuất HĐ này gộp chung cho phiếu %s."
                    ) % picking_link
                )
            if picking.misa_invoice_amount_mismatch:
                picking.message_post(
                    body=Markup("<b>⚠️ Lệch tiền với MISA:</b> Odoo %.0f đ vs MISA %.0f đ (chênh %.0f đ)") % (
                        getattr(picking, 'x_studio_tng_tin_sau_thu', 0.0) or 0.0,
                        picking.misa_invoice_amount or 0.0,
                        picking.misa_invoice_amount_diff,
                    )
                )
            results.append({
                'id': picking.id,
                'name': picking.name,
                'state': picking.misa_invoice_state,
                'state_label': MISA_INVOICE_STATE_LABELS.get(picking.misa_invoice_state, picking.misa_invoice_state),
            })
        if extra_masters_to_check:
            results += extra_masters_to_check.action_check_misa_invoice_status(request_map=request_map)
        return results

    def action_mark_misa_invoice_exception(self):
        """Mở wizard nhập lý do — dùng chung cho nút trên form (1 phiếu), bulk action trên
        list (nhiều phiếu), và nút trên drawer dashboard (1 phiếu, gọi qua doAction).

        ⚠️ Action dict dựng tay: khi gọi qua nút form (type="object") hoặc ir.actions.server,
        Odoo tự nới đủ field còn thiếu trước khi đưa cho JS. Nhưng khi JS gọi thẳng qua
        orm.call() rồi đưa kết quả cho action.doAction(), KHÔNG có bước nới đó — thiếu
        "views" sẽ làm _preprocessAction() lỗi ngay (đã gặp y hệt ở
        get_misa_invoice_order_report_action). Nên trả đủ "views" ở đây luôn để an toàn cho
        mọi đường gọi."""
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'misa.invoice.exception.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'default_picking_ids': self.ids},
        }

    def _misa_invoice_apply_exception(self, reason, source_note=''):
        """Ghi nhận đánh dấu ngoại lệ — dùng chung cho wizard nội bộ
        (misa.invoice.exception.wizard) và hành động từ trang public /misa_sale_status.
        source_note: ghi chú thêm vào chatter (VD "trang public — mã sale NV001") để biết
        nguồn gốc thao tác khi không có res.users cụ thể để trỏ vào (public/anonymous)."""
        self.write({
            'misa_invoice_exception': True,
            'misa_invoice_exception_reason': reason,
            'misa_invoice_exception_by_id': self.env.user.id,
            'misa_invoice_exception_date': fields.Datetime.now(),
        })
        note_html = (Markup(" (%s)") % source_note) if source_note else ""
        for picking in self:
            picking.message_post(
                body=Markup("<b>Đã đánh dấu ngoại lệ xuất hóa đơn MISA%s.</b><br/>Lý do: %s")
                % (note_html, reason)
            )

    def action_unmark_misa_invoice_exception(self):
        self.write({
            'misa_invoice_exception': False,
            'misa_invoice_exception_reason': False,
            'misa_invoice_exception_by_id': False,
            'misa_invoice_exception_date': False,
        })
        self.message_post(body=Markup("Đã bỏ đánh dấu ngoại lệ xuất hóa đơn MISA."))
        return True

    def action_apply_manual_invoice_link(self, refno, source_note=''):
        """Gắn mã đề nghị MISA thủ công + kiểm tra lại theo mã đó ngay — dùng chung cho wizard
        nội bộ (misa.invoice.manual.link.wizard) và hành động từ trang public
        /misa_sale_status. Trả về dict kết quả kiểm tra (xem action_check_misa_invoice_status)
        thay vì raise khi MISA chưa xác nhận đã xuất HĐ — mã vẫn được lưu lại để lần kiểm tra
        sau (kể cả cron) tự dùng, caller tự quyết định có cảnh báo người dùng hay không."""
        self.ensure_one()
        refno = (refno or '').strip()
        if not refno:
            raise UserError("Vui lòng nhập mã đề nghị MISA.")
        self.misa_invoice_manual_refno = refno
        note_html = (Markup(" (%s)") % source_note) if source_note else ""
        self.message_post(
            body=Markup(
                "Đã gắn mã đề nghị MISA thủ công%s: <b>%s</b> (dùng khi refno tự sinh trên "
                "MISA không khớp tên phiếu)."
            ) % (note_html, refno)
        )
        results = self.action_check_misa_invoice_status()
        return results[0] if results else {}

    def action_open_misa_invoice_manual_link_wizard(self):
        """Mở wizard gắn mã đề nghị MISA thủ công cho 1 phiếu (nút form/list, hoặc gọi qua
        doAction từ drawer phiếu trên dashboard) — dùng khi sale quên ghi đúng số phiếu xuất
        kho lúc tạo đề nghị xuất HĐ trên MISA."""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'misa.invoice.manual.link.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {
                'default_picking_id': self.id,
                'allowed_picking_ids': self.ids,
            },
        }

    @api.model
    def action_mark_misa_invoice_exception_for_order(self, order_id):
        """Đánh dấu ngoại lệ cho TẤT CẢ phiếu xuất kho (đã done, chưa ngoại lệ) của 1 đơn
        bán — dùng từ drawer đơn hàng, gộp chung 1 lý do cho cả nhóm thay vì phải mở từng
        phiếu riêng lẻ."""
        order = self.env['sale.order'].sudo().browse(order_id)
        if not order.exists():
            return {'type': 'ir.actions.act_window_close'}
        pickings = order.misa_invoice_picking_ids.filtered(
            lambda p: p.state == 'done' and not p.misa_invoice_exception
        )
        if not pickings:
            return {'type': 'ir.actions.act_window_close'}
        return pickings.action_mark_misa_invoice_exception()

    @api.model
    def action_unmark_misa_invoice_exception_for_order(self, order_id):
        order = self.env['sale.order'].sudo().browse(order_id)
        if not order.exists():
            return 0
        pickings = order.misa_invoice_picking_ids.filtered(lambda p: p.misa_invoice_exception)
        if pickings:
            pickings.action_unmark_misa_invoice_exception()
        return len(pickings)

    @api.model
    def action_open_misa_invoice_manual_link_wizard_for_order(self, order_id):
        """Như action_open_misa_invoice_manual_link_wizard nhưng gọi từ drawer đơn hàng —
        chưa biết trước phiếu nào nên để trống picking_id, chỉ giới hạn lựa chọn trong các
        phiếu (đã done, chưa xuất HĐ) của đúng đơn hàng đang xem."""
        order = self.env['sale.order'].sudo().browse(order_id)
        picking_ids = order.misa_invoice_picking_ids.filtered(
            lambda p: p.picking_type_code == 'outgoing' and p.state == 'done'
            and p.misa_invoice_state != 'invoiced'
        ).ids
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'misa.invoice.manual.link.wizard',
            'view_mode': 'form',
            'views': [(False, 'form')],
            'target': 'new',
            'context': {'allowed_picking_ids': picking_ids},
        }

    @api.model
    def get_misa_invoice_can_configure(self):
        """Cờ quyền cho trang danh sách đơn hàng độc lập (misa_order_list_page.js) — dashboard
        chính đã có sẵn field này trong get_misa_invoice_dashboard_data, nhưng trang riêng
        không tải dữ liệu dashboard nên cần 1 endpoint nhẹ riêng."""
        return self.env.user.has_group(MISA_INVOICE_RECONCILE_GROUP)

    def _misa_invoice_scan_domain(self, date_from=False, date_to=False, include_invoiced=False):
        domain = self._misa_invoice_dashboard_base_domain(date_from, date_to) + [
            ('misa_invoice_exception', '=', False),
        ]
        if not include_invoiced:
            # Cron mặc định loại phiếu đã "Đã xuất HĐ" ra khỏi vòng quét định kỳ để giảm tần
            # suất gọi MISA — include_invoiced=True chỉ dùng cho nút quét thủ công khi cần
            # backfill lại (VD sau khi sửa logic ghép nhiều phiếu/1 đề nghị xuất hóa đơn).
            domain.append(('misa_invoice_state', '!=', 'invoiced'))
        return domain

    def _misa_invoice_check_batch(self, pickings):
        """Kiểm tra 1 lô phiếu bằng 1 map đề nghị xuất HĐ dùng chung (thay vì gọi API tìm
        đề nghị riêng cho từng phiếu) — vừa giảm số lệnh gọi MISA, vừa xử lý đúng trường hợp
        1 đề nghị đại diện xuất hóa đơn cho nhiều phiếu gộp chung (xem get_invoice_request_map)."""
        if not pickings:
            return []
        dates = [d for d in pickings.mapped('date_done') if d]
        date_from_iso = date_to_iso = False
        if dates:
            date_from = min(dates) - timedelta(days=MISA_INVOICE_MAP_LOOKBACK_DAYS)
            date_to = max(dates) + timedelta(days=1)
            date_from_iso = date_from.isoformat() + "Z"
            date_to_iso = date_to.isoformat() + "Z"

        misa_utils = self.env['misa.api.utils']
        try:
            request_map = misa_utils.get_invoice_request_map(date_from_iso, date_to_iso)
        except Exception:
            _logger.exception("❌ [MISA INVOICE STATUS BATCH] Lỗi tải map đề nghị xuất HĐ, quay lại tra từng phiếu")
            request_map = None
        return pickings.action_check_misa_invoice_status(request_map=request_map)

    @api.model
    def action_check_misa_invoice_status_batch(self, picking_ids):
        """Kiểm tra nhiều phiếu 1 lượt (map đề nghị xuất HĐ dùng chung) — gọi từ dashboard
        khi quét theo lô, thay vì 1 lệnh RPC/phiếu."""
        pickings = self.sudo().browse(picking_ids).exists()
        return self._misa_invoice_check_batch(pickings)

    @api.model
    def action_check_misa_invoice_order(self, order_id):
        """Kiểm tra MISA cho TẤT CẢ phiếu xuất kho (đã done) của 1 đơn bán — dùng khi người
        dùng chọn thẳng 1 đơn hàng cần đối chiếu ngay từ drawer, thay vì phải tìm/chọn từng
        phiếu xuất kho riêng lẻ."""
        order = self.env['sale.order'].sudo().browse(order_id)
        if not order.exists():
            return {'results': [], 'count': 0}
        pickings = order.misa_invoice_picking_ids.filtered(lambda p: p.state == 'done')
        if not pickings:
            return {'results': [], 'count': 0}
        results = self._misa_invoice_check_batch(pickings)
        return {'results': results, 'count': len(pickings)}

    def _cron_scan_misa_invoice_status(self):
        pickings = self.search(
            self._misa_invoice_scan_domain(),
            order='misa_invoice_last_checked asc nulls first',
            limit=MISA_INVOICE_SCAN_BATCH_SIZE,
        )
        try:
            self._misa_invoice_check_batch(pickings)
        except Exception:
            _logger.exception("❌ [MISA INVOICE STATUS CRON] Lỗi xử lý theo lô")

    @api.model
    def get_misa_invoice_scan_candidates(
        self, limit=MISA_INVOICE_SCAN_BATCH_SIZE, date_from=False, date_to=False, include_invoiced=False,
    ):
        """Danh sách phiếu SẼ được quét (chưa gọi MISA) — dùng để dashboard chạy
        từng phiếu một và hiện tiến trình thực (thay vì 1 lệnh lớn chạy âm thầm).

        Khi có date_from/date_to (đang xem theo 1 khoảng ngày xuất kho cụ thể), JS sẽ
        lặp gọi hàm này nhiều lần (mỗi lần 1 batch) cho tới khi quét hết `total` — nhờ
        vậy vẫn chia nhỏ từng lệnh gọi MISA nhưng làm trọn được cả khoảng đang cần gấp,
        thay vì luôn chỉ dừng ở 1 batch như khi không chọn khoảng ngày nào.

        include_invoiced=True: quét lại CẢ phiếu đã "Đã xuất HĐ" — chỉ để chủ động backfill
        1 lần (VD sau khi sửa logic ghép nhiều phiếu/1 đề nghị), không dùng cho quét thường
        ngày vì sẽ gọi MISA lại cho những phiếu vốn đã xong."""
        if include_invoiced and not self.env.user.has_group(MISA_INVOICE_RECONCILE_GROUP):
            raise AccessError(_("Bạn không có quyền quét lại phiếu đã xuất hóa đơn."))
        domain = self._misa_invoice_scan_domain(date_from, date_to, include_invoiced=include_invoiced)
        Picking = self.sudo()
        pickings = Picking.search(domain, order='misa_invoice_last_checked asc nulls first', limit=limit)
        return {
            'candidates': [{'id': picking.id, 'name': picking.name} for picking in pickings],
            'total': Picking.search_count(domain),
        }

    # ==================== Mốc ngày đối soát (cấu hình được) ====================

    def _get_misa_invoice_cutoff_date(self):
        raw = (self.env['ir.config_parameter'].sudo().get_param(MISA_INVOICE_CUTOFF_PARAM) or '').strip()
        for value in (raw, MISA_INVOICE_CUTOFF_DEFAULT):
            if not value:
                continue
            try:
                return fields.Date.from_string(value)
            except Exception:
                continue
        return fields.Date.from_string(MISA_INVOICE_CUTOFF_DEFAULT)

    @api.model
    def set_misa_invoice_cutoff_date(self, date_str):
        if not self.env.user.has_group(MISA_INVOICE_RECONCILE_GROUP):
            raise AccessError(_("Bạn không có quyền thay đổi mốc đối soát MISA."))
        try:
            parsed = fields.Date.from_string(date_str)
        except Exception:
            parsed = False
        if not parsed:
            raise UserError(_("Ngày không hợp lệ: %s") % date_str)
        self.env['ir.config_parameter'].sudo().set_param(
            MISA_INVOICE_CUTOFF_PARAM, fields.Date.to_string(parsed)
        )
        return self.get_misa_invoice_dashboard_data()

    # ==================== Dữ liệu cho Dashboard OWL ====================

    def _misa_invoice_dashboard_base_domain(
        self, date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False, shopee=False,
    ):
        """Domain nền cho mọi truy vấn đối soát: phiếu xuất kho đã done, từ mốc
        đối soát trở đi. date_from/date_to lọc theo NGÀY XUẤT KHO (date_done, có thể
        là 1 ngày cụ thể nếu from=to, hoặc 1 khoảng) — chỉ dùng để THU HẸP thêm, không
        bao giờ vượt ra ngoài mốc đối soát. invoice_date_from/to lọc theo NGÀY XUẤT
        HÓA ĐƠN (misa_invoice_date) — độc lập với ngày xuất kho.

        shopee=False (mặc định): phạm vi đối soát MISA (sa_invoice_request) như trước giờ —
        loại phiếu Shopee ra vì chúng dùng luồng hóa đơn điện tử meInvoice riêng, không đi qua
        MISA. shopee=True: đảo ngược lại — CHỈ lấy phiếu Shopee, dùng cho tab/đối soát riêng
        (xem _misa_invoice_shopee_domain) để tổng tiền xuất kho toàn hệ thống có thể cộng đủ
        cả 2 luồng lại (MISA + Shopee) mà không đếm trùng hay bỏ sót phiếu nào."""
        lower = self._get_misa_invoice_cutoff_date()
        if date_from:
            try:
                parsed_from = fields.Date.from_string(date_from)
            except Exception:
                parsed_from = False
            if parsed_from and parsed_from > lower:
                lower = parsed_from

        domain = [
            ('picking_type_id.code', '=', 'outgoing'),
            ('state', '=', 'done'),
            ('date_done', '>=', fields.Datetime.to_string(datetime.combine(lower, dt_time.min))),
            ('misa_invoice_is_shopee', '=', bool(shopee)),
            ('origin', 'not ilike', 'trả hàng'),
        ]
        if date_to:
            try:
                parsed_to = fields.Date.from_string(date_to)
            except Exception:
                parsed_to = False
            if parsed_to:
                domain.append(
                    ('date_done', '<=', fields.Datetime.to_string(datetime.combine(parsed_to, dt_time.max)))
                )
        if invoice_date_from:
            domain.append(('misa_invoice_date', '>=', invoice_date_from))
        if invoice_date_to:
            domain.append(('misa_invoice_date', '<=', invoice_date_to))
        return domain

    # ==================== Đơn Shopee (hóa đơn điện tử meInvoice riêng, amis_callback) ====================

    def _misa_invoice_shopee_domain(self, date_from=False, date_to=False):
        return self._misa_invoice_dashboard_base_domain(date_from, date_to, shopee=True)

    def _misa_invoice_shopee_representative_invoice(self, order):
        """1 đơn Shopee có thể có nhiều bản ghi meinvoice.invoice theo thời gian (nháp, hủy rồi
        tạo lại...) — lấy bản ĐÃ PHÁT HÀNH (accepted) mới nhất nếu có (đúng nghĩa hóa đơn hợp
        lệ cuối cùng đại diện cho đơn), không thì lấy bản chưa hủy mới nhất để biết đang ở
        bước nào. Bỏ qua hẳn các bản đã hủy (cancelled) — không phản ánh thực trạng hiện tại."""
        invoices = order.amis_draft_invoice_ids.filtered(lambda inv: inv.state != 'cancelled')
        if not invoices:
            return self.env['meinvoice.invoice'].browse()
        accepted = invoices.filtered(lambda inv: inv.state == 'accepted')
        if accepted:
            return accepted.sorted('write_date', reverse=True)[0]
        return invoices.sorted('write_date', reverse=True)[0]

    def _misa_invoice_shopee_picking_to_row(self, picking, today):
        orders = picking.misa_invoice_sale_order_ids
        invoice = self.env['meinvoice.invoice'].browse()
        for order in orders:
            candidate = self._misa_invoice_shopee_representative_invoice(order)
            if not candidate:
                continue
            if not invoice or candidate.state == 'accepted':
                invoice = candidate
            if invoice.state == 'accepted':
                break
        state = invoice.state if invoice else 'missing'
        done_date = picking.date_done.date() if picking.date_done else False
        return {
            'id': picking.id,
            'name': picking.name,
            'partner_name': picking.misa_invoice_root_partner_id.display_name or picking.partner_id.display_name or '',
            'sale_order_name': ', '.join(orders.mapped('name')),
            'saler_code': picking.misa_invoice_saler_code or '',
            'date_done': fields.Date.to_string(done_date) if done_date else '',
            'days_pending': (today - done_date).days if done_date else 0,
            'actual_amount': picking.x_studio_tng_tin_sau_thu or 0.0,
            'state': state,
            'state_label': MISA_SHOPEE_INVOICE_STATE_LABELS.get(state, state),
            'invoice_no': invoice.inv_no or False,
            'invoice_date': fields.Date.to_string(invoice.inv_date_result) if invoice and invoice.inv_date_result else False,
            'invoice_amount': (invoice.total_amount_oc or 0.0) if state == 'accepted' else 0.0,
        }

    def _misa_invoice_shopee_summary(self, domain):
        """Tổng hợp toàn bộ phiếu Shopee khớp domain — dùng cho cả tile tổng quan lẫn số liệu
        nền cho tab Đơn Shopee. Phải build từng dòng bằng Python (không read_group được) vì
        trạng thái/tiền HĐĐT nằm ở model meinvoice.invoice, không phải field trực tiếp trên
        stock.picking — chấp nhận được vì tập Shopee luôn là 1 phần nhỏ của tổng phiếu."""
        Picking = self.sudo()
        pickings = Picking.search(domain)
        today = fields.Date.context_today(self)
        rows = [Picking._misa_invoice_shopee_picking_to_row(p, today) for p in pickings]
        by_state = {key: {'count': 0, 'actual_amount': 0.0, 'invoice_amount': 0.0} for key in MISA_SHOPEE_INVOICE_STATE_LABELS}
        for row in rows:
            bucket = by_state[row['state']]
            bucket['count'] += 1
            bucket['actual_amount'] += row['actual_amount']
            bucket['invoice_amount'] += row['invoice_amount']
        return {
            'rows': rows,
            'by_state': by_state,
            'total_count': len(rows),
            'total_actual_amount': sum(r['actual_amount'] for r in rows),
            'total_invoice_amount': sum(r['invoice_amount'] for r in rows),
        }

    @api.model
    def get_misa_invoice_shopee_list(
        self, limit=20, offset=0, search=False, state=False, saler_code=False,
        date_from=False, date_to=False,
    ):
        """Tab 'Đơn Shopee' trên dashboard nội bộ — danh sách phiếu Shopee + tình trạng hóa
        đơn điện tử (meInvoice), lọc/phân trang bằng Python vì trạng thái tính từ model khác
        (xem _misa_invoice_shopee_summary)."""
        Picking = self.sudo()
        domain = Picking._misa_invoice_shopee_domain(date_from, date_to)
        if saler_code:
            value = False if saler_code == MISA_INVOICE_UNASSIGNED_SALER else saler_code
            domain.append(('misa_invoice_saler_code', '=', value))
        if search:
            domain += ['|', ('name', 'ilike', search), ('misa_invoice_sale_order_ids.name', 'ilike', search)]

        summary = Picking._misa_invoice_shopee_summary(domain)
        rows = summary['rows']
        if state:
            rows = [row for row in rows if row['state'] == state]
        rows.sort(key=lambda row: row['date_done'], reverse=True)
        total = len(rows)
        return {
            'rows': rows[offset:offset + limit],
            'total': total,
            'counts': {key: bucket['count'] for key, bucket in summary['by_state'].items()},
        }

    @api.model
    def get_misa_invoice_reconciliation_totals(self, date_from=False, date_to=False, saler_code=False):
        """Số liệu đối chiếu tổng: Tổng tiền xuất kho (MISA + Shopee gộp lại) = tiền đã xuất
        HĐ MISA + tiền đã xuất HĐ Shopee + tiền còn lại chưa xuất HĐ (ở luồng nào cũng tính) —
        dùng chung cho dashboard nội bộ VÀ trang public /misa_sale_status, để con số tổng luôn
        khớp giữa các mảnh thay vì mỗi nơi tính rời rạc ra kết quả lệch nhau."""
        Picking = self.sudo()
        misa_domain = Picking._misa_invoice_dashboard_base_domain(date_from, date_to)
        shopee_domain = Picking._misa_invoice_shopee_domain(date_from, date_to)
        if saler_code:
            value = False if saler_code == MISA_INVOICE_UNASSIGNED_SALER else saler_code
            misa_domain = misa_domain + [('misa_invoice_saler_code', '=', value)]
            shopee_domain = shopee_domain + [('misa_invoice_saler_code', '=', value)]

        misa_actual_group = Picking.read_group(misa_domain, ['x_studio_tng_tin_sau_thu:sum'], [])
        misa_actual_total = (misa_actual_group[0]['x_studio_tng_tin_sau_thu'] or 0.0) if misa_actual_group else 0.0
        misa_invoiced_group = Picking.read_group(
            misa_domain + [('misa_invoice_state', '=', 'invoiced')], ['misa_invoice_amount:sum'], [],
        )
        misa_invoiced_total = (misa_invoiced_group[0]['misa_invoice_amount'] or 0.0) if misa_invoiced_group else 0.0

        shopee_summary = Picking._misa_invoice_shopee_summary(shopee_domain)

        total_actual_amount = misa_actual_total + shopee_summary['total_actual_amount']
        total_invoiced_amount = misa_invoiced_total + shopee_summary['total_invoice_amount']

        return {
            'total_actual_amount': total_actual_amount,
            'misa_actual_amount': misa_actual_total,
            'misa_invoiced_amount': misa_invoiced_total,
            'shopee_actual_amount': shopee_summary['total_actual_amount'],
            'shopee_invoiced_amount': shopee_summary['total_invoice_amount'],
            'outstanding_amount': total_actual_amount - total_invoiced_amount,
        }

    # ==================== Đơn hải quan (hóa đơn xuất TRƯỚC khi xuất kho Odoo) ====================
    # Case đặc biệt: hàng hải quan phải xuất hóa đơn MISA TRƯỚC khi tạo/xác nhận phiếu xuất
    # kho Odoo — lúc đó chưa hề có refno picking nào để đối soát theo luồng thông thường
    # (sa_invoice_request). Giải pháp: cho nhập thẳng SỐ HÓA ĐƠN, tra theo chứng từ bán hàng
    # thật (sa_voucher_get) 1 lần để lấy toàn bộ dòng hàng (đơn hàng + mã hàng), rồi ghi nhận
    # lại — ở mức ĐƠN HÀNG + MÃ HÀNG (không phải cả đơn) vì 1 hóa đơn có thể chỉ phủ 1 PHẦN
    # đơn hàng (xuất kho từng phần).

    @api.model
    def fetch_misa_customs_invoice(self, inv_no):
        """Tra 1 hóa đơn MISA theo SỐ HÓA ĐƠN — trả về PREVIEW (chưa lưu) để người dùng xem
        lại (đơn hàng nào khớp được trong Odoo, đơn nào không) trước khi ghi nhận."""
        inv_no = (inv_no or '').strip()
        if not inv_no:
            raise UserError("Vui lòng nhập số hóa đơn.")
        misa_utils = self.env['misa.api.utils']
        voucher = misa_utils.get_voucher_by_inv_no(inv_no)
        if not voucher:
            raise UserError("Không tìm thấy hóa đơn số \"%s\" trên MISA." % inv_no)
        refid = voucher.get('refid')
        lines = misa_utils.get_voucher_lines(refid) if refid else []

        order_codes = sorted({(line.get('order_code') or '').strip() for line in lines if line.get('order_code')})
        orders = self.env['sale.order'].sudo().search([('name', 'in', order_codes)]) if order_codes else self.env['sale.order']
        orders_by_name = {order.name: order for order in orders}

        preview_lines = []
        for line in lines:
            order_code = (line.get('order_code') or '').strip()
            order = orders_by_name.get(order_code)
            preview_lines.append({
                'order_code': order_code,
                'sale_order_id': order.id if order else False,
                'sale_order_found': bool(order),
                'inventory_item_code': line.get('inventory_item_code') or '',
                'description': line.get('description') or '',
                'quantity': line.get('quantity') or 0.0,
                'unit_price': line.get('unit_price') or 0.0,
                'amount': line.get('amount_oc') or 0.0,
            })

        return {
            'invoice_no': voucher.get('inv_no') or inv_no,
            'invoice_refid': refid,
            'refno_finance': voucher.get('refno_finance') or '',
            'invoice_date': voucher.get('inv_date'),
            'partner_name': voucher.get('account_object_name') or '',
            'total_amount': voucher.get('total_amount') or 0.0,
            'lines': preview_lines,
        }

    @api.model
    def save_misa_customs_invoice(self, inv_no):
        """Ghi nhận (lưu) 1 hóa đơn hải quan — tự fetch lại MISA lần nữa (không tin dữ liệu
        preview gửi ngược từ client) để đảm bảo dữ liệu lưu luôn khớp với MISA ngay tại thời
        điểm lưu. Fetch lại cùng 1 số hóa đơn nhiều lần sẽ THAY THẾ hoàn toàn các dòng cũ
        (xóa rồi tạo lại) — coi như "đồng bộ lại", không cộng dồn trùng.

        Mỗi dòng vừa tạo được thử KHỚP NGAY với 1 phiếu xuất kho (nếu đã tồn tại và đã done)
        — nếu chưa có phiếu (hàng chưa xuất kho) hoặc phiếu chưa hoàn tất, dòng ở lại
        'pending' và cron định kỳ (_cron_scan_misa_customs_pending) sẽ tự thử lại sau,
        không cần thao tác gì thêm."""
        preview = self.fetch_misa_customs_invoice(inv_no)
        CustomsLine = self.env['misa.invoice.customs.line'].sudo()
        CustomsLine.search([('invoice_no', '=', preview['invoice_no'])]).unlink()

        invoice_date = False
        if preview['invoice_date']:
            try:
                invoice_date = fields.Date.to_date(preview['invoice_date'])
            except Exception:
                invoice_date = False

        created = CustomsLine.browse()
        for line in preview['lines']:
            created |= CustomsLine.create({
                'invoice_no': preview['invoice_no'],
                'invoice_refid': preview['invoice_refid'],
                'refno_finance': preview.get('refno_finance') or '',
                'invoice_date': invoice_date,
                'partner_name': preview['partner_name'],
                'sale_order_id': line['sale_order_id'] or False,
                'order_code': line['order_code'],
                'inventory_item_code': line['inventory_item_code'],
                'description': line['description'],
                'quantity': line['quantity'],
                'unit_price': line['unit_price'],
                'amount': line['amount'],
                'fetched_by_id': self.env.user.id,
                'fetched_at': fields.Datetime.now(),
            })
        matched_count = 0
        for line in created:
            if self._misa_invoice_customs_try_match(line):
                matched_count += 1
        return {'count': len(created), 'matched_count': matched_count, 'invoice_no': preview['invoice_no']}

    def _misa_invoice_customs_try_match(self, line):
        """Thử tìm 1 phiếu xuất kho (đã done) khớp ĐÚNG đơn bán + mã hàng + số lượng của dòng
        hải quan này — nếu tìm được, gán luôn và ghi nhận phiếu đó "đã xuất hóa đơn" (đúng
        tinh thần: hóa đơn có trước, xuất kho Odoo xác nhận sau). Số lượng phải khớp gần đúng
        (sai số 0.01) vì có thể xuất kho nhiều đợt cho cùng đơn/mã hàng — chỉ nhận phiếu mà
        tổng SL xuất của đúng mã hàng đó khớp với SL trên hóa đơn, tránh gán nhầm phiếu khác
        đợt của cùng đơn."""
        line.ensure_one()
        if line.match_state == 'matched':
            return True
        if not line.sale_order_id or not line.inventory_item_code:
            return False
        product = self.env['product.product'].sudo().search(
            [('default_code', '=', line.inventory_item_code)], limit=1,
        )
        if not product:
            return False
        moves = self.env['stock.move'].sudo().search([
            ('sale_line_id.order_id', '=', line.sale_order_id.id),
            ('product_id', '=', product.id),
            ('picking_id.picking_type_id.code', '=', 'outgoing'),
            ('picking_id.state', '=', 'done'),
        ])
        if not moves:
            return False
        qty_by_picking = {}
        for move in moves:
            qty_by_picking[move.picking_id] = qty_by_picking.get(move.picking_id, 0.0) + move.quantity
        best_picking, best_diff = None, None
        for picking, qty in qty_by_picking.items():
            diff = abs(qty - line.quantity)
            if best_diff is None or diff < best_diff:
                best_diff, best_picking = diff, picking
        if not best_picking or best_diff > 0.01:
            return False
        line.write({
            'picking_id': best_picking.id,
            'match_state': 'matched',
            'matched_at': fields.Datetime.now(),
        })
        self._misa_invoice_customs_apply_to_picking(best_picking)
        return True

    def _misa_invoice_customs_apply_to_picking(self, picking):
        """Khi 1 phiếu xuất kho có >=1 dòng hải quan đã khớp — ghi nhận phiếu đó 'đã xuất HĐ'
        (nếu chưa từng ghi nhận qua luồng nào khác), lấy số HĐ/ngày HĐ từ dòng hải quan, tiền
        = tổng các dòng hải quan khớp với phiếu này (không phải tổng cả hóa đơn, vì 1 hóa đơn
        có thể gộp nhiều đơn/nhiều phiếu khác nhau)."""
        if picking.misa_invoice_state == 'invoiced':
            return
        lines = self.env['misa.invoice.customs.line'].sudo().search([('picking_id', '=', picking.id)])
        if not lines:
            return
        old_state = picking.misa_invoice_state
        picking.write({
            'misa_invoice_state': 'invoiced',
            'misa_invoice_no': lines[0].invoice_no,
            'misa_invoice_date': lines[0].invoice_date,
            'misa_invoice_amount': sum(lines.mapped('amount')),
            'misa_invoice_last_checked': fields.Datetime.now(),
        })
        picking.message_post(
            body=Markup(
                "<b>Đã ghi nhận xuất hóa đơn (hải quan — hóa đơn xuất trước xuất kho):</b> "
                "%s → %s, số hóa đơn %s."
            ) % (
                MISA_INVOICE_STATE_LABELS.get(old_state, old_state),
                MISA_INVOICE_STATE_LABELS.get('invoiced', 'invoiced'),
                lines[0].invoice_no,
            )
        )

    def _cron_scan_misa_customs_pending(self):
        """Quét định kỳ các dòng hải quan còn 'pending' (chưa có phiếu xuất kho tương ứng
        hoặc phiếu chưa hoàn tất lúc ghi nhận) — tự thử khớp lại, không cần thao tác thủ công
        khi phiếu xuất kho được tạo/hoàn tất sau đó."""
        pending = self.env['misa.invoice.customs.line'].sudo().search(
            [('match_state', '=', 'pending')], limit=200,
        )
        for line in pending:
            try:
                self._misa_invoice_customs_try_match(line)
            except Exception:
                _logger.exception(
                    "❌ [MISA CUSTOMS SCAN] Lỗi thử khớp dòng hải quan #%s (HĐ %s)", line.id, line.invoice_no,
                )

    @api.model
    def get_misa_customs_lines(self, search=False, pending_only=False, limit=50, offset=0):
        Lines = self.env['misa.invoice.customs.line'].sudo()
        domain = []
        if search:
            domain += [
                '|', '|', ('invoice_no', 'ilike', search),
                ('order_code', 'ilike', search), ('inventory_item_code', 'ilike', search),
            ]
        if pending_only:
            domain.append(('match_state', '=', 'pending'))
        lines = Lines.search(domain, limit=limit, offset=offset)
        return {
            'rows': [
                {
                    'id': line.id,
                    'invoice_no': line.invoice_no,
                    'refno_finance': line.refno_finance or '',
                    'invoice_date': fields.Date.to_string(line.invoice_date) if line.invoice_date else '',
                    'partner_name': line.partner_name or '',
                    'order_code': line.order_code,
                    'sale_order_id': line.sale_order_id.id if line.sale_order_id else False,
                    'sale_order_name': line.sale_order_id.name if line.sale_order_id else line.order_code,
                    'sale_order_found': bool(line.sale_order_id),
                    'inventory_item_code': line.inventory_item_code,
                    'description': line.description or '',
                    'quantity': line.quantity,
                    'unit_price': line.unit_price,
                    'amount': line.amount,
                    'match_state': line.match_state,
                    'match_state_label': 'Đã khớp phiếu xuất kho' if line.match_state == 'matched' else 'Chờ xuất kho',
                    'picking_id': line.picking_id.id if line.picking_id else False,
                    'picking_name': line.picking_id.name if line.picking_id else False,
                    'fetched_by': line.fetched_by_id.name or '',
                    'fetched_at': fields.Datetime.to_string(line.fetched_at) if line.fetched_at else '',
                }
                for line in lines
            ],
            'total': Lines.search_count(domain),
            'pending_count': Lines.search_count([('match_state', '=', 'pending')]),
        }

    @api.model
    def delete_misa_customs_invoice(self, inv_no):
        inv_no = (inv_no or '').strip()
        if not inv_no:
            return 0
        lines = self.env['misa.invoice.customs.line'].sudo().search([('invoice_no', '=', inv_no)])
        count = len(lines)
        lines.unlink()
        return count

    def _misa_invoice_state_breakdown(self, domain):
        Picking = self.sudo()
        return {
            'missing': Picking.search_count(
                domain + [('misa_invoice_state', '=', 'missing'), ('misa_invoice_exception', '=', False)]
            ),
            'requested': Picking.search_count(
                domain + [('misa_invoice_state', '=', 'requested'), ('misa_invoice_exception', '=', False)]
            ),
            'invoiced': Picking.search_count(domain + [('misa_invoice_state', '=', 'invoiced')]),
            'exception': Picking.search_count(domain + [('misa_invoice_exception', '=', True)]),
        }

    def _misa_invoice_amount_sums(self, pickings):
        invoiced = pickings.filtered(lambda p: p.misa_invoice_state == 'invoiced')
        not_invoiced = pickings - invoiced
        return {
            'actual_amount_total': sum(pickings.mapped('x_studio_tng_tin_sau_thu')),
            'invoice_amount_total': sum(invoiced.mapped('misa_invoice_amount')),
            'outstanding_amount_total': sum(not_invoiced.mapped('x_studio_tng_tin_sau_thu')),
        }

    def _misa_invoice_grouped_breakdown(self, domain, groupby_field):
        """Như _misa_invoice_amount_sums() + _misa_invoice_state_breakdown() nhưng cho TẤT
        CẢ các nhóm của 1 field (VD từng nhân viên sale, từng khách hàng) cùng lúc, bằng ĐÚNG
        1 lệnh read_group (SQL GROUP BY) — thay vì lặp N truy vấn (search + 4 search_count +
        vài mapped) cho từng nhóm. Bắt buộc phải làm vậy vì số nhóm (đặc biệt là khách hàng)
        có thể lên tới hàng trăm/nghìn khi phạm vi lọc có hàng nghìn phiếu, N+1 query ở đây
        mới chính là nguyên nhân dashboard lag chứ không phải do thiếu phân trang.

        Trả về dict {group_key: {total, missing, requested, invoiced, exception,
        actual_amount_total, invoice_amount_total, outstanding_amount_total}} — group_key là
        id (Many2one), giá trị field (Char), hoặc False cho nhóm rỗng."""
        Picking = self.sudo()
        groups = defaultdict(lambda: {
            'total': 0, 'missing': 0, 'requested': 0, 'invoiced': 0, 'exception': 0,
            'actual_amount_total': 0.0, 'invoice_amount_total': 0.0, 'outstanding_amount_total': 0.0,
        })
        rows = Picking.read_group(
            domain,
            ['x_studio_tng_tin_sau_thu:sum', 'misa_invoice_amount:sum'],
            [groupby_field, 'misa_invoice_state', 'misa_invoice_exception'],
            lazy=False,
        )
        for row in rows:
            key = row[groupby_field]
            key = key[0] if isinstance(key, tuple) else key
            count = row['__count']
            state = row['misa_invoice_state']
            exception = row['misa_invoice_exception']
            actual_sum = row['x_studio_tng_tin_sau_thu'] or 0.0
            invoice_sum = row['misa_invoice_amount'] or 0.0

            bucket = groups[key]
            bucket['total'] += count
            bucket['actual_amount_total'] += actual_sum
            if state == 'invoiced':
                bucket['invoiced'] += count
                bucket['invoice_amount_total'] += invoice_sum
            else:
                bucket['outstanding_amount_total'] += actual_sum
                if not exception:
                    if state == 'missing':
                        bucket['missing'] += count
                    elif state == 'requested':
                        bucket['requested'] += count
            if exception:
                bucket['exception'] += count
        return groups

    @api.model
    def get_misa_invoice_dashboard_data(
        self, date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
    ):
        """Số liệu tổng quan cho dashboard OWL (KPI tiles + bảng theo kho/sale/khách hàng)."""
        Picking = self.sudo()
        base_domain = self._misa_invoice_dashboard_base_domain(
            date_from, date_to, invoice_date_from, invoice_date_to
        )

        counts = {}
        for state in MISA_INVOICE_STATE_LABELS:
            counts[state] = Picking.search_count(
                base_domain + [('misa_invoice_state', '=', state), ('misa_invoice_exception', '=', False)]
            )
        exception_count = Picking.search_count(base_domain + [('misa_invoice_exception', '=', True)])
        mismatch_count = Picking.search_count(base_domain + [('misa_invoice_amount_mismatch', '=', True)])
        total = sum(counts.values()) + exception_count

        invoiced_sum = Picking.read_group(
            base_domain + [('misa_invoice_state', '=', 'invoiced')], ['misa_invoice_amount:sum'], [],
        )
        invoiced_amount = (invoiced_sum[0]['misa_invoice_amount'] or 0.0) if invoiced_sum else 0.0

        by_warehouse = []
        warehouses = self.env['stock.warehouse'].sudo().search([])
        for wh in warehouses:
            wh_domain = base_domain + [('picking_type_id.warehouse_id', '=', wh.id)]
            wh_pickings = Picking.search(wh_domain)
            if not wh_pickings:
                continue
            row = self._misa_invoice_state_breakdown(wh_domain)
            row.update({
                'warehouse_id': wh.id, 'warehouse_name': wh.name, 'total': len(wh_pickings),
                'pending': row['missing'] + row['requested'],
            })
            row.update(self._misa_invoice_amount_sums(wh_pickings))
            by_warehouse.append(row)
        by_warehouse.sort(key=lambda row: row['missing'], reverse=True)

        by_saler = []
        saler_groups = Picking.read_group(base_domain, ['id'], ['misa_invoice_saler_code'])
        saler_stats = self._misa_invoice_grouped_breakdown(base_domain, 'misa_invoice_saler_code')
        for grp in saler_groups:
            stats = saler_stats[grp['misa_invoice_saler_code']]
            row = {
                'missing': stats['missing'],
                'requested': stats['requested'],
                'invoiced': stats['invoiced'],
                'exception': stats['exception'],
                'saler_code': grp['misa_invoice_saler_code'] or MISA_INVOICE_UNASSIGNED_SALER,
                'total': grp['misa_invoice_saler_code_count'],
                'pending': stats['missing'] + stats['requested'],
                'actual_amount_total': stats['actual_amount_total'],
                'invoice_amount_total': stats['invoice_amount_total'],
                'outstanding_amount_total': stats['outstanding_amount_total'],
            }
            # % hoàn thành = SỐ LƯỢNG phiếu đã xuất HĐ / tổng số phiếu (không so theo tiền —
            # 2 số tiền đến từ 2 hệ thống khác nhau, tổng có thể lệch nên tỷ lệ theo tiền
            # từng cho ra > 100%, không phản ánh đúng "hoàn thành bao nhiêu %").
            row['completion_pct'] = round(row['invoiced'] / row['total'] * 100, 1) if row['total'] else 0.0
            by_saler.append(row)
        by_saler.sort(key=lambda row: row['completion_pct'], reverse=True)
        for idx, row in enumerate(by_saler, start=1):
            row['rank'] = idx

        # Nhóm theo công ty gốc (misa_invoice_root_partner_id), không theo địa chỉ/chi
        # nhánh cụ thể trên từng phiếu — tránh 1 khách hàng bị tách thành nhiều dòng.
        by_customer = []
        customer_groups = Picking.read_group(base_domain, ['id'], ['misa_invoice_root_partner_id'])
        customer_stats = self._misa_invoice_grouped_breakdown(base_domain, 'misa_invoice_root_partner_id')
        for grp in customer_groups:
            partner = grp['misa_invoice_root_partner_id']  # False, hoặc (id, display_name)
            partner_id = partner[0] if partner else False
            stats = customer_stats[partner_id]
            by_customer.append({
                'missing': stats['missing'],
                'requested': stats['requested'],
                'invoiced': stats['invoiced'],
                'exception': stats['exception'],
                'partner_id': partner_id,
                'partner_name': partner[1] if partner else 'Chưa có khách hàng',
                'total': grp['misa_invoice_root_partner_id_count'],
                'pending': stats['missing'] + stats['requested'],
                'actual_amount_total': stats['actual_amount_total'],
                'invoice_amount_total': stats['invoice_amount_total'],
                'outstanding_amount_total': stats['outstanding_amount_total'],
            })
        by_customer.sort(key=lambda row: row['pending'], reverse=True)

        cron = self.env.ref('misa_invoice_status_report.ir_cron_misa_invoice_status_scan', raise_if_not_found=False)
        last_scan_at = False
        if cron and cron.sudo().lastcall:
            last_scan_at = fields.Datetime.to_string(cron.sudo().lastcall)

        return {
            'counts': counts,
            'exception_count': exception_count,
            'mismatch_count': mismatch_count,
            'total': total,
            'invoiced_amount': invoiced_amount,
            'by_warehouse': by_warehouse,
            'by_saler': by_saler,
            'by_customer': by_customer,
            'last_scan_at': last_scan_at,
            'cutoff_date': fields.Date.to_string(self._get_misa_invoice_cutoff_date()),
            'can_configure': self.env.user.has_group(MISA_INVOICE_RECONCILE_GROUP),
        }

    @api.model
    def get_misa_invoice_status_summary(
        self, date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
    ):
        """Bảng 'Tình trạng xuất hóa đơn': đúng 4 trạng thái đối soát đã dùng xuyên suốt
        dashboard (Chưa kiểm tra / Chưa có đề nghị / Đã đề nghị chờ HĐ / Đã xuất HĐ) + Ngoại lệ
        + Đơn Shopee (luồng hóa đơn điện tử meInvoice riêng), kèm số phiếu / tổng tiền XK /
        tổng tiền đã xuất HĐ / tỷ lệ phiếu. Dòng Shopee được CỘNG VÀO dòng TỔNG CỘNG để tổng
        tiền xuất kho/đã xuất HĐ phản ánh đúng TOÀN BỘ hệ thống (MISA + Shopee), không chỉ
        riêng phần MISA — đây là điểm mấu chốt để 2 số cộng lại luôn khớp với tổng."""
        # Gộp bằng 1 lệnh read_group (SQL GROUP BY) thay vì search() cả nghìn phiếu rồi
        # filtered()/mapped() nhiều lần trong Python — tránh tải cả recordset lớn vào bộ nhớ.
        Picking = self.sudo()
        domain = self._misa_invoice_dashboard_base_domain(
            date_from, date_to, invoice_date_from, invoice_date_to
        )
        rows = {state: {'count': 0, 'actual_amount': 0.0, 'invoice_amount': 0.0} for state in MISA_INVOICE_STATE_LABELS}
        rows['exception'] = {'count': 0, 'actual_amount': 0.0, 'invoice_amount': 0.0}
        rows['total'] = {'count': 0, 'actual_amount': 0.0, 'invoice_amount': 0.0}

        grouped = Picking.read_group(
            domain,
            ['x_studio_tng_tin_sau_thu:sum', 'misa_invoice_amount:sum'],
            ['misa_invoice_state', 'misa_invoice_exception'],
            lazy=False,
        )
        for grp in grouped:
            count = grp['__count']
            state = grp['misa_invoice_state']
            exception = grp['misa_invoice_exception']
            actual_sum = grp['x_studio_tng_tin_sau_thu'] or 0.0
            invoice_sum = grp['misa_invoice_amount'] or 0.0

            rows['total']['count'] += count
            rows['total']['actual_amount'] += actual_sum
            if state == 'invoiced':
                rows['total']['invoice_amount'] += invoice_sum

            if exception:
                rows['exception']['count'] += count
                rows['exception']['actual_amount'] += actual_sum
                if state == 'invoiced':
                    rows['exception']['invoice_amount'] += invoice_sum
            elif state in rows:
                rows[state]['count'] += count
                rows[state]['actual_amount'] += actual_sum
                if state == 'invoiced':
                    rows[state]['invoice_amount'] += invoice_sum

        shopee_domain = Picking._misa_invoice_shopee_domain(date_from, date_to)
        shopee_summary = Picking._misa_invoice_shopee_summary(shopee_domain)
        rows['shopee'] = {
            'count': shopee_summary['total_count'],
            'actual_amount': shopee_summary['total_actual_amount'],
            'invoice_amount': shopee_summary['total_invoice_amount'],
        }
        rows['total']['count'] += rows['shopee']['count']
        rows['total']['actual_amount'] += rows['shopee']['actual_amount']
        rows['total']['invoice_amount'] += rows['shopee']['invoice_amount']

        total_count = rows['total']['count'] or 1
        for row in rows.values():
            row['percentage'] = round(row['count'] / total_count * 100, 1)
        return rows

    @api.model
    def get_misa_invoice_daily_stats(
        self, date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
        saler_code=False, weekly=False,
    ):
        """Bảng 'Theo ngày': tổng tiền xuất kho vs tổng tiền đã xuất HĐ, theo từng ngày (hoặc
        từng tuần nếu weekly=True) trong phạm vi lọc, lọc thêm được theo 1 nhân viên sale.
        Gộp bằng Python (không dùng read_group theo granularity ngày/tuần) để tránh phụ
        thuộc định dạng nhãn ngày theo locale của Odoo, đảm bảo sort/hiển thị ổn định."""
        Picking = self.sudo()
        domain = self._misa_invoice_dashboard_base_domain(
            date_from, date_to, invoice_date_from, invoice_date_to
        )
        if saler_code:
            value = False if saler_code == MISA_INVOICE_UNASSIGNED_SALER else saler_code
            domain.append(('misa_invoice_saler_code', '=', value))

        pickings = Picking.search(domain)
        buckets = {}
        for picking in pickings:
            if not picking.date_done:
                continue
            day = picking.date_done.date()
            if weekly:
                iso_year, iso_week, _iso_weekday = day.isocalendar()
                key = (iso_year, iso_week)
                label = "Tuần %s/%s" % (iso_week, iso_year)
                week_start = date.fromisocalendar(iso_year, iso_week, 1)
                bucket_date_from = fields.Date.to_string(week_start)
                bucket_date_to = fields.Date.to_string(week_start + timedelta(days=6))
            else:
                key = day
                label = fields.Date.to_string(day)
                bucket_date_from = bucket_date_to = label
            bucket = buckets.setdefault(key, {
                'label': label, 'actual_amount': 0.0, 'invoice_amount': 0.0,
                'date_from': bucket_date_from, 'date_to': bucket_date_to,
            })
            bucket['actual_amount'] += picking.x_studio_tng_tin_sau_thu or 0.0
            if picking.misa_invoice_state == 'invoiced':
                bucket['invoice_amount'] += picking.misa_invoice_amount or 0.0

        return [buckets[key] for key in sorted(buckets.keys())]

    def _misa_invoice_picking_to_row(self, picking, today):
        done_date = picking.date_done.date() if picking.date_done else False
        master = picking.misa_invoice_master_picking_id
        # Phiếu "ăn theo" 1 đề nghị gộp chung tự lưu misa_invoice_amount = 0 (tránh cộng dồn
        # trùng ở các tổng khác) — hiển thị ở đây thì lấy tiền hóa đơn ĐẦY ĐỦ từ phiếu gốc để
        # người dùng không hiểu lầm "đã xuất HĐ" nhưng tiền lại bằng 0.
        invoice_amount = (master.misa_invoice_amount or 0.0) if master else (picking.misa_invoice_amount or 0.0)
        diff_source = master if master else picking
        return {
            'id': picking.id,
            'name': picking.name,
            'partner_name': picking.misa_invoice_root_partner_id.display_name or picking.partner_id.display_name or '',
            'sale_order_name': ', '.join(picking.misa_invoice_sale_order_ids.mapped('name')),
            'saler_code': picking.misa_invoice_saler_code or '',
            'date_done': fields.Date.to_string(done_date) if done_date else '',
            'days_pending': (today - done_date).days if done_date else 0,
            'state': picking.misa_invoice_state,
            'state_label': MISA_INVOICE_STATE_LABELS.get(picking.misa_invoice_state, picking.misa_invoice_state),
            'actual_amount': picking.x_studio_tng_tin_sau_thu or 0.0,
            'invoice_amount': invoice_amount,
            'invoice_no': picking.misa_invoice_no or False,
            'outstanding_amount': 0.0 if picking.misa_invoice_state == 'invoiced' else (
                picking.x_studio_tng_tin_sau_thu or 0.0
            ),
            'master_picking_id': master.id if master else False,
            'master_picking_name': master.name if master else False,
            'covered_pickings': [
                {'id': covered.id, 'name': covered.name}
                for covered in picking.misa_invoice_covered_picking_ids
            ],
            'exception': picking.misa_invoice_exception,
            'exception_reason': picking.misa_invoice_exception_reason or '',
            'multi_order_group': picking.misa_invoice_multi_order_group,
            'group_order_names': picking.misa_invoice_group_order_names,
            'manual_refno': picking.misa_invoice_manual_refno or False,
            'amount_diff': diff_source.misa_invoice_amount_diff or 0.0,
            'amount_mismatch': diff_source.misa_invoice_amount_mismatch,
        }

    @api.model
    def get_misa_invoice_urgent_list(
        self, limit=10, date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
    ):
        """Top phiếu cần hối gấp nhất: chưa xuất HĐ, không ngoại lệ, xuất kho lâu nhất."""
        domain = self._misa_invoice_dashboard_base_domain(
            date_from, date_to, invoice_date_from, invoice_date_to
        ) + [
            ('misa_invoice_state', 'in', ('missing', 'requested')),
            ('misa_invoice_exception', '=', False),
        ]
        pickings = self.sudo().search(domain, order='date_done asc', limit=limit)
        today = fields.Date.context_today(self)
        return [self._misa_invoice_picking_to_row(picking, today) for picking in pickings]

    def _misa_invoice_picking_list_domain(
        self, search=False, state=False, saler_code=False,
        date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
    ):
        domain = self._misa_invoice_dashboard_base_domain(
            date_from, date_to, invoice_date_from, invoice_date_to
        )
        if search:
            domain.append('|')
            domain.append(('name', 'ilike', search))
            domain.append(('misa_invoice_root_partner_id.display_name', 'ilike', search))
        if state:
            domain.append(('misa_invoice_state', '=', state))
        if saler_code:
            value = False if saler_code == MISA_INVOICE_UNASSIGNED_SALER else saler_code
            domain.append(('misa_invoice_saler_code', '=', value))
        return domain

    @api.model
    def get_misa_invoice_picking_list(
        self, limit=20, offset=0, search=False, state=False, saler_code=False,
        date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
    ):
        """Danh sách phiếu XUẤT KHO 'phẳng' (mọi trạng thái, không group, key là
        stock.picking KBC/OUT/...) — tab 'Phiếu xuất kho' trên dashboard. Có phân trang
        server-side vì có thể lên tới hàng nghìn dòng."""
        Picking = self.sudo()
        domain = self._misa_invoice_picking_list_domain(
            search, state, saler_code, date_from, date_to, invoice_date_from, invoice_date_to
        )
        total = Picking.search_count(domain)
        pickings = Picking.search(domain, order='date_done desc', limit=limit, offset=offset)
        today = fields.Date.context_today(self)
        return {
            'rows': [self._misa_invoice_picking_to_row(picking, today) for picking in pickings],
            'total': total,
        }

    def _misa_invoice_export_workbook(self, sheet_name, headers, rows, money_cols=None):
        """Dựng file .xlsx trong bộ nhớ (xlsxwriter) — dùng chung cho mọi nút "Xuất Excel"
        trên dashboard. money_cols: tập chỉ số cột (0-based) cần định dạng số tiền."""
        money_cols = money_cols or set()
        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        worksheet = workbook.add_worksheet(sheet_name[:31])

        fmt_header = workbook.add_format({
            'bold': True, 'bg_color': '#2a78d6', 'font_color': '#ffffff',
            'border': 1, 'align': 'center', 'valign': 'vcenter',
        })
        fmt_cell = workbook.add_format({'border': 1, 'valign': 'vcenter'})
        fmt_money = workbook.add_format({'border': 1, 'valign': 'vcenter', 'num_format': '#,##0', 'align': 'right'})

        worksheet.set_row(0, 22)
        for col, header in enumerate(headers):
            worksheet.write(0, col, header, fmt_header)
            worksheet.set_column(col, col, max(14, len(header) + 4))

        for row_idx, row in enumerate(rows, start=1):
            for col, value in enumerate(row):
                worksheet.write(row_idx, col, value, fmt_money if col in money_cols else fmt_cell)

        workbook.close()
        output.seek(0)
        return output.read()

    def _misa_invoice_create_export_attachment(self, filename, content):
        attachment = self.env['ir.attachment'].sudo().create({
            'name': filename,
            'type': 'binary',
            'datas': base64.b64encode(content),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            'res_model': self._name,
            'res_id': 0,
        })
        return attachment.id

    @api.model
    def export_misa_invoice_picking_list_excel(
        self, search=False, state=False, saler_code=False,
        date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
    ):
        """Xuất Excel TOÀN BỘ phiếu khớp filter hiện tại của tab 'Phiếu xuất kho' (không giới
        hạn theo trang đang xem) — trả về id ir.attachment, JS tự điều hướng tới
        /web/content/<id>?download=true để tải về."""
        Picking = self.sudo()
        domain = self._misa_invoice_picking_list_domain(
            search, state, saler_code, date_from, date_to, invoice_date_from, invoice_date_to
        )
        pickings = Picking.search(domain, order='date_done desc')
        today = fields.Date.context_today(self)
        rows = [
            [
                row['name'], row['partner_name'], row['sale_order_name'], row['date_done'],
                row['actual_amount'], row['invoice_amount'], row['outstanding_amount'], row['state_label'],
            ]
            for row in (self._misa_invoice_picking_to_row(picking, today) for picking in pickings)
        ]
        headers = [
            'Phiếu', 'Khách hàng', 'Đơn bán', 'Ngày xuất kho',
            'Tiền thực xuất', 'Tiền đã xuất HĐ', 'Tiền chưa xuất HĐ', 'Trạng thái',
        ]
        content = self._misa_invoice_export_workbook('Phiếu xuất kho', headers, rows, money_cols={4, 5, 6})
        return self._misa_invoice_create_export_attachment(
            'phieu_xuat_kho_%s.xlsx' % fields.Date.to_string(today), content
        )

    @api.model
    def get_misa_invoice_saler_options(self):
        """Danh sách mã sale (toàn bộ phạm vi đối soát, không giới hạn ngày) để đổ vào dropdown
        lọc — dùng cho trang "Danh sách đơn hàng" độc lập, nơi không có sẵn state.data.by_saler
        như dashboard Tổng quan."""
        Picking = self.sudo()
        domain = self._misa_invoice_dashboard_base_domain()
        groups = Picking.read_group(domain, ['id'], ['misa_invoice_saler_code'])
        return [
            {
                'code': grp['misa_invoice_saler_code'] or MISA_INVOICE_UNASSIGNED_SALER,
                'count': grp['misa_invoice_saler_code_count'],
            }
            for grp in groups
        ]

    # ==================== Trang public /misa_sale_status (misa_invoice_public_controller) ====================
    # Mỗi sale theo dõi + tự thao tác (gắn mã đề nghị thủ công, đánh dấu ngoại lệ) trên các
    # phiếu của MÌNH mà không cần vào backend Odoo. Vì nhiều sale dùng chung 1 mật khẩu trang
    # public (giống /sale_plan, /search_invoice), danh tính "tôi là sale nào" xác định bằng
    # cách TỰ CHỌN đúng mã sale MISA của mình trong danh sách hợp lệ (đăng ký sẵn qua
    # res.users.x_misa_saler_codes, xem get_misa_invoice_saler_code_registry) — không cần
    # đăng nhập Odoo thật, cùng mức tin cậy với hlv_order_cancel_request (đã áp dụng y hệt
    # kiểu xác thực "tự khai mã sale" này cho 1 trang public khác trong cùng hệ thống).

    @api.model
    def get_misa_invoice_saler_code_registry(self):
        """Gộp TẤT CẢ mã sale MISA đã đăng ký qua res.users.x_misa_saler_codes (của mọi user,
        không chỉ user đang gọi) thành 1 danh sách phẳng, không trùng — nguồn cho ô chọn mã
        sale trên trang public. Cùng cách hlv_sale_delivery_planning gộp
        x_sale_plan_mention_names cho trang /sale_plan."""
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

    @api.model
    def get_misa_invoice_public_list(
        self, saler_code, search=False, state=False, date_from=False, date_to=False,
        multi_order_group=False, multi_request=False, limit=50, offset=0,
    ):
        """Danh sách phiếu xuất kho của ĐÚNG 1 mã sale cho trang public, lọc thêm được theo
        khoảng NGÀY XUẤT KHO (date_from/date_to) và theo trạng thái cụ thể:
        - state rỗng/'pending' (mặc định): chưa xuất HĐ, chưa ngoại lệ — đúng mục đích "theo
          dõi đơn chưa XHD".
        - 'missing' / 'requested' / 'invoiced': đúng trạng thái đó, chưa ngoại lệ.
        - 'exception': đã đánh dấu ngoại lệ (không phân biệt trạng thái xuất HĐ).
        - 'all': không lọc trạng thái/ngoại lệ, chỉ còn scope theo mã sale + ngày.
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
        domain = list(base_domain)
        if state == 'exception':
            domain.append(('misa_invoice_exception', '=', True))
        elif state in ('missing', 'requested', 'invoiced'):
            domain += [('misa_invoice_state', '=', state), ('misa_invoice_exception', '=', False)]
        elif state != 'all':
            domain += [('misa_invoice_state', '!=', 'invoiced'), ('misa_invoice_exception', '=', False)]
        if search:
            domain += ['|', ('name', 'ilike', search), ('misa_invoice_sale_order_ids.name', 'ilike', search)]
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
    def get_misa_invoice_public_shopee_list(
        self, saler_code, search=False, state=False, date_from=False, date_to=False,
        limit=50, offset=0,
    ):
        """Tab 'Đơn Shopee' trên trang public, scope theo đúng 1 mã sale — tái dùng
        get_misa_invoice_shopee_list (nội bộ) sau khi xác thực mã sale."""
        code = self._misa_invoice_validate_public_saler_code(saler_code)
        return self.sudo().get_misa_invoice_shopee_list(
            limit=limit, offset=offset, search=search, state=state, saler_code=code,
            date_from=date_from, date_to=date_to,
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

    def _misa_invoice_order_state(self, states):
        """Trạng thái tổng hợp của 1 đơn bán từ tập trạng thái các phiếu xuất kho liên quan
        (trong phạm vi đang lọc) — 1 đơn có thể có nhiều phiếu/nhiều đề nghị xuất HĐ."""
        states = set(states)
        if states == {'invoiced'}:
            return 'invoiced'
        if 'invoiced' in states:
            return 'partial'
        if 'requested' in states:
            return 'requested'
        if 'missing' in states:
            return 'missing'
        return 'not_checked'

    def _misa_invoice_order_row(self, order, picking_id_set):
        """Dựng 1 dòng cho tab 'Đơn hàng' — tách riêng khỏi get_misa_invoice_order_list để
        dùng chung được cho cả đường phân trang thường VÀ đường lọc multi_request (phải tính
        cho toàn bộ candidate trước khi phân trang, xem bên dưới)."""
        order_pickings = order.misa_invoice_picking_ids.filtered(lambda p: p.id in picking_id_set)
        states = order_pickings.mapped('misa_invoice_state')
        overall_state = self._misa_invoice_order_state(states)
        # Phiếu "ăn theo" 1 đề nghị gộp chung lưu misa_invoice_amount = 0 (tránh cộng
        # trùng) — muốn ra đúng tổng tiền HĐ của đơn phải quy về phiếu ĐẠI DIỆN của từng
        # đề nghị rồi khử trùng theo id đại diện đó (2 phiếu ăn theo cùng 1 đề nghị chỉ
        # tính 1 lần; 2 đề nghị khác nhau vẫn cộng đủ cả 2).
        invoiced_pickings = order_pickings.filtered(lambda p: p.misa_invoice_state == 'invoiced')
        representatives = {
            (p.misa_invoice_master_picking_id or p).id: (p.misa_invoice_master_picking_id or p)
            for p in invoiced_pickings
        }
        invoiced_amount = sum(rep.misa_invoice_amount or 0.0 for rep in representatives.values())
        return {
            'id': order.id,
            'name': order.name,
            'partner_name': order.partner_id.commercial_partner_id.display_name or '',
            'picking_names': ', '.join(order_pickings.mapped('name')),
            'amount_total': order.amount_total,
            'invoice_amount': invoiced_amount,
            'outstanding_amount': 0.0 if overall_state == 'invoiced' else order.amount_total,
            'state': overall_state,
            'state_label': MISA_ORDER_STATE_LABELS.get(overall_state, overall_state),
            # True nếu đơn này đã được xuất HĐ qua từ 2 đề nghị/phiếu đại diện KHÁC NHAU trở
            # lên — VD giao/xuất HĐ nhiều đợt cho cùng 1 đơn (khác với
            # misa_invoice_multi_order_group trên picking, vốn là chiều ngược lại: 1 đề nghị
            # gộp NHIỀU đơn).
            'multi_request': len(representatives) > 1,
            'has_exception': any(order_pickings.mapped('misa_invoice_exception')),
            'pickings': [
                {
                    'id': p.id,
                    'name': p.name,
                    'state': p.misa_invoice_state,
                    'state_label': MISA_INVOICE_STATE_LABELS.get(p.misa_invoice_state, p.misa_invoice_state),
                    'actual_amount': p.x_studio_tng_tin_sau_thu or 0.0,
                    'invoice_amount': (
                        p.misa_invoice_master_picking_id.misa_invoice_amount
                        if p.misa_invoice_master_picking_id else p.misa_invoice_amount
                    ) or 0.0,
                    'invoice_no': p.misa_invoice_no or False,
                    'master_picking_id': p.misa_invoice_master_picking_id.id or False,
                    'master_picking_name': p.misa_invoice_master_picking_id.name or False,
                    'exception': p.misa_invoice_exception,
                    'manual_refno': p.misa_invoice_manual_refno or False,
                }
                for p in order_pickings
            ],
        }

    @api.model
    def get_misa_invoice_order_list(
        self, limit=20, offset=0, search=False, state=False, saler_code=False, multi_request=False,
        date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
    ):
        """Danh sách ĐƠN BÁN (key là sale.order DH...) — tab 'Đơn hàng' trên dashboard.
        Khác tab 'Phiếu xuất kho': 1 đơn có thể gộp nhiều phiếu/nhiều đề nghị xuất HĐ, nên
        số tiền lấy từ chính đơn bán (amount_total), không cộng dồn từ các phiếu (tránh đếm
        trùng khi 1 phiếu gộp giao cho nhiều đơn).

        state/saler_code lọc theo PHIẾU (không phải theo trạng thái tổng hợp của đơn) — VD
        lọc "Đã xuất HĐ" sẽ ra các đơn có ít nhất 1 phiếu đã xuất HĐ trong phạm vi đang lọc
        (đơn "Một phần đã xuất HĐ" vẫn xuất hiện), đủ dùng để thu hẹp danh sách mà không cần
        tính lại state tổng hợp cho toàn bộ đơn trước khi phân trang.

        multi_request=True: lọc "đơn đã xuất HĐ qua nhiều đề nghị khác nhau" (VD giao/xuất
        nhiều đợt) — phải tính cho TẤT CẢ candidate rồi mới phân trang được (không lọc bằng
        domain SQL thường vì cần so sánh giữa các phiếu của cùng 1 đơn), nên chỉ áp dụng khi
        thật sự bật filter này (bộ lọc audit, không phải đường tải chính hàng ngày)."""
        Picking = self.sudo()
        SaleOrder = self.env['sale.order'].sudo()
        # 2 domain tách riêng: base_picking_ids quyết định "phiếu nào thuộc phạm vi đang lọc
        # ngày/tháng" (dùng để tính state/tiền hiển thị của TOÀN BỘ đơn, không bị ảnh hưởng
        # bởi filter trạng thái/sale) — filter_picking_ids thêm state/saler_code CHỈ để chọn
        # đơn nào lọt vào danh sách (đơn "Một phần đã xuất HĐ" vẫn hiện đủ thông tin, không
        # bị cắt bớt phiếu chỉ vì lọc "Đã xuất HĐ").
        base_picking_domain = self._misa_invoice_dashboard_base_domain(
            date_from, date_to, invoice_date_from, invoice_date_to
        )
        base_picking_ids = Picking.search(base_picking_domain).ids
        base_picking_id_set = set(base_picking_ids)

        if state or saler_code:
            filter_picking_domain = self._misa_invoice_picking_list_domain(
                False, state, saler_code, date_from, date_to, invoice_date_from, invoice_date_to
            )
            filter_picking_ids = Picking.search(filter_picking_domain).ids
        else:
            filter_picking_ids = base_picking_ids

        order_domain = [('misa_invoice_picking_ids', 'in', filter_picking_ids)] if filter_picking_ids else [('id', '=', 0)]
        if search:
            order_domain.append(('name', 'ilike', search))

        if multi_request:
            all_orders = SaleOrder.search(order_domain, order='date_order desc')
            all_rows = [self._misa_invoice_order_row(order, base_picking_id_set) for order in all_orders]
            filtered_rows = [row for row in all_rows if row['multi_request']]
            total = len(filtered_rows)
            rows = filtered_rows[offset:offset + limit]
            return {'rows': rows, 'total': total}

        total = SaleOrder.search_count(order_domain)
        orders = SaleOrder.search(order_domain, order='date_order desc', limit=limit, offset=offset)
        rows = [self._misa_invoice_order_row(order, base_picking_id_set) for order in orders]
        return {'rows': rows, 'total': total}

    @api.model
    def export_misa_invoice_order_list_excel(
        self, search=False, state=False, saler_code=False, multi_request=False,
        date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
    ):
        """Xuất Excel TOÀN BỘ đơn hàng khớp filter hiện tại của tab 'Đơn hàng' — trả về id
        ir.attachment, JS tự điều hướng tới /web/content/<id>?download=true để tải về.
        Giới hạn 10.000 dòng (đủ dư cho quy mô dữ liệu hiện tại) để tránh xuất vô hạn nếu
        filter quá rộng."""
        result = self.get_misa_invoice_order_list(
            limit=10000, offset=0, search=search, state=state, saler_code=saler_code, multi_request=multi_request,
            date_from=date_from, date_to=date_to,
            invoice_date_from=invoice_date_from, invoice_date_to=invoice_date_to,
        )
        rows = [
            [
                row['name'], row['partner_name'], row['picking_names'],
                row['amount_total'], row['invoice_amount'], row['outstanding_amount'], row['state_label'],
            ]
            for row in result['rows']
        ]
        headers = [
            'Đơn hàng', 'Khách hàng', 'Phiếu xuất kho',
            'Tổng tiền đơn', 'Tiền đã xuất HĐ', 'Tiền chưa xuất HĐ', 'Trạng thái',
        ]
        content = self._misa_invoice_export_workbook('Đơn hàng', headers, rows, money_cols={3, 4, 5})
        return self._misa_invoice_create_export_attachment(
            'don_hang_%s.xlsx' % fields.Date.to_string(fields.Date.context_today(self)), content
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

    def _misa_invoice_picking_line_items(self, picking):
        """Chi tiết sản phẩm/mã hàng/số lượng/giá trị xuất kho của 1 phiếu — dùng chung cho
        drawer hiển thị (get_misa_invoice_picking_lines) VÀ đối chiếu từng dòng với MISA
        (get_misa_invoice_line_reconciliation, so theo default_code).

        Giá trị xuất kho = qty * đơn giá trên dòng đơn bán tương ứng (prorate theo
        qty đã giao trên dòng đó). Riêng combo/kit (BOM phantom): các dòng move con do
        Odoo tự nổ ra khi giao hàng đều trỏ về CÙNG 1 sale.order.line của sản phẩm combo,
        và giá chỉ nằm ở đó (giá sản phẩm con = 0) — nên gán toàn bộ price_subtotal của
        dòng combo cho 1 dòng đại diện, còn các sản phẩm con hiển thị giá trị = 0.
        """
        moves = picking.move_ids_without_package.filtered(lambda m: m.quantity > 0)
        groups = {}
        order = []
        for move in moves:
            key = move.sale_line_id.id
            if key not in groups:
                groups[key] = self.env['stock.move']
                order.append(key)
            groups[key] |= move

        Bom = self.env['mrp.bom'].sudo()
        lines = []
        for key in order:
            group_moves = groups[key]
            sale_line = group_moves[0].sale_line_id
            is_kit = bool(sale_line and Bom.search_count([
                ('product_tmpl_id', '=', sale_line.product_id.product_tmpl_id.id),
                ('type', '=', 'phantom'),
                ('active', '=', True),
            ]))

            if sale_line and is_kit:
                lines.append({
                    'product_name': sale_line.product_id.display_name,
                    'default_code': sale_line.product_id.default_code or False,
                    'qty': sale_line.product_uom_qty,
                    'uom_name': sale_line.product_uom.name,
                    'value': sale_line.price_subtotal,
                    'is_combo': True,
                })
                for move in group_moves:
                    lines.append({
                        'product_name': move.product_id.display_name,
                        'default_code': move.product_id.default_code or False,
                        'qty': move.quantity,
                        'uom_name': move.product_uom.name,
                        'value': 0.0,
                        'is_component': True,
                    })
                continue

            for move in group_moves:
                value = 0.0
                if sale_line and sale_line.product_uom_qty:
                    value = move.quantity * (sale_line.price_subtotal / sale_line.product_uom_qty)
                lines.append({
                    'product_name': move.product_id.display_name,
                    'default_code': move.product_id.default_code or False,
                    'qty': move.quantity,
                    'uom_name': move.product_uom.name,
                    'value': value,
                })
        return lines

    @api.model
    def get_misa_invoice_picking_lines(self, picking_id):
        """Chi tiết sản phẩm/số lượng/giá trị xuất kho của 1 phiếu, dùng cho drawer chi tiết."""
        picking = self.sudo().browse(picking_id)
        if not picking.exists():
            return []
        return self._misa_invoice_picking_line_items(picking)

    def _misa_invoice_group_odoo_lines(self, pickings, misa_codes=None):
        """Gộp dòng hàng Odoo của TOÀN BỘ phiếu trong 1 nhóm gộp chung đề nghị xuất HĐ, theo
        mã hàng (default_code) — MISA cũng gộp chung các phiếu này vào 1 đề nghị/hóa đơn nên
        phải so theo tổng cả nhóm, không so lẻ từng phiếu.

        Dòng sản phẩm con của combo/kit (is_component) mặc định bị bỏ qua (giá trị của cả
        combo đã tính đủ ở dòng đại diện) — TRỪ KHI misa_codes cho biết MISA cũng có dòng
        riêng cho đúng mã con đó. Thực tế quan sát được: MISA rã hẳn combo ra từng sản phẩm
        con khi tạo đề nghị xuất HĐ (không giữ 1 dòng combo gộp), nên nếu cứ bỏ qua sẽ báo
        nhầm "thiếu trên Odoo" cho các mã con dù giá trị/số lượng đã được gộp đủ ở dòng combo
        — bật lại dòng con (qty thật, value=0 vì tiền đã nằm ở dòng combo) khi MISA có báo
        đúng mã đó để 2 bên so khớp nhau, còn KHÔNG có ở MISA thì vẫn bỏ qua như cũ."""
        misa_codes = misa_codes or set()
        totals = {}
        for picking in pickings:
            for line in self._misa_invoice_picking_line_items(picking):
                code = line['default_code'] or line['product_name']
                if line.get('is_component') and code not in misa_codes:
                    continue
                bucket = totals.setdefault(
                    code, {'product_name': line['product_name'], 'uom_name': line['uom_name'], 'qty': 0.0, 'value': 0.0}
                )
                bucket['qty'] += line['qty']
                bucket['value'] += line['value']
        return totals

    def _misa_invoice_request_lines_by_code(self, misa_lines):
        """Gộp dòng hàng MISA (đã lấy qua get_invoice_request_lines) theo mã hàng
        (inventory_item_code) — 1 mã hàng có thể xuất hiện nhiều lần nếu đề nghị gộp
        nhiều đơn bán khác nhau cùng mua chung 1 sản phẩm."""
        totals = {}
        for line in misa_lines:
            code = line.get('inventory_item_code') or line.get('description') or '?'
            bucket = totals.setdefault(
                code, {'product_name': line.get('description'), 'unit_name': line.get('unit_name'), 'qty': 0.0, 'value': 0.0}
            )
            bucket['qty'] += line.get('quantity') or 0.0
            bucket['value'] += line.get('amount_oc') or 0.0
        return totals

    def _misa_invoice_resolve_qty_via_unit_convert(self, code, odoo_qty, misa_qty, misa_unit_name):
        """Khi số lượng Odoo/MISA lệch nhau ở 1 mã hàng, kiểm tra xem có phải do 2 bên ghi
        nhận khác đơn vị tính không (VD Odoo 1000 Cái = MISA 5 Bịch, 1 Bịch = 200 Cái) trước
        khi kết luận lệch thật — CHỈ gọi hàm này cho dòng đã bị đánh dấu lệch số lượng, không
        gọi tràn lan cho mọi dòng.

        MISA không có API tra quy đổi ĐVT theo 1 mã hàng lẻ — chỉ có API đồng bộ TOÀN BỘ danh
        mục hàng hóa theo trang (get_dictionary data_type=2, xem amis_callback), gọi riêng cho
        1 mã sẽ tốn hơn nhiều so với đọc thẳng từ cache đã đồng bộ sẵn (model
        amis.misa.inventory.cache, cron của module amis_callback) — nên đọc cache ở đây, không
        gọi thêm API MISA nào cả. Nếu mã hàng chưa có cache hoặc cache không có bảng quy đổi
        phù hợp, trả None (giữ nguyên kết luận lệch ban đầu)."""
        Cache = self.env.get('amis.misa.inventory.cache')
        if Cache is None or not code:
            return None
        cache = Cache.sudo().search(
            [('inventory_item_code', '=', code), ('is_deleted', '=', False)],
            order='write_date desc', limit=1,
        )
        if not cache or not cache.unit_convert_json:
            return None
        try:
            converts = json.loads(cache.unit_convert_json)
        except Exception:
            return None
        if isinstance(converts, dict):
            converts = [converts]
        if not isinstance(converts, list):
            return None

        target_key = (misa_unit_name or '').strip().casefold()
        if not target_key:
            return None
        for convert in converts:
            if not isinstance(convert, dict):
                continue
            convert_name = (convert.get('unit_name') or convert.get('unit_name_convert') or '').strip().casefold()
            if convert_name != target_key:
                continue
            try:
                rate = float(convert.get('convert_rate') or 1.0) or 1.0
            except Exception:
                rate = 1.0
            operator = (convert.get('exchange_rate_operator') or '*').strip() or '*'
            converted_qty = (misa_qty / rate) if operator == '/' else (misa_qty * rate)
            return {
                'matched': abs(converted_qty - odoo_qty) <= 0.01,
                'converted_qty': converted_qty,
                'main_unit_name': cache.main_unit_name or '',
            }
        return None

    @api.model
    def get_misa_invoice_line_reconciliation(self, picking_id):
        """Đối chiếu TỪNG DÒNG HÀNG (mã hàng, số lượng, tiền hàng chưa VAT) giữa Odoo và MISA
        cho 1 phiếu — tự động gộp cả nhóm khi phiếu này nằm trong 1 đề nghị xuất HĐ gộp chung
        nhiều phiếu (không so lẻ từng phiếu, vì MISA cũng gộp chung dòng hàng của tất cả các
        đơn bán liên quan vào 1 đề nghị duy nhất).

        Phần "tổng đơn" (tiền có VAT) dùng lại đúng misa_invoice_amount_diff/mismatch đã tính
        sẵn trên phiếu đại diện (đã xử lý đúng case gộp chung) — không tính lại ở đây để
        tránh 2 nơi tính ra 2 kết quả lệch nhau."""
        picking = self.sudo().browse(picking_id)
        if not picking.exists():
            return False

        representative = picking.misa_invoice_master_picking_id or picking
        if not representative.misa_invoice_request_refid:
            return False

        group_pickings = representative | representative.misa_invoice_covered_picking_ids

        misa_utils = self.env['misa.api.utils']
        try:
            misa_lines = misa_utils.get_invoice_request_lines(representative.misa_invoice_request_refid)
        except Exception as e:
            return {'error': str(e)}

        misa_totals = self._misa_invoice_request_lines_by_code(misa_lines)
        odoo_totals = self._misa_invoice_group_odoo_lines(group_pickings, misa_codes=set(misa_totals.keys()))

        rows = []
        for code in set(odoo_totals) | set(misa_totals):
            odoo = odoo_totals.get(code)
            misa = misa_totals.get(code)
            odoo_qty = odoo['qty'] if odoo else 0.0
            odoo_value = odoo['value'] if odoo else 0.0
            misa_qty = misa['qty'] if misa else 0.0
            misa_value = misa['value'] if misa else 0.0
            amount_diff = odoo_value - misa_value
            qty_diff = odoo_qty - misa_qty
            amount_mismatch = abs(amount_diff) > MISA_INVOICE_AMOUNT_TOLERANCE
            qty_mismatch = abs(qty_diff) > 0.001

            unit_convert_note = None
            # Chỉ tra quy đổi ĐVT khi ĐÃ bị đánh dấu lệch số lượng và khớp được cả 2 bên (bỏ
            # qua case chỉ có ở 1 bên — lúc đó là thiếu dòng thật, không phải khác đơn vị).
            if qty_mismatch and odoo and misa:
                resolution = self._misa_invoice_resolve_qty_via_unit_convert(
                    code, odoo_qty, misa_qty, misa.get('unit_name')
                )
                if resolution:
                    unit_convert_note = '%s %s = %s %s' % (
                        misa_qty, misa.get('unit_name') or '',
                        resolution['converted_qty'], odoo.get('uom_name') or resolution['main_unit_name'],
                    )
                    if resolution['matched']:
                        qty_mismatch = False

            rows.append({
                'code': code,
                'product_name': (odoo and odoo['product_name']) or (misa and misa['product_name']) or code,
                'odoo_qty': odoo_qty,
                'odoo_value': odoo_value,
                'misa_qty': misa_qty,
                'misa_value': misa_value,
                'qty_diff': qty_diff,
                'amount_diff': amount_diff,
                'mismatch': amount_mismatch or qty_mismatch,
                'unit_convert_note': unit_convert_note,
                'in_odoo_only': odoo is not None and misa is None,
                'in_misa_only': misa is not None and odoo is None,
            })
        rows.sort(key=lambda r: (not r['mismatch'], r['product_name'] or ''))

        return {
            'rows': rows,
            'group_picking_names': group_pickings.mapped('name'),
            'order_level': {
                'actual_amount': sum(group_pickings.mapped('x_studio_tng_tin_sau_thu')),
                'invoice_amount': representative.misa_invoice_amount or 0.0,
                'diff': representative.misa_invoice_amount_diff,
                'mismatch': representative.misa_invoice_amount_mismatch,
            },
        }

    @api.model
    def get_misa_invoice_report_action(
        self, state=False, exception=None, saler_code=False, mismatch=False, partner_id=False,
        warehouse_id=False, date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
    ):
        """Trả action list đã có sẵn (action_misa_invoice_status_report), lọc theo tile/dòng được bấm.
        exception=None: không ép domain, để search view tự quyết định (dùng cho "Xem tất cả").
        exception=True/False: ép domain đúng theo tile."""
        action = self.env['ir.actions.actions']._for_xml_id(
            'misa_invoice_status_report.action_misa_invoice_status_report'
        )
        domain = self._misa_invoice_dashboard_base_domain(
            date_from, date_to, invoice_date_from, invoice_date_to
        )
        if state:
            domain.append(('misa_invoice_state', '=', state))
            if exception is None:
                exception = False
        if exception is not None:
            domain.append(('misa_invoice_exception', '=', bool(exception)))
            # Action gốc có context mặc định tự áp filter "Chưa đánh dấu ngoại lệ"
            # (search_default_filter_no_exception) trên search view — nếu domain ở đây đã
            # tự quyết định rõ ràng theo ngoại lệ (VD tile "Đã đánh dấu ngoại lệ" ép
            # exception=True) mà vẫn giữ nguyên default đó, search view sẽ tự thêm domain
            # đối lập (exception=False) đè lên, ra kết quả rỗng/sai. Xóa default để domain
            # mình set là quyết định duy nhất.
            action['context'] = {}
        if saler_code:
            value = False if saler_code == MISA_INVOICE_UNASSIGNED_SALER else saler_code
            domain.append(('misa_invoice_saler_code', '=', value))
        if partner_id:
            domain.append(('misa_invoice_root_partner_id', '=', partner_id))
        if warehouse_id:
            domain.append(('picking_type_id.warehouse_id', '=', warehouse_id))
        if mismatch:
            domain.append(('misa_invoice_amount_mismatch', '=', True))
        action['domain'] = domain
        return action
