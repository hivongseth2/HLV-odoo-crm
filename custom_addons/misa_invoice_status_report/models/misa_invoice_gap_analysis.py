from collections import defaultdict
from datetime import timedelta

from odoo import api, fields, models

from .misa_invoice_gap_utils import GAP_CATEGORIES, GAP_CATEGORY_BY_KEY, classify_misa_picking_gap, month_key
from .stock_picking import MISA_INVOICE_AMOUNT_TOLERANCE


class StockPickingMisaInvoiceGapAnalysis(models.Model):
    """Phân tích "Còn lại chưa xuất HĐ": lệch vì lý do gì, ở tháng nào, phiếu nào.

    Tính trên tiền HĐ đã quy về từng phiếu (misa_invoice_allocated_amount) — cùng cách với ô
    tổng, nên tổng các nhóm luôn bằng đúng số "Còn lại" đang hiện. Nhờ vậy phiếu ăn theo đề nghị
    của phiếu khác (kể cả phiếu gốc nằm ngoài khoảng ngày/khác sale) tự ra lệch 0, không cần xử
    lý riêng — phần lệch của cả nhóm dồn về phiếu gốc, hiện 1 dòng duy nhất.
    """
    _inherit = 'stock.picking'

    @api.model
    def get_misa_invoice_gap_analysis(
        self, date_from=False, date_to=False, saler_code=False, invoice_date_from=False, invoice_date_to=False,
        category=False, month=False, limit=300,
    ):
        """Trả {outstanding_amount, categories, months, rows, row_total}. category/month
        ('YYYY-MM') lọc danh sách rows; categories luôn tính trên toàn bộ phạm vi (là phép tách
        của số tổng), còn months tính trong nhóm đang chọn — để số phiếu trên chip tháng khớp
        đúng danh sách hiện ra khi bấm vào nó."""
        Picking = self.sudo()
        misa_domain, shopee_domain = Picking._misa_invoice_scoped_domains(
            date_from, date_to, saler_code, invoice_date_from, invoice_date_to,
        )
        entries = Picking._misa_invoice_gap_entries(misa_domain, shopee_domain)
        customs = Picking._misa_invoice_customs_summary(date_from, date_to, saler_code)

        totals = defaultdict(lambda: {'amount': 0.0, 'count': 0})
        rounding = 0.0
        for entry in entries:
            if entry['category'] is None:
                rounding += entry['gap']
                continue
            totals[entry['category']]['amount'] += entry['gap']
            totals[entry['category']]['count'] += 1
        if customs['pending_amount']:
            totals['customs'] = {'amount': -customs['pending_amount'], 'count': customs['pending_count']}
        # Sai số luôn cộng vào tổng (để tổng khớp tới từng đồng với ô "Còn lại"), nhưng chỉ
        # hiện thành 1 nhóm riêng khi đủ lớn để người xem thắc mắc.
        outstanding = rounding + sum(
            value['amount'] for key, value in totals.items() if GAP_CATEGORY_BY_KEY[key]['counted']
        )
        if abs(rounding) >= MISA_INVOICE_AMOUNT_TOLERANCE:
            totals['rounding'] = {'amount': rounding, 'count': 0}

        # Chip tháng và danh sách dùng CÙNG 1 tập phiếu, nếu không số phiếu trên chip khác số
        # dòng hiện ra khi bấm vào. Chưa chọn nhóm = chỉ phiếu cần xử lý; phiếu đã xác minh xong
        # chỉ hiện khi bấm đúng nhóm của nó.
        in_category = [
            e for e in entries
            if e['category'] is not None and (
                e['category'] == category if category else GAP_CATEGORY_BY_KEY[e['category']]['counted']
            )
        ]
        rows_matching = [e for e in in_category if not month or e['month'] == month]
        # Cần xử lý lên trước, đã xác minh xong xuống cuối; trong mỗi phần lệch lớn lên trước.
        rows_matching.sort(key=lambda e: -abs(e['gap']))
        today = fields.Date.context_today(self)

        return {
            'outstanding_amount': outstanding,
            'categories': [
                dict(cat, amount=totals[cat['key']]['amount'], count=totals[cat['key']]['count'])
                for cat in GAP_CATEGORIES if cat['key'] in totals
            ],
            'months': self._misa_invoice_gap_months(in_category),
            'rows': [Picking._misa_invoice_gap_row(e, today) for e in rows_matching[:limit]],
            'row_total': len(rows_matching),
        }

    def _misa_invoice_gap_order_ids(self, domain, checked_before):
        """Id các đơn bán có ÍT NHẤT 1 phiếu đang lệch trong domain và chưa soát theo đơn với
        MISA kể từ checked_before — đơn chưa soát bao giờ lên trước. Chỉ soát đơn đang lệch:
        đơn đã khớp thì hỏi lại MISA không đổi được gì."""
        picking_ids = self.search(domain).ids
        if not picking_ids:
            return []
        self.env.cr.execute("""
            SELECT so.id
            FROM stock_picking p
            JOIN misa_invoice_picking_sale_order_rel rel ON rel.picking_id = p.id
            JOIN sale_order so ON so.id = rel.order_id
            WHERE p.id = ANY(%s)
              AND ABS(COALESCE(p.misa_invoice_net_actual_amount, 0) - COALESCE(p.misa_invoice_allocated_amount, 0)) > %s
              AND (so.misa_invoice_order_checked_at IS NULL OR so.misa_invoice_order_checked_at < %s)
            GROUP BY so.id, so.misa_invoice_order_checked_at
            ORDER BY so.misa_invoice_order_checked_at NULLS FIRST, so.id
        """, (picking_ids, MISA_INVOICE_AMOUNT_TOLERANCE, checked_before))
        return [row[0] for row in self.env.cr.fetchall()]

    def _cron_refresh_misa_invoice_orders(self, limit=20):
        """Cron: soát theo đơn với MISA các đơn đang lệch, mỗi đơn tối đa 1 lần/ngày — đơn vừa
        được kế toán xuất HĐ thêm sẽ tự hết lệch trong vòng 1 ngày."""
        order_ids = self._misa_invoice_gap_order_ids(
            self._misa_invoice_dashboard_base_domain(), fields.Datetime.now() - timedelta(days=1),
        )
        self.env['sale.order'].sudo().browse(order_ids[:limit])._misa_invoice_refresh_order_truth()

    @api.model
    def refresh_misa_invoice_gap_orders(self, date_from=False, date_to=False, saler_code=False, started_at=False, limit=10):
        """Nút "Hỏi lại MISA theo đơn" trên khung "Vì sao còn lệch": soát 1 lô đơn đang lệch
        trong đúng phạm vi đang xem. Giao diện gọi lặp tới khi remaining = 0 (hoặc 1 lô không
        soát được đơn nào — MISA đang lỗi). started_at: lượt đầu bỏ trống, server lấy giờ của
        mình rồi trả về để các lô sau gửi lại — đơn vừa soát trong lượt này không bị chọn lại,
        và không phụ thuộc đồng hồ máy người bấm."""
        misa_domain, _shopee_domain = self.sudo()._misa_invoice_scoped_domains(date_from, date_to, saler_code)
        checked_before = fields.Datetime.to_datetime(started_at) if started_at else fields.Datetime.now()
        order_ids = self.sudo()._misa_invoice_gap_order_ids(misa_domain, checked_before)
        batch = self.env['sale.order'].sudo().browse(order_ids[:limit])
        done = batch._misa_invoice_refresh_order_truth()
        return {
            'done': done, 'failed': len(batch) - done, 'remaining': max(len(order_ids) - len(batch), 0),
            'started_at': fields.Datetime.to_string(checked_before),
        }

    def _misa_invoice_gap_entries(self, misa_domain, shopee_domain):
        """Mỗi phiếu trong phạm vi 1 entry {picking, source, gap, category, month}. category
        None = lệch trong dung sai (chỉ cộng vào sai số làm tròn, không liệt kê)."""
        entries = []
        for picking in self.search(misa_domain):
            allocated = picking.misa_invoice_allocated_amount or 0.0
            gap = (picking.misa_invoice_net_actual_amount or 0.0) - allocated
            entries.append({
                'picking': picking, 'source': 'misa', 'gap': gap,
                'category': classify_misa_picking_gap(
                    picking.misa_invoice_state == 'invoiced', picking.misa_invoice_gap_resolved,
                    gap, allocated, MISA_INVOICE_AMOUNT_TOLERANCE,
                ),
                'month': month_key(picking.date_done and picking.date_done.date()),
            })
        today = fields.Date.context_today(self)
        for picking in self.search(shopee_domain):
            # Cùng hàm dựng dòng với ô tổng Shopee (_misa_invoice_shopee_summary) để 2 số khớp.
            shopee_row = self._misa_invoice_shopee_picking_to_row(picking, today)
            gap = shopee_row['actual_amount'] - shopee_row['invoice_amount']
            entries.append({
                'picking': picking, 'source': 'shopee', 'gap': gap, 'shopee_row': shopee_row,
                'category': 'shopee' if abs(gap) > MISA_INVOICE_AMOUNT_TOLERANCE else None,
                'month': month_key(picking.date_done and picking.date_done.date()),
            })
        return entries

    def _misa_invoice_gap_months(self, entries):
        """Tổng lệch theo tháng xuất kho của các entry truyền vào, tháng cũ lên trước. HĐ hải
        quan không có ở đây vì đi theo ngày hóa đơn, không theo ngày xuất kho."""
        months = defaultdict(lambda: {'amount': 0.0, 'count': 0})
        for entry in entries:
            months[entry['month']]['amount'] += entry['gap']
            months[entry['month']]['count'] += 1
        return [
            {'key': key, 'label': '%s/%s' % (key[5:7], key[:4]) if key else 'Không rõ ngày', **value}
            for key, value in sorted(months.items())
        ]

    def _misa_invoice_gap_row(self, entry, today):
        """Dòng hiển thị: dựng từ đúng hàm dòng của tab tương ứng (để bấm vào mở được drawer
        chi tiết sẵn có), thêm các cột của phần phân tích."""
        picking = entry['picking']
        meta = GAP_CATEGORY_BY_KEY[entry['category']]
        if entry['source'] == 'shopee':
            row = dict(entry['shopee_row'], allocated_amount=entry['shopee_row']['invoice_amount'])
            row['group_picking_names'] = [picking.name]
        else:
            row = self._misa_invoice_picking_to_row(picking, today)
            row['allocated_amount'] = picking.misa_invoice_allocated_amount or 0.0
            covered = picking.misa_invoice_covered_picking_ids
            row['group_picking_names'] = (picking | covered).mapped('name')
            # Phiếu gốc của đề nghị gộp: tiền HĐ của cả đề nghị và phần đã chia cho các phiếu đi
            # kèm, để hiểu vì sao tiền HĐ quy về phiếu này nhỏ (hoặc âm).
            row['request_invoice_amount'] = picking.misa_invoice_effective_amount or 0.0
            row['passed_to_others_amount'] = (
                (picking.misa_invoice_effective_amount or 0.0) - row['allocated_amount']
                if picking.misa_invoice_state == 'invoiced' and not picking.misa_invoice_master_picking_id else 0.0
            )
            row['gap_summary'] = picking.misa_invoice_gap_summary or ''
            # Đã có số theo đơn hàng: tiền HĐ lấy từ MISA theo mã đơn, ghi chú "đề nghị gộp" ở
            # trên không còn là lý do nữa — hiện nguồn theo đơn thay vào.
            row['order_based'] = picking.misa_invoice_order_allocation_ok
            row['order_notes'] = [
                {
                    'order': order.name,
                    'invoiced': order.misa_invoice_order_invoiced_amount,
                    'customs': sum(self.env['misa.invoice.customs.line'].sudo().search(
                        [('sale_order_id', '=', order.id)]
                    ).mapped('amount')),
                    'pending': order.misa_invoice_order_pending_amount,
                    'sources': order.misa_invoice_order_sources or '',
                    'checked_at': fields.Datetime.to_string(order.misa_invoice_order_checked_at),
                }
                for order in picking.misa_invoice_sale_order_ids if order.misa_invoice_order_checked_at
            ]
        row.update({
            'source': entry['source'],
            'diff': entry['gap'],
            'category': entry['category'],
            'category_label': meta['label'],
            'month': entry['month'],
            'gap_resolved': entry['category'] == 'resolved',
        })
        return row
