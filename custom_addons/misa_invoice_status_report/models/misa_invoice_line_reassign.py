from collections import defaultdict

from odoo import models

from .misa_invoice_reassign_utils import find_mislabeled_lines, item_key, owned_qty


class SaleOrderMisaInvoiceLineReassign(models.Model):
    """Dòng đề nghị xuất HĐ ghi nhầm / bỏ trống mã đơn: gom đủ dữ liệu quanh 1 đơn — đề nghị ghi
    mã đơn, đề nghị đang gắn vào phiếu của đơn, và đề nghị của các đơn dính vào — rồi để
    find_mislabeled_lines quyết định phần dòng nào tính cho đơn nào. Chỉ đọc, không ghi gì.

    Vì sao cần: soát HĐ theo đơn (_misa_invoice_refresh_order_truth) chỉ cộng dòng ghi đúng mã
    đơn, còn phiếu chưa soát theo đơn lại tính HĐ qua đề nghị gắn vào nó. Sale ghi nhầm mã đơn
    thì 1 dòng bị đếm 2 lần (KBC/OUT/09356 thừa 4.984.200 đ là hàng của KBC/OUT/12296); bỏ trống
    mã đơn thì đơn thật soát theo đơn ra 0 dù phiếu đã có HĐ."""
    _inherit = 'sale.order'

    def _misa_invoice_done_out_pickings(self):
        return self.misa_invoice_picking_ids.filtered(
            lambda p: p.state == 'done' and p.picking_type_id.code == 'outgoing'
        )

    def _misa_invoice_requests_by_code(self, requests_cache):
        """Đề nghị MISA tìm theo mã đơn (get_invoice_requests_for_order), có cache theo mã."""
        self.ensure_one()
        if self.name not in requests_cache:
            requests_cache[self.name] = self.env['misa.api.utils'].get_invoice_requests_for_order(self.name)
        return requests_cache[self.name]

    def _misa_invoice_linked_requests(self, requests_cache, known_refids):
        """{refid: đề nghị} thuộc phiếu của đơn mà KHÔNG có trong known_refids: đề nghị đang gắn vào
        phiếu (chính phiếu hoặc phiếu nó ăn theo), và đề nghị ĐẶT TÊN THEO phiếu mà lại đang gắn vào
        phiếu khác (case thật đề nghị KBC/OUT/13410 gắn vào KBC/OUT/13412 của DH…236901, trong khi
        KBC/OUT/13410 là phiếu của DH…234115). Tra lại MISA theo SỐ đề nghị để biết đã phát hành HĐ
        chưa — chỉ cho đề nghị lạ, đề nghị đã tìm ra theo mã đơn thì khỏi gọi thêm."""
        self.ensure_one()
        misa = self.env['misa.api.utils']
        pickings = self._misa_invoice_done_out_pickings()
        holders = [picking.misa_invoice_master_picking_id or picking for picking in pickings]
        holders += list(self.env['stock.picking'].sudo().search([
            ('misa_invoice_request_refno', 'in', pickings.mapped('name')), ('misa_invoice_request_refid', '!=', False),
        ]))
        result = {}
        for holder in holders:
            refid, refno = holder.misa_invoice_request_refid, holder.misa_invoice_request_refno
            if not refid or not refno or refid in known_refids or refid in result:
                continue
            if refno not in requests_cache:
                requests_cache[refno] = misa.get_invoice_requests_for_order(refno)
            match = next((r for r in requests_cache[refno] if r['refid'] == refid), None)
            if match:
                result[refid] = match
        return result

    def _misa_invoice_pickings_on_requests(self, requests):
        """{refid: [{picking, order, items}]} — phiếu xuất kho đã xong, thuộc ĐÚNG 1 đơn, thuộc đề
        nghị refid: đang gắn vào nó (chính phiếu hoặc phiếu nó ăn theo), HOẶC đề nghị đặt đúng tên
        phiếu — sale đặt tên đề nghị theo phiếu là bằng chứng mạnh nhất đề nghị đó của phiếu nào, kể
        cả khi đề nghị bị gắn nhầm sang phiếu khác. requests = {refid: đề nghị}; items = {mã hàng:
        SL đã xuất}."""
        refids = list(requests)
        refid_by_name = {(req['refno'] or '').strip(): refid for refid, req in requests.items() if req.get('refno')}
        pickings = self.env['stock.picking'].sudo().search([
            '|', '|', ('misa_invoice_request_refid', 'in', refids),
            ('misa_invoice_master_picking_id.misa_invoice_request_refid', 'in', refids),
            ('name', 'in', list(refid_by_name)),
        ]).filtered(lambda p: p.state == 'done' and p.picking_type_id.code == 'outgoing'
                    and len(p.misa_invoice_sale_order_ids) == 1)
        result = defaultdict(list)
        for picking in pickings:
            items = defaultdict(float)
            for move in picking.move_ids.filtered(lambda m: m.state == 'done'):
                items[item_key(move.product_id.default_code)] += move.quantity
            entry = {'picking': picking.name, 'order': picking.misa_invoice_sale_order_ids.name, 'items': dict(items)}
            own_refids = {
                picking.misa_invoice_request_refid, picking.misa_invoice_master_picking_id.misa_invoice_request_refid,
                refid_by_name.get(picking.name),
            }
            for refid in own_refids & set(refids):
                result[refid].append(entry)
        return dict(result)

    def _misa_invoice_delivered_by_item(self):
        self.ensure_one()
        result = defaultdict(float)
        for line in self.order_line.filtered(lambda l: not l.display_type):
            result[item_key(line.product_id.default_code)] += line.qty_delivered
        return dict(result)

    def _misa_invoice_line_moves(self, requests_cache, lines_cache):
        """Cho 1 đơn, trả (moves, lines):
          lines = {key (refid, stt dòng): (đề nghị {refno, refid, inv_no}, dòng MISA)} — mọi dòng
                  của các đề nghị đã xét;
          moves = find_mislabeled_lines(...) = {key: [(mã đơn nhận, phiếu, SL chuyển)]}.
        Chỉ kéo thêm đơn X (ghi trên dòng của đề nghị gắn vào phiếu đơn này, đúng mã hàng phiếu
        đã xuất) và đơn Y (có phiếu gắn vào đề nghị ghi mã đơn này) — không phải mọi đơn trên đề
        nghị gộp, đỡ mỗi đơn vài chục lệnh gọi MISA. Không có đơn nào dính vào và không có dòng bỏ
        trống mã đơn thì không cần quyết định gì → ({}, lines) ngay.

        Lỗi gọi MISA để lọt ra ngoài — người gọi xử lý như lỗi soát đơn."""
        self.ensure_one()
        misa = self.env['misa.api.utils']

        def load_lines(refids):
            for refid in refids:
                if refid not in lines_cache:
                    lines_cache[refid] = misa.get_invoice_request_lines(refid)

        own = {r['refid']: r for r in self._misa_invoice_requests_by_code(requests_cache)}
        linked_requests = self._misa_invoice_linked_requests(requests_cache, set(own))
        requests = {**own, **linked_requests}
        load_lines(requests)
        linked = self._misa_invoice_pickings_on_requests(requests)

        # Đề nghị có phiếu của CHÍNH đơn này gắn vào — kể cả đề nghị đã tìm ra theo mã đơn (MISA
        # tìm theo nhiều trường, đề nghị trùng tên phiếu vẫn ra dù dòng bỏ trống mã đơn).
        own_items = set()
        self_refids = set()
        for refid, plist in linked.items():
            for p in plist:
                if p['order'] == self.name:
                    own_items |= set(p['items'])
                    self_refids.add(refid)
        self_lines = [raw for refid in self_refids for raw in lines_cache.get(refid, [])]
        targets = {p['order'] for refid in own for p in linked.get(refid, [])} - {self.name}
        sources = {
            (raw.get('order_code') or '').strip()
            for raw in self_lines if item_key(raw.get('inventory_item_code')) in own_items
        } - {'', self.name}
        has_blank = any(not (raw.get('order_code') or '').strip() for raw in self_lines)
        involved = self.search([('name', 'in', list(targets | sources))])
        for order in involved:
            for req in order._misa_invoice_requests_by_code(requests_cache):
                requests.setdefault(req['refid'], req)
        load_lines(requests)

        lines, flat = {}, []
        for refid, req in requests.items():
            for idx, raw in enumerate(lines_cache[refid]):
                key = (refid, idx)
                lines[key] = (req, raw)
                flat.append({
                    'key': key, 'refid': refid, 'order': (raw.get('order_code') or '').strip(),
                    'item': item_key(raw.get('inventory_item_code')), 'qty': raw.get('quantity') or 0.0,
                    'issued': bool(req['inv_no']),
                })
        if not involved and not has_blank:
            return {}, lines
        delivered = {order.name: order._misa_invoice_delivered_by_item() for order in self | involved}
        return find_mislabeled_lines(flat, delivered, linked), lines

    def _misa_invoice_owned_request_amounts(self, moves, lines):
        """Tiền CÓ VAT từng đề nghị tính cho đơn này, sau khi chuyển dòng ghi nhầm / bỏ trống mã đơn
        (kết quả _misa_invoice_line_moves). Trả [(đề nghị, tiền, [ghi chú chuyển dòng])], chỉ đề
        nghị có tiền; dòng tách 1 phần chia tiền theo SL."""
        self.ensure_one()
        Picking = self.env['stock.picking']
        per_request = {}
        for key, (req, raw) in lines.items():
            line_order = (raw.get('order_code') or '').strip()
            line_qty = raw.get('quantity') or 0.0
            line_moves = moves.get(key, [])
            qty = owned_qty(self.name, line_order, line_qty, line_moves)
            if qty <= 0:
                continue
            amount = Picking._misa_invoice_request_line_amount([raw])
            share = amount * qty / line_qty if line_qty else amount
            entry = per_request.setdefault(req['refid'], [req, 0.0, []])
            entry[1] += share
            code = raw.get('inventory_item_code')
            for target, picking, moved_qty in line_moves:
                if target == self.name:
                    entry[2].append("nhận %g [%s] ghi mã %s — hàng của phiếu %s" % (
                        moved_qty, code, line_order or '(trống)', picking))
                elif line_order == self.name:
                    entry[2].append("chuyển %g [%s] sang %s — hàng của phiếu %s" % (moved_qty, code, target, picking))
        return [tuple(entry) for entry in per_request.values() if entry[1]]
