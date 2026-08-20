from odoo import api, fields, models

class StockQuantPackage(models.Model):
    _inherit = "stock.quant.package"

    # Không store để khỏi cần depends, tính lúc in label là đủ
    pack_sequence = fields.Integer(string="Package Sequence", compute="_compute_pack_seq")
    pack_total = fields.Integer(string="Total Packages", compute="_compute_pack_seq")

    def _compute_pack_seq(self):
        """Batch: trước đây làm 2 query RIÊNG cho từng kiện (search move line + duyệt
        picking.move_line_ids) — hợp lý khi gọi cho 1 kiện lúc in nhãn, nhưng thành N+1 nặng
        nếu caller khác (VD dashboard) request field này cho hàng trăm kiện cùng lúc qua
        search_read (đo thực tế: ~370 kiện -> ~728 query, ~8.6s). Gộp lại còn đúng 2 query
        cho toàn bộ self, giữ nguyên ngữ nghĩa cũ (limit=1 không chỉ định order -> lấy theo
        thứ tự mặc định của model, giống search_read không order)."""
        if not self:
            return
        MoveLine = self.env['stock.move.line']

        # 1 query: move line đại diện (1 cái/kiện) cho TOÀN BỘ self
        ml_recs = MoveLine.search_read(
            [('result_package_id', 'in', self.ids)],
            ['result_package_id', 'picking_id'],
        )
        picking_by_pack = {}
        for r in ml_recs:
            pack_id = r['result_package_id'][0] if r.get('result_package_id') else None
            pk_id = r['picking_id'][0] if r.get('picking_id') else None
            if pack_id and pk_id and pack_id not in picking_by_pack:
                picking_by_pack[pack_id] = pk_id

        # 1 query: tất cả move line (có kiện) của các picking liên quan, để tính total/seq
        picking_ids = list(set(picking_by_pack.values()))
        all_ml = MoveLine.search_read(
            [('picking_id', 'in', picking_ids), ('result_package_id', '!=', False)],
            ['picking_id', 'result_package_id'],
        ) if picking_ids else []
        packs_by_picking = {}
        for r in all_ml:
            pk_id = r['picking_id'][0] if r.get('picking_id') else None
            p_id = r['result_package_id'][0] if r.get('result_package_id') else None
            if pk_id and p_id:
                packs_by_picking.setdefault(pk_id, set()).add(p_id)

        for pack in self:
            pk_id = picking_by_pack.get(pack.id)
            if not pk_id:
                pack.pack_sequence = 0
                pack.pack_total = 0
                continue
            pack_ids = sorted(packs_by_picking.get(pk_id, set()))
            total = len(pack_ids)
            seq = pack_ids.index(pack.id) + 1 if pack.id in pack_ids else 0
            pack.pack_total = total
            pack.pack_sequence = seq
