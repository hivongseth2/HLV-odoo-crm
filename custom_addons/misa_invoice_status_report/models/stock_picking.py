import json
import logging
from datetime import datetime, time as dt_time, timedelta

from markupsafe import Markup

from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError
from odoo.osv import expression

_logger = logging.getLogger(__name__)

MISA_INVOICE_STATE_LABELS = {
    'not_checked': 'Chưa kiểm tra',
    'missing': 'Chưa có đề nghị xuất HĐ',
    'requested': 'Đã đề nghị, chờ HĐ',
    'invoiced': 'Đã xuất hóa đơn',
}

# Giới hạn số phiếu xử lý mỗi lần chạy cron, tránh gọi MISA API quá nhiều cùng lúc.
MISA_INVOICE_SCAN_BATCH_SIZE = 50

# Giới hạn số phiếu ĐẠI DIỆN quét "đơn xuất kèm" (misa_invoice_group_checked) mỗi lần cron
# chạy — bước này vốn chỉ tự kích hoạt 1 LẦN DUY NHẤT ngay lúc phiếu chuyển 'invoiced' (xem
# action_check_misa_invoice_status); nếu lần đó lỡ mất, phiếu đã 'invoiced' sẽ KHÔNG BAO GIỜ
# bị quét lại ở nhánh chính (domain chỉ lấy phiếu CHƯA invoiced) — quét bù nhỏ giọt ở cron để
# không bị kẹt vĩnh viễn.
MISA_INVOICE_GROUP_SCAN_BATCH_SIZE = 20

# Mốc ngày mặc định bắt đầu đối soát nếu chưa cấu hình (có thể đổi trên dashboard).
MISA_INVOICE_CUTOFF_PARAM = 'misa_invoice_status_report.cutoff_date'
MISA_INVOICE_CUTOFF_DEFAULT = '2026-05-01'
MISA_INVOICE_RECONCILE_GROUP = 'misa_invoice_status_report.group_misa_invoice_reconciliation'
# Ẩn/hiện các nút "công cụ quản trị" (Quét đơn xuất kèm / Sửa gộp sai / Cập nhật lý do lệch /
# Sửa gán lồng nhau) trên dashboard — đây là các nút vá dữ liệu/bảo trì, không cần dùng hàng
# ngày, để mặc định HIỆN (giữ hành vi hiện tại) nhưng cho nhóm "Đối soát XHD" tự ẩn bớt cho đỡ
# rối nếu không cần — xem get_misa_invoice_show_admin_tools/set_misa_invoice_show_admin_tools.
MISA_INVOICE_SHOW_ADMIN_TOOLS_PARAM = 'misa_invoice_status_report.show_admin_tools'

# Sai số cho phép khi so tiền hóa đơn MISA với tiền thực xuất trên phiếu kho (làm tròn).
MISA_INVOICE_AMOUNT_TOLERANCE = 1.0

MISA_INVOICE_UNASSIGNED_SALER = 'Chưa gán mã sale'

