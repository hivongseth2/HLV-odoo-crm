import io
import json
import logging
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models, http
from odoo.http import request, content_disposition

_logger = logging.getLogger(__name__)


class ProductFlowAnalysis(models.AbstractModel):
    _name = 'product.flow.analysis'
    _description = 'Phân tích lưu thông hàng hóa'

    @api.model
    def get_product_flow_data(self, period='month', date_from=False, date_to=False, warehouse_id=False):
        """Lấy dữ liệu phân tích mua hàng & lưu thông sản phẩm."""
        date_from, date_to = self._compute_date_range(period, date_from, date_to)

        domain = [
            ('state', '=', 'done'),
            ('date', '>=', fields.Datetime.to_string(date_from)),
            ('date', '<=', fields.Datetime.to_string(date_to)),
            ('product_id.type', '!=', 'service'),
        ]
        if warehouse_id:
            domain.append(('warehouse_id', '=', warehouse_id))

        moves = self.env['stock.move'].search(domain)

        # Tính tổng số ngày trong kỳ
        total_days = max((date_to - date_from).days, 1)

        product_data = {}
        # Track incoming dates per product để tính thời gian lưu kho
        product_incoming_dates = {}  # {product_id: [datetime, ...]}
        product_outgoing_dates = {}  # {product_id: [datetime, ...]}

        for move in moves:
            prod = move.product_id
            if prod.id not in product_data:
                product_data[prod.id] = {
                    'product_id': prod.id,
                    'product_name': prod.display_name,
                    'default_code': prod.default_code or '',
                    'incoming_qty': 0.0,
                    'outgoing_qty': 0.0,
                    'internal_qty': 0.0,
                    'incoming_count': 0,
                    'outgoing_count': 0,
                    'total_qty': 0.0,
                    'move_count': 0,
                    'turnover_count': 0,
                    'qty_available': prod.qty_available,
                }
                product_incoming_dates[prod.id] = []
                product_outgoing_dates[prod.id] = []

            qty = move.product_uom_qty
            picking_type = move.picking_type_id.code if move.picking_type_id else ''

            if picking_type == 'incoming':
                product_data[prod.id]['incoming_qty'] += qty
                if move.date:
                    product_incoming_dates[prod.id].append(move.date)
                # Chỉ đếm lần mua nếu move gắn với đơn mua hàng (PO)
                if move.purchase_line_id:
                    product_data[prod.id]['incoming_count'] += 1
            elif picking_type == 'outgoing':
                product_data[prod.id]['outgoing_qty'] += qty
                if move.date:
                    product_outgoing_dates[prod.id].append(move.date)
                # Chỉ đếm lần bán nếu move gắn với đơn bán hàng (SO)
                if move.sale_line_id:
                    product_data[prod.id]['outgoing_count'] += 1
            elif picking_type == 'internal':
                product_data[prod.id]['internal_qty'] += qty

            product_data[prod.id]['total_qty'] += qty
            product_data[prod.id]['move_count'] += 1
            product_data[prod.id]['turnover_count'] += 1

        # Tính thời gian lưu kho trung bình cho từng sản phẩm
        for pid, data in product_data.items():
            in_dates = sorted(product_incoming_dates.get(pid, []))
            out_dates = sorted(product_outgoing_dates.get(pid, []))

            if in_dates and out_dates:
                # Tính trung bình khoảng cách nhập → xuất gần nhất
                storage_days = []
                in_idx = 0
                for out_dt in out_dates:
                    # Tìm ngày nhập gần nhất trước ngày xuất
                    best_in = None
                    for i in range(in_idx, len(in_dates)):
                        if in_dates[i] <= out_dt:
                            best_in = in_dates[i]
                            in_idx = i + 1
                        else:
                            break
                    if best_in:
                        diff = (out_dt - best_in).days
                        storage_days.append(max(diff, 0))
                data['avg_storage_days'] = round(sum(storage_days) / len(storage_days), 1) if storage_days else 0
            elif data['qty_available'] > 0 and in_dates:
                # Có nhập nhưng chưa xuất → tính từ ngày nhập gần nhất đến hôm nay
                from datetime import datetime
                now = datetime.now()
                last_in = in_dates[-1]
                # Xử lý timezone-aware vs naive
                if last_in.tzinfo:
                    from datetime import timezone
                    now = now.replace(tzinfo=timezone.utc)
                data['avg_storage_days'] = (now - last_in).days
            else:
                data['avg_storage_days'] = 0

        result = sorted(product_data.values(), key=lambda x: x['incoming_count'], reverse=True)
        return {
            'products': result,
            'date_from': str(date_from),
            'date_to': str(date_to),
            'period': period,
            'total_count': len(result),
        }

    @api.model
    def get_supplier_flow_data(self, period='month', date_from=False, date_to=False, warehouse_id=False):
        """Lấy dữ liệu nhà cung cấp từ đơn mua hàng (PO), bao gồm cả PO chưa nhập kho."""
        date_from, date_to = self._compute_date_range(period, date_from, date_to)

        po_domain = [
            ('date_order', '>=', fields.Datetime.to_string(date_from)),
            ('date_order', '<=', fields.Datetime.to_string(date_to)),
            ('state', 'in', ('purchase', 'done')),
        ]
        if warehouse_id:
            po_domain.append(('picking_type_id.warehouse_id', '=', warehouse_id))

        orders = self.env['purchase.order'].search(po_domain)

        supplier_data = {}
        for order in orders:
            partner = order.partner_id
            if not partner:
                continue

            if partner.id not in supplier_data:
                supplier_data[partner.id] = {
                    'partner_id': partner.id,
                    'partner_name': partner.display_name,
                    'total_qty': 0.0,
                    'total_amount': 0.0,
                    'move_count': 0,
                    'product_count': 0,
                    'products': {},
                    '_po_ids': set(),
                }

            supplier_data[partner.id]['_po_ids'].add(order.id)

            for line in order.order_line:
                if line.display_type:
                    continue
                prod = line.product_id
                if not prod or prod.type == 'service':
                    continue

                qty = line.product_qty
                price = line.price_unit or 0.0

                supplier_data[partner.id]['total_qty'] += qty
                supplier_data[partner.id]['total_amount'] += qty * price

                if prod.id not in supplier_data[partner.id]['products']:
                    supplier_data[partner.id]['products'][prod.id] = {
                        'product_id': prod.id,
                        'product_name': prod.display_name,
                        'default_code': prod.default_code or '',
                        'qty': 0.0,
                        'amount': 0.0,
                        '_all_pos': set(),
                        '_received_pos': set(),
                        '_pickings': set(),
                    }

                p = supplier_data[partner.id]['products'][prod.id]
                p['qty'] += qty
                p['amount'] += qty * price
                p['_all_pos'].add(order.name)

                # Kiểm tra phiếu nhập kho cho dòng PO này
                received_moves = line.move_ids.filtered(lambda m: m.state == 'done')
                if received_moves:
                    p['_received_pos'].add(order.name)
                    for m in received_moves:
                        if m.picking_id:
                            p['_pickings'].add(m.picking_id.name)

        # Convert to final format
        for sid in supplier_data:
            supplier_data[sid]['move_count'] = len(supplier_data[sid].pop('_po_ids', set()))
            prods = supplier_data[sid]['products']
            for prod_data in prods.values():
                all_pos = prod_data.pop('_all_pos', set())
                received_pos = prod_data.pop('_received_pos', set())
                pickings = prod_data.pop('_pickings', set())
                prod_data['po_names'] = sorted(all_pos)
                prod_data['picking_names'] = sorted(pickings)
                prod_data['pending_po_names'] = sorted(all_pos - received_pos)
            supplier_data[sid]['products'] = sorted(
                prods.values(),
                key=lambda x: x['qty'],
                reverse=True,
            )
            supplier_data[sid]['product_count'] = len(supplier_data[sid]['products'])

        result = sorted(supplier_data.values(), key=lambda x: x['total_qty'], reverse=True)
        return {
            'suppliers': result,
            'date_from': str(date_from),
            'date_to': str(date_to),
            'period': period,
        }

    @api.model
    def get_inventory_planning_data(self, period='month', date_from=False, date_to=False, warehouse_id=False, min_frequency=3):
        """Gợi ý tồn kho tối thiểu dựa trên tần suất lưu thông.
        Chỉ ưu tiên sản phẩm có tần suất mua/bán >= min_frequency.
        """
        date_from, date_to = self._compute_date_range(period, date_from, date_to)

        # Calculate total days in period
        total_days = max((date_to - date_from).days, 1)

        # Lấy cả outgoing lẫn incoming moves để tính tần suất tổng
        domain_base = [
            ('state', '=', 'done'),
            ('date', '>=', fields.Datetime.to_string(date_from)),
            ('date', '<=', fields.Datetime.to_string(date_to)),
            ('product_id.type', '!=', 'service'),
        ]
        if warehouse_id:
            domain_base.append(('warehouse_id', '=', warehouse_id))

        outgoing_moves = self.env['stock.move'].search(domain_base + [('picking_type_id.code', '=', 'outgoing')])
        incoming_moves = self.env['stock.move'].search(domain_base + [('picking_type_id.code', '=', 'incoming'), ('purchase_line_id', '!=', False)])

        # Track incoming counts per product
        incoming_count_map = {}
        incoming_qty_map = {}
        for move in incoming_moves:
            pid = move.product_id.id
            incoming_count_map[pid] = incoming_count_map.get(pid, 0) + 1
            incoming_qty_map[pid] = incoming_qty_map.get(pid, 0) + move.product_uom_qty

        product_plan = {}
        for move in outgoing_moves:
            prod = move.product_id
            if prod.id not in product_plan:
                product_plan[prod.id] = {
                    'product_id': prod.id,
                    'product_name': prod.display_name,
                    'default_code': prod.default_code or '',
                    'categ_name': prod.categ_id.name or '',
                    'total_outgoing': 0.0,
                    'total_incoming': incoming_qty_map.get(prod.id, 0),
                    'outgoing_count': 0,
                    'incoming_count': incoming_count_map.get(prod.id, 0),
                    'qty_available': prod.qty_available,
                }
            product_plan[prod.id]['total_outgoing'] += move.product_uom_qty
            # Chỉ đếm lần bán nếu gắn SO
            if move.sale_line_id:
                product_plan[prod.id]['outgoing_count'] += 1

        planning = []
        for data in product_plan.values():
            # Tần suất tổng = lần mua + lần bán
            total_frequency = data['incoming_count'] + data['outgoing_count']

            avg_daily = data['total_outgoing'] / total_days
            lead_time_days = 7
            safety_days = 3
            min_stock = round(avg_daily * (lead_time_days + safety_days), 2)
            reorder_point = round(avg_daily * lead_time_days, 2)

            days_remaining = round(data['qty_available'] / avg_daily, 1) if avg_daily > 0 else 9999

            # Tính priority_score: tần suất cao + tồn kho thấp = ưu tiên cao
            freq_score = min(total_frequency / max(min_frequency, 1), 5)  # cap at 5
            urgency_score = max(0, 1 - (days_remaining / 30)) if days_remaining < 9999 else 0
            priority_score = round(freq_score * 0.6 + urgency_score * 0.4, 2)

            # Xác định priority_level
            if total_frequency >= min_frequency * 2:
                priority_level = 'high'
            elif total_frequency >= min_frequency:
                priority_level = 'medium'
            else:
                priority_level = 'low'

            planning.append({
                **data,
                'total_frequency': total_frequency,
                'avg_daily': round(avg_daily, 2),
                'min_stock': min_stock,
                'reorder_point': reorder_point,
                'days_remaining': days_remaining,
                'priority_score': priority_score,
                'priority_level': priority_level,
                'status': 'danger' if days_remaining <= lead_time_days
                          else 'warning' if days_remaining <= (lead_time_days + safety_days)
                          else 'ok',
            })

        planning.sort(key=lambda x: (-x['priority_score'], x['days_remaining']))
        return {
            'planning': planning,
            'date_from': str(date_from),
            'date_to': str(date_to),
            'period': period,
            'total_days': total_days,
            'lead_time_days': 7,
            'safety_days': 3,
            'min_frequency': min_frequency,
        }

    @api.model
    def get_aggregate_trend_data(self, warehouse_id=False, months=6):
        """Lấy dữ liệu trend tổng hợp mua/bán theo tháng (6 tháng gần nhất)."""
        from collections import defaultdict
        today = date.today()
        start = (today - relativedelta(months=months - 1)).replace(day=1)
        end = (today.replace(day=1) + relativedelta(months=1)) - timedelta(days=1)

        domain_base = [
            ('state', '=', 'done'),
            ('date', '>=', fields.Datetime.to_string(start)),
            ('date', '<=', fields.Datetime.to_string(end)),
            ('product_id.type', '!=', 'service'),
        ]
        if warehouse_id:
            domain_base.append(('warehouse_id', '=', warehouse_id))

        incoming = self.env['stock.move'].search(
            domain_base + [('picking_type_id.code', '=', 'incoming'), ('purchase_line_id', '!=', False)]
        )
        outgoing = self.env['stock.move'].search(
            domain_base + [('picking_type_id.code', '=', 'outgoing')]
        )

        monthly = defaultdict(lambda: {
            'buy_qty': 0, 'sell_qty': 0, 'buy_amount': 0,
            'po_ids': set(), 'so_ids': set(),
            'buy_products': set(), 'sell_products': set(),
        })

        for m in incoming:
            key = m.date.strftime('%Y-%m')
            monthly[key]['buy_qty'] += m.product_uom_qty
            monthly[key]['buy_amount'] += m.product_uom_qty * (m.price_unit or 0)
            monthly[key]['buy_products'].add(m.product_id.id)
            if m.purchase_line_id and m.purchase_line_id.order_id:
                monthly[key]['po_ids'].add(m.purchase_line_id.order_id.id)

        for m in outgoing:
            key = m.date.strftime('%Y-%m')
            monthly[key]['sell_qty'] += m.product_uom_qty
            monthly[key]['sell_products'].add(m.product_id.id)
            if m.sale_line_id and m.sale_line_id.order_id:
                monthly[key]['so_ids'].add(m.sale_line_id.order_id.id)

        trends = []
        for i in range(months - 1, -1, -1):
            m_date = today - relativedelta(months=i)
            key = m_date.strftime('%Y-%m')
            d = monthly.get(key, {})
            trends.append({
                'month': m_date.strftime('%m/%Y'),
                'month_label': m_date.strftime('%m/%y'),
                'buy_qty': d.get('buy_qty', 0),
                'sell_qty': d.get('sell_qty', 0),
                'buy_amount': round(d.get('buy_amount', 0)),
                'buy_count': len(d.get('po_ids', set())),
                'sell_count': len(d.get('so_ids', set())),
                'buy_products': len(d.get('buy_products', set())),
                'sell_products': len(d.get('sell_products', set())),
            })

        return {'trends': trends}

    @api.model
    def get_dashboard_summary(self, period='month', date_from=False, date_to=False, warehouse_id=False):
        """Lấy tổng quan cho dashboard."""
        date_from, date_to = self._compute_date_range(period, date_from, date_to)

        domain_base = [
            ('state', '=', 'done'),
            ('date', '>=', fields.Datetime.to_string(date_from)),
            ('date', '<=', fields.Datetime.to_string(date_to)),
        ]
        if warehouse_id:
            domain_base.append(('warehouse_id', '=', warehouse_id))

        StockMove = self.env['stock.move']

        incoming_moves = StockMove.search(domain_base + [('picking_type_id.code', '=', 'incoming')])
        outgoing_moves = StockMove.search(domain_base + [('picking_type_id.code', '=', 'outgoing')])
        internal_moves = StockMove.search(domain_base + [('picking_type_id.code', '=', 'internal')])

        total_incoming = sum(incoming_moves.mapped('product_uom_qty'))
        total_outgoing = sum(outgoing_moves.mapped('product_uom_qty'))
        total_internal = sum(internal_moves.mapped('product_uom_qty'))

        unique_products = len(set(
            incoming_moves.mapped('product_id.id') +
            outgoing_moves.mapped('product_id.id')
        ))
        # Chỉ đếm nhà cung cấp từ đơn mua hàng (loại trừ trả hàng khách)
        purchase_moves = incoming_moves.filtered(lambda m: m.purchase_line_id)
        unique_suppliers = len(set(
            purchase_moves.mapped('purchase_line_id.order_id.partner_id.id')
        ) - {False})

        # Get warehouses for dropdown
        warehouses = self.env['stock.warehouse'].search([])
        warehouse_list = [{'id': w.id, 'name': w.name} for w in warehouses]

        return {
            'total_incoming': total_incoming,
            'total_outgoing': total_outgoing,
            'total_internal': total_internal,
            'unique_products': unique_products,
            'unique_suppliers': unique_suppliers,
            'incoming_count': len(incoming_moves),
            'outgoing_count': len(outgoing_moves),
            'date_from': str(date_from),
            'date_to': str(date_to),
            'warehouses': warehouse_list,
        }

    @api.model
    def _compute_date_range(self, period, date_from=False, date_to=False):
        """Tính khoảng thời gian dựa trên period."""
        today = date.today()

        if date_from and date_to:
            if isinstance(date_from, str):
                date_from = fields.Date.from_string(date_from)
            if isinstance(date_to, str):
                date_to = fields.Date.from_string(date_to)
            return date_from, date_to

        if period == 'week':
            date_from = today - timedelta(days=today.weekday())
            date_to = date_from + timedelta(days=6)
        elif period == 'month':
            date_from = today.replace(day=1)
            date_to = (date_from + relativedelta(months=1)) - timedelta(days=1)
        elif period == 'quarter':
            quarter_month = ((today.month - 1) // 3) * 3 + 1
            date_from = today.replace(month=quarter_month, day=1)
            date_to = (date_from + relativedelta(months=3)) - timedelta(days=1)
        elif period == 'year':
            date_from = today.replace(month=1, day=1)
            date_to = today.replace(month=12, day=31)
        else:
            # Default: current month
            date_from = today.replace(day=1)
            date_to = (date_from + relativedelta(months=1)) - timedelta(days=1)

        return date_from, date_to

    @api.model
    def get_trend_data(self, product_id, months=6):
        """Lấy dữ liệu trend theo tháng cho 1 sản phẩm."""
        today = date.today()
        trends = []

        for i in range(months - 1, -1, -1):
            m_start = (today - relativedelta(months=i)).replace(day=1)
            m_end = (m_start + relativedelta(months=1)) - timedelta(days=1)

            domain = [
                ('state', '=', 'done'),
                ('product_id', '=', product_id),
                ('date', '>=', fields.Datetime.to_string(m_start)),
                ('date', '<=', fields.Datetime.to_string(m_end)),
            ]

            moves = self.env['stock.move'].search(domain)
            incoming = sum(m.product_uom_qty for m in moves if m.picking_type_id.code == 'incoming')
            outgoing = sum(m.product_uom_qty for m in moves if m.picking_type_id.code == 'outgoing')

            trends.append({
                'month': m_start.strftime('%m/%Y'),
                'incoming': incoming,
                'outgoing': outgoing,
            })

        return trends

    @api.model
    def export_product_flow_excel(self, period='month', date_from=False, date_to=False, warehouse_id=False):
        """Xuất dữ liệu sản phẩm ra Excel, trả về base64."""
        import base64
        try:
            import xlsxwriter
        except ImportError:
            raise Exception("Thiếu thư viện xlsxwriter. Chạy: pip install xlsxwriter")

        data = self.get_product_flow_data(
            period=period, date_from=date_from, date_to=date_to, warehouse_id=warehouse_id
        )
        products = data.get('products', [])

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})
        ws = wb.add_worksheet('Hàng hóa lưu thông')

        # Formats
        header_fmt = wb.add_format({
            'bold': True, 'bg_color': '#017e84', 'font_color': 'white',
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 11,
        })
        num_fmt = wb.add_format({'num_format': '#,##0.##', 'border': 1, 'align': 'right'})
        text_fmt = wb.add_format({'border': 1})
        title_fmt = wb.add_format({'bold': True, 'font_size': 14})

        ws.write(0, 0, f"Báo cáo lưu thông hàng hóa ({data['date_from']} → {data['date_to']})", title_fmt)

        headers = ['#', 'Mã SP', 'Tên sản phẩm', 'SL Mua', 'Lần mua',
                    'SL Bán', 'Lần bán', 'Luân chuyển', 'TB lưu kho (ngày)', 'Tồn kho']
        for col, h in enumerate(headers):
            ws.write(2, col, h, header_fmt)

        for idx, p in enumerate(products):
            row = idx + 3
            ws.write(row, 0, idx + 1, num_fmt)
            ws.write(row, 1, p.get('default_code', ''), text_fmt)
            ws.write(row, 2, p.get('product_name', ''), text_fmt)
            ws.write(row, 3, p.get('incoming_qty', 0), num_fmt)
            ws.write(row, 4, p.get('incoming_count', 0), num_fmt)
            ws.write(row, 5, p.get('outgoing_qty', 0), num_fmt)
            ws.write(row, 6, p.get('outgoing_count', 0), num_fmt)
            ws.write(row, 7, p.get('turnover_count', 0), num_fmt)
            ws.write(row, 8, p.get('avg_storage_days', 0), num_fmt)
            ws.write(row, 9, p.get('qty_available', 0), num_fmt)

        ws.set_column(0, 0, 5)
        ws.set_column(1, 1, 14)
        ws.set_column(2, 2, 40)
        ws.set_column(3, 9, 14)

        wb.close()
        output.seek(0)
        return base64.b64encode(output.read()).decode('utf-8')

    @api.model
    def export_supplier_flow_excel(self, period='month', date_from=False, date_to=False, warehouse_id=False):
        """Xuất dữ liệu nhà cung cấp ra Excel, trả về base64."""
        import base64
        try:
            import xlsxwriter
        except ImportError:
            raise Exception("Thiếu thư viện xlsxwriter. Chạy: pip install xlsxwriter")

        data = self.get_supplier_flow_data(
            period=period, date_from=date_from, date_to=date_to, warehouse_id=warehouse_id
        )
        suppliers = data.get('suppliers', [])

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})
        ws = wb.add_worksheet('Nhà cung cấp')

        header_fmt = wb.add_format({
            'bold': True, 'bg_color': '#017e84', 'font_color': 'white',
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 11,
        })
        num_fmt = wb.add_format({'num_format': '#,##0.##', 'border': 1, 'align': 'right'})
        money_fmt = wb.add_format({'num_format': '#,##0', 'border': 1, 'align': 'right'})
        text_fmt = wb.add_format({'border': 1})
        title_fmt = wb.add_format({'bold': True, 'font_size': 14})

        ws.write(0, 0, f"Báo cáo nhà cung cấp ({data['date_from']} → {data['date_to']})", title_fmt)

        headers = ['#', 'Nhà cung cấp', 'Tổng SL mua', 'Tổng giá trị', 'Số lần mua (PO)', 'Số SP']
        for col, h in enumerate(headers):
            ws.write(2, col, h, header_fmt)

        for idx, s in enumerate(suppliers):
            row = idx + 3
            ws.write(row, 0, idx + 1, num_fmt)
            ws.write(row, 1, s.get('partner_name', ''), text_fmt)
            ws.write(row, 2, s.get('total_qty', 0), num_fmt)
            ws.write(row, 3, s.get('total_amount', 0), money_fmt)
            ws.write(row, 4, s.get('move_count', 0), num_fmt)
            ws.write(row, 5, s.get('product_count', 0), num_fmt)

        ws.set_column(0, 0, 5)
        ws.set_column(1, 1, 35)
        ws.set_column(2, 5, 16)

        wb.close()
        output.seek(0)
        return base64.b64encode(output.read()).decode('utf-8')
