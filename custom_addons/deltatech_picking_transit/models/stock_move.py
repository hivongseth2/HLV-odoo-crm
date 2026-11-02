from odoo import api, models


def _hlv_pin_step2_source(records, vals, write):
    """Ghi vals cho records nhưng giữ nguồn của move/move line phiếu bước 2 = CHUYENKHO (đích bước 1).
    Đổi nguồn trên form phiếu, onchange của Odoo đổi luôn nguồn của move → move line và gửi kèm khi lưu;
    stock.picking.write chỉ chặn được location_id cấp phiếu nên phải chặn thêm ở đây."""
    if not vals.get("location_id"):
        return write(records, vals)
    pinned = {}
    rest = records
    for rec in records.filtered("picking_id"):
        hub = rec.picking_id._hlv_step2_source()
        if hub and hub.id != vals["location_id"]:
            pinned[hub] = pinned.get(hub, records.browse()) | rec
            rest -= rec
    res = True
    for hub, recs in pinned.items():
        res = write(recs, dict(vals, location_id=hub.id)) and res
    if rest:
        res = write(rest, vals) and res
    return res


def _hlv_pin_step2_source_create(env, vals_list):
    """Dòng mới thêm vào phiếu bước 2 cũng lấy nguồn = CHUYENKHO."""
    for vals in vals_list:
        if vals.get("picking_id") and vals.get("location_id"):
            hub = env["stock.picking"].browse(vals["picking_id"])._hlv_step2_source()
            if hub:
                vals["location_id"] = hub.id
    return vals_list


class StockMove(models.Model):
    _inherit = "stock.move"

    @api.model_create_multi
    def create(self, vals_list):
        return super().create(_hlv_pin_step2_source_create(self.env, vals_list))

    def write(self, vals):
        return _hlv_pin_step2_source(self, vals, lambda recs, v: super(StockMove, recs).write(v))