# Nhãn trạng thái stock.picking (KHÁC với MISA_INVOICE_STATE_LABELS ở trên, vốn là trạng thái
# xuất hóa đơn) — dùng khi liệt kê phiếu gợi ý cho tính năng "khớp thủ công" đơn hải quan.
STOCK_PICKING_STATE_LABELS = {
    'draft': 'Nháp', 'waiting': 'Chờ hàng', 'confirmed': 'Chờ hàng',
    'assigned': 'Sẵn sàng', 'done': 'Hoàn tất', 'cancel': 'Đã hủy',
}

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
    # Số ĐỀ NGHỊ xuất HĐ THẬT trên MISA (VD "KBC/OUT/11613" hoặc "DN0017572") — KHÁC
    # misa_invoice_request_refid (UUID nội bộ MISA, không đọc được) — lấy từ status['master_refno']
    # trong action_check_misa_invoice_status, LUÔN là refno THẬT của đề nghị tìm được (không chỉ
    # khi khác tên phiếu) — dùng để hiển thị "đơn này đi theo đề nghị nào" cho người dùng, case
    # thật: đơn DH...234781/phiếu KBC/OUT/11613 nhưng đề nghị lại tên "DN0017572" (sale gõ theo
    # mã đơn hàng khi tạo đề nghị trên MISA, không theo tên phiếu).
    misa_invoice_request_refno = fields.Char(string='Số đề nghị xuất HĐ (MISA)', copy=False)
    misa_invoice_no = fields.Char(string='Số hóa đơn MISA', copy=False)
    misa_invoice_date = fields.Date(string='Ngày hóa đơn MISA', copy=False)
    misa_invoice_amount = fields.Float(string='Tiền hóa đơn MISA', copy=False)
    # Đã đọc chi tiết dòng hàng (order_code) của đề nghị xuất HĐ để chủ động tìm đơn hàng KHÁC
    # được xuất kèm trong CÙNG đề nghị này chưa — xem _misa_invoice_discover_grouped_orders().
    # KHÔNG dùng "misa_invoice_covered_picking_ids rỗng" để suy ra "chưa kiểm tra", vì đa số
    # hóa đơn chỉ có 1 đơn (không có ai xuất kèm) nên covered_picking_ids SẼ MÃI rỗng dù đã
    # kiểm tra xong — phải có field riêng để không gọi lại MISA vô ích mỗi lần quét.
    misa_invoice_group_checked = fields.Boolean(string='Đã quét đơn xuất kèm', copy=False)
    # Đã kiểm tra lại nhóm gộp này (misa_invoice_covered_picking_ids) có bị gán SAI bởi phiên
    # bản CŨ của _misa_invoice_discover_grouped_orders chưa (ép cả phiếu ăn theo về 0 dù đề
    # nghị chỉ phủ 1 phần giá trị) — xem repair_misa_invoice_grouped_order().
    misa_invoice_group_repaired = fields.Boolean(string='Đã kiểm tra sửa gộp sai', copy=False)
    # Đã thử sửa "thiếu Số HĐ/Số đề nghị dù đã Đã xuất HĐ" chưa (dữ liệu cũ bị ghi thiếu do 1
    # đợt code lỗi trước đây — xem repair_misa_invoice_missing_no()) — PHẢI có field riêng để
    # domain quét tự RỖNG DẦN sau khi xử lý, không thì nút quét chạy vòng lặp không hội tụ
    # (bài học thật: misa_invoice_amount_mismatch không tự tắt sau khi tính lý do, khiến nút
    # "Cập nhật lý do lệch" từng bị lặp vô ích cho tới khi thêm field đánh dấu tương tự).
    misa_invoice_no_repaired = fields.Boolean(string='Đã kiểm tra sửa thiếu Số HĐ', copy=False)
    # Các lượt được xuất HĐ CHUNG qua đề nghị của 1 phiếu KHÁC, khớp theo TỪNG DÒNG HÀNG (mã
    # hàng + số lượng) — xem misa.invoice.grouped.line/.match và
    # _misa_invoice_discover_grouped_orders. Khác với misa_invoice_master_picking_id (chỉ gán
    # khi khớp ĐỦ 100%), field này cộng dồn được cả trường hợp chỉ khớp 1 PHẦN.
    misa_invoice_grouped_match_ids = fields.One2many(
        'misa.invoice.grouped.match', 'picking_id', string='Các lượt được xuất HĐ chung',
    )
    misa_invoice_grouped_matched_amount = fields.Float(
        string='Tiền đã xuất HĐ chung (qua đề nghị phiếu khác)',
        compute='_compute_misa_invoice_grouped_matched_amount', store=True,
        help='Tổng tiền (có VAT) của phần sản phẩm thuộc phiếu này đã được xuất hóa đơn CHUNG '
             'qua đề nghị của 1 phiếu KHÁC — có thể chỉ là 1 PHẦN giá trị thực xuất nếu đề nghị '
             'kia không phủ hết (case KBC/OUT/11016: chỉ 1/3 sản phẩm được phủ). Dùng để trừ '
             'vào phần "còn thiếu hóa đơn" thay vì tính thiếu toàn bộ.',
    )

    @api.depends('misa_invoice_grouped_match_ids.amount')
    def _compute_misa_invoice_grouped_matched_amount(self):
        for picking in self:
            picking.misa_invoice_grouped_matched_amount = sum(
                picking.misa_invoice_grouped_match_ids.mapped('amount')
            )

    # Tóm tắt LÝ DO CỤ THỂ (chưa xuất kho / chưa có phiếu / không rõ đơn / bị đề nghị khác
    # nhận) khiến 1 nhóm gộp chung có "chênh lệch" — tính sẵn (không tính lại mỗi lần hiện
    # danh sách "Đối chiếu tổng", vì danh sách đó có thể liệt kê hàng trăm nhóm cùng lúc, không
    # thể gọi API MISA cho từng dòng). Chỉ có ý nghĩa trên phiếu ĐẠI DIỆN (không phải phiếu ăn
    # theo) — xem _misa_invoice_refresh_gap_summary.
    misa_invoice_gap_summary = fields.Text(string='Lý do lệch (tóm tắt)', copy=False)
    misa_invoice_gap_checked_at = fields.Datetime(string='Lần cập nhật lý do lệch gần nhất', copy=False)
    # True khi TOÀN BỘ phần "lệch" của nhóm này đã được XÁC MINH là không phải vấn đề thật (mọi
    # lát khác 'linked' trong group_breakdown đều là 'resolved_elsewhere') — case thật
    # KBC/OUT/10826: số lệch 4.225.608đ vẫn còn nguyên (đúng bản chất, vì đơn của chính phiếu
    # này được xuất hóa đơn qua 1 đề nghị HOÀN TOÀN khác), nhưng KHÔNG cần ai xử lý tay nữa —
    # nếu không có cờ riêng này, dashboard hiện y hệt 1 lệch thật đang chờ xử lý, không ai phân
    # biệt được với case cần "hối" sale thật sự.
    misa_invoice_gap_resolved = fields.Boolean(string='Lệch đã xác minh xong (không cần xử lý)', copy=False)

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
    # So tiền hóa đơn MISA với tiền thực xuất RÒNG trên phiếu (misa_invoice_net_actual_amount,
    # xem field bên dưới) — không so trực tiếp với field Studio x_studio_tng_tin_sau_thu nữa vì
    # field đó là giá trị GỘP chụp nhanh lúc validate, không tự trừ khi có trả hàng sau đó.
    misa_invoice_amount_diff = fields.Float(
        string='Chênh lệch tiền (Odoo - MISA)', compute='_compute_misa_invoice_amount_mismatch', store=True,
    )
    misa_invoice_amount_mismatch = fields.Boolean(
        string='Lệch tiền so với MISA', compute='_compute_misa_invoice_amount_mismatch', store=True,
    )
    # Mức độ xuất HĐ THẬT theo ĐƠN HÀNG (không phải theo tên đề nghị/refno như
    # misa_invoice_state) — vì 1 đơn có thể được xuất hóa đơn qua NHIỀU đề nghị khác nhau
    # (chia nhỏ, gán nhầm tên đề nghị...), misa_invoice_state (dựa vào tìm ĐÚNG 1 refno khớp
    # tên phiếu) không phản ánh đúng "đã xuất bao nhiêu % giá trị đơn". Field này cộng dồn TẤT
    # CẢ tiền đã xuất HĐ qua MỌI đề nghị nhắc tới đơn hàng (get_invoice_requests_for_order,
    # không quan tâm tên đề nghị) so với tổng tiền thực xuất của TOÀN BỘ phiếu thuộc đơn đó.
    # CHỈ tính khi bước refno nhanh KHÔNG xác nhận đủ (state='missing' hoặc amount_mismatch=True)
    # — xem _misa_invoice_reconcile_order_coverage — để không tốn thêm API cho phần lớn phiếu
    # đã khớp sạch ngay từ bước refno.
    misa_invoice_order_coverage = fields.Selection([
        ('none', 'Chưa xuất HĐ'),
        ('partial', 'Xuất HĐ 1 phần'),
        ('full', 'Đã xuất HĐ đủ'),
    ], string='Mức độ xuất HĐ theo đơn hàng', copy=False)

    # ==== Trả hàng (khách trả lại 1 phần/toàn bộ sau khi đã xuất kho) ====
    # x_studio_tng_tin_sau_thu (field Studio, "tiền thực xuất GỘP") chỉ được set 1 LẦN lúc
    # phiếu validate xong, KHÔNG tự giảm khi sau đó có phiếu trả hàng (stock.return.picking,
    # tạo phiếu incoming reverse lại move gốc) — khiến mọi tổng đối soát trong module này bị
    # tính DƯ đúng bằng phần khách đã trả. 2 field dưới đây tính lại "phần ròng" (net = gộp -
    # đã trả), ghi tay tại 2 thời điểm: (1) phiếu xuất kho gốc validate xong (net = gộp, chưa
    # có trả), (2) phiếu TRẢ HÀNG liên quan validate xong (tính lại net cho phiếu gốc bị ảnh
    # hưởng) — xem button_validate()/_misa_invoice_recompute_net_amount(). KHÔNG dùng
    # @api.depends vì quan hệ trả hàng đi NGƯỢC (phiếu trả trỏ về move gốc qua
    # origin_returned_move_id) — Odoo không tự invalidate/recompute phiếu gốc chỉ vì có 1
    # record MỚI ở nơi khác trỏ về nó, nên phải trigger ghi tay tại đúng 2 điểm trên.
    misa_invoice_returned_amount = fields.Float(
        string='Tiền hàng đã trả (sau khi xuất kho)', copy=False,
        help='Giá trị (quy đổi theo giá bán sau thuế) của phần hàng đã bị khách trả lại, tính '
             'từ các phiếu trả hàng (incoming) liên kết ngược tới move của phiếu này.',
    )
    misa_invoice_net_actual_amount = fields.Float(
        string='Tiền thực xuất RÒNG (đã trừ hàng trả)', copy=False,
        help='= x_studio_tng_tin_sau_thu (tiền thực xuất gộp) − misa_invoice_returned_amount. '
             'Dùng số này thay cho x_studio_tng_tin_sau_thu ở mọi chỗ đối soát trong module.',
    )
    # Phiếu có trả hàng: KHÔNG kiểm soát được việc kế toán có thật sự lập hóa đơn điều chỉnh
    # (credit note) trên MISA hay không — nên COI NHƯ kế toán luôn làm đúng, tự giả định hóa
    # đơn đã được điều chỉnh xuống đúng bằng tiền thực xuất ròng, để phiếu này vẫn hiện bình
    # thường ở MỌI tab/tổng đối soát (không bị loại ra) mà không báo lệch tiền giả. Số liệu
    # THẬT (misa_invoice_amount, chưa điều chỉnh) vẫn giữ nguyên riêng để tham khảo/đối chiếu
    # thủ công — field này CHỈ dùng thay thế misa_invoice_amount ở các chỗ TÍNH TOÁN đối soát.
    misa_invoice_effective_amount = fields.Float(
        string='Tiền HĐ áp dụng (coi như đã điều chỉnh nếu có trả hàng)',
        compute='_compute_misa_invoice_effective_amount', store=True,
        help='Bình thường = misa_invoice_amount. Nếu phiếu có trả hàng, coi như kế toán đã '
             'điều chỉnh hóa đơn xuống đúng bằng misa_invoice_net_actual_amount (không xác '
             'minh được điều chỉnh thật trên MISA, chỉ là giả định hợp lý để không báo lệch '
             'giả) — misa_invoice_amount thật vẫn giữ nguyên, không bị field này ghi đè.',
    )

    misa_invoice_exception = fields.Boolean(string='Ngoại lệ (chấp nhận chờ xuất HĐ)', copy=False)
    misa_invoice_exception_reason = fields.Text(string='Lý do ngoại lệ', copy=False)
    misa_invoice_exception_by_id = fields.Many2one('res.users', string='Người đánh dấu', copy=False)
    misa_invoice_exception_date = fields.Datetime(string='Ngày đánh dấu', copy=False)

    # Nhắc nhở xuất HĐ Ở MỨC PHIẾU — dùng khi admin chọn nhắc trực tiếp 1/nhiều phiếu (tab
    # "Phiếu xuất kho") thay vì cả đơn hàng (xem sale.order.misa_invoice_reminder_at ở
    # models/sale_order.py và action_send_misa_invoice_reminder bên dưới).
    misa_invoice_reminder_at = fields.Datetime(string='Lần nhắc xuất HĐ gần nhất', copy=False)
    misa_invoice_reminder_by_id = fields.Many2one('res.users', string='Người nhắc xuất HĐ', copy=False)

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
        'misa_invoice_state', 'misa_invoice_amount', 'misa_invoice_net_actual_amount',
        'misa_invoice_returned_amount', 'misa_invoice_master_picking_id',
        'misa_invoice_grouped_matched_amount',
        'misa_invoice_covered_picking_ids.misa_invoice_net_actual_amount',
        'misa_invoice_covered_picking_ids.misa_invoice_returned_amount',
    )
    def _compute_misa_invoice_effective_amount(self):
        for picking in self:
            if picking.misa_invoice_master_picking_id:
                # Phiếu "ăn theo" 1 đề nghị gộp chung LUÔN phải = 0 (tiền đầy đủ nằm ở phiếu
                # gốc, xem misa_invoice_amount) — kể cả khi CHÍNH phiếu ăn theo này có trả hàng,
                # KHÔNG được ghi đè thành net_actual_amount, nếu không mọi tổng cộng dồn phẳng
                # (read_group misa_invoice_effective_amount:sum) sẽ cộng trùng với phiếu gốc.
                picking.misa_invoice_effective_amount = 0.0
                continue
            # Trả hàng có thể xảy ra ở BẤT KỲ phiếu nào trong nhóm (chính phiếu gốc hoặc 1
            # trong các phiếu ăn theo) — phải cộng dồn TOÀN NHÓM (không chỉ riêng phiếu gốc)
            # rồi mới quyết định có "coi như đã điều chỉnh" hay không, nếu không sẽ vứt mất
            # tiền của các phiếu ăn theo khác, tưởng nhầm là lệch (case KBC/OUT/10603 thực tế
            # gặp: phiếu gốc tự có trả hàng, effective_amount trước đây tính ra 0 tiền đóng góp
            # của 6 phiếu ăn theo còn lại).
            group_returned = picking.misa_invoice_returned_amount + sum(
                picking.misa_invoice_covered_picking_ids.mapped('misa_invoice_returned_amount')
            )
            if picking.misa_invoice_state == 'invoiced' and group_returned > 0:
                picking.misa_invoice_effective_amount = picking.misa_invoice_net_actual_amount + sum(
                    picking.misa_invoice_covered_picking_ids.mapped('misa_invoice_net_actual_amount')
                )
            elif picking.misa_invoice_state != 'invoiced' and picking.misa_invoice_grouped_matched_amount > 0:
                # Chưa có hóa đơn RIÊNG, nhưng 1 phần giá trị đã được xuất hóa đơn CHUNG qua đề
                # nghị của 1 phiếu KHÁC, khớp theo dòng hàng (misa_invoice_grouped_matched_amount
                # — xem _misa_invoice_discover_grouped_orders). Kẹp không vượt quá net_actual để
                # phòng sai số làm tưởng thừa hóa đơn so với thực xuất.
                picking.misa_invoice_effective_amount = min(
                    picking.misa_invoice_grouped_matched_amount, picking.misa_invoice_net_actual_amount,
                )
            else:
                picking.misa_invoice_effective_amount = picking.misa_invoice_amount

    @api.depends(
        'misa_invoice_state', 'misa_invoice_effective_amount', 'misa_invoice_net_actual_amount',
        'misa_invoice_master_picking_id', 'misa_invoice_covered_picking_ids.misa_invoice_net_actual_amount',
        'misa_invoice_covered_picking_ids.misa_invoice_effective_amount',
    )
    def _compute_misa_invoice_amount_mismatch(self):
        for picking in self:
            actual_amount = picking.misa_invoice_net_actual_amount or 0.0
            if picking.misa_invoice_master_picking_id:
                # Phiếu "ăn theo" 1 đề nghị gộp chung — không tự so tiền ở đây (tiền hóa đơn
                # đầy đủ được lưu ở phiếu gốc), xem đối chiếu tại misa_invoice_master_picking_id.
                picking.misa_invoice_amount_diff = 0.0
                picking.misa_invoice_amount_mismatch = False
            elif picking.misa_invoice_state == 'invoiced' and (actual_amount or picking.misa_invoice_covered_picking_ids):
                # Nếu có phiếu đi kèm gộp chung đề nghị, so theo TỔNG tiền thực xuất RÒNG của cả
                # nhóm với tiền hóa đơn ÁP DỤNG (đã lưu đầy đủ ở phiếu gốc) — so từng phiếu riêng
                # lẻ với tổng tiền hóa đơn gộp sẽ luôn báo lệch sai. Dùng effective_amount (không
                # phải misa_invoice_amount thô) để phiếu có trả hàng không bị báo lệch giả.
                group_actual = actual_amount + sum(
                    picking.misa_invoice_covered_picking_ids.mapped('misa_invoice_net_actual_amount')
                )
                diff = group_actual - (picking.misa_invoice_effective_amount or 0.0)
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
            # kiểm tra, phiếu này CÓ THỂ là "ăn theo" phiếu đó.
            #
            # QUAN TRỌNG (bài học thật): TRƯỚC ĐÂY, cứ tìm thấy tên là gán NGAY "ăn theo" (zero
            # tiền hóa đơn của phiếu này) — mù tịt không kiểm tra xem đề nghị đó có phủ ĐỦ giá
            # trị của phiếu này hay chỉ 1 PHẦN (case y hệt lỗi đã sửa ở Cơ chế B/
            # _misa_invoice_discover_grouped_orders cho KBC/OUT/11016 — 1 đề nghị chỉ phủ đúng
            # 1/3 sản phẩm của phiếu kia). Giờ KHÔNG tự ý gán "ăn theo"/zero tiền ở đây nữa —
            # chỉ ghi nhận phiếu này NHƯ THỂ tự tìm thấy hóa đơn ĐỘC LẬP (giữ nguyên tiền thô MISA
            # trả về), và đảm bảo phiếu đại diện (master_refno) được/đã quét bằng
            # _misa_invoice_discover_grouped_orders — engine đó đọc ĐÚNG order_code + số lượng
            # từng dòng hàng (get_invoice_request_lines), khớp CHÍNH XÁC theo dòng hàng thay vì
            # đoán mù theo tên, và tự quyết định: đủ → gán "ăn theo" (zero tiền); thiếu → chỉ
            # cộng dồn 1 phần (misa_invoice_grouped_matched_amount). _misa_invoice_dedupe_request_refid_groups
            # (chạy cuối hàm) vẫn là lưới an toàn dự phòng cho trường hợp cả 2 cơ chế trên đều
            # không tự nối được (không chia sẻ order_code nào phát hiện được).
            master_refno = status.get('master_refno')
            # True khi MISA báo phiếu này nằm chung đề nghị với 1 phiếu KHÁC (dù đã xác định
            # được ai là đại diện thật hay chưa) — dùng để: (a) không tự chạy discovery từ
            # chính phiếu này (nhường vai đại diện cho candidate_master, tránh 2 phiếu cùng 1
            # request_refid giành nhau tự nhận là gốc), (b) tạm giữ nguyên tiền hóa đơn thô
            # (không zero mù) cho tới khi discovery/dedupe xác nhận xong.
            found_master_refno = False
            # So với refno vừa dùng để tra (không phải luôn là tên phiếu — có thể là mã đề
            # nghị gắn tay) — nếu trùng nghĩa là đề nghị này chính là của phiếu đang xét,
            # không cần tìm phiếu gốc nào khác.
            if master_refno and master_refno != refno:
                candidate_master = self.sudo().search([('name', '=', master_refno)], limit=1)
                if candidate_master and candidate_master.id not in self._ids:
                    found_master_refno = True
                    if candidate_master.misa_invoice_state != 'invoiced':
                        # Phiếu đại diện chưa từng được kiểm tra — thêm vào lô kiểm tra ngay,
                        # tự nó sẽ gọi _misa_invoice_discover_grouped_orders khi trở thành 'invoiced'.
                        extra_masters_to_check |= candidate_master
                    elif (
                        picking.misa_invoice_master_picking_id != candidate_master
                        and not picking.misa_invoice_grouped_matched_amount
                    ):
                        # Phiếu đại diện ĐÃ được kiểm tra từ trước (group_checked có thể đã
                        # True) nhưng CHƯA từng biết tới phiếu đang xét (mới lộ ra qua
                        # master_refno lần này, VD phiếu vừa mới 'done' sau lượt quét trước) —
                        # buộc quét lại 1 lần để không bỏ sót vĩnh viễn (chỉ quét lại khi thật
                        # sự có tin mới, tránh tốn thêm API mỗi 30 phút cho mọi phiếu).
                        candidate_master.misa_invoice_group_checked = False
                        try:
                            candidate_master._misa_invoice_discover_grouped_orders()
                        except Exception:
                            _logger.exception(
                                "❌ [MISA GROUP DISCOVER] Lỗi quét lại phiếu đại diện %s (phát hiện qua "
                                "master_refno của phiếu %s)", candidate_master.name, picking.name,
                            )

            # QUAN TRỌNG — CHỐNG MẤT DỮ LIỆU (bài học thật: mô phỏng lại đúng luồng quét theo lô
            # bằng request_map với khoảng ngày hẹp, phát hiện lần quét đó "không tìm ra gì" cho
            # 1 phiếu ĐANG 'invoiced' hợp lệ — nếu ghi đè thẳng theo status ở dưới, sẽ XÓA MẤT
            # misa_invoice_no/request_refno/request_refid ĐÚNG đã có từ trước, dù hóa đơn thật
            # vẫn còn nguyên trên MISA, chỉ là lần tìm NÀY không thấy (phạm vi ngày/API tạm thời
            # không đủ). Phiếu đang 'invoiced' mà lần kiểm tra này ra 'missing' HOÀN TOÀN (không
            # tìm được request_refid nào, kể cả sau fallback theo mã đơn ở trên) → KHÔNG ghi đè,
            # chỉ cập nhật last_checked + cảnh báo, để không tự ý "hủy" 1 hóa đơn có thật chỉ vì
            # 1 lần tìm không ra.
            if (
                picking.misa_invoice_state == 'invoiced' and status['state'] != 'invoiced'
                and not status.get('request_refid')
            ):
                # Trước khi kết luận "không tìm thấy": nếu đang ở chế độ quét THEO LÔ (dùng
                # request_map giới hạn theo ngày) — thử xác minh lại ĐÚNG 1 LẦN bằng API SỐNG
                # (get_invoice_status_for_refno, không giới hạn ngày) CHỈ cho riêng phiếu này —
                # tốn thêm đúng 1 lệnh gọi cho ca hiếm gặp này (không quét sống tràn lan cho cả
                # lô, chỉ khi thật sự rơi vào nghi vấn), không ảnh hưởng hiệu năng chung.
                if request_map is not None:
                    try:
                        live_status = misa_utils.get_invoice_status_for_refno(refno)
                    except Exception:
                        _logger.exception(
                            "❌ [MISA INVOICE STATUS] Lỗi xác minh sống lại cho phiếu %s (quét theo lô "
                            "không tìm thấy)", picking.name,
                        )
                        live_status = None
                    if live_status and live_status.get('request_refid'):
                        # Xác minh sống TÌM RA — dùng kết quả MỚI này, rơi xuống xử lý bình
                        # thường bên dưới (vals = {...}) như 1 lần check thành công thật sự,
                        # không còn là "không tìm thấy" nữa.
                        status = live_status

                if not status.get('request_refid'):
                    # Vẫn KHÔNG tìm ra kể cả sau khi xác minh sống — GIỮ NGUYÊN dữ liệu cũ, vì
                    # rất có thể do phạm vi tìm kiếm/API tạm thời không đủ, không phải hóa đơn
                    # đã bị hủy thật trên MISA (bài học thật: mô phỏng lại đúng luồng quét theo
                    # lô với khoảng ngày hẹp, phát hiện lần quét đó "không tìm ra gì" cho 1
                    # phiếu ĐANG 'invoiced' hợp lệ — nếu ghi đè thẳng theo status, sẽ XÓA MẤT
                    # misa_invoice_no/request_refno/request_refid ĐÚNG đã có từ trước).
                    picking.misa_invoice_last_checked = fields.Datetime.now()
                    picking.message_post(body=Markup(
                        "<b>⚠️ Kiểm tra lại KHÔNG tìm thấy đề nghị/hóa đơn</b> (phiếu đang 'Đã xuất "
                        "HĐ' với số %s), kể cả sau khi xác minh lại bằng API sống — GIỮ NGUYÊN dữ "
                        "liệu cũ, KHÔNG tự xóa/hạ trạng thái. Kiểm tra tay trên MISA nếu thật sự "
                        "nghi ngờ hóa đơn đã bị hủy."
                    ) % (picking.misa_invoice_no or '?'))
                    results.append({
                        'id': picking.id, 'name': picking.name,
                        'state': picking.misa_invoice_state,
                        'state_label': MISA_INVOICE_STATE_LABELS.get(picking.misa_invoice_state, picking.misa_invoice_state),
                    })
                    continue

            vals = {
                'misa_invoice_state': status['state'],
                'misa_invoice_last_checked': fields.Datetime.now(),
                'misa_invoice_request_refid': status.get('request_refid') or False,
                'misa_invoice_request_refno': status.get('master_refno') or False,
                'misa_invoice_no': status.get('invoice_no') or False,
            }
            # Nếu vòng quét lại phiếu đại diện ở trên (elif) VỪA gán "ăn theo" cho picking này
            # (đủ dòng hàng → misa_invoice_master_picking_id + amount=0 đã ghi), KHÔNG được ghi
            # đè tiền thô của MISA lên nữa — không thì lại xóa mất kết quả vừa xác minh đúng.
            if not picking.misa_invoice_master_picking_id:
                vals['misa_invoice_amount'] = status.get('invoice_amount') or 0.0
            invoice_date = status.get('invoice_date')
            if invoice_date:
                try:
                    vals['misa_invoice_date'] = fields.Date.to_date(invoice_date)
                except Exception:
                    _logger.warning("Không parse được ngày hóa đơn MISA: %s", invoice_date)

            old_state = picking.misa_invoice_state
            picking.write(vals)

            if old_state != status['state']:
                picking.message_post(
                    body=Markup("<b>Tình trạng xuất hóa đơn MISA:</b> %s → %s") % (
                        MISA_INVOICE_STATE_LABELS.get(old_state, old_state),
                        MISA_INVOICE_STATE_LABELS.get(status['state'], status['state']),
                    )
                )
            # Không tự đăng thông báo "gộp chung" ở đây nữa — quyết định gán "ăn theo" hay chỉ
            # cộng dồn 1 phần giờ hoàn toàn do _misa_invoice_discover_grouped_orders quyết định
            # (đã tự đăng thông báo riêng khi thật sự khớp), tránh đăng trùng/đăng nhầm khi chưa
            # xác minh xong dòng hàng.
            if picking.misa_invoice_amount_mismatch:
                picking.message_post(
                    body=Markup("<b>⚠️ Lệch tiền với MISA:</b> Odoo %.0f đ vs MISA %.0f đ (chênh %.0f đ)") % (
                        picking.misa_invoice_net_actual_amount or 0.0,
                        picking.misa_invoice_amount or 0.0,
                        picking.misa_invoice_amount_diff,
                    )
                )
            # LUÔN xác minh mức độ xuất HĐ THẬT theo ĐƠN HÀNG (đối chiếu qua order_code, không
            # quan tâm tên đề nghị) — xem _misa_invoice_reconcile_order_coverage. TRƯỚC ĐÂY chỉ
            # chạy khi bước refno nhanh KHÔNG xác nhận đủ (missing/mismatch), nên nếu MỌI phiếu
            # của 1 đơn tự nó đều báo 'invoiced' sạch (case thật: đơn dùng chung 1 đề nghị gộp
            # chỉ phủ 1 phần tổng đơn — DH...234620), _misa_invoice_exact_* trên sale.order
            # KHÔNG BAO GIỜ được tính, khiến tab 'Đơn hàng' báo "đã xuất đủ" sai. Đổi thành LUÔN
            # chạy (mọi phiếu có đơn hàng) để invoice_amount/outstanding_amount theo đơn luôn
            # chính xác tuyệt đối — ĐÁNH ĐỔI: THÊM 1-2 lệnh gọi MISA/đơn hàng MỖI LẦN kiểm tra
            # (nút thủ công, cron, batch) — đã cân nhắc và chấp nhận đánh đổi này.
            if picking.misa_invoice_sale_order_ids:
                try:
                    picking._misa_invoice_reconcile_order_coverage()
                except Exception:
                    _logger.exception(
                        "❌ [MISA ORDER COVERAGE] Lỗi xác minh mức độ xuất HĐ theo đơn cho phiếu %s", picking.name,
                    )
            # Chỉ phiếu ĐẠI DIỆN (không phải ăn theo ai, và MISA không báo có phiếu đại diện
            # nào khác) mới cần tự đọc chi tiết dòng hàng đề nghị để tìm đơn xuất kèm — nếu đã
            # phát hiện có phiếu đại diện khác (found_master_refno), nhường việc quét cho phiếu
            # đó (xem khối master_refno ở trên) để tránh 2 phiếu cùng 1 request_refid giành
            # nhau tự nhận là gốc.
            if (
                not found_master_refno and not picking.misa_invoice_master_picking_id
                and status['state'] == 'invoiced' and not picking.misa_invoice_group_checked
            ):
                try:
                    picking._misa_invoice_discover_grouped_orders()
                except Exception:
                    _logger.exception(
                        "❌ [MISA GROUP DISCOVER] Lỗi quét đơn xuất kèm cho phiếu %s", picking.name,
                    )
            results.append({
                'id': picking.id,
                'name': picking.name,
                'state': picking.misa_invoice_state,
                'state_label': MISA_INVOICE_STATE_LABELS.get(picking.misa_invoice_state, picking.misa_invoice_state),
            })
        if extra_masters_to_check:
            results += extra_masters_to_check.action_check_misa_invoice_status(request_map=request_map)
        (self | extra_masters_to_check)._misa_invoice_dedupe_request_refid_groups()
        return results

    def _misa_invoice_request_line_amount(self, lines):
        """Tiền CÓ VAT của 1 tập dòng hàng đề nghị xuất HĐ (get_invoice_request_lines) — mỗi
        dòng MISA trả sẵn amount_oc (chưa VAT), vat_amount_oc, discount_amount_oc riêng, nên
        cộng trực tiếp ra đúng tiền CÓ VAT, không cần suy đoán % thuế chung cho cả đề nghị."""
        return sum(
            (line.get('amount_oc') or 0.0) + (line.get('vat_amount_oc') or 0.0)
            - (line.get('discount_amount_oc') or 0.0)
            for line in lines
        )

    def _misa_invoice_sum_invoiced_for_order(self, order_code, exclude_refids=None):
        """Cộng dồn tổng tiền CÓ VAT đã xuất hóa đơn cho 1 đơn hàng, tính trên MỌI đề nghị xuất
        HĐ nhắc tới đơn đó hiện có trên MISA (không chỉ đề nghị đã biết) — dùng
        get_invoice_requests_for_order để tìm hết, rồi get_invoice_request_lines cho từng đề
        nghị CHƯA đọc. `exclude_refids` — bỏ qua các refid ĐÃ BIẾT (khỏi tính trùng, khỏi gọi
        lại API cho đề nghị đã đọc rồi). Trả về (tổng tiền, list nguồn [{refno, refid, amount}]).

        CHỈ nên gọi khi THẬT SỰ cần xác minh (còn thiếu / đang nghi vấn trùng) — tốn thêm 1 API
        tìm đề nghị + 1 API/đề nghị mới tìm được, không nên gọi tràn lan cho mọi đơn hàng."""
        misa_utils = self.env['misa.api.utils']
        exclude_refids = set(exclude_refids or [])
        total = 0.0
        sources = []
        try:
            requests_found = misa_utils.get_invoice_requests_for_order(order_code)
        except Exception:
            _logger.exception("❌ [MISA GAP VERIFY] Lỗi tìm đề nghị cho đơn %s", order_code)
            return 0.0, []
        for req in requests_found:
            refid = req.get('refid')
            if not refid or refid in exclude_refids:
                continue
            try:
                lines = misa_utils.get_invoice_request_lines(refid)
            except Exception:
                _logger.exception(
                    "❌ [MISA GAP VERIFY] Lỗi đọc chi tiết dòng hàng đề nghị %s (%s)", req.get('refno'), refid,
                )
                continue
            own_lines = [line for line in lines if (line.get('order_code') or '').strip() == order_code]
            if not own_lines:
                continue
            amount = self._misa_invoice_request_line_amount(own_lines)
            if amount > 0:
                total += amount
                sources.append({'refno': req.get('refno'), 'refid': refid, 'amount': amount})
        return total, sources

    def _misa_invoice_compute_order_coverage_detail(self, order_name, exclude_refids=None):
        """Tính (shipped, invoiced, sources) THẬT cho 1 ĐƠN HÀNG (theo order_code, không quan
        tâm tên đề nghị) — phần PLUMBING dùng CHUNG cho cả misa_invoice_order_coverage (field
        lưu trên phiếu) VÀ nhánh "đơn hàng khác nhắc tới trong đề nghị" của
        _misa_invoice_compute_group_breakdown (donut "vì sao lệch"), để 2 nơi cùng xuất phát
        từ 1 nguồn số liệu duy nhất (tránh gọi API 2 lần/khác điều kiện exclude_refids ra 2 kết
        quả lệch nhau).

        shipped = tổng tiền thực xuất của TOÀN BỘ phiếu (đã done) thuộc đơn này; invoiced =
        tổng tiền đã xuất HĐ qua MỌI đề nghị tìm được cho đơn này.

        `level` (none/partial/full) đi kèm chỉ dùng LÀM MẶC ĐỊNH cho field
        misa_invoice_order_coverage (ngưỡng LỎNG 1 CHIỀU: invoiced thừa vẫn tính 'full', vì
        field này chỉ trả lời "đã xuất đủ tiền chưa", không quan tâm thừa/thiếu). Chỗ nào cần
        phân biệt "khớp đúng" với "thừa/thiếu bất thường cần kiểm tra tay" (VD donut
        conflict/resolved_elsewhere) PHẢI tự so sánh shipped/invoiced bằng ngưỡng riêng
        (abs(invoiced - shipped) <= tolerance, ĐỐI XỨNG 2 CHIỀU), KHÔNG dùng field `level` này."""
        order = self.env['sale.order'].sudo().with_context(active_test=False).search(
            [('name', '=', order_name)], limit=1,
        )
        if not order:
            return {'level': 'none', 'shipped': 0.0, 'invoiced': 0.0, 'sources': []}
        order_pickings = self.sudo().search([
            ('misa_invoice_sale_order_ids', '=', order.id),
            ('picking_type_id.code', '=', 'outgoing'),
            ('state', '=', 'done'),
        ])
        shipped = sum(order_pickings.mapped('misa_invoice_net_actual_amount'))
        invoiced, sources = self._misa_invoice_sum_invoiced_for_order(order_name, exclude_refids=exclude_refids)
        if shipped <= MISA_INVOICE_AMOUNT_TOLERANCE:
            level = 'full' if invoiced > MISA_INVOICE_AMOUNT_TOLERANCE else 'none'
        elif invoiced <= MISA_INVOICE_AMOUNT_TOLERANCE:
            level = 'none'
        elif invoiced >= shipped - MISA_INVOICE_AMOUNT_TOLERANCE:
            level = 'full'
        else:
            level = 'partial'
        return {'level': level, 'shipped': shipped, 'invoiced': invoiced, 'sources': sources}

    def _misa_invoice_verify_order_via_other_requests(self, order_names, known_refids):
        """Với 1 PHIẾU đang thiếu xác nhận (shortfall > 0): chủ động hỏi MISA có đề nghị nào
        KHÁC (refid ngoài known_refids) cũng nhắc tới (các) đơn hàng của phiếu này không, cộng
        dồn tiền dòng hàng MỚI tìm được. Case thật KBC/OUT/10714 (đơn DH125524949233673): bị
        chia xác nhận qua 2 đề nghị HOÀN TOÀN riêng biệt — KBC/OUT/10677 (refid
        e1e15df5-ca04-4780-9577-a3e09b977fab) và KBC/OUT/10877 (refid
        024dc159-f8b8-4604-8452-2eb2b1190de6) — trước đây nếu chỉ biết 1 trong 2, phần còn lại
        bị báo NHẦM là "chưa xác nhận" dù thực ra đã có hóa đơn riêng.

        Trả về (tổng tiền CÓ VAT xác nhận thêm được, list nguồn [{refno, refid, amount}])."""
        total_extra = 0.0
        sources = []
        seen_refids = set(known_refids)
        for order_name in order_names:
            amount, order_sources = self._misa_invoice_sum_invoiced_for_order(order_name, exclude_refids=seen_refids)
            for s in order_sources:
                seen_refids.add(s['refid'])
            total_extra += amount
            sources.extend(order_sources)
        return total_extra, sources

    def _misa_invoice_order_coverage_is_simple(self, picking, order):
        """True nếu đơn này ĐƠN GIẢN tới mức không cần gọi API sống để đối chiếu: CHỈ có ĐÚNG 1
        phiếu xuất kho (không giao nhiều đợt), phiếu đó không "ăn theo" ai và không ai "ăn
        theo" nó (1 phiếu = đúng 1 đề nghị, không gộp chung với đơn nào khác), đã 'invoiced'
        sạch (không mismatch), và tiền hóa đơn đã phủ ĐỦ cả tiền thực xuất lẫn amount_total của
        đơn (đủ hàng, không phải xuất từng phần) — khi đó số của CHÍNH phiếu này chắc chắn cũng
        là số của đơn, tra lại qua API chỉ tốn thêm chi phí mà không đổi kết quả."""
        return (
            len(order.misa_invoice_picking_ids) == 1
            and not picking.misa_invoice_master_picking_id
            and not picking.misa_invoice_covered_picking_ids
            and picking.misa_invoice_state == 'invoiced'
            and not picking.misa_invoice_amount_mismatch
            and abs((picking.misa_invoice_net_actual_amount or 0.0) - order.amount_total) <= MISA_INVOICE_AMOUNT_TOLERANCE
            and abs((picking.misa_invoice_effective_amount or 0.0) - order.amount_total) <= MISA_INVOICE_AMOUNT_TOLERANCE
        )

    def _misa_invoice_reconcile_order_coverage(self):
        """Xác định mức độ xuất HĐ THẬT theo ĐƠN HÀNG (misa_invoice_order_coverage) — chạy MỌI
        LẦN action_check_misa_invoice_status xử lý 1 phiếu có đơn hàng (xem call site), để
        misa_invoice_exact_* trên sale.order luôn được cập nhật.

        Với MỖI đơn hàng của phiếu: nếu là case ĐƠN GIẢN (xem _misa_invoice_order_coverage_is_simple)
        — dùng THẲNG số sẵn có trên phiếu, KHÔNG gọi API (tiết kiệm chi phí cho phần lớn đơn,
        vốn chỉ giao 1 đợt/1 đề nghị/đủ hàng). Ngược lại (gộp chung/ăn theo/nhiều đợt giao/thiếu
        tiền) mới cộng dồn TẤT CẢ tiền đã xuất HĐ qua MỌI đề nghị nhắc tới đơn đó
        (_misa_invoice_sum_invoiced_for_order — không quan tâm tên đề nghị/refno) so với tổng
        tiền thực xuất của TOÀN BỘ phiếu thuộc đơn đó (không chỉ phiếu đang xét). 1 phiếu có thể
        có nhiều đơn hàng — lấy mức THẤP NHẤT trong các đơn (none < partial < full) làm mức
        chung cho phiếu, vì phiếu chỉ thật sự "đã xuất đủ" khi TẤT CẢ đơn của nó đều đã xuất
        đủ."""
        rank = {'none': 0, 'partial': 1, 'full': 2}
        for picking in self:
            orders = picking.misa_invoice_sale_order_ids
            if not orders:
                picking.misa_invoice_order_coverage = False
                continue
            worst = 'full'
            for order in orders:
                if self._misa_invoice_order_coverage_is_simple(picking, order):
                    order.write({
                        'misa_invoice_exact_shipped_amount': picking.misa_invoice_net_actual_amount or 0.0,
                        'misa_invoice_exact_invoiced_amount': picking.misa_invoice_effective_amount or 0.0,
                        'misa_invoice_exact_checked_at': fields.Datetime.now(),
                    })
                    continue
                detail = self._misa_invoice_compute_order_coverage_detail(order.name)
                # Lưu lại shipped/invoiced THẬT (trước đây chỉ giữ 'level' rồi vứt số) — để
                # _misa_invoice_order_row đọc thẳng, tính invoice_amount/outstanding_amount
                # CHÍNH XÁC tuyệt đối (không đếm trùng cross-order, không lẫn phần chưa giao
                # hàng) mà không cần gọi lại API lúc render/export. Xem sale_order.py.
                order.write({
                    'misa_invoice_exact_shipped_amount': detail['shipped'],
                    'misa_invoice_exact_invoiced_amount': detail['invoiced'],
                    'misa_invoice_exact_checked_at': fields.Datetime.now(),
                })
                if detail['shipped'] <= MISA_INVOICE_AMOUNT_TOLERANCE:
                    continue
                if rank[detail['level']] < rank[worst]:
                    worst = detail['level']
            picking.misa_invoice_order_coverage = worst

    def _misa_invoice_discover_grouped_orders(self):
        """Sau khi phiếu này được xác nhận 'invoiced' (không phải ăn theo ai) — đọc CHI TIẾT
        TỪNG DÒNG HÀNG của đề nghị xuất HĐ (get_invoice_request_lines, mỗi dòng có order_code
        riêng) để CHỦ ĐỘNG tìm đơn hàng KHÁC được xuất hóa đơn CHUNG trong cùng đề nghị này (VD
        sale gộp 2 đơn của cùng khách vào 1 đề nghị) — cơ chế master_refno chính (dựa vào MISA
        tự báo đúng TÊN phiếu đại diện) KHÔNG phát hiện được case này, vì phiếu của đơn kia
        không hề xuất hiện trong refno/journal_memo — chỉ lộ ra khi đọc order_code ở CHI TIẾT
        DÒNG HÀNG.

        QUAN TRỌNG (bài học từ case thật KBC/OUT/11016): 1 phiếu xuất kho có thể có NHIỀU sản
        phẩm, nhưng đề nghị xuất HĐ có thể CHỈ liệt kê 1 phần trong số đó cho đúng đơn hàng này
        (phần còn lại xuất HĐ ở 1 đề nghị KHÁC, hoặc chưa xuất) — nếu cứ thấy order_code xuất
        hiện là ép CẢ PHIẾU về "ăn theo" (amount=0), sẽ xóa mất dấu vết phần chưa rõ hóa đơn.
        Nên khớp theo TỪNG DÒNG HÀNG (mã hàng + số lượng, giống hệt kiến trúc hàng hải quan —
        misa.invoice.grouped.line/.match + _misa_invoice_reconcile_line_match): mỗi dòng hàng
        của đơn kia được ghi nhận riêng và khớp với move thực xuất của (các) phiếu thuộc đúng
        đơn đó (FIFO, trừ hàng trả, không đếm trùng số lượng đã khớp bởi dòng khác). Chỉ gán
        "ăn theo" (amount=0, coi hẳn là đã xuất HĐ) cho 1 phiếu khi tổng tiền đã khớp qua dòng
        hàng (misa_invoice_grouped_matched_amount) phủ ĐỦ tiền thực xuất ròng của phiếu đó —
        nếu chỉ khớp 1 PHẦN thì giữ nguyên trạng thái/số tiền hóa đơn riêng của phiếu, phần đã
        khớp chỉ được trừ vào "còn thiếu hóa đơn" (misa_invoice_effective_amount), không mất
        dấu vết phần chưa rõ hóa đơn.

        QUAN TRỌNG #2 (bài học thật KBC/OUT/10559): CHÍNH đơn hàng của phiếu đại diện cũng có
        thể được xuất kho thành NHIỀU ĐỢT/NHIỀU PHIẾU (VD KBC/OUT/10466 + KBC/OUT/10559 cùng 1
        đơn DH...233409) — trước đây các dòng hàng có order_code TRÙNG với đơn của chính phiếu
        này bị BỎ QUA hoàn toàn (giả định sai: 1 đơn = 1 phiếu), khiến phiếu còn lại (10466)
        không bao giờ được xét dù đã 'done' và cùng nằm trong hóa đơn. Giờ xử lý y hệt 1 đơn
        "gộp chung" bình thường, chỉ khác 1 điểm: khi khớp dòng hàng, PHẢI loại (exclude) chính
        phiếu đại diện khỏi tập ứng viên nhận số lượng khớp (exclude_picking_ids=[self.id]) —
        vì phiếu đại diện đã có tiền hóa đơn riêng qua misa_invoice_amount rồi, không được để
        thuật toán "khớp lại" số lượng của chính nó.

        Chỉ đọc get_invoice_request_lines 1 LẦN cho mỗi phiếu (misa_invoice_group_checked) —
        tránh gọi thêm 1 API MISA mỗi lần phiếu được kiểm tra lại, kể cả khi không tìm thấy gì
        thêm (đa số hóa đơn chỉ có 1 đơn, không có ai xuất kèm).

        KHÔNG được lặng lẽ bỏ qua đơn hàng nào (bài học thật: đề nghị của KBC/OUT/10603 nhắc
        tới 6 đơn hàng khác nhưng dashboard chỉ hiện gộp được 2 — không có gì báo cho biết 4
        đơn còn lại đang bị bỏ sót vì lý do gì). Với MỖI order_code tìm thấy trong đề nghị mà
        không gán/khớp được gì, phải ghi rõ LÝ DO cụ thể (không tìm thấy đơn bán / phiếu xuất
        kho chưa hoàn tất (chưa 'done') / phiếu đã bị 1 đề nghị KHÁC nhận trước) — và nếu lý do
        là "chưa hoàn tất" (rất có thể sẽ done sau), KHÔNG đánh dấu misa_invoice_group_checked
        — để lần quét sau (cron 30 phút) tự thử lại, chứ không mất dấu vết vĩnh viễn."""
        self.ensure_one()
        if self.misa_invoice_group_checked or not self.misa_invoice_request_refid or self.misa_invoice_master_picking_id:
            return
        own_order_names = set(self.misa_invoice_sale_order_ids.mapped('name'))
        misa_utils = self.env['misa.api.utils']
        try:
            lines = misa_utils.get_invoice_request_lines(self.misa_invoice_request_refid)
        except Exception:
            _logger.exception(
                "❌ [MISA GROUP DISCOVER] Lỗi đọc chi tiết dòng hàng đề nghị cho phiếu %s", self.name,
            )
            return
        lines_by_order = {}
        for line in lines:
            code = (line.get('order_code') or '').strip()
            if not code:
                continue
            lines_by_order.setdefault(code, []).append(line)
        if not lines_by_order:
            # Đề nghị không đọc được order_code nào cả — không có gì để tìm thêm, đánh dấu đã
            # quét NGAY để khỏi gọi lại API này mỗi lần cron chạy qua phiếu.
            self.misa_invoice_group_checked = True
            return

        GroupedLine = self.env['misa.invoice.grouped.line'].sudo()
        any_pending = False
        for order_code, order_lines in lines_by_order.items():
            is_own_order = order_code in own_order_names
            # active_test=False: đơn bán CŨ/đã hoàn tất có thể bị lưu trữ (active=False) — tìm
            # cả đơn đã lưu trữ, nếu không sẽ báo nhầm "không tìm thấy đơn bán" hàng loạt cho
            # các đơn thật ra có tồn tại, chỉ là đã cũ/lưu trữ (case thật: 3/10 đơn trong 1
            # nhóm gộp KBC/OUT/10779 bị báo "không tìm thấy" dù order_code đọc đúng từ MISA).
            order = self.env['sale.order'].sudo().with_context(active_test=False).search(
                [('name', '=', order_code)], limit=1,
            )
            if not order:
                if not is_own_order:
                    self.message_post(body=Markup(
                        "<b>⚠️ Không tìm thấy đơn bán cho đơn hàng nhắc tới trong đề nghị:</b> đề "
                        "nghị xuất HĐ của phiếu này có nhắc tới đơn %s nhưng không tìm thấy đơn bán "
                        "nào tên như vậy trong Odoo — cần kiểm tra tay (có thể sai mã đơn, hoặc đơn "
                        "ở phân hệ khác)."
                    ) % order_code)
                continue

            all_order_pickings = self.sudo().search([
                ('misa_invoice_sale_order_ids', '=', order.id),
                ('picking_type_id.code', '=', 'outgoing'),
                ('id', '!=', self.id),
            ])
            not_done = all_order_pickings.filtered(lambda p: p.state not in ('done', 'cancel'))
            done_pickings = all_order_pickings.filtered(lambda p: p.state == 'done')
            # Đã là 1 phần ĐÚNG của group này rồi (từ lần quét trước, hoặc qua dedupe theo
            # request_refid) — không phải "phiếu bị đề nghị KHÁC cướp mất", không cần báo gì.
            already_in_group = done_pickings.filtered(lambda p: p.misa_invoice_master_picking_id == self)
            # Chỉ nhận phiếu CHƯA có quan hệ gộp hợp lệ nào khác VÀ CHƯA tự có hóa đơn riêng —
            # không "cướp" phiếu đã là gốc/ăn theo của 1 đề nghị KHÁC (tránh phá vỡ 1 nhóm gộp
            # đúng đã có sẵn), và QUAN TRỌNG: không "cướp" luôn cả phiếu đã TỰ tìm thấy hóa đơn
            # ĐỘC LẬP của riêng nó (misa_invoice_state == 'invoiced', chỉ là chưa có
            # master/covered vì nó không "ăn theo" ai cả — nó CÓ hóa đơn RIÊNG). Bài học thật:
            # 1 đơn bán 2 cái, xuất 2 phiếu, mỗi phiếu có 1 đề nghị xuất HĐ RIÊNG BIỆT (không
            # liên quan gì nhau) — nếu không loại trừ, FIFO khớp dòng hàng có thể vô tình gán
            # nhầm phiếu đã có hóa đơn đúng của nó vào nhóm của phiếu khác.
            sibling_pickings = done_pickings.filtered(
                lambda p: not p.misa_invoice_master_picking_id and not p.misa_invoice_covered_picking_ids
                and p.misa_invoice_request_refid != self.misa_invoice_request_refid
                and p.misa_invoice_state != 'invoiced'
            )
            claimed_elsewhere = done_pickings - sibling_pickings - already_in_group

            if not sibling_pickings:
                if not_done:
                    # Rất có thể sẽ 'done' sau (đang soạn/đóng gói) — KHÔNG đánh dấu đã quét
                    # xong, để lần cron sau tự thử lại thay vì mất dấu vết vĩnh viễn.
                    any_pending = True
                    self.message_post(body=Markup(
                        "<b>⏳ Đơn hàng %s (nhắc tới trong đề nghị%s) có phiếu xuất kho CHƯA hoàn "
                        "tất:</b> %s — chưa thể đối soát ngay, hệ thống sẽ tự kiểm tra lại ở lần "
                        "quét sau khi phiếu đó hoàn tất."
                    ) % (
                        order_code, ' — cùng đơn với chính phiếu này' if is_own_order else '',
                        ', '.join('%s (%s)' % (p.name, STOCK_PICKING_STATE_LABELS.get(p.state, p.state)) for p in not_done),
                    ))
                elif claimed_elsewhere:
                    self.message_post(body=Markup(
                        "<b>⚠️ Đơn hàng %s (nhắc tới trong đề nghị%s) đã có hóa đơn ở nơi KHÁC:</b> "
                        "%s — có thể đã bị gộp vào 1 đề nghị khác, hoặc tự có đề nghị/hóa đơn RIÊNG "
                        "biệt (VD 1 đơn bán nhiều cái, xuất kho + xuất HĐ thành nhiều đợt độc lập — "
                        "trường hợp này là bình thường). Cần kiểm tra tay nếu nghi ngờ bị tính trùng."
                    ) % (
                        order_code, ' — cùng đơn với chính phiếu này' if is_own_order else '',
                        ', '.join(claimed_elsewhere.mapped('name')),
                    ))
                elif not is_own_order and not all_order_pickings:
                    self.message_post(body=Markup(
                        "<b>⚠️ Chưa có phiếu xuất kho nào cho đơn hàng %s (nhắc tới trong đề "
                        "nghị):</b> có thể chưa xuất kho, hoặc phiếu chưa được đồng bộ đơn bán "
                        "đúng — cần kiểm tra tay."
                    ) % order_code)
                # else: already_in_group phủ hết done_pickings (đã xử lý đúng từ trước), hoặc là
                # đơn CHÍNH của phiếu này mà không có phiếu nào khác (trường hợp bình thường, 1
                # đơn = 1 phiếu) — không có gì mới để báo, im lặng bỏ qua (không phải lỗi).
                continue

            created_lines = GroupedLine.browse()
            for order_line in order_lines:
                item_code = (order_line.get('inventory_item_code') or '').strip()
                quantity = order_line.get('quantity') or 0.0
                unit_price = order_line.get('unit_price') or 0.0
                # Khóa dedup để idempotent khi bị quét lại (không phải chỉ chạy 1 lần tuyệt đối
                # — repair_misa_invoice_grouped_order có thể gọi lại nếu cần): không tạo trùng
                # dòng hàng đã ghi nhận từ 1 lần quét trước đó của CHÍNH phiếu đại diện này.
                # So gần đúng (không '=' tuyệt đối) để tránh tạo trùng dòng hàng vì sai số làm
                # tròn float khi round-trip qua JSON giữa các lần gọi API MISA.
                existing_candidates = GroupedLine.search([
                    ('master_picking_id', '=', self.id),
                    ('order_code', '=', order_code),
                    ('inventory_item_code', '=', item_code),
                ])
                existing = existing_candidates.filtered(
                    lambda l: abs(l.quantity - quantity) < 0.01 and abs(l.unit_price - unit_price) < 0.01
                )[:1]
                if existing:
                    created_lines |= existing
                    continue
                created_lines |= GroupedLine.create({
                    'master_picking_id': self.id,
                    'sale_order_id': order.id if order else False,
                    'order_code': order_code,
                    'inventory_item_code': item_code,
                    'description': order_line.get('description') or '',
                    'quantity': quantity,
                    'unit_price': unit_price,
                    'amount_oc': order_line.get('amount_oc') or 0.0,
                    'vat_amount_oc': order_line.get('vat_amount_oc') or 0.0,
                    'discount_amount_oc': order_line.get('discount_amount_oc') or 0.0,
                    'fetched_at': fields.Datetime.now(),
                })
            # Đơn CHÍNH của phiếu đại diện (is_own_order) được xuất kho thêm ở (các) phiếu KHÁC
            # — phiếu đại diện ĐÃ có tiền hóa đơn riêng qua misa_invoice_amount rồi, phải loại
            # chính nó khỏi tập ứng viên nhận số lượng khớp, nếu không thuật toán FIFO có thể
            # "khớp lại" nhầm số lượng của chính phiếu đại diện (case KBC/OUT/10559/10466).
            exclude_ids = [self.id] if is_own_order else None
            for gline in created_lines:
                try:
                    self._misa_invoice_grouped_try_match(gline, exclude_picking_ids=exclude_ids)
                except Exception:
                    _logger.exception(
                        "❌ [MISA GROUP DISCOVER] Lỗi khớp dòng hàng xuất HĐ chung (%s / %s) cho phiếu %s",
                        order_code, gline.inventory_item_code, self.name,
                    )

            sibling_pickings.invalidate_recordset(['misa_invoice_grouped_matched_amount'])
            newly_covered = self.env['stock.picking']
            partially_covered = self.env['stock.picking']
            for sibling in sibling_pickings:
                if sibling.misa_invoice_state == 'invoiced':
                    continue  # đã có hóa đơn riêng (kênh khác) — không đụng tới
                matched = sibling.misa_invoice_grouped_matched_amount
                target = sibling.misa_invoice_net_actual_amount
                if matched <= 0.01:
                    continue
                if target > 0 and matched >= target - MISA_INVOICE_AMOUNT_TOLERANCE:
                    sibling.write({
                        'misa_invoice_master_picking_id': self.id,
                        'misa_invoice_state': 'invoiced',
                        'misa_invoice_amount': 0.0,
                        'misa_invoice_no': self.misa_invoice_no,
                        'misa_invoice_date': self.misa_invoice_date,
                        'misa_invoice_request_refid': self.misa_invoice_request_refid,
                        'misa_invoice_request_refno': self.misa_invoice_request_refno,
                        'misa_invoice_last_checked': fields.Datetime.now(),
                        'misa_invoice_group_checked': True,
                    })
                    sibling.message_post(
                        body=Markup(
                            "<b>🔗 Tự động phát hiện xuất HĐ chung:</b> đơn hàng của phiếu này được "
                            "xuất hóa đơn CHUNG với phiếu %s (khớp ĐỦ theo từng dòng hàng) — đã gán "
                            "'ăn theo' phiếu đó, số hóa đơn %s."
                        ) % (self.name, self.misa_invoice_no or '')
                    )
                    newly_covered |= sibling
                else:
                    sibling.message_post(
                        body=Markup(
                            "<b>⚠️ Xuất HĐ MỘT PHẦN qua đề nghị chung:</b> đề nghị của phiếu %s có "
                            "phủ 1 phần giá trị của phiếu này (đã khớp %s/%s đ theo dòng hàng) — "
                            "phần đã khớp được trừ vào số tiền còn thiếu hóa đơn, phần còn lại vẫn "
                            "cần đề nghị/hóa đơn riêng. Xem chi tiết dòng hàng đã khớp ở "
                            "misa.invoice.grouped.line."
                        ) % (self.name, matched, target)
                    )
                    partially_covered |= sibling

            if newly_covered:
                self.message_post(
                    body=Markup(
                        "<b>🔗 Tự động phát hiện xuất HĐ chung (khớp đủ theo dòng hàng):</b> đề nghị "
                        "này xuất kèm ĐỦ cho đơn %s — đã gán các phiếu sau làm 'ăn theo': %s."
                    ) % (order_code, ', '.join(newly_covered.mapped('name')))
                )
            if partially_covered:
                self.message_post(
                    body=Markup(
                        "<b>⚠️ Xuất HĐ MỘT PHẦN cho đơn %s (đã ghi nhận theo dòng hàng):</b> chỉ "
                        "phủ 1 phần giá trị của: %s — không tự động gán 'ăn theo', phần còn thiếu "
                        "vẫn cần đề nghị/hóa đơn riêng."
                    ) % (order_code, ', '.join(partially_covered.mapped('name')))
                )

        # Chỉ đánh dấu "đã quét xong" khi KHÔNG còn đơn hàng nào đang chờ (phiếu xuất kho của
        # nó chưa 'done') — nếu còn, để nguyên False để lần quét sau (cron 30 phút,
        # action_check_misa_invoice_status) tự thử lại, không mất dấu vết vĩnh viễn.
        if not any_pending:
            self.misa_invoice_group_checked = True

        # Tận dụng luôn `lines` vừa đọc (không tốn thêm API MISA) để cập nhật lý do lệch —
        # hiện ngay trong danh sách "Đối chiếu tổng" mà không cần mở drawer từng phiếu.
        self.invalidate_recordset(['misa_invoice_covered_picking_ids', 'misa_invoice_amount_mismatch'])
        try:
            self._misa_invoice_refresh_gap_summary(
                misa_lines=lines, group_pickings=self | self.misa_invoice_covered_picking_ids,
            )
        except Exception:
            _logger.exception("❌ [MISA GAP SUMMARY] Lỗi cập nhật lý do lệch cho phiếu %s", self.name)

    def _misa_invoice_grouped_orders_domain(self):
        return [
            ('picking_type_id.code', '=', 'outgoing'),
            ('misa_invoice_state', '=', 'invoiced'),
            ('misa_invoice_master_picking_id', '=', False),
            ('misa_invoice_request_refid', '!=', False),
            ('misa_invoice_group_checked', '=', False),
        ]

    @api.model
    def scan_misa_invoice_grouped_orders(self, limit=100):
        """Quét các phiếu ĐÃ 'invoiced' (không ăn theo ai) nhưng CHƯA từng được kiểm tra xem đề
        nghị xuất HĐ của nó có xuất kèm đơn nào khác không — 1 lệnh XỬ LÝ NGẦM cả lô, dùng cho
        migration backfill (migrations/1.4), KHÔNG dùng cho nút bấm trên dashboard nữa (không
        có tiến độ hiện ra giữa chừng, phiếu nào cũng phải gọi thêm 1 API MISA nên với lô 100
        phiếu có thể mất vài phút mà không thấy gì — xem get_misa_invoice_grouped_orders_candidates
        + check_misa_invoice_grouped_order để hiện tiến độ từng phiếu)."""
        Picking = self.sudo()
        candidates = Picking.search(self._misa_invoice_grouped_orders_domain(), limit=limit)
        discovered_total = 0
        for picking in candidates:
            try:
                before = len(picking.misa_invoice_covered_picking_ids)
                picking._misa_invoice_discover_grouped_orders()
                picking.invalidate_recordset(['misa_invoice_covered_picking_ids'])
                discovered_total += len(picking.misa_invoice_covered_picking_ids) - before
            except Exception:
                _logger.exception("❌ [MISA GROUP DISCOVER] Lỗi quét phiếu %s", picking.name)
        return {'checked': len(candidates), 'discovered': discovered_total}

    @api.model
    def get_misa_invoice_grouped_orders_candidates(self, limit=100):
        """Danh sách phiếu SẼ được quét (chưa gọi MISA) — dùng để dashboard chạy từng phiếu một
        và hiện tiến trình thực qua check_misa_invoice_grouped_order(), giống hệt cách
        get_misa_invoice_scan_candidates() làm cho nút 'Kiểm tra MISA ngay'."""
        Picking = self.sudo()
        domain = self._misa_invoice_grouped_orders_domain()
        pickings = Picking.search(domain, limit=limit)
        return {
            'candidates': [{'id': p.id, 'name': p.name} for p in pickings],
            'total': Picking.search_count(domain),
        }

    @api.model
    def check_misa_invoice_grouped_order(self, picking_id):
        """Quét đơn xuất kèm cho ĐÚNG 1 phiếu — gọi lặp lại từ dashboard (1 lệnh/phiếu) để hiện
        tiến độ thực, thay vì 1 lệnh lớn xử lý ngầm cả trăm phiếu không thấy gì giữa chừng."""
        picking = self.sudo().browse(picking_id)
        if not picking.exists():
            return {'error': 'Phiếu này không còn tồn tại.'}
        try:
            before = picking.misa_invoice_covered_picking_ids
            picking._misa_invoice_discover_grouped_orders()
            picking.invalidate_recordset(['misa_invoice_covered_picking_ids'])
            after = picking.misa_invoice_covered_picking_ids
            new_covered = after - before
            return {'discovered_count': len(new_covered), 'discovered_names': new_covered.mapped('name')}
        except Exception as e:
            _logger.exception("❌ [MISA GROUP DISCOVER] Lỗi quét phiếu %s", picking.name)
            return {'error': str(e)}

    def _misa_invoice_grouped_orders_repair_domain(self):
        return [
            ('picking_type_id.code', '=', 'outgoing'),
            ('misa_invoice_state', '=', 'invoiced'),
            ('misa_invoice_master_picking_id', '=', False),
            ('misa_invoice_covered_picking_ids', '!=', False),
            ('misa_invoice_request_refid', '!=', False),
            ('misa_invoice_group_repaired', '=', False),
        ]

    @api.model
    def get_misa_invoice_grouped_orders_repair_candidates(self, limit=100):
        """Danh sách phiếu ĐẠI DIỆN (có phiếu ăn theo) cần kiểm tra lại xem có bị gán SAI bởi
        phiên bản CŨ của _misa_invoice_discover_grouped_orders không (ép cả phiếu ăn theo về đã
        xuất HĐ dù đề nghị chỉ phủ 1 PHẦN giá trị của nó — case thật KBC/OUT/11016: xuất 3 sản
        phẩm nhưng đề nghị chỉ phủ đúng 1). Dùng cho panel tiến độ trên dashboard, giống hệt
        get_misa_invoice_grouped_orders_candidates."""
        Picking = self.sudo()
        domain = self._misa_invoice_grouped_orders_repair_domain()
        pickings = Picking.search(domain, limit=limit)
        return {
            'candidates': [{'id': p.id, 'name': p.name} for p in pickings],
            'total': Picking.search_count(domain),
        }

    @api.model
    def repair_misa_invoice_grouped_order(self, picking_id):
        """Kiểm tra lại 1 phiếu đại diện — đọc lại chi tiết dòng hàng đề nghị xuất HĐ và trả các
        phiếu ăn theo bị gán SAI (chỉ khớp 1 PHẦN giá trị đơn hàng, không phải toàn bộ) về trạng
        thái CŨ để đối soát lại từ đầu bằng logic mới (khớp đủ theo dòng hàng)."""
        master = self.sudo().browse(picking_id)
        if not master.exists():
            return {'error': 'Phiếu này không còn tồn tại.'}
        if not master.misa_invoice_request_refid:
            master.misa_invoice_group_repaired = True
            return {'reverted_count': 0, 'reverted_names': []}
        misa_utils = self.env['misa.api.utils']
        try:
            lines = misa_utils.get_invoice_request_lines(master.misa_invoice_request_refid)
        except Exception as e:
            _logger.exception("❌ [MISA GROUP REPAIR] Lỗi đọc chi tiết dòng hàng cho phiếu %s", master.name)
            return {'error': str(e)}

        master.misa_invoice_group_repaired = True
        own_order_names = set(master.misa_invoice_sale_order_ids.mapped('name'))
        lines_by_order = {}
        for line in lines:
            code = (line.get('order_code') or '').strip()
            if not code or code in own_order_names:
                continue
            lines_by_order.setdefault(code, []).append(line)

        reverted = self.env['stock.picking']
        for covered in master.misa_invoice_covered_picking_ids:
            covered_orders = [
                name for name in covered.misa_invoice_sale_order_ids.mapped('name')
                if name in lines_by_order
            ]
            if not covered_orders:
                # Phiếu này được gán 'ăn theo' bằng cơ chế khác (master_refno chuẩn hoặc dedupe
                # theo request_refid) — không thuộc phạm vi lỗi đang sửa, không đụng tới.
                continue
            order_line_amount = master._misa_invoice_request_line_amount(
                [line for name in covered_orders for line in lines_by_order[name]]
            )
            if abs((covered.misa_invoice_net_actual_amount or 0.0) - order_line_amount) <= MISA_INVOICE_AMOUNT_TOLERANCE:
                continue  # khớp đủ thật, giữ nguyên
            covered.write({
                'misa_invoice_master_picking_id': False,
                'misa_invoice_state': 'not_checked',
                'misa_invoice_amount': 0.0,
                'misa_invoice_no': False,
                'misa_invoice_date': False,
                'misa_invoice_request_refid': False,
                'misa_invoice_group_checked': False,
            })
            covered.message_post(body=Markup(
                "<b>⚠️ Đã sửa lại (gộp sai trước đó):</b> phiếu này từng bị gán 'ăn theo' phiếu %s "
                "do lỗi phiên bản cũ (chỉ khớp 1 PHẦN đơn hàng nhưng ép cả phiếu về đã xuất HĐ) — "
                "đã trả về 'Chưa kiểm tra' để đối soát lại đúng bằng logic mới."
            ) % master.name)
            reverted |= covered

        if reverted:
            master.message_post(body=Markup(
                "<b>⚠️ Đã sửa gộp sai:</b> phát hiện %s phiếu ăn theo trước đây bị gán SAI (chỉ "
                "khớp 1 phần đơn hàng) — đã trả về trạng thái cũ để đối soát lại: %s."
            ) % (len(reverted), ', '.join(reverted.mapped('name'))))
            # Cho phép quét lại đề nghị này bằng logic MỚI (khớp theo dòng hàng, ghi nhận cả
            # phần khớp MỘT PHẦN qua misa.invoice.grouped.line thay vì chỉ khớp-đủ-hoặc-bỏ-qua)
            # — nếu không reset cờ này, master coi như "đã quét" (từ lần chạy CŨ) nên sẽ không
            # bao giờ tự chạy lại _misa_invoice_discover_grouped_orders nữa.
            master.misa_invoice_group_checked = False
            try:
                master._misa_invoice_discover_grouped_orders()
            except Exception:
                _logger.exception(
                    "❌ [MISA GROUP REPAIR] Lỗi quét lại (logic mới) đề nghị của phiếu %s", master.name,
                )
        return {'reverted_count': len(reverted), 'reverted_names': reverted.mapped('name')}

    @api.model
    def repair_misa_invoice_grouped_orders(self, limit=100):
        """Bản batch không hiện tiến độ — dùng cho migration backfill (migrations/1.5). Dùng
        get_misa_invoice_grouped_orders_repair_candidates + repair_misa_invoice_grouped_order
        cho nút bấm trên dashboard (hiện tiến độ từng phiếu)."""
        Picking = self.sudo()
        candidates = Picking.search(self._misa_invoice_grouped_orders_repair_domain(), limit=limit)
        total_reverted = 0
        for picking in candidates:
            try:
                result = picking.repair_misa_invoice_grouped_order(picking.id)
                total_reverted += result.get('reverted_count', 0)
            except Exception:
                _logger.exception("❌ [MISA GROUP REPAIR] Lỗi sửa phiếu %s", picking.name)
        return {'checked': len(candidates), 'reverted': total_reverted}

    def _misa_invoice_missing_no_repair_domain(self):
        return [
            ('picking_type_id.code', '=', 'outgoing'),
            ('misa_invoice_state', '=', 'invoiced'),
            ('misa_invoice_master_picking_id', '=', False),
            '|',
            ('misa_invoice_no', '=', False),
            ('misa_invoice_request_refno', '=', False),
            ('misa_invoice_no_repaired', '=', False),
        ]

    @api.model
    def get_misa_invoice_missing_no_repair_candidates(self, limit=100):
        """Danh sách phiếu ĐẠI DIỆN đang 'Đã xuất HĐ' nhưng thiếu Số HĐ/Số đề nghị — dữ liệu cũ
        bị ghi thiếu do 1 đợt code lỗi trước đây (commit 0415820cd vô tình revert mất 1 đoạn xử
        lý — case thật KBC/OUT/12440: live check lại ra đủ dữ liệu ngay, chứng tỏ code hiện tại
        đúng, chỉ là DỮ LIỆU CŨ bị đóng băng sai lúc code lỗi còn chạy). Dùng cho panel tiến độ
        trên dashboard, giống hệt get_misa_invoice_grouped_orders_repair_candidates."""
        Picking = self.sudo()
        domain = self._misa_invoice_missing_no_repair_domain()
        pickings = Picking.search(domain, limit=limit)
        return {
            'candidates': [{'id': p.id, 'name': p.name} for p in pickings],
            'total': Picking.search_count(domain),
        }

    @api.model
    def repair_misa_invoice_missing_no(self, picking_id):
        """Kiểm tra lại 1 phiếu đại diện đang thiếu Số HĐ/Số đề nghị — action_check_misa_invoice_status
        hiện tại (đã đúng) sẽ tự điền lại đầy đủ. Nếu phiếu này có "ăn theo" cũng đang thiếu
        (kế thừa từ đại diện lúc dữ liệu còn sai), đồng bộ luôn xuống — không cần đợi các phiếu
        đó tự lọt vào 1 lượt quét khác."""
        picking = self.sudo().browse(picking_id)
        if not picking.exists():
            return {'error': 'Phiếu này không còn tồn tại.'}
        try:
            picking.action_check_misa_invoice_status()
        except Exception as e:
            _logger.exception("❌ [MISA REPAIR NO] Lỗi kiểm tra lại phiếu %s", picking.name)
            return {'error': str(e)}
        picking.misa_invoice_no_repaired = True
        fixed = bool(picking.misa_invoice_no and picking.misa_invoice_request_refno)
        covered_fixed_names = []
        if fixed and picking.misa_invoice_covered_picking_ids:
            missing_covered = picking.misa_invoice_covered_picking_ids.filtered(
                lambda p: not p.misa_invoice_no or not p.misa_invoice_request_refno
            )
            if missing_covered:
                missing_covered.write({
                    'misa_invoice_no': picking.misa_invoice_no,
                    'misa_invoice_date': picking.misa_invoice_date,
                    'misa_invoice_request_refid': picking.misa_invoice_request_refid,
                    'misa_invoice_request_refno': picking.misa_invoice_request_refno,
                    'misa_invoice_no_repaired': True,
                })
                covered_fixed_names = missing_covered.mapped('name')
        return {
            'fixed': fixed,
            'covered_fixed_names': covered_fixed_names,
            'state': picking.misa_invoice_state,
            'state_label': MISA_INVOICE_STATE_LABELS.get(picking.misa_invoice_state, picking.misa_invoice_state),
        }

    def _misa_invoice_master_chain_domain(self):
        # 2 điều kiện quan hệ liên tiếp (master_picking_id.master_picking_id) — Odoo hỗ trợ
        # domain xuyên quan hệ Many2one nhiều tầng, tự JOIN.
        return [
            ('misa_invoice_master_picking_id', '!=', False),
            ('misa_invoice_master_picking_id.misa_invoice_master_picking_id', '!=', False),
        ]

    @api.model
    def get_misa_invoice_master_chain_candidates(self, limit=100):
        """Danh sách phiếu đang bị gán LỒNG NHAU (chain 2+ tầng, VD KBC/OUT/08194 → 09106 →
        08437) — case thật: tiền của phiếu bị "chôn" ở tầng giữa, không cộng vào tổng đối soát
        của phiếu đại diện thật sự. Dùng cho panel tiến độ trên dashboard."""
        Picking = self.sudo()
        domain = self._misa_invoice_master_chain_domain()
        pickings = Picking.search(domain, limit=limit)
        return {
            'candidates': [{'id': p.id, 'name': p.name} for p in pickings],
            'total': Picking.search_count(domain),
        }

    @api.model
    def flatten_misa_invoice_master_chain(self, picking_id):
        """Trỏ THẲNG 1 phiếu về đúng phiếu gốc CUỐI CÙNG (root) của chain — bất kể chain dài
        bao nhiêu tầng (phòng hờ, dù thực tế chỉ mới gặp chain 2 tầng)."""
        picking = self.sudo().browse(picking_id)
        if not picking.exists():
            return {'error': 'Phiếu này không còn tồn tại.'}
        if not picking.misa_invoice_master_picking_id:
            return {'flattened': False}
        old_master = picking.misa_invoice_master_picking_id
        root = old_master
        seen = {picking.id}
        while root.misa_invoice_master_picking_id and root.id not in seen:
            seen.add(root.id)
            root = root.misa_invoice_master_picking_id
        if root.id == old_master.id:
            return {'flattened': False}  # đã thẳng hàng, không có gì để sửa
        picking.write({
            'misa_invoice_master_picking_id': root.id,
            'misa_invoice_amount': 0.0,
            'misa_invoice_no': root.misa_invoice_no,
            'misa_invoice_date': root.misa_invoice_date,
            'misa_invoice_request_refid': root.misa_invoice_request_refid,
            'misa_invoice_request_refno': root.misa_invoice_request_refno,
            'misa_invoice_last_checked': fields.Datetime.now(),
        })
        picking.message_post(body=Markup(
            "<b>🔗 Sửa gán lồng nhau (chain):</b> phiếu này trước đó bị gán 'ăn theo' phiếu %s — "
            "nhưng %s CHÍNH NÓ cũng đang 'ăn theo' phiếu %s, khiến tiền của phiếu này bị 'chôn' 1 "
            "tầng, không cộng vào tổng đối soát. Đã trỏ thẳng về phiếu gốc thật sự: %s."
        ) % (old_master.name, old_master.name, root.name, root.name))
        return {'flattened': True, 'root_name': root.name}

    @api.model
    def flatten_misa_invoice_master_chains(self, limit=200):
        """Bản batch không hiện tiến độ — dùng cho migration/cron. Dùng
        get_misa_invoice_master_chain_candidates + flatten_misa_invoice_master_chain cho nút
        bấm trên dashboard (hiện tiến độ từng phiếu)."""
        Picking = self.sudo()
        candidates = Picking.search(self._misa_invoice_master_chain_domain(), limit=limit)
        total_flattened = 0
        for picking in candidates:
            try:
                result = picking.flatten_misa_invoice_master_chain(picking.id)
                if result.get('flattened'):
                    total_flattened += 1
            except Exception:
                _logger.exception("❌ [MISA CHAIN REPAIR] Lỗi sửa phiếu %s", picking.name)
        return {'checked': len(candidates), 'flattened': total_flattened}

    def _misa_invoice_dedupe_request_refid_groups(self, request_refids=None):
        """Lưới an toàn dự phòng cho việc gộp hóa đơn: cơ chế gộp chính (master_refno, xem
        action_check_misa_invoice_status ở trên) dựa vào MISA tự báo đúng TÊN phiếu đại diện —
        nếu MISA lưu refno của đề nghị/hóa đơn KHÔNG khớp tên phiếu Odoo nào (VD kế toán tự đặt
        mã khi tạo hóa đơn gộp), việc tìm phiếu gốc thất bại và MỖI phiếu cùng match vào hóa đơn
        đó sẽ tự ghi ĐỦ 100% tiền hóa đơn cho riêng mình — tính trùng N lần cho 1 hóa đơn duy
        nhất (N = số phiếu bị match nhầm).

        misa_invoice_request_refid (mã nội bộ MISA, không phải text refno dễ lệch) vẫn được ghi
        ĐÚNG và GIỐNG NHAU ở mọi phiếu cùng 1 hóa đơn dù master_refno có khớp hay không — dùng
        nó làm khóa gộp dự phòng: nếu có >=2 phiếu 'invoiced' cùng request_refid mà CHƯA phiếu
        nào được gán quan hệ gộp hợp lệ, tự chọn 1 làm đại diện (ưu tiên phiếu đã sẵn có quan hệ
        gộp nếu có, không thì phiếu xuất kho SỚM NHẤT) và trả tiền hóa đơn của các phiếu còn lại
        về 0, trỏ chúng về đúng phiếu đại diện đó.

        QUAN TRỌNG (bài học thật KBC/OUT/08194 → 09106 → 08437): TẤT CẢ phiếu cùng
        request_refid phải được trỏ THẲNG về CÙNG 1 đại diện — không chỉ những phiếu đang
        "ungrouped" (chưa có quan hệ gì). Nếu 1 phiếu trong nhóm ĐÃ là đại diện cho phiếu KHÁC
        (có covered_picking_ids riêng, VD 09106 từng tự gộp 08194 trước khi được elect làm
        'phiếu đại diện' của 1 request khác) mà chỉ trỏ MASTER của phiếu đó sang đại diện mới,
        không trỏ luôn các CON của nó — sẽ tạo ra CHAIN 2 tầng (08194→09106→08437) khiến tiền
        của 08194 bị "chôn" 1 tầng, không cộng vào tổng đối soát của đại diện thật sự. Nên phải
        flatten CẢ NHÓM (mọi phiếu trừ đại diện được chọn) về thẳng đại diện đó trong 1 lượt,
        bất kể trạng thái gộp hiện tại của từng phiếu là gì."""
        Picking = self.env['stock.picking'].sudo()
        if request_refids is None:
            request_refids = self.mapped('misa_invoice_request_refid')
        request_refids = sorted({r for r in request_refids if r})
        for refid in request_refids:
            group = Picking.search([
                ('misa_invoice_request_refid', '=', refid),
                ('misa_invoice_state', '=', 'invoiced'),
            ])
            if len(group) < 2:
                continue
            already_linked = group.filtered(
                lambda p: p.misa_invoice_master_picking_id or p.misa_invoice_covered_picking_ids
            )
            existing_master = next(
                (p.misa_invoice_master_picking_id for p in already_linked if p.misa_invoice_master_picking_id),
                self.browse(),
            )
            if existing_master:
                master = existing_master
            else:
                # Chưa ai trong nhóm được elect làm đại diện — ưu tiên phiếu ĐÃ là đại diện cho
                # phiếu khác trong CHÍNH nhóm này (giữ ổn định quan hệ đã có), không thì lấy
                # phiếu xuất kho SỚM NHẤT.
                sub_masters = group.filtered(lambda p: p.misa_invoice_covered_picking_ids)
                candidates = sub_masters or group
                if len(candidates) < 2 and not sub_masters and len(group) < 2:
                    continue
                master = candidates.sorted(key=lambda p: (p.date_done or p.create_date, p.id))[0]
            covered = group - master
            if not covered:
                continue  # đã đúng, không có gì lệch tầng để sửa
            covered.write({
                'misa_invoice_master_picking_id': master.id,
                'misa_invoice_amount': 0.0,
                'misa_invoice_no': master.misa_invoice_no,
                'misa_invoice_date': master.misa_invoice_date,
                'misa_invoice_request_refid': refid,
                'misa_invoice_request_refno': master.misa_invoice_request_refno,
            })
            note = Markup(
                "<b>🔗 Tự động gộp hóa đơn trùng:</b> phát hiện các phiếu này cùng khớp 1 hóa đơn MISA "
                "(request_refid trùng nhau) nhưng MISA không báo đúng tên phiếu đại diện lúc kiểm tra, "
                "khiến mỗi phiếu tự ghi đủ 100%% tiền hóa đơn — đã tự gộp lại về phiếu %s để không tính "
                "trùng tiền hóa đơn (trỏ THẲNG về đại diện, không qua trung gian)."
            ) % master.name
            for c in covered:
                c.message_post(body=note)
            master.message_post(
                body=Markup(
                    "<b>🔗 Tự động gộp hóa đơn trùng:</b> phát hiện %s phiếu khác cùng khớp hóa đơn này "
                    "(MISA không báo đúng tên phiếu đại diện) — đã tự gộp về phiếu này: %s."
                ) % (len(covered), ', '.join(covered.mapped('name')))
            )

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

        try:
            self.scan_misa_invoice_grouped_orders(limit=MISA_INVOICE_GROUP_SCAN_BATCH_SIZE)
        except Exception:
            _logger.exception("❌ [MISA GROUP DISCOVER CRON] Lỗi quét bù đơn xuất kèm")

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
        cả 2 luồng lại (MISA + Shopee) mà không đếm trùng hay bỏ sót phiếu nào.

        Phiếu có trả hàng KHÔNG bị loại khỏi domain này — vẫn hiện bình thường ở mọi tab/tổng
        đối soát như các phiếu khác, chỉ khác là tiền hóa đơn dùng để so sánh là
        misa_invoice_effective_amount (coi như kế toán đã điều chỉnh xuống đúng bằng tiền thực
        xuất ròng) thay vì misa_invoice_amount thô — xem _compute_misa_invoice_effective_amount.
        Tab riêng "Trả hàng / Điều chỉnh" (xem _misa_invoice_returns_domain) chỉ là 1 bộ lọc
        thêm để xem nhanh các phiếu này, không phải nơi duy nhất chúng xuất hiện."""
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

    def _misa_invoice_customs_summary(self, date_from=False, date_to=False, saler_code=False):
        """Tổng hợp toàn bộ dòng hải quan khớp bộ lọc (theo NGÀY HÓA ĐƠN, vì dòng pending chưa
        chắc đã có phiếu xuất kho/date_done nào) — dùng cho tile 'Đơn hải quan' trong thống kê
        đối soát. matched_amount = phần tiền ĐÃ được cộng vào misa_invoiced_amount thông qua
        match_ids (picking.misa_invoice_amount) — chỉ cộng pending_amount (phần CHƯA phản ánh
        qua picking nào) vào tổng chung, tránh đếm trùng 2 lần cho phần đã khớp."""
        Lines = self.env['misa.invoice.customs.line'].sudo()
        domain = []
        if date_from:
            domain.append(('invoice_date', '>=', date_from))
        if date_to:
            domain.append(('invoice_date', '<=', date_to))
        if saler_code:
            value = False if saler_code == MISA_INVOICE_UNASSIGNED_SALER else saler_code
            domain.append(('employee_code', '=', value))
        lines = Lines.search(domain)
        matched_amount = sum(lines.mapped('match_ids.amount'))
        total_amount = sum(lines.mapped('amount'))
        matched_lines = lines.filtered(lambda l: l.match_state == 'matched')
        return {
            'total_count': len(lines),
            'matched_count': len(matched_lines),
            'pending_count': len(lines) - len(matched_lines),
            'total_amount': total_amount,
            'matched_amount': matched_amount,
            'pending_amount': total_amount - matched_amount,
        }

    @api.model
    def get_misa_invoice_reconciliation_totals(self, date_from=False, date_to=False, saler_code=False):
        """Số liệu đối chiếu tổng: Tổng tiền xuất kho (MISA + Shopee + Hải quan gộp lại) =
        tiền đã xuất HĐ MISA + tiền đã xuất HĐ Shopee + tiền đã xuất HĐ hải quan CHƯA phản ánh
        qua phiếu xuất kho nào + tiền còn lại chưa xuất HĐ (ở luồng nào cũng tính) — dùng chung
        cho dashboard nội bộ VÀ trang public /misa_sale_status, để con số tổng luôn khớp giữa
        các mảnh thay vì mỗi nơi tính rời rạc ra kết quả lệch nhau.

        Hải quan chỉ cộng PHẦN CHƯA KHỚP (customs_summary['pending_amount']) vào tổng — phần
        đã khớp phiếu xuất kho thì tiền đó đã nằm sẵn trong misa_invoiced_amount rồi (qua
        picking.misa_invoice_amount), cộng thêm sẽ bị đếm trùng 2 lần."""
        Picking = self.sudo()
        misa_domain = Picking._misa_invoice_dashboard_base_domain(date_from, date_to)
        shopee_domain = Picking._misa_invoice_shopee_domain(date_from, date_to)
        if saler_code:
            value = False if saler_code == MISA_INVOICE_UNASSIGNED_SALER else saler_code
            misa_domain = misa_domain + [('misa_invoice_saler_code', '=', value)]
            shopee_domain = shopee_domain + [('misa_invoice_saler_code', '=', value)]

        misa_actual_group = Picking.read_group(misa_domain, ['misa_invoice_net_actual_amount:sum'], [])
        misa_actual_total = (
            (misa_actual_group[0]['misa_invoice_net_actual_amount'] or 0.0) if misa_actual_group else 0.0
        )
        misa_invoiced_group = Picking.read_group(
            misa_domain + [('misa_invoice_state', '=', 'invoiced')], ['misa_invoice_effective_amount:sum'], [],
        )
        misa_invoiced_total = (
            (misa_invoiced_group[0]['misa_invoice_effective_amount'] or 0.0) if misa_invoiced_group else 0.0
        )

        shopee_summary = Picking._misa_invoice_shopee_summary(shopee_domain)
        customs_summary = Picking._misa_invoice_customs_summary(date_from, date_to, saler_code)

        # Nhóm ĐÃ XÁC MINH XONG (misa_invoice_gap_resolved) — tiền của nhóm này thực chất ĐÃ có
        # hóa đơn, chỉ là gắn nhầm sang 1 đề nghị khác (case thật KBC/OUT/10826/11218) — phải
        # cộng phần "chênh lệch" của các nhóm này (misa_invoice_amount_diff) vào tiền đã xuất
        # HĐ, nếu không "Chênh lệch (xuất kho – xuất HĐ)" ở đây sẽ KHÔNG khớp với tổng lệch
        # "còn cần xử lý" ở bảng "Đối chiếu tổng" (get_misa_invoice_discrepancy đã loại các
        # nhóm này khỏi total_diff) — 2 nơi cùng nói về "còn lệch bao nhiêu" nhưng ra 2 số khác
        # nhau sẽ không ai tin được số nào.
        gap_resolved_group = Picking.read_group(
            misa_domain + [('misa_invoice_gap_resolved', '=', True)], ['misa_invoice_amount_diff:sum'], [],
        )
        gap_resolved_amount = (
            (gap_resolved_group[0]['misa_invoice_amount_diff'] or 0.0) if gap_resolved_group else 0.0
        )

        total_actual_amount = misa_actual_total + shopee_summary['total_actual_amount']
        total_invoiced_amount = (
            misa_invoiced_total + shopee_summary['total_invoice_amount'] + customs_summary['pending_amount']
            + gap_resolved_amount
        )

        return {
            'total_actual_amount': total_actual_amount,
            'misa_actual_amount': misa_actual_total,
            'misa_invoiced_amount': misa_invoiced_total,
            'gap_resolved_amount': gap_resolved_amount,
            'shopee_actual_amount': shopee_summary['total_actual_amount'],
            'shopee_invoiced_amount': shopee_summary['total_invoice_amount'],
            'customs_total_amount': customs_summary['total_amount'],
            'customs_matched_amount': customs_summary['matched_amount'],
            'customs_pending_amount': customs_summary['pending_amount'],
            'customs_total_count': customs_summary['total_count'],
            'customs_matched_count': customs_summary['matched_count'],
            'customs_pending_count': customs_summary['pending_count'],
            'outstanding_amount': total_actual_amount - total_invoiced_amount,
        }

    @api.model
    def get_misa_invoice_discrepancy(
        self, date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
        saler_code=False, limit=200,
    ):
        """Chi tiết CÁC PHIẾU đang góp phần vào 'chênh lệch' (tổng tiền xuất kho - tổng đã xuất
        HĐ) — để trả lời "lệch phiếu nào" thay vì chỉ biết mỗi tổng số. Gồm 2 loại lệch, áp dụng
        cho cả 2 luồng MISA (thường) và Shopee:
        - Phiếu CHƯA xuất HĐ → lệch = toàn bộ tiền thực xuất (outstanding_amount).
        - Phiếu ĐÃ xuất HĐ nhưng tiền hóa đơn khác tiền thực xuất quá dung sai
          (misa_invoice_amount_mismatch/tương đương bên Shopee) → lệch = actual - invoice.
        Sắp xếp theo |lệch| giảm dần để thấy ngay phiếu lệch nhiều nhất.

        Hóa đơn hải quan CHƯA khớp phiếu xuất kho nào không có trong danh sách (không có "phiếu"
        nào để liệt kê) — chỉ trả kèm customs_pending_amount/count để biết còn khoản này nữa.

        Phiếu "ăn theo" 1 đề nghị gộp chung (misa_invoice_master_picking_id) KHÔNG hiện riêng —
        cả nhóm chỉ hiện 1 dòng DUY NHẤT (ở phiếu GỐC), vì mọi phiếu trong nhóm đều lấy chung 1
        con số lệch từ phiếu gốc (misa_invoice_amount_diff) — hiện riêng từng phiếu sẽ tưởng
        nhầm là N vấn đề khác nhau trong khi thực ra chỉ là 1 vấn đề của cả nhóm lặp lại N lần.
        actual_amount của dòng nhóm = TỔNG tiền thực xuất của CẢ NHÓM (không phải riêng phiếu
        gốc) để so cho đúng nghĩa với tiền hóa đơn (cũng là tổng của cả nhóm)."""
        Picking = self.sudo()
        today = fields.Date.context_today(self)
        misa_domain = Picking._misa_invoice_dashboard_base_domain(date_from, date_to, invoice_date_from, invoice_date_to)
        shopee_domain = Picking._misa_invoice_shopee_domain(date_from, date_to)
        if saler_code:
            value = False if saler_code == MISA_INVOICE_UNASSIGNED_SALER else saler_code
            misa_domain = misa_domain + [('misa_invoice_saler_code', '=', value)]
            shopee_domain = shopee_domain + [('misa_invoice_saler_code', '=', value)]

        rows = []
        for picking in Picking.search(misa_domain):
            if picking.misa_invoice_master_picking_id:
                continue  # đã gộp vào phiếu gốc — hiện qua đúng 1 dòng của phiếu gốc đó
            row = Picking._misa_invoice_picking_to_row(picking, today)
            # Đọc field ĐÃ LƯU SẴN (misa_invoice_gap_summary, cập nhật qua
            # _misa_invoice_discover_grouped_orders / nút "Cập nhật lý do lệch") — KHÔNG gọi
            # API MISA ở đây, vì danh sách này có thể liệt kê hàng trăm dòng cùng lúc.
            row['gap_summary'] = picking.misa_invoice_gap_summary or ''
            row['gap_checked_at'] = fields.Datetime.to_string(picking.misa_invoice_gap_checked_at) or ''
            row['gap_resolved'] = picking.misa_invoice_gap_resolved
            if picking.misa_invoice_covered_picking_ids:
                group = picking | picking.misa_invoice_covered_picking_ids
                row['actual_amount'] = sum(group.mapped('misa_invoice_net_actual_amount'))
                row['group_picking_names'] = group.mapped('name')
            else:
                row['group_picking_names'] = [picking.name]
            diff = row['amount_diff'] if row['state'] == 'invoiced' else row['outstanding_amount']
            if abs(diff) <= MISA_INVOICE_AMOUNT_TOLERANCE:
                continue
            row['diff'] = diff
            row['source'] = 'misa'
            rows.append(row)
        for picking in Picking.search(shopee_domain):
            row = Picking._misa_invoice_shopee_picking_to_row(picking, today)
            row['group_picking_names'] = [picking.name]  # Shopee không có cơ chế gộp nhóm
            row['gap_summary'] = ''  # Shopee chưa có cơ chế phân tích lý do lệch theo dòng hàng
            row['gap_checked_at'] = ''
            row['gap_resolved'] = False
            diff = row['actual_amount'] - row['invoice_amount']
            if abs(diff) <= MISA_INVOICE_AMOUNT_TOLERANCE:
                continue
            row['diff'] = diff
            row['source'] = 'shopee'
            rows.append(row)

        # Đơn CÒN CẦN XỬ LÝ THẬT lên trước (chưa xác minh xong), đơn đã xác minh xong
        # (gap_resolved) đẩy xuống cuối — không ẩn đi (vẫn cần minh bạch), chỉ không để nó chen
        # vào giữa những đơn cần "hối" sale thật, gây tưởng nhầm là còn nhiều vấn đề.
        rows.sort(key=lambda r: (r.get('gap_resolved', False), -abs(r['diff'])))
        customs_summary = Picking._misa_invoice_customs_summary(invoice_date_from, invoice_date_to, saler_code)
        actionable_rows = [r for r in rows if not r.get('gap_resolved')]
        return {
            'rows': rows[:limit],
            'total_count': len(actionable_rows),
            'total_diff': sum(r['diff'] for r in actionable_rows),
            'resolved_count': len(rows) - len(actionable_rows),
            'customs_pending_amount': customs_summary['pending_amount'],
            'customs_pending_count': customs_summary['pending_count'],
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

        conflict = self._misa_invoice_customs_conflicting_picking(voucher.get('inv_no') or inv_no)
        return {
            'invoice_no': voucher.get('inv_no') or inv_no,
            'invoice_refid': refid,
            'refno_finance': voucher.get('refno_finance') or '',
            'invoice_date': voucher.get('inv_date'),
            'partner_name': voucher.get('account_object_name') or '',
            'employee_code': voucher.get('employee_code') or '',
            'total_amount': voucher.get('total_amount') or 0.0,
            'lines': preview_lines,
            'conflict_picking_name': conflict.name if conflict else False,
        }

    def _misa_invoice_customs_conflicting_picking(self, inv_no):
        """Tìm phiếu xuất kho ĐÃ được gắn số hóa đơn này qua LUỒNG THÔNG THƯỜNG (sa_invoice_request
        theo refno=tên phiếu, hoặc gắn tay qua wizard — cả 2 đều đi qua action_check_misa_invoice_status
        nên đều set misa_invoice_request_refid) — dùng để chặn ghi nhận trùng, tránh 1 hóa đơn bị
        tính tiền 2 lần (1 lần qua luồng thường, 1 lần qua hải quan).

        CHỈ coi là trùng khi có misa_invoice_request_refid — field này CHỈ được set bởi luồng
        thông thường, KHÔNG BAO GIỜ bởi luồng hải quan (_misa_invoice_customs_apply_to_picking).
        Nhờ vậy phân biệt được với trường hợp phiếu chỉ có misa_invoice_no trùng do MỘT LƯỢT
        HẢI QUAN TRƯỚC ĐÓ của CHÍNH hóa đơn này để lại (VD sau khi xóa hóa đơn để ghi nhận lại —
        delete_misa_customs_invoice có revert nhưng dữ liệu cũ từ trước khi có fix này có thể
        vẫn còn sót) — không dùng match_ids còn tồn tại để loại trừ vì sau khi xóa dòng, match_ids
        cũng mất theo, sẽ nhận nhầm dữ liệu sót lại là "trùng từ luồng khác"."""
        inv_no = (inv_no or '').strip()
        if not inv_no:
            return self.browse()
        return self.sudo().search([
            ('misa_invoice_no', '=', inv_no),
            ('misa_invoice_request_refid', '!=', False),
        ], limit=1)

    @api.model
    def save_misa_customs_invoice(self, inv_no):
        """Ghi nhận (lưu) 1 hóa đơn hải quan — tự fetch lại MISA lần nữa (không tin dữ liệu
        preview gửi ngược từ client) để đảm bảo dữ liệu lưu luôn khớp với MISA ngay tại thời
        điểm lưu. Fetch lại cùng 1 số hóa đơn nhiều lần sẽ THAY THẾ hoàn toàn các dòng cũ
        (xóa rồi tạo lại) — coi như "đồng bộ lại", không cộng dồn trùng.

        Mỗi dòng vừa tạo được thử KHỚP NGAY với 1 phiếu xuất kho (nếu đã tồn tại và đã done)
        — nếu chưa có phiếu (hàng chưa xuất kho) hoặc phiếu chưa hoàn tất, dòng ở lại
        'pending' và cron định kỳ (_cron_scan_misa_customs_pending) sẽ tự thử lại sau,
        không cần thao tác gì thêm.

        CHẶN nếu phiếu xuất kho nào đó đã được gắn hóa đơn này qua luồng khác rồi — tránh trùng
        hóa đơn giữa phiếu xuất kho (luồng thông thường) và hải quan (bị tính tiền 2 lần)."""
        preview = self.fetch_misa_customs_invoice(inv_no)
        conflict = self._misa_invoice_customs_conflicting_picking(preview['invoice_no'])
        if conflict:
            raise UserError(
                "Hóa đơn \"%s\" đã được gắn với phiếu xuất kho %s qua luồng khác (không phải hải quan) — "
                "không thể ghi nhận trùng, sẽ bị tính hóa đơn này 2 lần." % (preview['invoice_no'], conflict.name)
            )
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
                'employee_code': preview.get('employee_code') or '',
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

    def _misa_invoice_reconcile_line_match(self, line, match_model_name, apply_to_picking=None, exclude_picking_ids=None):
        """Thuật toán khớp DÙNG CHUNG cho mọi model dạng "dòng hàng cần đối soát với phiếu xuất
        kho" (misa.invoice.customs.line — hàng hải quan; misa.invoice.grouped.line — hàng xuất
        HĐ chung qua đề nghị của phiếu khác). `line` phải có sale_order_id, inventory_item_code,
        quantity, amount, match_ids, matched_qty, remaining_qty() — xem 2 model trên.

        Thử tìm phiếu xuất kho (đã done) khớp đơn bán + mã hàng của dòng này — CHO PHÉP khớp
        TỪNG PHẦN vì hàng có thể xuất kho nhiều đợt (hóa đơn ghi số lượng 2 nhưng đợt xuất đầu
        chỉ có 1): dòng ở trạng thái 'partial' và vẫn tiếp tục được thử lại (cron/lần quét sau)
        cho tới khi tổng số lượng khớp (matched_qty, cộng dồn qua match_ids) đủ so với hóa đơn.
        Mỗi phiếu chỉ tính 1 lần cho dòng này, và số lượng đã bị dòng KHÁC (cùng đơn + cùng mã
        hàng, cùng match_model_name) lấy trước sẽ được trừ ra — tránh 2 dòng cùng cộng dồn 1
        lượng hàng xuất kho. Vì nới lỏng điều kiện (không còn đòi khớp CHÍNH XÁC tuyệt đối),
        thuật toán có thể chọn nhầm phiếu ở vài ca hiếm — dùng "Khớp thủ công" / "Xóa lượt
        khớp" trên UI (hàng hải quan) để sửa. `apply_to_picking(picking)` — nếu truyền vào —
        được gọi ngay sau khi tạo 1 lượt khớp mới cho phiếu đó (dùng cho hàng hải quan để ghi
        nhận "đã xuất HĐ" ngay; hàng xuất HĐ chung KHÔNG dùng callback này, xem
        _misa_invoice_discover_grouped_orders — quyết định gán "ăn theo" sau khi khớp XONG cả
        đơn, dựa vào misa_invoice_grouped_matched_amount cộng dồn). `exclude_picking_ids` — nếu
        truyền vào — loại hẳn những phiếu đó khỏi tập ứng viên nhận số lượng khớp: dùng khi
        khớp dòng hàng của CHÍNH đơn hàng phiếu đại diện (case KBC/OUT/10559: cùng 1 đơn hàng
        được xuất làm 2 đợt/2 phiếu, phiếu đại diện đã tự có tiền HĐ riêng qua misa_invoice_amount
        rồi — không được để thuật toán này "cướp" số lượng của chính nó qua match record."""
        line.ensure_one()
        if line.match_state == 'matched':
            return True
        if not line.sale_order_id:
            line.match_note = "Không tìm thấy đơn bán \"%s\" trong Odoo." % (line.order_code or '')
            return False
        item_code = (line.inventory_item_code or '').strip()
        if not item_code:
            line.match_note = "Dòng này không có mã hàng."
            return False
        # '=ilike' so khớp CHÍNH XÁC nhưng không phân biệt hoa/thường — mã hàng giữa MISA và
        # Odoo đôi khi lệch cách viết hoa dù cùng 1 sản phẩm, strip() để bỏ khoảng trắng thừa.
        product = self.env['product.product'].sudo().search(
            [('default_code', '=ilike', item_code)], limit=1,
        )
        if not product:
            line.match_note = "Không tìm thấy sản phẩm Odoo có mã hàng (default_code) = \"%s\"." % item_code
            return False
        remaining = line.remaining_qty()
        already_picking_ids = line.match_ids.mapped('picking_id').ids
        domain = [
            ('sale_line_id.order_id', '=', line.sale_order_id.id),
            ('product_id', '=', product.id),
            ('picking_id.picking_type_id.code', '=', 'outgoing'),
            ('picking_id.state', '=', 'done'),
        ]
        if already_picking_ids:
            domain.append(('picking_id', 'not in', already_picking_ids))
        if exclude_picking_ids:
            domain.append(('picking_id', 'not in', exclude_picking_ids))
        moves = self.env['stock.move'].sudo().search(domain)
        if not moves:
            if line.matched_qty > 0.01:
                line.match_note = "Đã khớp %s/%s — còn thiếu %s, đang chờ xuất kho đợt tiếp theo." % (
                    line.matched_qty, line.quantity, remaining,
                )
            else:
                line.match_note = (
                    "Tìm thấy sản phẩm \"%s\" nhưng chưa có phiếu xuất kho nào (đã hoàn tất) "
                    "cho đúng đơn bán %s."
                ) % (item_code, line.sale_order_id.name)
            return False
        # Trừ số lượng đã bị khách TRẢ LẠI (phiếu incoming reverse, liên kết qua
        # origin_returned_move_id) — nếu không, hàng trả vẫn bị tính là "đã xuất kho", có thể
        # khớp thừa với hóa đơn dù khách đã trả bớt.
        returned_moves = self.env['stock.move'].sudo().search([
            ('origin_returned_move_id', 'in', moves.ids), ('state', '=', 'done'),
        ])
        returned_qty_by_move = {}
        for rm in returned_moves:
            returned_qty_by_move[rm.origin_returned_move_id.id] = (
                returned_qty_by_move.get(rm.origin_returned_move_id.id, 0.0) + rm.quantity
            )
        qty_by_picking = {}
        for move in moves:
            net_qty = move.quantity - returned_qty_by_move.get(move.id, 0.0)
            if net_qty <= 0:
                continue
            qty_by_picking[move.picking_id] = qty_by_picking.get(move.picking_id, 0.0) + net_qty
        if not qty_by_picking:
            line.match_note = (
                "Có phiếu xuất kho cho mã hàng này nhưng toàn bộ số lượng đã bị khách trả lại — "
                "cần kiểm tra lại thủ công."
            )
            return False
        picking_ids = [p.id for p in qty_by_picking]
        other_matches = self.env[match_model_name].sudo().search([
            ('picking_id', 'in', picking_ids),
            ('line_id.sale_order_id', '=', line.sale_order_id.id),
            ('line_id.inventory_item_code', '=ilike', item_code),
            ('line_id', '!=', line.id),
        ])
        allocated_elsewhere = {}
        for m in other_matches:
            allocated_elsewhere[m.picking_id.id] = allocated_elsewhere.get(m.picking_id.id, 0.0) + m.quantity
        available_by_picking = {
            picking: qty - allocated_elsewhere.get(picking.id, 0.0)
            for picking, qty in qty_by_picking.items()
        }
        available_by_picking = {p: q for p, q in available_by_picking.items() if q > 0.01}
        if not available_by_picking:
            line.match_note = (
                "Có phiếu xuất kho cho mã hàng này nhưng toàn bộ số lượng đã được 1 dòng khác "
                "(cùng đơn, cùng mã hàng) sử dụng — cần kiểm tra lại thủ công."
            )
            return False
        # Xuất kho đợt nào trước thì tính vào hóa đơn trước (FIFO theo ngày hoàn tất phiếu).
        ordered_pickings = sorted(
            available_by_picking.items(),
            key=lambda kv: kv[0].date_done or kv[0].create_date or fields.Datetime.now(),
        )
        unit_amount = (line.amount / line.quantity) if line.quantity else 0.0
        for picking, free_qty in ordered_pickings:
            if remaining <= 0.01:
                break
            take_qty = min(free_qty, remaining)
            self.env[match_model_name].sudo().create({
                'line_id': line.id,
                'picking_id': picking.id,
                'quantity': take_qty,
                'amount': unit_amount * take_qty,
                'is_manual': False,
                'matched_at': fields.Datetime.now(),
            })
            if apply_to_picking:
                apply_to_picking(picking)
            remaining -= take_qty
        new_remaining = line.remaining_qty()
        if new_remaining <= 0.01:
            line.write({'match_state': 'matched', 'matched_at': fields.Datetime.now(), 'match_note': False})
            return True
        line.write({
            'match_state': 'partial' if line.matched_qty > 0.01 else 'pending',
            'match_note': "Đã khớp %s/%s — còn thiếu %s, đang chờ xuất kho đợt tiếp theo." % (
                line.matched_qty, line.quantity, new_remaining,
            ),
        })
        return False

    def _misa_invoice_customs_try_match(self, line):
        """Khớp 1 dòng hải quan (misa.invoice.customs.line) — xem
        _misa_invoice_reconcile_line_match. Ghi nhận "đã xuất HĐ" NGAY cho phiếu vừa khớp
        (apply_to_picking) vì hàng hải quan không có kênh nào khác báo hóa đơn cho phiếu đó."""
        return self._misa_invoice_reconcile_line_match(
            line, 'misa.invoice.customs.match', apply_to_picking=self._misa_invoice_customs_apply_to_picking,
        )

    def _misa_invoice_grouped_try_match(self, line, exclude_picking_ids=None):
        """Khớp 1 dòng hàng xuất HĐ CHUNG (misa.invoice.grouped.line) — xem
        _misa_invoice_reconcile_line_match. KHÔNG tự ghi nhận "đã xuất HĐ" ngay khi khớp (dù
        chỉ 1 phần) — chỉ cộng dồn misa_invoice_grouped_matched_amount (compute tự động qua
        misa_invoice_grouped_match_ids); _misa_invoice_discover_grouped_orders tự quyết định
        gán "ăn theo" hay không SAU KHI khớp xong toàn bộ dòng hàng của cả đơn."""
        return self._misa_invoice_reconcile_line_match(
            line, 'misa.invoice.grouped.match', exclude_picking_ids=exclude_picking_ids,
        )

    def _misa_invoice_customs_apply_to_picking(self, picking):
        """Khi 1 phiếu xuất kho có >=1 lượt khớp hải quan (match_ids) — ghi nhận phiếu đó 'đã
        xuất HĐ' (nếu chưa từng ghi nhận qua luồng nào khác), lấy số HĐ/ngày HĐ từ lượt khớp
        ĐẦU TIÊN, tiền = tổng amount đã quy cho phiếu này qua các lượt khớp (không phải tổng cả
        hóa đơn hay tổng cả dòng hải quan, vì 1 dòng có thể bị chia xuất kho nhiều đợt/phiếu)."""
        if picking.misa_invoice_state == 'invoiced':
            return
        matches = self.env['misa.invoice.customs.match'].sudo().search(
            [('picking_id', '=', picking.id)], order='matched_at',
        )
        if not matches:
            return
        first_line = matches[0].line_id
        old_state = picking.misa_invoice_state
        picking.write({
            'misa_invoice_state': 'invoiced',
            'misa_invoice_no': first_line.invoice_no,
            'misa_invoice_date': first_line.invoice_date,
            'misa_invoice_amount': sum(matches.mapped('amount')),
            'misa_invoice_last_checked': fields.Datetime.now(),
        })
        picking.message_post(
            body=Markup(
                "<b>Đã ghi nhận xuất hóa đơn (hải quan — hóa đơn xuất trước xuất kho):</b> "
                "%s → %s, số hóa đơn %s."
            ) % (
                MISA_INVOICE_STATE_LABELS.get(old_state, old_state),
                MISA_INVOICE_STATE_LABELS.get('invoiced', 'invoiced'),
                first_line.invoice_no,
            )
        )

    @api.model
    def search_pickings_for_customs_manual_match(self, line_id, search=False, limit=20):
        """Danh sách phiếu xuất kho gợi ý để người dùng CHỌN THỦ CÔNG khi tự động khớp sai/thiếu
        — mặc định chỉ hiện phiếu outgoing của ĐÚNG đơn bán trên dòng hải quan; cho tìm thêm
        theo tên phiếu (search) phòng trường hợp sale ghi nhầm mã đơn hàng trên MISA. Kèm số
        lượng đã xuất của đúng mã hàng (nếu xác định được sản phẩm) để người dùng đối chiếu."""
        line = self.env['misa.invoice.customs.line'].sudo().browse(line_id)
        if not line.exists():
            return []
        domain = [('picking_type_id.code', '=', 'outgoing'), ('state', '!=', 'cancel')]
        if search:
            domain.append(('name', 'ilike', search))
        elif line.sale_order_id:
            domain.append(('misa_invoice_sale_order_ids', '=', line.sale_order_id.id))
        else:
            return []
        pickings = self.sudo().search(domain, limit=limit, order='date_done desc, id desc')
        item_code = (line.inventory_item_code or '').strip()
        product = (
            self.env['product.product'].sudo().search([('default_code', '=ilike', item_code)], limit=1)
            if item_code else self.env['product.product']
        )
        Match = self.env['misa.invoice.customs.match'].sudo()
        result = []
        for picking in pickings:
            shipped_qty = 0.0
            if product:
                moves = picking.move_ids_without_package.filtered(lambda m: m.product_id == product)
                shipped_qty = sum(moves.mapped('quantity'))
            existing = Match.search([('picking_id', '=', picking.id), ('line_id', '=', line.id)], limit=1)
            result.append({
                'id': picking.id,
                'name': picking.name,
                'state': picking.state,
                'state_label': STOCK_PICKING_STATE_LABELS.get(picking.state, picking.state),
                'date_done': fields.Datetime.to_string(picking.date_done) if picking.date_done else '',
                'shipped_qty': shipped_qty,
                'already_matched_qty': existing.quantity if existing else 0.0,
            })
        return result

    @api.model
    def set_manual_customs_match(self, line_id, picking_id, quantity=False):
        """Cho người dùng CHỌN THỦ CÔNG 1 phiếu xuất kho để khớp với dòng hải quan này — dùng
        khi hệ thống tự động khớp SAI (chọn nhầm phiếu) hoặc khớp THIẾU (không tìm ra phiếu phù
        hợp). Không kiểm tra lại số lượng như khớp tự động — tin lựa chọn thủ công của người
        dùng, chỉ giới hạn không vượt quá số lượng còn thiếu của dòng."""
        line = self.env['misa.invoice.customs.line'].sudo().browse(line_id)
        if not line.exists():
            raise UserError("Dòng hải quan này không còn tồn tại.")
        picking = self.sudo().browse(picking_id)
        if not picking.exists():
            raise UserError("Phiếu xuất kho này không còn tồn tại.")
        remaining = line.remaining_qty()
        if remaining <= 0.01:
            raise UserError("Dòng hải quan này đã khớp đủ số lượng, không cần gán thêm.")
        qty = float(quantity) if quantity else remaining
        if qty <= 0:
            raise UserError("Số lượng gán phải lớn hơn 0.")
        qty = min(qty, remaining)
        unit_amount = (line.amount / line.quantity) if line.quantity else 0.0
        self.env['misa.invoice.customs.match'].sudo().create({
            'line_id': line.id,
            'picking_id': picking.id,
            'quantity': qty,
            'amount': unit_amount * qty,
            'is_manual': True,
            'matched_by_id': self.env.user.id,
            'matched_at': fields.Datetime.now(),
        })
        self._misa_invoice_customs_apply_to_picking(picking)
        new_remaining = line.remaining_qty()
        if new_remaining <= 0.01:
            line.write({'match_state': 'matched', 'matched_at': fields.Datetime.now(), 'match_note': False})
        else:
            line.write({
                'match_state': 'partial',
                'match_note': "Đã khớp %s/%s (gồm gán thủ công) — còn thiếu %s." % (
                    line.matched_qty, line.quantity, new_remaining,
                ),
            })
        return {'matched': line.match_state == 'matched', 'remaining_qty': new_remaining, 'picking_name': picking.name}

    @api.model
    def remove_customs_match(self, match_id):
        """Xóa 1 lượt khớp SAI (thủ công hoặc tự động) — khôi phục lại đúng trạng thái còn
        thiếu của dòng hải quan. Nếu phiếu xuất kho đó không còn lượt khớp nào khác trỏ tới,
        trả phiếu về 'chưa kiểm tra' để luồng đối soát HĐ thông thường (theo refno) tự đánh giá
        lại từ đầu — tránh phiếu bị "kẹt" ở trạng thái đã xuất HĐ chỉ vì 1 lượt khớp sai."""
        match = self.env['misa.invoice.customs.match'].sudo().browse(match_id)
        if not match.exists():
            return {'removed': False}
        line = match.line_id
        picking = match.picking_id
        match.unlink()
        remaining_matches = self.env['misa.invoice.customs.match'].sudo().search_count(
            [('picking_id', '=', picking.id)],
        )
        if not remaining_matches and picking.misa_invoice_state == 'invoiced':
            picking.write({
                'misa_invoice_state': 'not_checked',
                'misa_invoice_no': False,
                'misa_invoice_date': False,
                'misa_invoice_amount': 0.0,
            })
            picking.message_post(body="Đã xóa lượt khớp hải quan sai — trả phiếu về 'Chưa kiểm tra' để đối soát lại.")
        new_remaining = line.remaining_qty()
        if new_remaining <= 0.01:
            line.write({'match_state': 'matched', 'match_note': False})
        elif line.matched_qty > 0.01:
            line.write({
                'match_state': 'partial',
                'match_note': "Đã khớp %s/%s — còn thiếu %s." % (line.matched_qty, line.quantity, new_remaining),
            })
        else:
            line.write({'match_state': 'pending', 'match_note': "Chưa có phiếu xuất kho nào khớp."})
        return {'removed': True, 'line_id': line.id}

    def _cron_scan_misa_customs_pending(self):
        """Quét định kỳ các dòng hải quan còn 'pending' HOẶC 'partial' (chưa có phiếu xuất kho
        tương ứng, phiếu chưa hoàn tất, hoặc mới chỉ khớp được 1 phần số lượng) — tự thử khớp
        lại, không cần thao tác thủ công khi phiếu xuất kho được tạo/hoàn tất sau đó. LƯU Ý:
        trước đây chỉ quét đúng 'pending' — bỏ sót 'partial' khiến các dòng đã khớp 1 phần
        (VD hóa đơn ghi 2 nhưng mới xuất kho 1) không bao giờ được cron tự thử lại nữa."""
        pending = self.env['misa.invoice.customs.line'].sudo().search(
            [('match_state', 'in', ('pending', 'partial'))], limit=200,
        )
        for line in pending:
            try:
                self._misa_invoice_customs_try_match(line)
            except Exception:
                _logger.exception(
                    "❌ [MISA CUSTOMS SCAN] Lỗi thử khớp dòng hải quan #%s (HĐ %s)", line.id, line.invoice_no,
                )

    def button_validate(self):
        """2 việc cần trigger NGAY khi 1 phiếu validate xong, không đợi cron (30 phút/lần) hay
        bấm tay:
        1. Case hải quan: hóa đơn MISA có TRƯỚC, phiếu xuất kho xác nhận SAU — thử khớp ngay các
           dòng hải quan pending/partial của đúng (các) đơn bán trên phiếu vừa xuất.
        2. Case trả hàng: phiếu NÀY tự validate (outgoing) → tính lại misa_invoice_net_actual_amount
           (ban đầu = gộp, chưa có trả). Phiếu NÀY là 1 phiếu TRẢ HÀNG (incoming, reverse move của
           phiếu outgoing khác) validate xong → tìm phiếu outgoing gốc bị ảnh hưởng và tính lại
           net_actual_amount cho phiếu đó (trừ đi phần vừa trả)."""
        res = super().button_validate()
        for picking in self:
            if picking.state != 'done':
                continue
            if picking.picking_type_id.code == 'outgoing':
                try:
                    picking._misa_invoice_recompute_net_amount()
                except Exception:
                    _logger.exception(
                        "❌ [MISA RETURN] Lỗi tính lại tiền thực xuất ròng cho phiếu %s", picking.name,
                    )
                try:
                    picking._misa_invoice_customs_try_match_for_picking()
                except Exception:
                    _logger.exception(
                        "❌ [MISA CUSTOMS] Lỗi thử khớp hải quan ngay khi xuất kho phiếu %s", picking.name,
                    )
            elif picking.picking_type_id.code == 'incoming':
                try:
                    picking._misa_invoice_recompute_return_impact()
                except Exception:
                    _logger.exception(
                        "❌ [MISA RETURN] Lỗi tính lại ảnh hưởng trả hàng cho phiếu %s", picking.name,
                    )
        return res

    def _misa_invoice_recompute_return_impact(self):
        """Khi phiếu incoming này là phiếu TRẢ HÀNG (reverse 1 hay nhiều move xuất kho gốc, tạo
        qua wizard stock.return.picking chuẩn của Odoo — mỗi move trả có origin_returned_move_id
        trỏ về move gốc) — tìm đúng (các) phiếu xuất kho gốc bị ảnh hưởng và tính lại
        misa_invoice_net_actual_amount cho phiếu đó, để tổng đối soát không bị đếm dư phần khách
        đã trả lại. Không làm gì nếu đây không phải phiếu trả hàng (phiếu incoming bình thường
        không có move nào set origin_returned_move_id)."""
        self.ensure_one()
        returned_moves = self.move_ids.filtered(lambda m: m.origin_returned_move_id and m.state == 'done')
        if not returned_moves:
            return
        original_pickings = returned_moves.mapped('origin_returned_move_id.picking_id')
        for picking in original_pickings:
            picking._misa_invoice_recompute_net_amount()

    def _misa_invoice_recompute_net_amount(self):
        """Tính lại misa_invoice_returned_amount (tiền hàng đã trả, quy đổi theo đơn giá SAU
        THUẾ của đúng sale.order.line gắn với từng move — line.price_total / line.product_uom_qty
        × số lượng đã trả) và misa_invoice_net_actual_amount (= gộp − đã trả) cho 1 phiếu xuất
        kho. Gọi lại mỗi khi: (1) phiếu này tự validate xong (chưa có trả, net = gộp), hoặc (2)
        có phiếu trả hàng liên quan tới phiếu này được validate sau đó (xem
        _misa_invoice_recompute_return_impact)."""
        self.ensure_one()
        returned_amount = 0.0
        original_moves = self.move_ids.filtered(lambda m: m.state == 'done' and m.sale_line_id)
        if original_moves:
            returned_moves = self.env['stock.move'].sudo().search([
                ('origin_returned_move_id', 'in', original_moves.ids), ('state', '=', 'done'),
            ])
            returned_qty_by_move = {}
            for rm in returned_moves:
                returned_qty_by_move[rm.origin_returned_move_id.id] = (
                    returned_qty_by_move.get(rm.origin_returned_move_id.id, 0.0) + rm.quantity
                )
            for move in original_moves:
                returned_qty = returned_qty_by_move.get(move.id, 0.0)
                if not returned_qty:
                    continue
                line = move.sale_line_id
                if not line.product_uom_qty:
                    continue
                unit_price_after_tax = line.price_total / line.product_uom_qty
                returned_amount += unit_price_after_tax * returned_qty
        gross = self.x_studio_tng_tin_sau_thu or 0.0
        self.write({
            'misa_invoice_returned_amount': returned_amount,
            'misa_invoice_net_actual_amount': max(gross - returned_amount, 0.0),
        })

    def _misa_invoice_customs_try_match_for_picking(self):
        """Thử khớp NGAY các dòng hải quan đang pending/partial của ĐÚNG (các) đơn bán trên
        phiếu này — gọi khi phiếu vừa validate xong (xem button_validate)."""
        self.ensure_one()
        order_ids = self.misa_invoice_sale_order_ids.ids
        if not order_ids:
            return
        lines = self.env['misa.invoice.customs.line'].sudo().search([
            ('sale_order_id', 'in', order_ids),
            ('match_state', 'in', ('pending', 'partial')),
        ])
        for line in lines:
            self._misa_invoice_customs_try_match(line)

    @api.model
    def retry_all_pending_customs_matches(self, saler_code=False, limit=500):
        """Nút 'Kiểm tra tất cả đang chờ' trên tab Đơn hải quan — thử khớp lại NGAY toàn bộ các
        dòng pending/partial (bấm tay, không chờ cron) — dùng khi nghi ngờ có phiếu đã xuất kho
        xong nhưng vì lý do gì đó (phiếu validate trước khi có bản vá này, lỗi tạm thời...) chưa
        được tự động thử khớp. saler_code (tùy chọn): scope cho trang public, mỗi sale chỉ kiểm
        tra đúng hóa đơn của mình."""
        domain = [('match_state', 'in', ('pending', 'partial'))]
        if saler_code:
            value = False if saler_code == MISA_INVOICE_UNASSIGNED_SALER else saler_code
            domain.append(('employee_code', '=', value))
        lines = self.env['misa.invoice.customs.line'].sudo().search(domain, limit=limit)
        matched_count = 0
        for line in lines:
            try:
                if self._misa_invoice_customs_try_match(line):
                    matched_count += 1
            except Exception:
                _logger.exception(
                    "❌ [MISA CUSTOMS] Lỗi thử khớp lại hàng loạt dòng hải quan #%s (HĐ %s)", line.id, line.invoice_no,
                )
        return {'checked': len(lines), 'matched_count': matched_count}

    @api.model
    def retry_all_pending_customs_matches_public(self, saler_code):
        code = self._misa_invoice_validate_public_saler_code(saler_code)
        return self.sudo().retry_all_pending_customs_matches(saler_code=code)

    @api.model
    def get_misa_customs_lines(self, search=False, pending_only=False, saler_code=False, limit=50, offset=0):
        """saler_code (tùy chọn): lọc theo đúng employee_code trên hóa đơn — dùng bởi trang
        public /misa_sale_status (mỗi sale chỉ thấy hóa đơn của mình), KHÔNG dùng ở dashboard
        nội bộ (admin xem hết, không truyền tham số này)."""
        Lines = self.env['misa.invoice.customs.line'].sudo()
        base_domain = []
        if saler_code:
            base_domain.append(('employee_code', '=', saler_code))
        domain = list(base_domain)
        if search:
            domain += [
                '|', '|', ('invoice_no', 'ilike', search),
                ('order_code', 'ilike', search), ('inventory_item_code', 'ilike', search),
            ]
        if pending_only:
            domain.append(('match_state', 'in', ('pending', 'partial')))
        lines = Lines.search(domain, limit=limit, offset=offset)
        match_state_labels = {
            'matched': 'Đã khớp phiếu xuất kho', 'partial': 'Khớp một phần', 'pending': 'Chờ xuất kho',
        }
        return {
            'rows': [
                {
                    'id': line.id,
                    'invoice_no': line.invoice_no,
                    'refno_finance': line.refno_finance or '',
                    'invoice_date': fields.Date.to_string(line.invoice_date) if line.invoice_date else '',
                    'partner_name': line.partner_name or '',
                    'employee_code': line.employee_code or '',
                    'order_code': line.order_code,
                    'sale_order_id': line.sale_order_id.id if line.sale_order_id else False,
                    'sale_order_name': line.sale_order_id.name if line.sale_order_id else line.order_code,
                    'sale_order_found': bool(line.sale_order_id),
                    'inventory_item_code': line.inventory_item_code,
                    'description': line.description or '',
                    'quantity': line.quantity,
                    'unit_price': line.unit_price,
                    'amount': line.amount,
                    'matched_qty': line.matched_qty,
                    'remaining_qty': line.remaining_qty(),
                    'match_state': line.match_state,
                    'match_state_label': match_state_labels.get(line.match_state, line.match_state),
                    'match_note': line.match_note or '',
                    'picking_id': line.picking_id.id if line.picking_id else False,
                    'picking_name': line.picking_id.name if line.picking_id else False,
                    'matches': [
                        {
                            'id': m.id,
                            'picking_id': m.picking_id.id,
                            'picking_name': m.picking_id.name,
                            'quantity': m.quantity,
                            'amount': m.amount,
                            'is_manual': m.is_manual,
                            'matched_by': m.matched_by_id.name or '',
                            'matched_at': fields.Datetime.to_string(m.matched_at) if m.matched_at else '',
                        }
                        for m in line.match_ids
                    ],
                    'fetched_by': line.fetched_by_id.name or '',
                    'fetched_at': fields.Datetime.to_string(line.fetched_at) if line.fetched_at else '',
                }
                for line in lines
            ],
            'total': Lines.search_count(domain),
            'pending_count': Lines.search_count(base_domain + [('match_state', 'in', ('pending', 'partial'))]),
        }

    @api.model
    def get_misa_invoice_public_customs_lines(self, saler_code, search=False, pending_only=False, limit=50, offset=0):
        code = self._misa_invoice_validate_public_saler_code(saler_code)
        return self.sudo().get_misa_customs_lines(
            search=search, pending_only=pending_only, saler_code=code, limit=limit, offset=offset,
        )

    @api.model
    def delete_misa_customs_invoice(self, inv_no):
        """Chỉ nhóm 'Đối soát XHD' (admin) mới được xóa — trang public /misa_sale_status chạy
        bằng user public/portal nên KHÔNG bao giờ thuộc nhóm này, tự động chặn sale xóa dù có
        gọi thẳng API cũng không qua được (không chỉ ẩn nút trên UI)."""
        if not self.env.user.has_group(MISA_INVOICE_RECONCILE_GROUP):
            raise AccessError(_("Chỉ quản trị viên (nhóm Đối soát XHD) mới được xóa hóa đơn hải quan."))
        inv_no = (inv_no or '').strip()
        if not inv_no:
            return 0
        Lines = self.env['misa.invoice.customs.line'].sudo()
        lines = Lines.search([('invoice_no', '=', inv_no)])
        count = len(lines)
        # Trả lại đúng trạng thái cho các phiếu đã được khớp qua hóa đơn NÀY trước khi xóa —
        # nếu không, phiếu sẽ bị "kẹt" ở misa_invoice_state='invoiced'/misa_invoice_no=<hóa đơn
        # vừa xóa> dù dữ liệu hải quan đã không còn, khiến lần ghi nhận lại sau này (re-sync)
        # bị hiểu nhầm là "trùng với luồng khác" (xem _misa_invoice_customs_conflicting_picking).
        affected_pickings = lines.mapped('match_ids.picking_id')
        lines.unlink()
        Match = self.env['misa.invoice.customs.match'].sudo()
        for picking in affected_pickings:
            if picking.misa_invoice_state != 'invoiced':
                continue
            if Match.search_count([('picking_id', '=', picking.id)]):
                continue
            picking.write({
                'misa_invoice_state': 'not_checked',
                'misa_invoice_no': False,
                'misa_invoice_date': False,
                'misa_invoice_amount': 0.0,
            })
            picking.message_post(
                body=_("Đã xóa hóa đơn hải quan %s — trả phiếu về 'Chưa kiểm tra' để đối soát lại.") % inv_no
            )
        return count

    @api.model
    def retry_misa_customs_match(self, line_id):
        """Thử khớp lại NGAY 1 dòng hải quan cụ thể (bấm tay) — không cần chờ tới lượt cron
        định kỳ, để người dùng thấy ngay kết quả/lý do sau khi vừa tạo/hoàn tất phiếu xuất
        kho hoặc sửa mã hàng trên Odoo."""
        line = self.env['misa.invoice.customs.line'].sudo().browse(line_id)
        if not line.exists():
            return {'matched': False, 'match_note': 'Dòng này không còn tồn tại.'}
        matched = self._misa_invoice_customs_try_match(line)
        return {
            'matched': matched,
            'match_note': line.match_note or '',
            'picking_name': line.picking_id.name if line.picking_id else False,
            'remaining_qty': line.remaining_qty(),
        }

    def _misa_invoice_picking_to_row(self, picking, today):
        done_date = picking.date_done.date() if picking.date_done else False
        master = picking.misa_invoice_master_picking_id
        # Phiếu "ăn theo" 1 đề nghị gộp chung tự lưu misa_invoice_amount = 0 (tránh cộng dồn
        # trùng ở các tổng khác) — hiển thị ở đây thì lấy tiền hóa đơn ĐẦY ĐỦ từ phiếu gốc để
        # người dùng không hiểu lầm "đã xuất HĐ" nhưng tiền lại bằng 0. Dùng effective_amount
        # (không phải misa_invoice_amount thô) để phiếu có trả hàng không hiện lệch giả.
        invoice_amount = (
            (master.misa_invoice_effective_amount or 0.0) if master else (picking.misa_invoice_effective_amount or 0.0)
        )
        diff_source = master if master else picking
        has_return = (picking.misa_invoice_returned_amount or 0.0) > 0
        # Đã khớp 1 PHẦN (không đủ để gán "ăn theo") qua đề nghị xuất HĐ chung của 1 phiếu
        # khác, theo dòng hàng — xem misa_invoice_grouped_matched_amount /
        # _misa_invoice_discover_grouped_orders. Chỉ còn ý nghĩa khi phiếu CHƯA có hóa đơn
        # riêng (nếu đã 'invoiced' hoặc đã "ăn theo" — master có id — thì đã có tiền HĐ đủ rồi).
        grouped_matched_amount = picking.misa_invoice_grouped_matched_amount or 0.0
        has_partial_group_invoice = (
            grouped_matched_amount > 0.01 and picking.misa_invoice_state != 'invoiced' and not master
        )
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
            'actual_amount': picking.misa_invoice_net_actual_amount or 0.0,
            'invoice_amount': invoice_amount,
            'invoice_no': picking.misa_invoice_no or False,
            # TRƯỚC ĐÂY: ép cứng 0 nếu picking.misa_invoice_state == 'invoiced', bất kể
            # invoice_amount có thực sự phủ đủ actual_amount hay không — SAI cho phiếu "ăn
            # theo"/gộp chung mà invoice_amount (effective_amount CỦA CẢ NHÓM, pha loãng) không
            # đủ so với chính net_actual_amount của phiếu này (case y hệt đã sửa ở
            # _misa_invoice_order_row cho tab Đơn hàng — DH...234620). Luôn trừ thật, nhất quán
            # với get_misa_invoice_reconciliation_totals (tính outstanding = actual - invoiced,
            # không có ngoại lệ theo state).
            'outstanding_amount': max((picking.misa_invoice_net_actual_amount or 0.0) - invoice_amount, 0.0),
            # Có trả hàng — tiền HĐ ở trên (invoice_amount) là số ĐÃ COI NHƯ kế toán điều chỉnh
            # (không phải misa_invoice_amount thật từ MISA) — kèm số gốc để frontend tự dựng
            # ghi chú (không build sẵn chuỗi tiếng Việt có định dạng tiền ở đây, để frontend
            # dùng chung 1 hàm formatCurrency() cho nhất quán với toàn bộ dashboard).
            'has_return': has_return,
            'original_invoice_amount': picking.misa_invoice_amount or 0.0,
            'returned_amount': picking.misa_invoice_returned_amount or 0.0,
            # Xuất HĐ MỘT PHẦN qua đề nghị chung của phiếu khác (khớp theo dòng hàng) — kèm số
            # tiền đã khớp để frontend tự dựng ghi chú, cùng convention với has_return ở trên.
            'has_partial_group_invoice': has_partial_group_invoice,
            'grouped_matched_amount': grouped_matched_amount,
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
            # Xem giải thích tương tự ở _misa_invoice_order_row — highlight tới khi hết
            # 'invoiced', không tự xóa reminder_at để giữ lịch sử.
            'reminded': bool(picking.misa_invoice_reminder_at) and picking.misa_invoice_state != 'invoiced',
            'reminder_note': picking.misa_invoice_reminder_at and (
                'Đã nhắc lúc %s%s' % (
                    fields.Datetime.to_string(picking.misa_invoice_reminder_at),
                    (' bởi %s' % picking.misa_invoice_reminder_by_id.name) if picking.misa_invoice_reminder_by_id else '',
                )
            ) or False,
        }

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
        # QUAN TRỌNG: rep.misa_invoice_effective_amount là tiền HÓA ĐƠN CỦA CẢ NHÓM đại diện
        # đó (có thể gộp NHIỀU đơn bán khác nhau vào 1 đề nghị) — cộng thẳng vào invoiced_amount
        # của đơn NÀY có thể ra SỐ THỪA (case thật: 2 đơn khác nhau của cùng khách hàng cùng
        # "ăn theo" 1 đề nghị gộp chung, mỗi đơn lại bị gán ĐỦ cả tiền hóa đơn của group, cộng
        # dồn ra invoiced_amount > amount_total của chính đơn đó — vô lý). Muốn tính ĐÚNG phần
        # tiền hóa đơn CHỈ RIÊNG đơn này cần tra order_code ở dòng hàng (như
        # _misa_invoice_compute_order_coverage_detail đang làm) — nhưng đó là API SỐNG, KHÔNG
        # được gọi tràn lan cho mọi dòng trong 1 danh sách (có thể hàng trăm-nghìn dòng/trang).
        # Chốt lại: chỉ CHẶN TRẦN ở amount_total để số hiển thị không vô lý (đã xuất > tổng
        # đơn) — số chính xác tuyệt đối xem trong drawer chi tiết phiếu (mở riêng từng phiếu).
        #
        # exact=True: order.misa_invoice_exact_* đã từng được tính (qua
        # _misa_invoice_reconcile_order_coverage, chạy MỌI LẦN action_check_misa_invoice_status
        # xử lý 1 phiếu của đơn này — xem stock_picking.py) — dùng THẲNG số đã quy đúng theo
        # order_code qua API sống (không đếm trùng cross-order), rẻ vì chỉ đọc field đã lưu,
        # không gọi lại API lúc render/export. LƯU Ý mẫu số đổi từ amount_total (tổng đơn, kể cả
        # phần CHƯA giao) sang misa_invoice_exact_shipped_amount (đã giao thực tế) — khớp đúng
        # cách "Đối chiếu tổng" đang tính, không còn thổi phồng outstanding cho đơn giao dở dang.
        # Đơn CHƯA từng được tính (exact=False) vẫn dùng công thức xấp xỉ cũ làm fallback.
        exact = bool(order.misa_invoice_exact_checked_at)
        if exact:
            invoiced_amount = min(order.misa_invoice_exact_invoiced_amount, order.misa_invoice_exact_shipped_amount)
            value_partial_coverage = 0 < invoiced_amount < (
                order.misa_invoice_exact_shipped_amount - MISA_INVOICE_AMOUNT_TOLERANCE
            )
        else:
            invoiced_amount = min(
                sum(rep.misa_invoice_effective_amount or 0.0 for rep in representatives.values()),
                order.amount_total,
            )
            # QUAN TRỌNG: KHÁC với overall_state ở trên (chỉ nhìn TRẠNG THÁI thô của từng phiếu,
            # 'partial' = có phiếu invoiced + có phiếu chưa) — cần bắt thêm cả case 1 đơn có TẤT
            # CẢ phiếu đều đã 'invoiced' (nên overall_state ra 'invoiced' bình thường, đúng theo
            # trạng thái từng phiếu) nhưng TỔNG tiền hóa đơn (invoiced_amount, đã tính ở trên)
            # vẫn KHÔNG phủ đủ amount_total — case thật KBC/OUT/11611+11645+11695 (đơn
            # DH...234620): cả 3 phiếu cùng "ăn theo" 1 đề nghị chỉ phủ 7,8tr/28,9tr, mỗi phiếu
            # tự nó vẫn "invoiced" nên trước đây không có gì báo hiệu còn thiếu.
            value_partial_coverage = 0 < invoiced_amount < (order.amount_total - MISA_INVOICE_AMOUNT_TOLERANCE)
        partial_coverage = value_partial_coverage or 'partial' in order_pickings.mapped('misa_invoice_order_coverage')
        return {
            'id': order.id,
            'name': order.name,
            'partner_name': order.partner_id.commercial_partner_id.display_name or '',
            'picking_names': ', '.join(order_pickings.mapped('name')),
            'amount_total': order.amount_total,
            'invoice_amount': invoiced_amount,
            # Trước đây: 0 nếu overall_state=='invoiced', ngược lại LUÔN = amount_total (kể cả
            # khi đã có 1 phần invoiced_amount > 0) — hiện SAI cho mọi đơn "1 phần"/"nhiều
            # phiếu" (case thật: đơn đã xuất 21tr nhưng vẫn báo "còn thiếu" đúng bằng tổng đơn,
            # như đã có tiền đã xuất = 0). Đổi thành phép trừ thật, luôn nhất quán với 2 cột
            # "Tiền đã xuất HĐ" ngay cạnh nó. exact=True: trừ trên misa_invoice_exact_shipped_amount
            # (đã giao thực tế) thay vì amount_total (tổng đơn, kể cả phần chưa giao).
            'outstanding_amount': max(
                (order.misa_invoice_exact_shipped_amount if exact else order.amount_total) - invoiced_amount, 0.0
            ),
            'state': overall_state,
            'state_label': MISA_ORDER_STATE_LABELS.get(overall_state, overall_state),
            'partial_coverage': partial_coverage,
            # True nếu order.misa_invoice_exact_* đã được tính (số tiền chính xác tuyệt đối,
            # quy đúng theo order_code) — dùng ở misa_invoice_export.py để KHÔNG áp lại công
            # thức khử-trùng xấp xỉ (_misa_invoice_dedupe_order_rows) đè lên số đã đúng sẵn.
            'exact': exact,
            # True nếu đơn này đã được xuất HĐ qua từ 2 đề nghị/phiếu đại diện KHÁC NHAU trở
            # lên — VD giao/xuất HĐ nhiều đợt cho cùng 1 đơn (khác với
            # misa_invoice_multi_order_group trên picking, vốn là chiều ngược lại: 1 đề nghị
            # gộp NHIỀU đơn).
            'multi_request': len(representatives) > 1,
            'has_exception': any(order_pickings.mapped('misa_invoice_exception')),
            # Đã bị "nhắc xuất HĐ" và VẪN CHƯA xuất đủ — chỉ highlight khi còn actionable, tự
            # hết highlight khi đơn đã invoiced đủ (không cần dọn field reminder_at, giữ lại để
            # còn lịch sử/audit — xem action_send_misa_invoice_reminder).
            'reminded': bool(order.misa_invoice_reminder_at) and overall_state != 'invoiced',
            'reminder_note': order.misa_invoice_reminder_at and (
                'Đã nhắc lúc %s%s' % (
                    fields.Datetime.to_string(order.misa_invoice_reminder_at),
                    (' bởi %s' % order.misa_invoice_reminder_by_id.name) if order.misa_invoice_reminder_by_id else '',
                )
            ) or False,
            'pickings': [
                {
                    'id': p.id,
                    'name': p.name,
                    'state': p.misa_invoice_state,
                    'state_label': MISA_INVOICE_STATE_LABELS.get(p.misa_invoice_state, p.misa_invoice_state),
                    'actual_amount': p.misa_invoice_net_actual_amount or 0.0,
                    'invoice_amount': (
                        p.misa_invoice_master_picking_id.misa_invoice_effective_amount
                        if p.misa_invoice_master_picking_id else p.misa_invoice_effective_amount
                    ) or 0.0,
                    'invoice_no': p.misa_invoice_no or False,
                    # Số ĐỀ NGHỊ xuất HĐ thật trên MISA (VD "DN0017572") — có thể KHÁC hẳn tên
                    # mọi phiếu (case thật KBC/OUT/11613/đơn DH...234781, đề nghị tên
                    # "DN0017572") — đọc từ phiếu ĐẠI DIỆN (nếu đang "ăn theo") vì phiếu ăn
                    # theo không tự lưu refno của chính mình.
                    'request_refno': (p.misa_invoice_master_picking_id or p).misa_invoice_request_refno or False,
                    'master_picking_id': p.misa_invoice_master_picking_id.id or False,
                    'master_picking_name': p.misa_invoice_master_picking_id.name or False,
                    # Mã đơn hàng của phiếu ĐẠI DIỆN (nếu đang "ăn theo") — phiếu đại diện có
                    # thể thuộc đơn KHÁC với đơn đang xem (case "resolved_elsewhere": đơn A bị
                    # xuất chung với đơn B), hiện thêm ra để không phải tra cứu tay.
                    'master_picking_order_code': (
                        ', '.join(p.misa_invoice_master_picking_id.misa_invoice_sale_order_ids.mapped('name'))
                        if p.misa_invoice_master_picking_id else False
                    ) or False,
                    'exception': p.misa_invoice_exception,
                    'manual_refno': p.misa_invoice_manual_refno or False,
                }
                for p in order_pickings
            ],
        }

    @api.model
    def get_misa_invoice_order_list(
        self, limit=20, offset=0, search=False, state=False, saler_code=False, multi_request=False,
        partial_coverage_only=False, mismatch_only=False, states=None, date_from=False, date_to=False,
        invoice_date_from=False, invoice_date_to=False,
    ):
        """Danh sách ĐƠN BÁN (key là sale.order DH...) — tab 'Đơn hàng' trên dashboard.
        Khác tab 'Phiếu xuất kho': 1 đơn có thể gộp nhiều phiếu/nhiều đề nghị xuất HĐ, nên
        số tiền lấy từ chính đơn bán (amount_total), không cộng dồn từ các phiếu (tránh đếm
        trùng khi 1 phiếu gộp giao cho nhiều đơn).

        state/saler_code lọc theo PHIẾU (không phải theo trạng thái tổng hợp của đơn) — VD
        lọc "Đã xuất HĐ" sẽ ra các đơn có ít nhất 1 phiếu đã xuất HĐ trong phạm vi đang lọc
        (đơn "Một phần đã xuất HĐ" vẫn xuất hiện), đủ dùng để thu hẹp danh sách mà không cần
        tính lại state tổng hợp cho toàn bộ đơn trước khi phân trang.

        states: list nhiều lựa chọn cùng lúc (VD ['missing', 'partial']) — OR với nhau, dùng
        cho bộ lọc multi-select mới trên UI. Khi truyền states thì state/partial_coverage_only/
        mismatch_only (dạng đơn lẻ, giữ lại cho tương thích ngược với dashboard nội bộ) bị bỏ
        qua, không kết hợp cả 2 kiểu cùng lúc cho khỏi rối.

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

        states = [s for s in (states or []) if s]
        if states:
            value_gap = 'value_gap' in states
            normal_states = [s for s in states if s != 'value_gap']
            picking_filter_ids = set()
            if normal_states:
                common_domain = self._misa_invoice_picking_list_domain(
                    False, False, saler_code, date_from, date_to, invoice_date_from, invoice_date_to
                )
                sub_domains = []
                for key in normal_states:
                    if key == 'partial':
                        sub_domains.append(common_domain + [('misa_invoice_order_coverage', '=', 'partial')])
                    elif key == 'mismatch':
                        sub_domains.append(common_domain + [('misa_invoice_amount_mismatch', '=', True)])
                    else:
                        sub_domains.append(common_domain + [('misa_invoice_state', '=', key)])
                picking_filter_ids.update(Picking.search(expression.OR(sub_domains)).ids)
            if value_gap:
                # "Còn nợ tiền HĐ (giá trị)" — bắt case TỪNG PHIẾU của đơn đều tự báo 'invoiced'
                # (không missing/mismatch ở mức phiếu) nhưng invoiced_amount (đã quy về đại diện,
                # khử trùng) vẫn KHÔNG đủ amount_total (xem value_partial_coverage trong
                # _misa_invoice_order_row). misa_invoice_order_coverage (dùng bởi key 'partial'
                # ở trên) KHÔNG bắt được case này vì field đó chỉ được tính lại khi bước refno
                # nhanh báo phiếu 'missing'/mismatch (_misa_invoice_reconcile_order_coverage) —
                # không có tín hiệu nào kích hoạt khi mọi phiếu đã tự 'invoiced'. Không thể diễn
                # tả bằng domain SQL trên stock.picking nên phải quét toàn bộ candidate (giới hạn
                # theo saler_code/ngày, giống phạm vi multi_request) rồi lọc bằng giá trị tiền.
                saler_picking_domain = self._misa_invoice_picking_list_domain(
                    False, False, saler_code, date_from, date_to, invoice_date_from, invoice_date_to
                )
                saler_picking_ids = Picking.search(saler_picking_domain).ids
                value_gap_order_domain = (
                    [('misa_invoice_picking_ids', 'in', saler_picking_ids)] if saler_picking_ids else [('id', '=', 0)]
                )
                for candidate_order in SaleOrder.search(value_gap_order_domain):
                    candidate_row = self._misa_invoice_order_row(candidate_order, base_picking_id_set)
                    if candidate_row['partial_coverage']:
                        picking_filter_ids.update(p['id'] for p in candidate_row['pickings'])
            filter_picking_ids = list(picking_filter_ids)
        elif state or saler_code or partial_coverage_only or mismatch_only:
            filter_picking_domain = self._misa_invoice_picking_list_domain(
                False, state, saler_code, date_from, date_to, invoice_date_from, invoice_date_to
            )
            if partial_coverage_only:
                filter_picking_domain = filter_picking_domain + [('misa_invoice_order_coverage', '=', 'partial')]
            if mismatch_only:
                filter_picking_domain = filter_picking_domain + [('misa_invoice_amount_mismatch', '=', True)]
            filter_picking_ids = Picking.search(filter_picking_domain).ids
        else:
            filter_picking_ids = base_picking_ids

        order_domain = [('misa_invoice_picking_ids', 'in', filter_picking_ids)] if filter_picking_ids else [('id', '=', 0)]
        if search:
            order_domain += ['|', ('name', 'ilike', search), ('partner_id.name', 'ilike', search)]

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
    def get_misa_invoice_public_full_detail(self, picking_id, saler_code):
        """Chi tiết ĐẦY ĐỦ đề nghị xuất HĐ + hóa đơn thật (kèm từng dòng hàng) từ MISA cho
        1 phiếu — dùng cho nút "Xem hóa đơn/đề nghị" ở drawer. Đọc LIVE trực tiếp từ MISA
        (không lưu bảng riêng) vì chỉ gọi khi người dùng chủ động bấm xem 1 phiếu, không phải
        quét hàng loạt."""
        code = self._misa_invoice_validate_public_saler_code(saler_code)
        picking = self.sudo().browse(picking_id).exists()
        if not picking or picking.misa_invoice_saler_code != code:
            raise UserError("Bạn không có quyền xem phiếu này.")
        return picking._misa_invoice_fetch_full_detail()

    def _misa_invoice_fetch_full_detail(self):
        """Đọc theo phiếu ĐẠI DIỆN nếu đang 'ăn theo' (giống mọi chỗ khác đang đọc
        invoice_no/refno) — trả về:
        - 'line_reconciliation': đối chiếu TỪNG DÒNG HÀNG Odoo (xuất kho) vs MISA (đề nghị),
          tái dùng NGUYÊN get_misa_invoice_line_reconciliation() đã có sẵn (đã xử lý đúng case
          gộp nhóm nhiều phiếu/nhiều đơn) — để vẽ 2 bên kèm mũi tên so khớp trên UI, thay vì
          chỉ liệt kê rời rạc dòng hàng MISA như trước.
        - 'invoice'/'invoice_lines': hóa đơn THẬT đã phát hành (sa_voucher_get), kèm dòng hàng
          — tài liệu chính thức, tách riêng khỏi phần đối chiếu ở trên."""
        self.ensure_one()
        effective = self.misa_invoice_master_picking_id or self
        misa_utils = self.env['misa.api.utils']
        result = {
            'picking_name': self.name,
            'effective_picking_name': effective.name,
            'request': False,
            'line_reconciliation': False,
            'invoice': False,
            'invoice_lines': [],
        }

        def _line_dict(l):
            return {
                'order_code': (l.get('order_code') or '').strip(),
                'inventory_item_code': l.get('inventory_item_code') or '',
                'description': l.get('description') or '',
                'quantity': l.get('quantity') or 0.0,
                'unit_price': l.get('unit_price') or 0.0,
                'amount': l.get('amount_oc') or 0.0,
            }

        refid = effective.misa_invoice_request_refid
        if refid:
            result['request'] = {'refid': refid, 'refno': effective.misa_invoice_request_refno or False}
            try:
                result['line_reconciliation'] = self.get_misa_invoice_line_reconciliation(self.id)
            except Exception:
                _logger.exception("Lỗi đối chiếu dòng hàng Odoo/MISA (picking=%s)", self.name)
                result['line_reconciliation'] = False

        invoice_no = effective.misa_invoice_no
        if invoice_no:
            try:
                voucher = misa_utils.get_voucher_by_inv_no(invoice_no)
            except Exception:
                _logger.exception("Lỗi tải hóa đơn MISA (inv_no=%s)", invoice_no)
                voucher = None
            if voucher:
                v_refid = voucher.get('refid')
                result['invoice'] = {
                    'inv_no': voucher.get('inv_no') or invoice_no,
                    'inv_date': voucher.get('inv_date'),
                    'total_amount': voucher.get('total_amount') or 0.0,
                    'account_object_name': voucher.get('account_object_name') or '',
                }
                try:
                    vlines = misa_utils.get_voucher_lines(v_refid) if v_refid else []
                except Exception:
                    _logger.exception("Lỗi tải chi tiết hóa đơn MISA (refid=%s)", v_refid)
                    vlines = []
                result['invoice_lines'] = [_line_dict(l) for l in vlines]
        return result

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

            order_code = sale_line.order_id.name if sale_line else None
            if sale_line and is_kit:
                lines.append({
                    'product_name': sale_line.product_id.display_name,
                    'default_code': sale_line.product_id.default_code or False,
                    'qty': sale_line.product_uom_qty,
                    'uom_name': sale_line.product_uom.name,
                    'value': sale_line.price_subtotal,
                    'pre_tax_unit_price': sale_line.price_unit,
                    'tax_value': sale_line.price_tax,
                    'post_tax_unit_price': (
                        sale_line.price_total / sale_line.product_uom_qty
                        if sale_line.product_uom_qty else sale_line.price_unit
                    ),
                    'is_combo': True,
                    'order_code': order_code,
                })
                for move in group_moves:
                    lines.append({
                        'product_name': move.product_id.display_name,
                        'default_code': move.product_id.default_code or False,
                        'qty': move.quantity,
                        'uom_name': move.product_uom.name,
                        'value': 0.0,
                        'pre_tax_unit_price': 0.0,
                        'tax_value': 0.0,
                        'post_tax_unit_price': 0.0,
                        'is_component': True,
                        'order_code': order_code,
                    })
                continue

            for move in group_moves:
                value = 0.0
                tax_value = 0.0
                post_tax_unit_price = 0.0
                pre_tax_unit_price = sale_line.price_unit if sale_line else 0.0
                if sale_line and sale_line.product_uom_qty:
                    value = move.quantity * (sale_line.price_subtotal / sale_line.product_uom_qty)
                    tax_value = move.quantity * (sale_line.price_tax / sale_line.product_uom_qty)
                    post_tax_unit_price = sale_line.price_total / sale_line.product_uom_qty
                lines.append({
                    'product_name': move.product_id.display_name,
                    'default_code': move.product_id.default_code or False,
                    'qty': move.quantity,
                    'uom_name': move.product_uom.name,
                    'value': value,
                    'pre_tax_unit_price': pre_tax_unit_price,
                    'tax_value': tax_value,
                    'post_tax_unit_price': post_tax_unit_price,
                    'order_code': order_code,
                })
        return lines

    @api.model
    def get_misa_invoice_picking_lines(self, picking_id):
        """Chi tiết sản phẩm/số lượng/giá trị xuất kho của 1 phiếu, dùng cho drawer chi tiết."""
        picking = self.sudo().browse(picking_id)
        if not picking.exists():
            return []
        return self._misa_invoice_picking_line_items(picking)

    def _misa_invoice_group_odoo_lines(self, pickings, misa_codes=None, exclude_order_codes=None):
        """Gộp dòng hàng Odoo của TOÀN BỘ phiếu trong 1 nhóm gộp chung đề nghị xuất HĐ, theo
        mã hàng (default_code) — MISA cũng gộp chung các phiếu này vào 1 đề nghị/hóa đơn nên
        phải so theo tổng cả nhóm, không so lẻ từng phiếu.

        Dòng sản phẩm con của combo/kit (is_component) mặc định bị bỏ qua (giá trị của cả
        combo đã tính đủ ở dòng đại diện) — TRỪ KHI misa_codes cho biết MISA cũng có dòng
        riêng cho đúng mã con đó. Thực tế quan sát được: MISA rã hẳn combo ra từng sản phẩm
        con khi tạo đề nghị xuất HĐ (không giữ 1 dòng combo gộp), nên nếu cứ bỏ qua sẽ báo
        nhầm "thiếu trên Odoo" cho các mã con dù giá trị/số lượng đã được gộp đủ ở dòng combo
        — bật lại dòng con (qty thật, value=0 vì tiền đã nằm ở dòng combo) khi MISA có báo
        đúng mã đó để 2 bên so khớp nhau, còn KHÔNG có ở MISA thì vẫn bỏ qua như cũ.

        exclude_order_codes: bỏ qua các dòng thuộc về 1 đơn hàng đã được xác minh là CÓ hóa
        đơn riêng, độc lập qua 1 đề nghị KHÁC (case thật KBC/OUT/10826 tự xuất đơn
        DH...233733 của chính nó, nhưng đơn đó lại được xuất hóa đơn qua đề nghị của phiếu
        KBC/OUT/11218 hoàn toàn khác) — nếu không loại, dòng hàng của đơn này bị tính lộn vào
        tổng Odoo của nhóm hiện tại trong khi tiền của nó đã nằm ở 1 hóa đơn khác rồi."""
        misa_codes = misa_codes or set()
        exclude_order_codes = exclude_order_codes or set()
        totals = {}
        for picking in pickings:
            for line in self._misa_invoice_picking_line_items(picking):
                if line.get('order_code') and line['order_code'] in exclude_order_codes:
                    continue
                code = line['default_code'] or line['product_name']
                if line.get('is_component') and code not in misa_codes:
                    continue
                bucket = totals.setdefault(
                    code, {
                        'product_name': line['product_name'], 'uom_name': line['uom_name'],
                        'qty': 0.0, 'value': 0.0, 'picking_names': [],
                    }
                )
                bucket['qty'] += line['qty']
                bucket['value'] += line['value']
                if line['qty'] and picking.name not in bucket['picking_names']:
                    bucket['picking_names'].append(picking.name)
        return totals

    def _misa_invoice_group_matched_lines_outside(self, representative, group_pickings):
        """Bù thêm phần hàng đã xuất kho THẬT nhưng qua 1 phiếu KHÔNG nằm trong group_pickings
        — case thật KBC/OUT/06650: chỉ phủ 1 PHẦN giá trị của phiếu này (phần còn lại thuộc 1
        đề nghị xuất HĐ khác), nên đúng ra bị loại khỏi group_pickings (chưa đủ điều kiện gán
        "ăn theo" toàn phần) — nhưng phần ĐÃ khớp của nó (ghi nhận qua
        misa.invoice.grouped.line/.match khi phiếu đại diện discover đơn KHÁC) vẫn phải tính
        vào bảng đối chiếu dòng hàng, nếu không sẽ báo nhầm "Thiếu trên Odoo" cho sản phẩm đã
        xuất kho thật.

        value trả về là tiền CHƯA VAT (prorate theo amount_oc gốc của dòng theo đúng tỉ lệ số
        lượng đã khớp), để cùng đơn vị với _misa_invoice_group_odoo_lines."""
        totals = {}
        glines = self.env['misa.invoice.grouped.line'].sudo().search([
            ('master_picking_id', '=', representative.id),
        ])
        for gline in glines:
            outside_matches = gline.match_ids.filtered(lambda m: m.picking_id not in group_pickings)
            matched_qty_outside = sum(outside_matches.mapped('quantity'))
            if matched_qty_outside <= 0:
                continue
            code = (gline.inventory_item_code or '').strip()
            if not code:
                continue
            pre_vat_value = (gline.amount_oc * matched_qty_outside / gline.quantity) if gline.quantity else 0.0
            bucket = totals.setdefault(code, {'qty': 0.0, 'value': 0.0, 'picking_names': []})
            bucket['qty'] += matched_qty_outside
            bucket['value'] += pre_vat_value
            for name in outside_matches.mapped('picking_id.name'):
                if name not in bucket['picking_names']:
                    bucket['picking_names'].append(name)
        return totals

    def _misa_invoice_request_lines_by_code(self, misa_lines):
        """Gộp dòng hàng MISA (đã lấy qua get_invoice_request_lines) theo mã hàng
        (inventory_item_code) — 1 mã hàng có thể xuất hiện nhiều lần nếu đề nghị gộp
        nhiều đơn bán khác nhau cùng mua chung 1 sản phẩm."""
        totals = {}
        for line in misa_lines:
            code = line.get('inventory_item_code') or line.get('description') or '?'
            bucket = totals.setdefault(
                code, {
                    'product_name': line.get('description'), 'unit_name': line.get('unit_name'),
                    'qty': 0.0, 'value': 0.0, 'order_codes': [],
                }
            )
            bucket['qty'] += line.get('quantity') or 0.0
            bucket['value'] += line.get('amount_oc') or 0.0
            order_code = (line.get('order_code') or '').strip()
            if order_code and order_code not in bucket['order_codes']:
                bucket['order_codes'].append(order_code)
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

    def _misa_invoice_filter_cross_request_orders(self, representative, group_pickings, misa_lines):
        """Tìm các đơn hàng bị "double book" giữa 2 đề nghị xuất HĐ HOÀN TOÀN khác nhau — case
        thật: phiếu KBC/OUT/10826 tự xuất đơn DH...233733 của CHÍNH NÓ, nhưng đơn đó lại được 1
        đề nghị KHÁC (của phiếu KBC/OUT/11218, không liên quan gì tới 10826) xác nhận hóa đơn,
        trong khi đề nghị CỦA CHÍNH 10826 chỉ nói tới 1 đơn khác hẳn (DH...234645, qua phiếu
        11771). Nếu không lọc, bảng đối chiếu dòng hàng báo SAI Ở CẢ 2 CHIỀU: bên 10826 báo
        "thiếu trên MISA" (Odoo có xuất đơn 233733, đề nghị của 10826 không nhắc), bên 11218
        báo "thiếu trên Odoo" (đề nghị của 11218 có nhắc đơn 233733, nhưng nhóm Odoo của 11218
        không xuất đơn đó) — trong khi thực ra 2 số đó CHỈ LÀ 1 và bù trừ đúng nhau.

        Trả về (excluded_misa_orders, excluded_odoo_orders):
        - excluded_misa_orders: mã đơn xuất hiện trong misa_lines của đề nghị này nhưng THỰC RA
          thuộc về 1 phiếu KHÁC (ngoài group) đã có hóa đơn riêng qua 1 đề nghị khác — loại khỏi
          misa_totals vì tiền của nó không thuộc đề nghị đang xem.
        - excluded_odoo_orders: mã đơn hàng CHÍNH của 1 phiếu trong group nhưng đề nghị này
          không hề nhắc tới, ĐÃ xác minh qua MISA là có hóa đơn riêng ở 1 đề nghị khác — loại
          khỏi odoo_totals vì tiền của nó đã nằm ở hóa đơn khác rồi, không phải thiếu thật."""
        own_order_codes = set(group_pickings.mapped('misa_invoice_sale_order_ids.name'))
        misa_order_codes = {
            (line.get('order_code') or '').strip() for line in misa_lines if line.get('order_code')
        }

        excluded_misa_orders = set()
        for order_code in misa_order_codes - own_order_codes:
            other_pickings = self.sudo().search([('misa_invoice_sale_order_ids.name', '=', order_code)])
            elsewhere = other_pickings.filtered(
                lambda p: p.misa_invoice_state == 'invoiced'
                and p.misa_invoice_request_refid
                and p.misa_invoice_request_refid != representative.misa_invoice_request_refid
            )
            if elsewhere:
                excluded_misa_orders.add(order_code)

        excluded_odoo_orders = set()
        for order_code in own_order_codes - misa_order_codes:
            total_invoiced, _sources = self._misa_invoice_sum_invoiced_for_order(
                order_code, exclude_refids={representative.misa_invoice_request_refid}
            )
            if total_invoiced > MISA_INVOICE_AMOUNT_TOLERANCE:
                excluded_odoo_orders.add(order_code)

        return excluded_misa_orders, excluded_odoo_orders

    def _misa_invoice_fallback_match_by_name(self, odoo_totals, misa_totals):
        """Fallback khớp theo TÊN sản phẩm khi không khớp được theo mã hàng — 1 sản phẩm có
        thể đã bị LƯU TRỮ (archived) và GỠ default_code để gán mã đó cho 1 sản phẩm MỚI khác
        (thực tế hay gặp khi đổi/thay nhà cung cấp cùng 1 mặt hàng), khiến các move CŨ của nó
        không còn mã nội bộ (default_code=False) dù MISA vẫn ghi đúng TÊN hàng lúc xuất kho —
        case thật: 'Dây cáp vải 5Tx6M' không có default_code, phải khớp qua tên với dòng MISA
        cùng tên (MISA vẫn có inventory_item_code riêng, không liên quan gì tới việc Odoo còn
        giữ mã hay không).

        CHỈ áp dụng cho các mã CHƯA khớp được ở CẢ 2 BÊN (tránh phá vỡ những mã đã khớp đúng
        theo code) — đổi KHÓA của phía Odoo sang đúng khóa MISA khi tên khớp Y HỆT (so sánh đã
        chuẩn hóa hoa/thường + khoảng trắng đầu-cuối), không suy đoán khớp gần đúng/mờ để tránh
        gán nhầm sang sản phẩm khác tên tương tự. Chỉ đổi khóa hiển thị, KHÔNG cộng gộp số liệu
        2 bên vào nhau — số Odoo/MISA vẫn giữ nguyên, chỉ để chúng xuất hiện CHUNG 1 dòng thay
        vì 2 dòng "Thiếu trên Odoo"/"Thiếu trên MISA" giả tạo."""
        unmatched_odoo = [code for code in odoo_totals if code not in misa_totals]
        unmatched_misa = {code: val for code, val in misa_totals.items() if code not in odoo_totals}
        used_misa_codes = set()
        renamed = {}
        for o_code in unmatched_odoo:
            o_name = (odoo_totals[o_code].get('product_name') or o_code or '').strip().casefold()
            if not o_name:
                continue
            for m_code, m_val in unmatched_misa.items():
                if m_code in used_misa_codes:
                    continue
                m_name = (m_val.get('product_name') or m_code or '').strip().casefold()
                if m_name and m_name == o_name:
                    renamed[o_code] = m_code
                    used_misa_codes.add(m_code)
                    break
        for o_code, m_code in renamed.items():
            odoo_totals[m_code] = odoo_totals.pop(o_code)
        return odoo_totals

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

        excluded_misa_orders, excluded_odoo_orders = self._misa_invoice_filter_cross_request_orders(
            representative, group_pickings, misa_lines
        )
        misa_lines_for_group = misa_lines
        if excluded_misa_orders:
            misa_lines_for_group = [
                line for line in misa_lines
                if (line.get('order_code') or '').strip() not in excluded_misa_orders
            ]

        misa_totals = self._misa_invoice_request_lines_by_code(misa_lines_for_group)
        odoo_totals = self._misa_invoice_group_odoo_lines(
            group_pickings, misa_codes=set(misa_totals.keys()), exclude_order_codes=excluded_odoo_orders
        )
        matched_outside = self._misa_invoice_group_matched_lines_outside(representative, group_pickings)
        for code, extra in matched_outside.items():
            bucket = odoo_totals.get(code)
            if bucket is None:
                bucket = {'product_name': None, 'uom_name': None, 'qty': 0.0, 'value': 0.0, 'picking_names': []}
                odoo_totals[code] = bucket
            bucket['qty'] += extra['qty']
            bucket['value'] += extra['value']
            existing_names = bucket.setdefault('picking_names', [])
            for name in extra['picking_names']:
                if name not in existing_names:
                    existing_names.append(name)
        odoo_totals = self._misa_invoice_fallback_match_by_name(odoo_totals, misa_totals)
        group_breakdown = self._misa_invoice_compute_group_breakdown(representative, group_pickings, misa_lines)

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
                # Dòng này thuộc VỀ phiếu xuất kho nào (bên Odoo) / đơn hàng nào (bên MISA) —
                # bắt buộc phải có khi nhóm gộp nhiều phiếu/nhiều đơn, nếu không "Thiếu trên
                # Odoo: 550.000đ" không nói lên được gì, không biết đi hỏi ai/kiểm tra phiếu
                # nào (bài học thật: nhóm 11 phiếu, nhìn bảng cũ không đoán được).
                'odoo_picking_names': (odoo and odoo['picking_names']) or [],
                'misa_order_codes': (misa and misa['order_codes']) or [],
            })
        rows.sort(key=lambda r: (not r['mismatch'], r['product_name'] or ''))

        return {
            'rows': rows,
            'group_picking_names': group_pickings.mapped('name'),
            'order_level': {
                'actual_amount': sum(group_pickings.mapped('misa_invoice_net_actual_amount')),
                'invoice_amount': representative.misa_invoice_effective_amount or 0.0,
                'diff': representative.misa_invoice_amount_diff,
                'mismatch': representative.misa_invoice_amount_mismatch,
            },
            'group_breakdown': group_breakdown,
        }

    def _misa_invoice_compute_group_breakdown(self, representative, group_pickings, misa_lines):
        """Chia nhỏ tiền hóa đơn của 1 nhóm gộp chung ra từng "phần" để vẽ donut giải thích rõ
        lệch ở đâu — thay vì chỉ hiện 1 con số "chênh lệch" khó hiểu. Case thật KBC/OUT/10735:
        hóa đơn nhắc tới đơn DH...234127 nhưng phiếu xuất kho của đơn đó (KBC/OUT/11154) đang
        'Sẵn sàng' (chưa xuất kho) — phải nói RÕ đây là lý do lệch, không được im lặng bỏ qua.

        Mỗi phần (slice) có `kind`:
        - 'linked': 1 phiếu ĐÃ trong nhóm (đã xuất kho) — amount = tiền thực xuất ròng của phiếu đó.
        - 'not_shipped': đơn hàng được nhắc tới trong đề nghị, có phiếu xuất kho nhưng CHƯA
          hoàn tất ('done') — amount = tiền dòng hàng (có VAT) của đơn đó theo MISA.
        - 'no_picking': đơn hàng được nhắc tới nhưng chưa có phiếu xuất kho nào trong Odoo.
        - 'unknown_order': không tìm thấy đơn bán nào khớp mã đơn MISA trả về.
        - 'not_matched': có phiếu ĐÃ 'done' cho đơn này nhưng CHƯA được đối soát/gán vào nhóm
          nào cả (misa_invoice_state != 'invoiced', không có master/covered) — KHÔNG PHẢI lỗi,
          chỉ là chưa được "Quét đơn xuất kèm" xử lý tới.
        - 'conflict': có phiếu đã 'done' cho đơn này và ĐÃ có hóa đơn ở nơi KHÁC — hoặc do đã
          bị 1 nhóm khác nhận (master/covered), hoặc đã TỰ có misa_invoice_state='invoiced' độc
          lập. TRƯỚC KHI gắn nhãn này, đã chủ động hỏi MISA (get_invoice_requests_for_order)
          tổng tiền đã xuất hóa đơn cho đúng đơn này qua TẤT CẢ đề nghị hiện có, so với tổng
          tiền thực xuất thật — nếu khớp đủ thì xếp vào 'resolved_elsewhere' thay vì 'conflict'.
          Chỉ còn lại 'conflict' khi xác minh xong vẫn KHÔNG khớp (thiếu hoặc thừa) — thật sự
          cần kiểm tra tay.
        - 'resolved_elsewhere': đã XÁC MINH qua MISA rằng đơn này được xuất hóa đơn ĐỦ, chỉ là
          qua 1 hay nhiều đề nghị khác nhau (không phải đề nghị đang xem) — case thật: 1 đơn bán
          2 cái, 2 phiếu xuất kho, mỗi phiếu 1 đề nghị xuất HĐ RIÊNG BIỆT, cộng lại vừa đủ.
          amount luôn = 0 (không tính vào phần "còn thiếu"), không cần kiểm tra tay.
        - 'self_unconfirmed': CHÍNH phiếu ĐẠI DIỆN của nhóm chỉ được đề nghị xuất HĐ này xác
          nhận đúng 1 PHẦN giá trị của chính nó qua dòng hàng — phần còn lại vẫn hiện trong
          'linked' như bình thường nhưng KHÔNG có dòng hàng nào trong đề nghị này xác nhận (bài
          học thật: phiếu xuất kho dùng làm đề nghị xuất HĐ cũng có thể chỉ phủ 1 phần chính nó
          — trước đây mặc định coi phiếu đại diện là 'linked' ĐỦ 100% chỉ vì nó là gốc của
          nhóm, không hề đối chiếu dòng hàng riêng cho chính nó). CHỈ áp dụng cho phiếu đại
          diện — phiếu "ăn theo" (covered) dùng thẳng misa_invoice_grouped_matched_amount đã
          lưu sẵn (cộng dồn ĐÚNG từ MỌI đề nghị từng khớp nó, không chỉ đề nghị đang xem — bài
          học thật: 1 phiếu ăn theo có thể được khớp một phần bởi đề nghị NÀY, một phần bởi 1
          đề nghị KHÁC hoàn toàn — nếu chỉ tính theo dòng hàng của đề nghị đang xem sẽ báo nhầm
          "chưa xác nhận" cho phần đã được đề nghị khác xác nhận từ trước)."""
        accounted_order_codes = set(group_pickings.mapped('misa_invoice_sale_order_ids').mapped('name'))
        lines_by_order = {}
        for line in misa_lines:
            code = (line.get('order_code') or '').strip()
            if not code:
                continue
            lines_by_order.setdefault(code, []).append(line)

        slices = []
        for p in group_pickings.sorted('date_done'):
            net_actual = p.misa_invoice_net_actual_amount or 0.0
            known_refids = {representative.misa_invoice_request_refid}
            if p.id == representative.id:
                # Phiếu đại diện: không có misa_invoice_grouped_matched_amount cho CHÍNH nó
                # (cơ chế khớp dòng hàng luôn loại trừ chính phiếu đại diện khỏi việc "tự khớp
                # mình" — xem exclude_picking_ids trong _misa_invoice_discover_grouped_orders),
                # nên phải tự đối chiếu dòng hàng của CHÍNH đề nghị đang xem cho phần của nó.
                own_lines = [
                    line for code in p.misa_invoice_sale_order_ids.mapped('name')
                    for line in lines_by_order.get(code, [])
                ]
                # QUAN TRỌNG (case thật KBC/OUT/10826): trước đây nếu KHÔNG có dòng hàng nào
                # của đơn thuộc CHÍNH phiếu đại diện trong đề nghị đang xét thì mặc định "tin
                # đủ" (confirmed = net_actual) để tránh báo động giả — nhưng điều đó lại VÔ
                # TÌNH bỏ qua luôn bước xác minh qua đề nghị khác bên dưới, nên khi đơn của
                # chính phiếu đại diện thực ra được xuất hóa đơn qua 1 đề nghị HOÀN TOÀN khác
                # (không liên quan gì tới nhóm này), hệ thống coi như "không có gì bất thường"
                # và "Cập nhật lý do" không hiện được lý do thật. Đổi lại: coi như CHƯA xác
                # nhận (confirmed=0) để luôn đi qua bước xác minh chung bên dưới — nếu có đề
                # nghị khác xác nhận đủ thì vẫn ra kết quả đúng (confirmed=net_actual) NHƯNG
                # đã được XÁC MINH thật, không phải đoán.
                confirmed = min(representative._misa_invoice_request_line_amount(own_lines), net_actual) if own_lines else 0.0
            else:
                # Phiếu "ăn theo" (covered): 2 NGUỒN xác nhận độc lập, lấy nguồn nào LỚN HƠN
                # (không cộng dồn cả 2 — tránh đếm trùng):
                # (1) misa_invoice_grouped_matched_amount — cộng dồn từ MỌI đề nghị từng khớp
                #     nó qua cơ chế FIFO line-matching (_misa_invoice_discover_grouped_orders).
                # (2) dòng hàng của CHÍNH đơn thuộc phiếu này có ngay trong đề nghị đang xem
                #     (lines_by_order) — QUAN TRỌNG (case thật KBC/OUT/09521): phiếu ăn theo
                #     được gán qua cơ chế master_refno CŨ (MISA tự báo đúng tên phiếu đại diện,
                #     xem action_check_misa_invoice_status) KHÔNG đi qua FIFO line-matching nên
                #     KHÔNG BAO GIỜ có misa.invoice.grouped.line/match record — (1) mãi mãi = 0
                #     dù dòng hàng của nó đã nằm sẵn ngay trong đề nghị đang xem, khiến nó bị
                #     báo nhầm "chưa xác nhận" toàn bộ dù thực ra đã khớp đủ.
                own_lines = [
                    line for code in p.misa_invoice_sale_order_ids.mapped('name')
                    for line in lines_by_order.get(code, [])
                ]
                own_lines_amount = representative._misa_invoice_request_line_amount(own_lines) if own_lines else 0.0
                confirmed = min(max(p.misa_invoice_grouped_matched_amount or 0.0, own_lines_amount), net_actual)
                if p.misa_invoice_request_refid:
                    known_refids.add(p.misa_invoice_request_refid)
            shortfall = max(net_actual - confirmed, 0.0)

            # QUAN TRỌNG (case thật KBC/OUT/10714): còn thiếu không có nghĩa là THẬT SỰ thiếu —
            # đơn hàng của phiếu này có thể bị CHIA xác nhận qua 1 đề nghị HOÀN TOÀN riêng biệt
            # mà hệ thống chưa từng biết tới (khác request_refid, có thể do đề nghị đó chưa bao
            # giờ được quét/khớp cho phiếu này). Chỉ khi THẬT SỰ còn thiếu mới chủ động hỏi MISA
            # "có đề nghị nào KHÁC nhắc tới đơn này không" (get_invoice_requests_for_order) —
            # tránh tốn thêm API cho mọi phiếu, chỉ hỏi khi cần xác minh.
            verified_sources = []
            unexplained_note = None
            if shortfall > MISA_INVOICE_AMOUNT_TOLERANCE:
                needed = shortfall
                extra_amount, verify_sources = self._misa_invoice_verify_order_via_other_requests(
                    p.misa_invoice_sale_order_ids.mapped('name'), known_refids,
                )
                if extra_amount > 0:
                    # QUAN TRỌNG (case thật KBC/OUT/10826, phát hiện khi đối chiếu 2 chiều với
                    # KBC/OUT/11218): số tìm được ở đề nghị khác PHẢI khớp GẦN ĐÚNG với đúng
                    # phần còn thiếu mới coi là đã xử lý xong — nếu tìm ra NHIỀU/ÍT hơn hẳn (ở
                    # đây thừa 756.000đ, do 1 dòng CAPVAI5TX6M bị MISA gộp chung số lượng của 2
                    # đơn khác nhau vào 1 dòng), đó vẫn là 1 bất thường THẬT — trước đây cứ tìm
                    # ra >= phần cần bù là coi như xong (min() "nuốt" mất phần thừa/thiếu, ĐỒNG
                    # THỜI làm shortfall về 0 nên self_unconfirmed cũng không hiện ra — im lặng
                    # 2 lần), khiến 1 nhóm tự nhận "đã xác minh" trong khi phía đối ứng (11218)
                    # vẫn đúng khi báo "conflict" — 2 nơi mâu thuẫn nhau, tổng KPI và tổng bảng
                    # "Đối chiếu tổng" lệch nhau không giải thích được. Chỉ áp dụng extra_amount
                    # vào confirmed khi khớp gần đúng; nếu không, GIỮ NGUYÊN shortfall ban đầu
                    # (không capping) để self_unconfirmed vẫn hiện, kèm ghi chú đã tìm thấy gì.
                    if abs(extra_amount - needed) <= MISA_INVOICE_AMOUNT_TOLERANCE:
                        confirmed = min(confirmed + extra_amount, net_actual)
                        shortfall = max(net_actual - confirmed, 0.0)
                        verified_sources = verify_sources
                    else:
                        refnos = ', '.join(s['refno'] for s in verify_sources if s.get('refno'))
                        diff_fmt = '{:,.0f}'.format(abs(extra_amount - needed)).replace(',', '.')
                        unexplained_note = (
                            'đã tìm thấy %s đ xác nhận qua đề nghị %s cho đơn %s, nhưng %s đúng %s đ '
                            'so với phần còn thiếu (%s) — có thể do 1 dòng hàng bị MISA gộp chung số '
                            'lượng của nhiều đơn khác nhau, cần kiểm tra tay'
                        ) % (
                            '{:,.0f}'.format(extra_amount).replace(',', '.'), refnos or '?',
                            ', '.join(p.misa_invoice_sale_order_ids.mapped('name')),
                            'thừa' if extra_amount > needed else 'thiếu', diff_fmt,
                            p.name,
                        )

            slices.append({
                'kind': 'linked',
                'label': p.name,
                'amount': confirmed,
                'picking_id': p.id,
            })
            if verified_sources:
                # Ghi nhận rõ: phần tiền trên KHÔNG PHẢI tự đề nghị này xác nhận, mà đã được
                # XÁC MINH qua (các) đề nghị khác hoàn toàn — amount=0 (không cộng dồn lần 2,
                # tiền đã nằm trong 'linked' ở trên), chỉ để hiển thị minh bạch lý do. Nói rõ
                # ĐÚNG những gì đã xác minh (đơn nào, qua đề nghị nào) thay vì câu chung chung
                # "đã xác nhận đủ qua đề nghị khác" — bài học thật (case KBC/OUT/10826): người
                # xem không tự suy ra được là do dòng hàng trên đề nghị KHÁC vẫn ghi đúng mã đơn
                # của phiếu này, chỉ là MISA gán NHẦM số đề nghị — phải nói thẳng ra.
                order_names = ', '.join(p.misa_invoice_sale_order_ids.mapped('name'))
                refnos = ', '.join(s['refno'] for s in verified_sources if s.get('refno'))
                slices.append({
                    'kind': 'resolved_elsewhere',
                    # 'label' hiện trong LEGEND donut — phải NGẮN (giống các slice khác đều
                    # dùng tên phiếu), câu giải thích đầy đủ để riêng ở 'text' (hiện trong dòng
                    # "Cập nhật lý do lệch" của dashboard, có chỗ hiện câu dài).
                    'label': '%s (qua %s)' % (p.name, refnos or '?'),
                    'text': (
                        '%s tự xuất đơn %s, nhưng đơn này lại nằm trong đề nghị %s (không phải '
                        'đề nghị của chính %s) — MISA ghi nhầm số đề nghị, dòng hàng vẫn đúng mã '
                        'đơn, không phải thiếu tiền'
                    ) % (p.name, order_names, refnos or '?', p.name),
                    'amount': 0.0,
                    'picking_id': p.id,
                    'picking_names': [p.name],
                })
            if shortfall > MISA_INVOICE_AMOUNT_TOLERANCE:
                slices.append({
                    'kind': 'self_unconfirmed',
                    'label': p.name,
                    'text': (
                        '%s chỉ được đề nghị này xác nhận 1 phần chính nó, còn thiếu %s đ — %s' % (
                            p.name, '{:,.0f}'.format(shortfall).replace(',', '.'), unexplained_note
                        ) if unexplained_note else None
                    ),
                    'amount': shortfall,
                    'picking_id': p.id,
                })

        for order_code, order_lines in lines_by_order.items():
            if order_code in accounted_order_codes:
                continue
            order_amount = representative._misa_invoice_request_line_amount(order_lines)
            # active_test=False: xem lý do ở _misa_invoice_discover_grouped_orders — đơn bán cũ
            # có thể đã bị lưu trữ (active=False), phải tìm cả đơn lưu trữ để không báo nhầm
            # "không tìm thấy đơn bán".
            order = self.env['sale.order'].sudo().with_context(active_test=False).search(
                [('name', '=', order_code)], limit=1,
            )
            if not order:
                slices.append({
                    'kind': 'unknown_order', 'label': order_code, 'amount': order_amount,
                    'order_code': order_code,
                })
                continue
            order_pickings = self.sudo().search([
                ('misa_invoice_sale_order_ids', '=', order.id),
                ('picking_type_id.code', '=', 'outgoing'),
            ])
            not_done = order_pickings.filtered(lambda p: p.state not in ('done', 'cancel'))
            if not_done:
                slices.append({
                    'kind': 'not_shipped',
                    'label': ', '.join(not_done.mapped('name')),
                    'amount': order_amount,
                    'order_code': order_code,
                    'picking_names': not_done.mapped('name'),
                    'picking_ids': not_done.ids,
                    'picking_states': [STOCK_PICKING_STATE_LABELS.get(p.state, p.state) for p in not_done],
                })
            elif not order_pickings:
                slices.append({
                    'kind': 'no_picking', 'label': order_code, 'amount': order_amount,
                    'order_code': order_code,
                })
            else:
                # Tất cả pickings của đơn này đã 'done' — phân biệt "chưa từng được đối soát"
                # (không phải lỗi, chỉ chưa quét tới) với "đã có hóa đơn RIÊNG ở nơi khác" (đã
                # bị 1 nhóm khác nhận HOẶC tự có misa_invoice_state='invoiced' độc lập — case
                # thật: 1 đơn bán 2 cái, 2 phiếu xuất kho, mỗi phiếu có 1 đề nghị xuất HĐ riêng
                # biệt, hoàn toàn hợp lệ — không phải "chưa đối soát").
                claimed_elsewhere = order_pickings.filtered(
                    lambda p: p.misa_invoice_master_picking_id or p.misa_invoice_covered_picking_ids
                    or p.misa_invoice_state == 'invoiced'
                )
                not_matched = order_pickings - claimed_elsewhere
                if not_matched:
                    slices.append({
                        'kind': 'not_matched',
                        'label': ', '.join(not_matched.mapped('name')),
                        'amount': order_amount if not claimed_elsewhere else sum(
                            not_matched.mapped('misa_invoice_net_actual_amount')
                        ),
                        'order_code': order_code,
                        'picking_names': not_matched.mapped('name'),
                        'picking_ids': not_matched.ids,
                    })
                if claimed_elsewhere:
                    # QUAN TRỌNG (case thật KBC/OUT/10714, lặp lại ở MỨC ĐƠN HÀNG): đơn này có
                    # thể ĐÃ được xuất hóa đơn ĐỦ — chỉ là qua NHIỀU đề nghị khác nhau (không
                    # chỉ đề nghị đang xem) — trước khi kết luận đây là "cần kiểm tra tay", xác
                    # minh qua _misa_invoice_compute_order_coverage_detail (CÙNG nguồn số liệu
                    # với misa_invoice_order_coverage — không tự gọi lại API riêng ở đây nữa).
                    # Dùng ngưỡng ĐỐI XỨNG (abs diff <= tolerance) của RIÊNG donut này, không
                    # dùng detail['level'] (ngưỡng lỏng 1 chiều, không phân biệt được thừa bất
                    # thường — xem docstring helper).
                    detail = self._misa_invoice_compute_order_coverage_detail(order_code)
                    all_actual = detail['shipped']
                    total_invoiced = detail['invoiced']
                    verify_sources = detail['sources']
                    if total_invoiced and abs(total_invoiced - all_actual) <= MISA_INVOICE_AMOUNT_TOLERANCE:
                        # Xác nhận: đơn này ĐÃ có đủ hóa đơn (qua 1 hay nhiều đề nghị riêng biệt)
                        # — không phải gap thật, không tính vào phần "còn thiếu", không cần
                        # kiểm tra tay nữa. Nói rõ đơn nào (order_code), phiếu nào xuất kho
                        # (claimed_elsewhere), và ĐÃ TÌM RA hóa đơn thật ở đề nghị nào (refnos) —
                        # không chỉ nói chung chung "đã xác nhận đủ".
                        refnos = ', '.join(s['refno'] for s in verify_sources if s.get('refno'))
                        slices.append({
                            'kind': 'resolved_elsewhere',
                            'label': ', '.join(claimed_elsewhere.mapped('name')),
                            'text': 'đơn %s (phiếu %s) đã có hóa đơn qua đề nghị %s (không phải đề nghị đang xem) — không phải thiếu, chỉ khác đề nghị' % (
                                order_code, ', '.join(claimed_elsewhere.mapped('name')), refnos or '?'
                            ),
                            'amount': 0.0,
                            'order_code': order_code,
                            'picking_names': claimed_elsewhere.mapped('name'),
                            'picking_ids': claimed_elsewhere.ids,
                        })
                    else:
                        # Đã hỏi MISA nhưng số tìm được (total_invoiced) KHÔNG khớp đúng với
                        # tổng tiền thực xuất (all_actual) của đơn này — nói rõ CHÊNH LỆCH THẬT
                        # là bao nhiêu và đã tìm thấy gì ở đâu, để người xem biết ngay hướng
                        # kiểm tra thay vì chỉ thấy "đã bị đề nghị khác nhận" mơ hồ.
                        diff_fmt = '{:,.0f}'.format(abs(total_invoiced - all_actual)).replace(',', '.') if total_invoiced else None
                        slices.append({
                            'kind': 'conflict',
                            'label': ', '.join(claimed_elsewhere.mapped('name')),
                            'text': (
                                'đơn %s (phiếu %s) đã bị đề nghị khác nhận, nhưng tổng tiền hóa đơn tìm '
                                'được (%s đ) lệch %s đ so với tiền thực xuất (%s đ) — cần kiểm tra tay'
                            ) % (
                                order_code, ', '.join(claimed_elsewhere.mapped('name')),
                                '{:,.0f}'.format(total_invoiced).replace(',', '.'), diff_fmt,
                                '{:,.0f}'.format(all_actual).replace(',', '.'),
                            ) if total_invoiced else None,
                            'amount': order_amount if not not_matched else max(
                                order_amount - sum(not_matched.mapped('misa_invoice_net_actual_amount')), 0.0
                            ),
                            'order_code': order_code,
                            'picking_names': claimed_elsewhere.mapped('name'),
                            'picking_ids': claimed_elsewhere.ids,
                        })

        return {
            'slices': slices,
            'total': sum(s['amount'] for s in slices),
        }

    def _misa_invoice_gap_summary_text(self, breakdown):
        """Rút gọn group_breakdown (xem _misa_invoice_compute_group_breakdown) thành 1 chuỗi
        ngắn, đọc được ngay trong danh sách "Đối chiếu tổng" — không cần mở drawer từng phiếu.
        Chỉ liệt kê các lát KHÔNG PHẢI 'linked' (đó mới là phần gây lệch).

        LƯU Ý: 'resolved_elsewhere' VẪN phải sinh text dù amount luôn = 0 — nếu để rỗng, UI
        (misa_invoice_dashboard.xml, t-if="row.gap_summary") không phân biệt được "đã kiểm tra,
        không có gì bất thường" với "chưa từng kiểm tra", nên vẫn hiện nhầm "Chưa rõ lý do —
        bấm Cập nhật lý do" dù đã bấm và đã xác minh xong (case thật KBC/OUT/10826)."""
        gap_slices = [s for s in breakdown['slices'] if s['kind'] != 'linked']
        if not gap_slices:
            return ''
        parts = []
        for s in gap_slices:
            if s.get('text'):
                # Ưu tiên câu giải thích ĐẦY ĐỦ do nơi tạo slice tự soạn (nói rõ đơn nào, phiếu
                # nào, qua đề nghị nào) — chỉ dùng mẫu câu chung chung bên dưới khi không có.
                parts.append(s['text'])
            elif s['kind'] == 'resolved_elsewhere':
                parts.append('%s đã xác nhận đủ qua đề nghị khác' % s['label'])
            elif s['kind'] == 'not_shipped':
                parts.append('%s chưa xuất kho (%s đ)' % (s['label'], '{:,.0f}'.format(s['amount']).replace(',', '.')))
            elif s['kind'] == 'no_picking':
                parts.append('đơn %s chưa có phiếu xuất kho (%s đ)' % (
                    s['order_code'], '{:,.0f}'.format(s['amount']).replace(',', '.')
                ))
            elif s['kind'] == 'unknown_order':
                parts.append('không tìm thấy đơn bán %s (%s đ)' % (
                    s['order_code'], '{:,.0f}'.format(s['amount']).replace(',', '.')
                ))
            elif s['kind'] == 'self_unconfirmed':
                parts.append('%s chỉ được đề nghị này xác nhận 1 phần chính nó, còn thiếu %s đ' % (
                    s['label'], '{:,.0f}'.format(s['amount']).replace(',', '.')
                ))
            elif s['kind'] == 'not_matched':
                parts.append('%s đã xuất kho nhưng chưa được đối soát/gộp (%s đ)' % (
                    s['label'], '{:,.0f}'.format(s['amount']).replace(',', '.')
                ))
            elif s['kind'] == 'conflict':
                parts.append('%s đã bị đề nghị khác nhận (%s đ)' % (
                    s['label'], '{:,.0f}'.format(s['amount']).replace(',', '.')
                ))
        return '; '.join(parts)

    def _misa_invoice_refresh_gap_summary(self, misa_lines=None, group_pickings=None):
        """Tính lại và LƯU misa_invoice_gap_summary cho 1 phiếu đại diện — dùng để hiện ngay
        trong danh sách "Đối chiếu tổng" (679 phiếu lệch) mà KHÔNG cần gọi API MISA cho từng
        dòng khi hiện danh sách đó (chỉ đọc field đã lưu sẵn). `misa_lines`/`group_pickings` —
        nếu đã có sẵn (VD gọi từ _misa_invoice_discover_grouped_orders, cùng 1 lượt quét) thì
        truyền vào để khỏi gọi thêm 1 API MISA; nếu không sẽ tự fetch."""
        self.ensure_one()
        if not self.misa_invoice_request_refid:
            return
        if group_pickings is None:
            group_pickings = self | self.misa_invoice_covered_picking_ids
        if misa_lines is None:
            try:
                misa_lines = self.env['misa.api.utils'].get_invoice_request_lines(self.misa_invoice_request_refid)
            except Exception:
                _logger.exception("❌ [MISA GAP SUMMARY] Lỗi đọc chi tiết dòng hàng cho phiếu %s", self.name)
                return
        breakdown = self._misa_invoice_compute_group_breakdown(self, group_pickings, misa_lines)
        gap_slices = [s for s in breakdown['slices'] if s['kind'] != 'linked']
        # "Đã xác minh xong" = có phân tích ra lý do (không phải im lặng không thấy gì) VÀ mọi
        # lý do đó đều là 'resolved_elsewhere' (đã XÁC MINH đủ qua đề nghị khác) — chỉ cần 1 lát
        # thuộc loại khác (self_unconfirmed/not_matched/conflict/...) là vẫn còn việc cần xử lý.
        gap_resolved = bool(gap_slices) and all(s['kind'] == 'resolved_elsewhere' for s in gap_slices)
        self.write({
            'misa_invoice_gap_summary': self._misa_invoice_gap_summary_text(breakdown),
            'misa_invoice_gap_checked_at': fields.Datetime.now(),
            'misa_invoice_gap_resolved': gap_resolved,
        })

    def _misa_invoice_gap_summary_domain(self, date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False):
        """QUAN TRỌNG: bắt buộc phải có ('misa_invoice_gap_checked_at', '=', False) — chỉ quét
        phiếu CHƯA TỪNG được tính lý do lệch. misa_invoice_amount_mismatch KHÔNG tự tắt sau khi
        tính xong (đó là số tiền lệch thật, không phải cờ "đã xử lý"), nên nếu thiếu điều kiện
        này, 1 phiếu lệch THẬT (còn cần xử lý tay) sẽ mãi mãi nằm trong domain này — khiến nút
        "Cập nhật lý do lệch" (chạy qua _runScanUntilDone, vốn giả định domain RỖNG DẦN tới khi
        hết) không bao giờ thật sự hết việc, cứ quét đi quét lại CÙNG 1 tập phiếu, gọi API MISA
        lãng phí (bài học thật: quan sát thấy "166/143" — done vượt hẳn total ban đầu, dấu hiệu
        vòng lặp không hội tụ). Muốn tính lại 1 phiếu ĐÃ check rồi (VD nghi ngờ lý do cũ sai),
        dùng nút "Cập nhật lý do" ngay trên drawer của phiếu đó (gọi refresh_misa_invoice_gap_
        summary trực tiếp, không qua domain này).

        date_from/date_to/invoice_date_from/invoice_date_to: PHẢI truyền đúng bộ lọc đang chọn
        trên dashboard (giống hệt get_misa_invoice_discrepancy) — nếu không, số "còn cần cập
        nhật lý do" sẽ tính trên TOÀN BỘ lịch sử thay vì đúng phạm vi đang xem, khiến người
        dùng thấy 2 con số (VD "287 phiếu đang lệch" trong tháng đang lọc vs "143 phiếu cần
        cập nhật lý do" tính trên toàn bộ lịch sử) không khớp nhau mà không hiểu vì sao."""
        return self._misa_invoice_dashboard_base_domain(
            date_from, date_to, invoice_date_from, invoice_date_to
        ) + [
            ('misa_invoice_state', '=', 'invoiced'),
            ('misa_invoice_master_picking_id', '=', False),
            ('misa_invoice_request_refid', '!=', False),
            ('misa_invoice_amount_mismatch', '=', True),
            ('misa_invoice_gap_checked_at', '=', False),
        ]

    @api.model
    def get_misa_invoice_gap_summary_candidates(
        self, limit=100, date_from=False, date_to=False, invoice_date_from=False, invoice_date_to=False,
    ):
        """Danh sách phiếu đại diện ĐANG lệch (misa_invoice_amount_mismatch) cần tính/cập nhật
        lý do lệch — dùng cho panel tiến độ trên dashboard, giống hệt các nút quét khác."""
        Picking = self.sudo()
        domain = self._misa_invoice_gap_summary_domain(date_from, date_to, invoice_date_from, invoice_date_to)
        pickings = Picking.search(domain, order='misa_invoice_gap_checked_at asc nulls first', limit=limit)
        return {
            'candidates': [{'id': p.id, 'name': p.name} for p in pickings],
            'total': Picking.search_count(domain),
        }

    @api.model
    def refresh_misa_invoice_gap_summary(self, picking_id):
        """Cập nhật lý do lệch cho ĐÚNG 1 phiếu — gọi lặp lại từ dashboard (1 lệnh/phiếu) để
        hiện tiến độ thực, giống hệt check_misa_invoice_grouped_order."""
        picking = self.sudo().browse(picking_id)
        if not picking.exists():
            return {'error': 'Phiếu này không còn tồn tại.'}
        try:
            picking._misa_invoice_refresh_gap_summary()
            return {'gap_summary': picking.misa_invoice_gap_summary or ''}
        except Exception as e:
            _logger.exception("❌ [MISA GAP SUMMARY] Lỗi cập nhật lý do lệch cho phiếu %s", picking.name)
            return {'error': str(e)}

    @api.model
    def refresh_misa_invoice_gap_summaries(self, limit=100):
        """Bản batch không hiện tiến độ — dùng cho migration backfill. Dùng
        get_misa_invoice_gap_summary_candidates + refresh_misa_invoice_gap_summary cho nút bấm
        trên dashboard (hiện tiến độ từng phiếu)."""
        Picking = self.sudo()
        candidates = Picking.search(self._misa_invoice_gap_summary_domain(), limit=limit)
        for picking in candidates:
            try:
                picking._misa_invoice_refresh_gap_summary()
            except Exception:
                _logger.exception("❌ [MISA GAP SUMMARY] Lỗi cập nhật lý do lệch cho phiếu %s", picking.name)
        return {'checked': len(candidates)}

    @api.model
    def get_misa_invoice_report_action(
        self, state=False, exception=None, saler_code=False, mismatch=False, partial_coverage=False,
        partner_id=False, warehouse_id=False, date_from=False, date_to=False,
        invoice_date_from=False, invoice_date_to=False,
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
        if partial_coverage:
            domain.append(('misa_invoice_order_coverage', '=', 'partial'))
        action['domain'] = domain
        return action
