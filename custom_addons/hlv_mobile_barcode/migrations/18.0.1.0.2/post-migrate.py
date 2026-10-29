import logging

from odoo import SUPERUSER_ID, api
from odoo.addons.hlv_mobile_barcode.models.barcode_permission import CODES_SPLIT_FROM_INT

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Chép quyền quét INT sẵn có của từng người × kho sang các mã mới tách khỏi INT (CKD, CKN, SD, TT).

    App kiểm quyền theo mã trình tự của loại phiếu: người đã có bảng quyền mà thiếu dòng cho mã thì bị chặn quét.
    Không chép thì phiếu chuyển kho tạo từ app (nay là CKD) bị chặn ngay. Người không có dòng INT thì không được
    thêm gì — giữ đúng mức quyền cũ. Dòng mã mới đã có thì giữ nguyên.
    """
    env = api.Environment(cr, SUPERUSER_ID, {})
    Line = env['hlv.barcode.picking.permission']
    int_lines = Line.search([('picking_type_code', '=', 'INT')])
    existing = {(line.permission_id.id, line.picking_type_code)
                for line in Line.search([('picking_type_code', 'in', CODES_SPLIT_FROM_INT)])}
    vals_list = [
        {
            'permission_id': line.permission_id.id,
            'picking_type_code': code,
            'can_view': line.can_view,
            'can_edit': line.can_edit,
            'can_delete': line.can_delete,
            'can_confirm': line.can_confirm,
        }
        for line in int_lines
        for code in CODES_SPLIT_FROM_INT
        if (line.permission_id.id, code) not in existing
    ]
    Line.create(vals_list)
    _logger.info('hlv_mobile_barcode: chép quyền quét INT sang %s — tạo %s dòng', CODES_SPLIT_FROM_INT, len(vals_list))
