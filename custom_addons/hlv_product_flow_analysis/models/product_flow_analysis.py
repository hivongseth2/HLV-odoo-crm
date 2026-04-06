import base64
import io
import json
import logging
import re
import time
import requests
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
        """Lấy dữ liệu phân tích mua hàng & bán hàng theo đơn PO/SO."""
        date_from, date_to = self._compute_date_range(period, date_from, date_to)

        # ── Query Purchase Order Lines ──
        po_domain = [
            ('order_id.state', 'in', ('purchase', 'done')),
            ('order_id.date_order', '>=', fields.Datetime.to_string(date_from)),
            ('order_id.date_order', '<=', fields.Datetime.to_string(date_to)),
            ('product_id.type', '!=', 'service'),
            ('display_type', '=', False),
        ]
        if warehouse_id:
            po_domain.append(('order_id.picking_type_id.warehouse_id', '=', warehouse_id))

        po_lines = self.env['purchase.order.line'].search(po_domain)

        # ── Query Sale Order Lines ──
        so_domain = [
            ('order_id.state', 'in', ('sale', 'done')),
            ('order_id.date_order', '>=', fields.Datetime.to_string(date_from)),
            ('order_id.date_order', '<=', fields.Datetime.to_string(date_to)),
            ('product_id.type', '!=', 'service'),
            ('display_type', '=', False),
        ]
        if warehouse_id:
            so_domain.append(('order_id.warehouse_id', '=', warehouse_id))

        so_lines = self.env['sale.order.line'].search(so_domain)

        product_data = {}

        for line in po_lines:
            prod = line.product_id
            if not prod:
                continue
            if prod.id not in product_data:
                product_data[prod.id] = {
                    'product_id': prod.id,
                    'product_name': prod.display_name,
                    'default_code': prod.default_code or '',
                    'incoming_qty': 0.0,
                    'outgoing_qty': 0.0,
                    'received_qty': 0.0,
                    'delivered_qty': 0.0,
                    'incoming_count': 0,
                    'outgoing_count': 0,
                    'total_qty': 0.0,
                    'move_count': 0,
                    'turnover_count': 0,
                    'qty_available': prod.qty_available,
                    'avg_storage_days': 0,
                }
            d = product_data[prod.id]
            d['incoming_qty'] += line.product_qty
            d['received_qty'] += line.qty_received
            d['incoming_count'] += 1
            d['total_qty'] += line.product_qty
            d['move_count'] += 1

        for line in so_lines:
            prod = line.product_id
            if not prod:
                continue
            if prod.id not in product_data:
                product_data[prod.id] = {
                    'product_id': prod.id,
                    'product_name': prod.display_name,
                    'default_code': prod.default_code or '',
                    'incoming_qty': 0.0,
                    'outgoing_qty': 0.0,
                    'received_qty': 0.0,
                    'delivered_qty': 0.0,
                    'incoming_count': 0,
                    'outgoing_count': 0,
                    'total_qty': 0.0,
                    'move_count': 0,
                    'turnover_count': 0,
                    'qty_available': prod.qty_available,
                    'avg_storage_days': 0,
                }
            d = product_data[prod.id]
            d['outgoing_qty'] += line.product_uom_qty
            d['delivered_qty'] += line.qty_delivered
            d['outgoing_count'] += 1
            d['total_qty'] += line.product_uom_qty
            d['move_count'] += 1

        # Tính turnover_count = tổng lần mua + lần bán
        for d in product_data.values():
            d['turnover_count'] = d['incoming_count'] + d['outgoing_count']

        # ── Tính avg_storage_days từ stock.move (FIFO theo số lượng) ──
        if product_data:
            move_domain = [
                ('state', '=', 'done'),
                ('date', '>=', fields.Datetime.to_string(date_from)),
                ('date', '<=', fields.Datetime.to_string(date_to)),
                ('product_id', 'in', list(product_data.keys())),
            ]
            if warehouse_id:
                move_domain.append(('warehouse_id', '=', warehouse_id))

            moves = self.env['stock.move'].search(move_domain, order='date asc')
            # Thu thập moves kèm qty, sort theo ngày
            product_incoming_moves = {}  # pid -> [(date, remaining_qty)]
            product_outgoing_moves = {}  # pid -> [(date, qty)]

            for move in moves:
                pid = move.product_id.id
                ptype = move.picking_type_id.code if move.picking_type_id else ''
                qty = move.product_uom_qty
                if ptype == 'incoming' and move.date and qty > 0:
                    product_incoming_moves.setdefault(pid, []).append([move.date, qty])
                elif ptype == 'outgoing' and move.date and qty > 0:
                    product_outgoing_moves.setdefault(pid, []).append((move.date, qty))

            for pid, data in product_data.items():
                in_batches = product_incoming_moves.get(pid, [])
                out_moves = product_outgoing_moves.get(pid, [])

                if in_batches and out_moves:
                    # FIFO: mỗi lần xuất tiêu thụ từ lô nhập cũ nhất còn lại
                    weighted_days = 0.0
                    total_matched_qty = 0.0
                    in_idx = 0

                    for out_dt, out_qty in out_moves:
                        remaining_out = out_qty
                        while remaining_out > 0 and in_idx < len(in_batches):
                            in_dt, in_remaining = in_batches[in_idx]
                            if in_dt > out_dt:
                                break  # lô nhập sau ngày xuất → bỏ qua
                            matched = min(remaining_out, in_remaining)
                            days = max((out_dt - in_dt).days, 0)
                            weighted_days += days * matched
                            total_matched_qty += matched
                            remaining_out -= matched
                            in_batches[in_idx][1] -= matched
                            if in_batches[in_idx][1] <= 0:
                                in_idx += 1

                    data['avg_storage_days'] = round(weighted_days / total_matched_qty, 1) if total_matched_qty > 0 else 0

                elif out_moves and not in_batches:
                    # Không có nhập trong kỳ → tìm lần nhập gần nhất trước kỳ
                    pre_incoming = self.env['stock.move'].search([
                        ('product_id', '=', pid),
                        ('state', '=', 'done'),
                        ('picking_type_id.code', '=', 'incoming'),
                        ('date', '<', fields.Datetime.to_string(date_from)),
                    ], order='date desc', limit=1)
                    if pre_incoming:
                        last_in = pre_incoming.date
                        weighted = sum(max((out_dt - last_in).days, 0) * qty for out_dt, qty in out_moves)
                        total_qty = sum(qty for _, qty in out_moves)
                        data['avg_storage_days'] = round(weighted / total_qty, 1) if total_qty > 0 else 0

                elif data['qty_available'] > 0 and in_batches:
                    # Còn tồn kho + có nhập nhưng chưa xuất → tính từ lần nhập cuối
                    from datetime import datetime, timezone
                    last_in_dt = in_batches[-1][0]
                    now = datetime.now(timezone.utc) if last_in_dt.tzinfo else datetime.now()
                    data['avg_storage_days'] = (now - last_in_dt).days

        result = sorted(product_data.values(), key=lambda x: x['incoming_count'], reverse=True)
        return {
            'products': result,
            'date_from': str(date_from),
            'date_to': str(date_to),
            'period': period,
            'total_count': len(result),
        }

    @api.model
    def get_product_orders(self, product_id, period='month', date_from=False, date_to=False, warehouse_id=False):
        """Lấy danh sách đơn mua hàng (PO) và đơn bán hàng (SO) của 1 sản phẩm trong kỳ."""
        date_from, date_to = self._compute_date_range(period, date_from, date_to)

        # Purchase Order Lines
        po_domain = [
            ('product_id', '=', product_id),
            ('order_id.state', 'in', ('purchase', 'done')),
            ('order_id.date_order', '>=', fields.Datetime.to_string(date_from)),
            ('order_id.date_order', '<=', fields.Datetime.to_string(date_to)),
            ('display_type', '=', False),
        ]
        if warehouse_id:
            po_domain.append(('order_id.picking_type_id.warehouse_id', '=', warehouse_id))

        po_lines = self.env['purchase.order.line'].search(po_domain, order='order_id desc')

        purchase_records = []
        for line in po_lines:
            po = line.order_id
            purchase_records.append({
                'line_id': line.id,
                'po_id': po.id,
                'po_name': po.name,
                'date': str(po.date_order.date()) if po.date_order else '',
                'partner_name': po.partner_id.display_name if po.partner_id else '',
                'qty': line.product_qty,
                'received_qty': line.qty_received,
                'price_unit': line.price_unit or 0,
                'amount': line.price_subtotal or 0,
                'state': po.state,
                'fully_received': line.qty_received >= line.product_qty,
            })

        # Sale Order Lines
        so_domain = [
            ('product_id', '=', product_id),
            ('order_id.state', 'in', ('sale', 'done')),
            ('order_id.date_order', '>=', fields.Datetime.to_string(date_from)),
            ('order_id.date_order', '<=', fields.Datetime.to_string(date_to)),
            ('display_type', '=', False),
        ]
        if warehouse_id:
            so_domain.append(('order_id.warehouse_id', '=', warehouse_id))

        so_lines = self.env['sale.order.line'].search(so_domain, order='order_id desc')

        sale_records = []
        for line in so_lines:
            so = line.order_id
            sale_records.append({
                'line_id': line.id,
                'so_id': so.id,
                'so_name': so.name,
                'date': str(so.date_order.date()) if so.date_order else '',
                'partner_name': so.partner_id.display_name if so.partner_id else '',
                'qty': line.product_uom_qty,
                'delivered_qty': line.qty_delivered,
                'price_unit': line.price_unit or 0,
                'amount': line.price_subtotal or 0,
                'state': so.state,
                'fully_delivered': line.qty_delivered >= line.product_uom_qty,
            })

        return {
            'purchase_records': purchase_records,
            'sale_records': sale_records,
            'po_count': len(purchase_records),
            'so_count': len(sale_records),
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

            # Gộp theo tên công ty (commercial_partner) để tránh trùng NCC cùng tên
            company = partner.commercial_partner_id or partner
            group_key = (company.name or company.display_name or '').strip()
            if not group_key:
                continue

            if group_key not in supplier_data:
                supplier_data[group_key] = {
                    'partner_id': company.id,
                    'partner_name': group_key,
                    'total_qty': 0.0,
                    'total_amount': 0.0,
                    'move_count': 0,
                    'product_count': 0,
                    'products': {},
                    '_po_ids': set(),
                    '_delivery_days': [],
                }

            sd = supplier_data[group_key]
            sd['_po_ids'].add(order.id)

            # Tính thời gian giao hàng: PO date_order → picking done date
            if order.date_order:
                for picking in order.picking_ids.filtered(lambda pk: pk.state == 'done' and pk.date_done):
                    delta = (picking.date_done - order.date_order).days
                    if delta >= 0:
                        sd['_delivery_days'].append(delta)

            for line in order.order_line:
                if line.display_type:
                    continue
                prod = line.product_id
                if not prod or prod.type == 'service':
                    continue

                qty = line.product_qty
                price = line.price_unit or 0.0

                sd['total_qty'] += qty
                sd['total_amount'] += qty * price

                if prod.id not in sd['products']:
                    sd['products'][prod.id] = {
                        'product_id': prod.id,
                        'product_name': prod.display_name,
                        'default_code': prod.default_code or '',
                        'qty': 0.0,
                        'amount': 0.0,
                        '_all_pos': set(),
                        '_received_pos': set(),
                        '_pickings': set(),
                    }

                p = sd['products'][prod.id]
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
            delivery_days = supplier_data[sid].pop('_delivery_days', [])
            if delivery_days:
                supplier_data[sid]['avg_delivery_days'] = round(sum(delivery_days) / len(delivery_days), 1)
                supplier_data[sid]['min_delivery_days'] = min(delivery_days)
                supplier_data[sid]['max_delivery_days'] = max(delivery_days)
                supplier_data[sid]['delivery_count'] = len(delivery_days)
            else:
                supplier_data[sid]['avg_delivery_days'] = 0
                supplier_data[sid]['min_delivery_days'] = 0
                supplier_data[sid]['max_delivery_days'] = 0
                supplier_data[sid]['delivery_count'] = 0
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
        Trả về TẤT CẢ sản phẩm storable (không chỉ sản phẩm có giao dịch).
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

        # Track outgoing counts per product
        outgoing_count_map = {}
        outgoing_qty_map = {}
        for move in outgoing_moves:
            pid = move.product_id.id
            outgoing_qty_map[pid] = outgoing_qty_map.get(pid, 0) + move.product_uom_qty
            if move.sale_line_id:
                outgoing_count_map[pid] = outgoing_count_map.get(pid, 0) + 1

        # Lấy TẤT CẢ sản phẩm storable (product.product)
        all_products = self.env['product.product'].search([
            ('type', '!=', 'service'),
            ('active', '=', True),
        ])

        lead_time_days = 7
        safety_days = 3

        planning = []
        for prod in all_products:
            pid = prod.id
            total_outgoing = outgoing_qty_map.get(pid, 0)
            total_incoming = incoming_qty_map.get(pid, 0)
            outgoing_count = outgoing_count_map.get(pid, 0)
            incoming_count = incoming_count_map.get(pid, 0)
            total_frequency = incoming_count + outgoing_count

            avg_daily = total_outgoing / total_days
            min_stock = round(avg_daily * (lead_time_days + safety_days), 2)
            reorder_point = round(avg_daily * lead_time_days, 2)

            days_remaining = round(prod.qty_available / avg_daily, 1) if avg_daily > 0 else 9999

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
                'product_id': pid,
                'product_name': prod.display_name,
                'default_code': prod.default_code or '',
                'categ_name': prod.categ_id.name or '',
                'total_outgoing': total_outgoing,
                'total_incoming': total_incoming,
                'outgoing_count': outgoing_count,
                'incoming_count': incoming_count,
                'qty_available': prod.qty_available,
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
        """Lấy tổng quan cho dashboard dựa trên PO/SO."""
        date_from, date_to = self._compute_date_range(period, date_from, date_to)

        # ── Purchase Orders ──
        po_domain = [
            ('state', 'in', ('purchase', 'done')),
            ('date_order', '>=', fields.Datetime.to_string(date_from)),
            ('date_order', '<=', fields.Datetime.to_string(date_to)),
        ]
        if warehouse_id:
            po_domain.append(('picking_type_id.warehouse_id', '=', warehouse_id))

        purchase_orders = self.env['purchase.order'].search(po_domain)
        po_lines = purchase_orders.mapped('order_line').filtered(
            lambda l: not l.display_type and l.product_id and l.product_id.type != 'service'
        )
        total_incoming = sum(po_lines.mapped('product_qty'))
        po_product_ids = set(po_lines.mapped('product_id.id'))

        # ── Sale Orders ──
        so_domain = [
            ('state', 'in', ('sale', 'done')),
            ('date_order', '>=', fields.Datetime.to_string(date_from)),
            ('date_order', '<=', fields.Datetime.to_string(date_to)),
        ]
        if warehouse_id:
            so_domain.append(('warehouse_id', '=', warehouse_id))

        sale_orders = self.env['sale.order'].search(so_domain)
        so_lines = sale_orders.mapped('order_line').filtered(
            lambda l: not l.display_type and l.product_id and l.product_id.type != 'service'
        )
        total_outgoing = sum(so_lines.mapped('product_uom_qty'))
        so_product_ids = set(so_lines.mapped('product_id.id'))

        # ── Internal transfers (vẫn từ stock.move) ──
        move_domain = [
            ('state', '=', 'done'),
            ('date', '>=', fields.Datetime.to_string(date_from)),
            ('date', '<=', fields.Datetime.to_string(date_to)),
            ('picking_type_id.code', '=', 'internal'),
        ]
        if warehouse_id:
            move_domain.append(('warehouse_id', '=', warehouse_id))
        internal_moves = self.env['stock.move'].search(move_domain)
        total_internal = sum(internal_moves.mapped('product_uom_qty'))

        unique_products = len(po_product_ids | so_product_ids)
        unique_suppliers = len(set(
            purchase_orders.mapped('partner_id.commercial_partner_id.id')
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
            'incoming_count': len(purchase_orders),
            'outgoing_count': len(sale_orders),
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

    # ── AI Procurement Analysis ──────────────────────────────────────────

    @api.model
    def get_ai_procurement_analysis(self, period='month', date_from=False, date_to=False, warehouse_id=False):
        """Phân tích AI kiểu MCP: GPT tự query database qua function calling."""
        api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key', '')
        if not api_key:
            return {'error': 'Chưa cấu hình OpenAI API Key. Vào Cài đặt → Thông số hệ thống → thêm key "openai.api_key".'}

        # Quick stats for sidebar display
        product_data = self.get_product_flow_data(
            period=period, date_from=date_from, date_to=date_to, warehouse_id=warehouse_id
        )
        products = product_data.get('products', [])
        product_stats = {
            'total': len(products),
            'high_freq': len([p for p in products if p['outgoing_count'] >= 5]),
            'medium_freq': len([p for p in products if 2 <= p['outgoing_count'] < 5]),
            'low_freq': len([p for p in products if p['outgoing_count'] == 1]),
            'no_sell': len([p for p in products if p['outgoing_count'] == 0 and p['incoming_count'] > 0]),
        }

        # Date range context
        d_from, d_to = self._compute_date_range(period, date_from, date_to)
        date_ctx = f"Kỳ phân tích: {d_from} đến {d_to}"
        if warehouse_id:
            wh = self.env['stock.warehouse'].browse(warehouse_id)
            date_ctx += f", Kho: {wh.name}"

        schema = self._get_db_schema_description()
        system_prompt = (
            "Bạn là chuyên gia phân tích chuỗi cung ứng và quản lý tồn kho cho công ty thương mại.\n\n"
            "Đặc điểm nghiệp vụ:\n"
            "- Công ty MUA hàng từ nhà cung cấp rồi BÁN lại cho khách hàng\n"
            "- Có kho riêng lưu trữ hàng hóa\n"
            "- KHÔNG phải tất cả sản phẩm đều nên lưu kho\n"
            "- Nhiều SP chỉ mua-bán 1-2 lần (mua theo yêu cầu khách)\n"
            "- Một số SP bán thường xuyên → nên lưu kho sẵn\n\n"
            "Bạn có quyền truy vấn database PostgreSQL (chỉ SELECT) để lấy dữ liệu.\n"
            "Hãy tự query dữ liệu cần thiết, phân tích và đưa ra đề xuất cụ thể.\n"
            "Chú ý thêm LIMIT vào mỗi query (tối đa 200 dòng).\n\n"
            "QUAN TRỌNG - Cách query tồn kho đúng:\n"
            "- Tồn kho thực tế nằm ở bảng stock_quant, KHÔNG phải từ đơn hàng\n"
            "- Nhiều SP có tồn kho nhưng CHƯA BAO GIỜ bán → không có trong sale_order_line\n"
            "- Khi phân tích tồn kho, phải bắt đầu từ stock_quant rồi LEFT JOIN với sale_order_line/purchase_order_line\n"
            "- KHÔNG được bắt đầu từ sale/purchase rồi JOIN stock_quant vì sẽ bỏ sót SP không có giao dịch\n\n"
            "Nhiệm vụ phân tích:\n"
            "1. Phân loại SP: nên lưu kho vs mua theo đơn\n"
            "2. Chiến lược mua hàng: thời điểm, số lượng cho SP bán thường xuyên\n"
            "3. Tồn kho tối thiểu cho SP cần lưu kho (đưa CON SỐ CỤ THỂ)\n"
            "4. Đánh giá nhà cung cấp: ổn định, giao nhanh, nên ưu tiên\n"
            "5. Cảnh báo rủi ro: hàng sắp hết, tồn lâu, xu hướng bất thường\n"
            "6. Xu hướng và dự báo ngắn hạn\n\n"
            f"Database schema:\n{schema}\n\n"
            "Trả lời bằng tiếng Việt, ngắn gọn, có cấu trúc rõ ràng.\n"
            "Sử dụng markdown: ## heading, **bold**, - bullet points.\n"
            "Đưa ra con số cụ thể khi đề xuất."
        )

        tools = [{
            "type": "function",
            "function": {
                "name": "query_database",
                "description": "Thực thi truy vấn SQL SELECT trên database PostgreSQL để lấy dữ liệu phân tích. Luôn thêm LIMIT (tối đa 200).",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {
                            "type": "string",
                            "description": "Câu truy vấn PostgreSQL SELECT"
                        },
                        "purpose": {
                            "type": "string",
                            "description": "Mục đích của truy vấn này"
                        }
                    },
                    "required": ["sql", "purpose"]
                }
            }
        }]

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{date_ctx}.\nPhân tích dữ liệu lưu thông hàng hóa và đề xuất chiến lược mua hàng, tồn kho tối thiểu."},
        ]

        headers = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }
        total_tokens = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
        model_used = 'gpt-4o-mini'

        try:
            for iteration in range(8):
                payload = {
                    'model': 'gpt-4o-mini',
                    'messages': messages,
                    'tools': tools,
                    'tool_choice': 'auto',
                    'temperature': 0.3,
                    'max_tokens': 4000,
                }
                result = self._call_openai_with_retry(headers, payload)
                model_used = result.get('model', model_used)
                usage = result.get('usage', {})
                for k in total_tokens:
                    total_tokens[k] += usage.get(k, 0)

                choice = result['choices'][0]
                message = choice['message']
                messages.append(message)

                tool_calls = message.get('tool_calls')
                if tool_calls:
                    for tc in tool_calls:
                        fn_name = tc['function']['name']
                        try:
                            args = json.loads(tc['function']['arguments'])
                        except json.JSONDecodeError:
                            args = {}

                        if fn_name == 'query_database':
                            sql = args.get('sql', '')
                            _logger.info("AI query [%s]: %s", args.get('purpose', ''), sql[:200])
                            query_result = self._execute_readonly_query(sql)
                            tool_content = json.dumps(query_result, ensure_ascii=False, default=str)
                            # Truncate large results to reduce token usage and prevent slow responses
                            if len(tool_content) > 6000:
                                tool_content = tool_content[:6000] + '...(truncated)'
                            messages.append({
                                'role': 'tool',
                                'tool_call_id': tc['id'],
                                'content': tool_content,
                            })
                        else:
                            messages.append({
                                'role': 'tool',
                                'tool_call_id': tc['id'],
                                'content': json.dumps({'error': f'Unknown function: {fn_name}'}),
                            })
                else:
                    # Final response — no more tool calls
                    return {
                        'analysis': message.get('content', ''),
                        'model': model_used,
                        'tokens': total_tokens,
                        'product_stats': product_stats,
                    }

            # Max iterations reached
            last_content = ''
            for msg in reversed(messages):
                if msg.get('role') == 'assistant' and msg.get('content'):
                    last_content = msg['content']
                    break
            return {
                'analysis': last_content or 'Phân tích chưa hoàn tất (đã đạt giới hạn vòng lặp).',
                'model': model_used,
                'tokens': total_tokens,
                'product_stats': product_stats,
            }

        except requests.exceptions.Timeout as e:
            return {'error': f'OpenAI API timeout sau nhiều lần thử. Vui lòng thử câu hỏi ngắn hơn hoặc thử lại sau. ({e})'}
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else 'unknown'
            detail = ''
            if e.response is not None:
                try:
                    detail = e.response.json().get('error', {}).get('message', '')
                except Exception:
                    pass
            return {'error': f'OpenAI API lỗi ({status}): {detail}'}
        except Exception as e:
            _logger.exception("AI analysis error")
            return {'error': f'Lỗi khi gọi AI: {str(e)}'}

    @api.model
    def _execute_readonly_query(self, sql, max_rows=200):
        """Execute a read-only SQL SELECT query safely with savepoint protection."""
        sql = sql.strip().rstrip(';').strip()

        if not sql.upper().startswith('SELECT'):
            return {'error': 'Chỉ cho phép truy vấn SELECT.'}

        sql_upper = sql.upper()
        banned_keywords = [
            'INSERT', 'UPDATE', 'DELETE', 'DROP', 'ALTER', 'CREATE',
            'TRUNCATE', 'GRANT', 'REVOKE', 'EXECUTE', 'COPY', 'VACUUM',
        ]
        for kw in banned_keywords:
            if re.search(r'\b' + kw + r'\b', sql_upper):
                return {'error': f'Từ khóa không được phép: {kw}'}

        if 'LIMIT' not in sql_upper:
            sql = f"SELECT * FROM ({sql}) _sub LIMIT {max_rows}"

        cr = self.env.cr
        try:
            cr.execute("SAVEPOINT ai_query_sp")
            cr.execute("SET LOCAL statement_timeout = '30s'")
            cr.execute(sql)
            columns = [desc[0] for desc in cr.description]
            rows = cr.fetchmany(max_rows)
            cr.execute("RELEASE SAVEPOINT ai_query_sp")

            data = [dict(zip(columns, row)) for row in rows]
            return {'columns': columns, 'row_count': len(data), 'data': data}
        except Exception as e:
            try:
                cr.execute("ROLLBACK TO SAVEPOINT ai_query_sp")
            except Exception:
                pass
            return {'error': f'Lỗi truy vấn: {str(e)}'}

    @api.model
    def _call_openai_with_retry(self, headers, payload, max_retries=3, base_timeout=60):
        """Call OpenAI API with retry logic and progressive timeout.

        - Retry on timeout/5xx errors with exponential backoff.
        - Timeout increases: 60s → 90s → 120s per attempt.
        """
        last_error = None
        for attempt in range(max_retries):
            timeout = base_timeout + attempt * 30  # 60, 90, 120
            try:
                _logger.info("OpenAI API call attempt %d/%d (timeout=%ds)", attempt + 1, max_retries, timeout)
                response = requests.post(
                    'https://api.openai.com/v1/chat/completions',
                    headers=headers,
                    json=payload,
                    timeout=timeout,
                )
                response.raise_for_status()
                return response.json()
            except requests.exceptions.Timeout:
                last_error = f'OpenAI API timeout (lần {attempt + 1}/{max_retries}, {timeout}s)'
                _logger.warning(last_error)
                if attempt < max_retries - 1:
                    wait = 2 ** attempt  # 1s, 2s
                    time.sleep(wait)
            except requests.exceptions.HTTPError as e:
                status = e.response.status_code if e.response else 0
                detail = ''
                if e.response is not None:
                    try:
                        detail = e.response.json().get('error', {}).get('message', '')
                    except Exception:
                        detail = e.response.text[:200]
                # Retry on 429 (rate limit) and 5xx (server errors)
                if status in (429, 500, 502, 503, 504) and attempt < max_retries - 1:
                    wait = 2 ** attempt + 1
                    _logger.warning("OpenAI %d error, retrying in %ds: %s", status, wait, detail)
                    time.sleep(wait)
                    last_error = f'OpenAI API lỗi ({status}): {detail}'
                else:
                    raise  # Non-retryable HTTP error
        # All retries exhausted
        raise requests.exceptions.Timeout(last_error or 'OpenAI API timeout sau nhiều lần thử')

    @api.model
    def _get_db_schema_description(self):
        """Return database schema description for AI context."""
        return (
            "1. product_product (pp) - Sản phẩm\n"
            "   - id, default_code (SKU/mã SP), barcode, active, product_tmpl_id\n"
            "2. product_template (pt) - Template SP (JOIN pp.product_tmpl_id = pt.id)\n"
            "   - id, name, list_price, standard_price, type, categ_id\n"
            "3. purchase_order (po) - Đơn mua hàng\n"
            "   - id, name, partner_id (NCC), date_order, state, amount_total, currency_id\n"
            "   - state: 'draft','sent','purchase' (đã xác nhận),'done' (hoàn thành),'cancel'\n"
            "4. purchase_order_line (pol) - Chi tiết đơn mua\n"
            "   - id, order_id, product_id, product_qty, qty_received, price_unit, price_subtotal, date_planned\n"
            "5. sale_order (so) - Đơn bán hàng\n"
            "   - id, name, partner_id (KH), date_order, state, amount_total, warehouse_id\n"
            "   - state: 'draft','sent','sale' (đã xác nhận),'done','cancel'\n"
            "6. sale_order_line (sol) - Chi tiết đơn bán\n"
            "   - id, order_id, product_id, product_uom_qty, qty_delivered, price_unit, price_subtotal\n"
            "7. stock_move (sm) - Dịch chuyển kho\n"
            "   - id, product_id, product_uom_qty, state, date, picking_id, origin, location_id, location_dest_id\n"
            "   - state: 'draft','waiting','confirmed','assigned','done','cancel'\n"
            "8. stock_quant (sq) - Tồn kho hiện tại\n"
            "   - id, product_id, location_id, quantity, reserved_quantity\n"
            "9. stock_warehouse (sw) - Kho hàng: id, name, code\n"
            "10. stock_location (sl) - Vị trí kho\n"
            "    - id, name, usage ('internal','customer','supplier','transit'), complete_name\n"
            "11. res_partner (rp) - Đối tác: id, name, supplier_rank, customer_rank, email, phone, city\n"
            "12. product_category (pc) - Danh mục SP: id, name, complete_name, parent_id\n\n"
            "Lưu ý:\n"
            "- supplier_rank > 0 = nhà cung cấp, customer_rank > 0 = khách hàng\n"
            "- stock_location.usage = 'internal' cho vị trí kho nội bộ\n"
            "- Tồn kho thực = stock_quant.quantity tại location có usage='internal'\n"
            "- Dùng date_order để lọc theo kỳ phân tích"
        )

    @api.model
    def chat_with_ai(self, user_message, conversation_history=None, period='month',
                     date_from=False, date_to=False, warehouse_id=False):
        """Chat tương tác với AI — hỗ trợ query DB và tạo Excel."""
        api_key = self.env['ir.config_parameter'].sudo().get_param('openai.api_key', '')
        if not api_key:
            return {'error': 'Chưa cấu hình OpenAI API Key. Vào Cài đặt → Thông số hệ thống → thêm key "openai.api_key".'}

        if not user_message or not user_message.strip():
            return {'error': 'Vui lòng nhập câu hỏi.'}

        d_from, d_to = self._compute_date_range(period, date_from, date_to)
        date_ctx = f"Kỳ phân tích hiện tại: {d_from} đến {d_to}"
        if warehouse_id:
            wh = self.env['stock.warehouse'].browse(warehouse_id)
            date_ctx += f", Kho: {wh.name}"

        schema = self._get_db_schema_description()
        system_prompt = (
            "Bạn là trợ lý AI phân tích mua hàng cho công ty thương mại (trading company).\n\n"
            "Bạn có thể:\n"
            "1. Truy vấn database PostgreSQL (chỉ SELECT) để lấy dữ liệu theo yêu cầu người dùng\n"
            "2. Tạo file Excel báo cáo từ kết quả truy vấn\n\n"
            "Đặc điểm nghiệp vụ:\n"
            "- Công ty MUA hàng từ NCC rồi BÁN lại cho khách\n"
            "- Có kho riêng lưu trữ. Không phải SP nào cũng nên lưu kho\n"
            "- Nhiều SP chỉ mua-bán 1-2 lần (mua theo yêu cầu)\n\n"
            f"Database schema:\n{schema}\n\n"
            f"{date_ctx}\n\n"
            "QUAN TRỌNG - Cách query tồn kho đúng:\n"
            "- Tồn kho thực tế nằm ở bảng stock_quant, KHÔNG phải từ đơn hàng\n"
            "- Nhiều SP có tồn kho nhưng CHƯA BAO GIỜ bán → không có trong sale_order_line\n"
            "- Khi hỏi về 'tồn kho cao nhưng ít bán', phải bắt đầu từ stock_quant rồi LEFT JOIN với sale_order_line\n"
            "- KHÔNG được bắt đầu từ sale_order_line rồi JOIN stock_quant vì sẽ bỏ sót SP chưa bán lần nào\n"
            "- Query mẫu cho tồn kho cao ít bán:\n"
            "  SELECT pp.id, pp.default_code, pt.name, SUM(sq.quantity) as stock_qty,\n"
            "         COALESCE(sale.sold_qty, 0) as sold_qty, COALESCE(sale.sale_count, 0) as sale_count\n"
            "  FROM stock_quant sq\n"
            "  JOIN stock_location sl ON sq.location_id = sl.id AND sl.usage = 'internal'\n"
            "  JOIN product_product pp ON sq.product_id = pp.id\n"
            "  JOIN product_template pt ON pp.product_tmpl_id = pt.id\n"
            "  LEFT JOIN (\n"
            "    SELECT sol.product_id, SUM(sol.product_uom_qty) as sold_qty, COUNT(*) as sale_count\n"
            "    FROM sale_order_line sol\n"
            "    JOIN sale_order so ON sol.order_id = so.id\n"
            "    WHERE so.state IN ('sale','done') AND so.date_order >= '...' AND so.date_order <= '...'\n"
            "    GROUP BY sol.product_id\n"
            "  ) sale ON sale.product_id = pp.id\n"
            "  WHERE pt.type != 'service'\n"
            "  GROUP BY pp.id, pp.default_code, pt.name, sale.sold_qty, sale.sale_count\n"
            "  HAVING SUM(sq.quantity) > 0\n"
            "  ORDER BY stock_qty DESC\n\n"
            "Quy tắc:\n"
            "- Luôn thêm LIMIT (tối đa 200) trong mỗi query\n"
            "- Trả lời bằng tiếng Việt, ngắn gọn, rõ ràng\n"
            "- Sử dụng markdown: ## heading, **bold**, - bullet points\n"
            "- Khi người dùng yêu cầu tạo báo cáo/excel, hãy:\n"
            "  + Đầu tiên query dữ liệu cần thiết\n"
            "  + Sau đó gọi generate_excel với tiêu đề cột và dữ liệu\n"
            "- Đưa ra con số cụ thể trong phân tích"
        )

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "query_database",
                    "description": "Truy vấn SQL SELECT trên database PostgreSQL. Luôn thêm LIMIT (tối đa 200).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "sql": {"type": "string", "description": "Câu truy vấn PostgreSQL SELECT"},
                            "purpose": {"type": "string", "description": "Mục đích truy vấn"}
                        },
                        "required": ["sql", "purpose"]
                    }
                }
            },
            {
                "type": "function",
                "function": {
                    "name": "generate_excel",
                    "description": "Tạo file Excel từ dữ liệu đã query. Gọi sau khi đã có dữ liệu từ query_database.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string", "description": "Tiêu đề báo cáo"},
                            "sheets": {
                                "type": "array",
                                "description": "Danh sách các sheet trong Excel",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "name": {"type": "string", "description": "Tên sheet (max 31 ký tự)"},
                                        "headers": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                            "description": "Tên cột header"
                                        },
                                        "rows": {
                                            "type": "array",
                                            "items": {
                                                "type": "array",
                                                "items": {}
                                            },
                                            "description": "Dữ liệu các dòng, mỗi dòng là mảng giá trị"
                                        }
                                    },
                                    "required": ["name", "headers", "rows"]
                                }
                            }
                        },
                        "required": ["title", "sheets"]
                    }
                }
            },
        ]

        # Build messages from history
        messages = [{"role": "system", "content": system_prompt}]
        if conversation_history:
            for msg in conversation_history:
                role = msg.get('role', 'user')
                if role in ('user', 'assistant'):
                    messages.append({"role": role, "content": msg.get('content', '')})
        messages.append({"role": "user", "content": user_message})

        headers_req = {
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json',
        }
        total_tokens = {'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}
        model_used = 'gpt-4o-mini'
        excel_file = None

        try:
            for iteration in range(8):
                payload = {
                    'model': 'gpt-4o-mini',
                    'messages': messages,
                    'tools': tools,
                    'tool_choice': 'auto',
                    'temperature': 0.3,
                    'max_tokens': 4000,
                }
                result = self._call_openai_with_retry(headers_req, payload)
                model_used = result.get('model', model_used)
                usage = result.get('usage', {})
                for k in total_tokens:
                    total_tokens[k] += usage.get(k, 0)

                choice = result['choices'][0]
                message = choice['message']
                messages.append(message)

                tool_calls = message.get('tool_calls')
                if tool_calls:
                    for tc in tool_calls:
                        fn_name = tc['function']['name']
                        try:
                            args = json.loads(tc['function']['arguments'])
                        except json.JSONDecodeError:
                            args = {}

                        if fn_name == 'query_database':
                            sql = args.get('sql', '')
                            _logger.info("AI Chat query [%s]: %s", args.get('purpose', ''), sql[:200])
                            query_result = self._execute_readonly_query(sql)
                            tool_content = json.dumps(query_result, ensure_ascii=False, default=str)
                            if len(tool_content) > 6000:
                                tool_content = tool_content[:6000] + '...(truncated)'
                            messages.append({
                                'role': 'tool',
                                'tool_call_id': tc['id'],
                                'content': tool_content,
                            })
                        elif fn_name == 'generate_excel':
                            title = args.get('title', 'Báo cáo')
                            sheets = args.get('sheets', [])
                            _logger.info("AI generating Excel: %s (%d sheets)", title, len(sheets))
                            excel_result = self._generate_excel_from_ai(title, sheets)
                            if excel_result.get('success'):
                                excel_file = {
                                    'data': excel_result['data'],
                                    'filename': excel_result['filename'],
                                }
                                messages.append({
                                    'role': 'tool',
                                    'tool_call_id': tc['id'],
                                    'content': json.dumps({
                                        'success': True,
                                        'message': f'Đã tạo file Excel "{excel_result["filename"]}" thành công.',
                                    }),
                                })
                            else:
                                messages.append({
                                    'role': 'tool',
                                    'tool_call_id': tc['id'],
                                    'content': json.dumps({'error': excel_result.get('error', 'Lỗi tạo Excel')}),
                                })
                        else:
                            messages.append({
                                'role': 'tool',
                                'tool_call_id': tc['id'],
                                'content': json.dumps({'error': f'Unknown function: {fn_name}'}),
                            })
                else:
                    # Final response
                    resp = {
                        'reply': message.get('content', ''),
                        'model': model_used,
                        'tokens': total_tokens,
                    }
                    if excel_file:
                        resp['excel'] = excel_file
                    return resp

            # Max iterations
            last_content = ''
            for msg in reversed(messages):
                if msg.get('role') == 'assistant' and msg.get('content'):
                    last_content = msg['content']
                    break
            resp = {
                'reply': last_content or 'Xử lý chưa hoàn tất.',
                'model': model_used,
                'tokens': total_tokens,
            }
            if excel_file:
                resp['excel'] = excel_file
            return resp

        except requests.exceptions.Timeout as e:
            return {'error': f'OpenAI API timeout sau nhiều lần thử. Vui lòng thử câu hỏi ngắn hơn hoặc thử lại sau. ({e})'}
        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response else 'unknown'
            detail = ''
            if e.response is not None:
                try:
                    detail = e.response.json().get('error', {}).get('message', '')
                except Exception:
                    pass
            return {'error': f'OpenAI API lỗi ({status}): {detail}'}
        except Exception as e:
            _logger.exception("AI chat error")
            return {'error': f'Lỗi: {str(e)}'}

    @api.model
    def _generate_excel_from_ai(self, title, sheets):
        """Generate Excel file from AI-provided data structure."""
        try:
            import xlsxwriter
        except ImportError:
            return {'error': 'Thiếu thư viện xlsxwriter.'}

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})

        header_fmt = wb.add_format({
            'bold': True, 'bg_color': '#667eea', 'font_color': 'white',
            'border': 1, 'align': 'center', 'valign': 'vcenter', 'font_size': 11,
        })
        num_fmt = wb.add_format({'num_format': '#,##0.##', 'border': 1, 'align': 'right'})
        text_fmt = wb.add_format({'border': 1, 'text_wrap': True})
        title_fmt = wb.add_format({'bold': True, 'font_size': 14})

        for sheet_def in sheets[:5]:  # Max 5 sheets
            sheet_name = str(sheet_def.get('name', 'Sheet'))[:31]
            ws = wb.add_worksheet(sheet_name)

            ws.write(0, 0, title, title_fmt)

            col_headers = sheet_def.get('headers', [])
            for col, h in enumerate(col_headers):
                ws.write(2, col, str(h), header_fmt)

            rows = sheet_def.get('rows', [])
            for r_idx, row_data in enumerate(rows[:500]):  # Max 500 rows
                for c_idx, val in enumerate(row_data):
                    if val is None:
                        ws.write(r_idx + 3, c_idx, '', text_fmt)
                    elif isinstance(val, (int, float)):
                        ws.write_number(r_idx + 3, c_idx, val, num_fmt)
                    else:
                        ws.write(r_idx + 3, c_idx, str(val), text_fmt)

            # Auto-size columns (estimate)
            for col in range(len(col_headers)):
                max_len = len(str(col_headers[col])) if col < len(col_headers) else 8
                for row_data in rows[:50]:
                    if col < len(row_data) and row_data[col] is not None:
                        max_len = max(max_len, len(str(row_data[col])))
                ws.set_column(col, col, min(max_len + 2, 50))

        wb.close()
        output.seek(0)

        safe_title = re.sub(r'[^\w\s-]', '', title).strip().replace(' ', '_')[:40]
        filename = f"{safe_title}_{date.today().strftime('%Y%m%d')}.xlsx"

        return {
            'success': True,
            'data': base64.b64encode(output.read()).decode('utf-8'),
            'filename': filename,
        }
