from . import models
from . import wizard
from . import controllers

import logging

_logger = logging.getLogger(__name__)


def post_init_hook(env):
    """Backfill 1 LẦN cho toàn bộ phiếu outgoing đã done đang tồn tại TRƯỚC khi có tính năng
    'trừ hàng trả' (misa_invoice_net_actual_amount) — field mới mặc định = 0.0 cho mọi phiếu cũ
    (chưa từng qua button_validate với code mới), nếu không backfill thì ngay sau khi nâng cấp
    module, toàn bộ tổng đối soát trên dashboard sẽ đột ngột về gần 0 vì các query đã chuyển
    sang đọc field mới này thay vì x_studio_tng_tin_sau_thu."""
    Picking = env['stock.picking'].sudo()
    pickings = Picking.search([
        ('picking_type_id.code', '=', 'outgoing'),
        ('state', '=', 'done'),
    ])
    _logger.info("🔄 [MISA RETURN] Backfill tiền thực xuất ròng cho %s phiếu xuất kho...", len(pickings))
    done = 0
    for picking in pickings:
        try:
            picking._misa_invoice_recompute_net_amount()
            done += 1
        except Exception:
            _logger.exception("❌ [MISA RETURN] Lỗi backfill phiếu %s", picking.name)
    _logger.info("✅ [MISA RETURN] Backfill hoàn tất: %s/%s phiếu.", done, len(pickings))
