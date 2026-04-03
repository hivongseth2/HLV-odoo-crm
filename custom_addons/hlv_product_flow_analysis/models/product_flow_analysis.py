import logging
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class ProductFlowAnalysis(models.AbstractModel):
    _name = 'product.flow.analysis'
    _description = 'Phân tích lưu thông hàng hóa'

    @api.model
    def get_product_flow_data(self, period='month', date_from=False, date_to=False, warehouse_id=False):
        """Lấy dữ liệu phân tích lưu thông sản phẩm."""
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

        product_data = {}
        for move in moves:
            prod = move.product_id
            if prod.id not in product_data:
                product_data[prod.id] = {
                    'product_id': prod.id,
                    'product_name': prod.display_name,
                    'default_code': prod.default_code or '',
                    'categ_name': prod.categ_id.name or '',
                    'categ_id': prod.categ_id.id,
                    'incoming_qty': 0.0,
                    'outgoing_qty': 0.0,
                    'internal_qty': 0.0,
                    'total_qty': 0.0,
                    'move_count': 0,
                    'qty_available': prod.qty_available,
                }

            qty = move.product_uom_qty
            picking_type = move.picking_type_id.code if move.picking_type_id else ''

            if picking_type == 'incoming':
                product_data[prod.id]['incoming_qty'] += qty
            elif picking_type == 'outgoing':
                product_data[prod.id]['outgoing_qty'] += qty
            elif picking_type == 'internal':
                product_data[prod.id]['internal_qty'] += qty

            product_data[prod.id]['total_qty'] += qty
            product_data[prod.id]['move_count'] += 1

        result = sorted(product_data.values(), key=lambda x: x['total_qty'], reverse=True)
        return {
            'products': result,
            'date_from': str(date_from),
            'date_to': str(date_to),
            'period': period,
        }

    @api.model
    def get_supplier_flow_data(self, period='month', date_from=False, date_to=False, warehouse_id=False):
        """Lấy dữ liệu phân tích nhà cung cấp."""
        date_from, date_to = self._compute_date_range(period, date_from, date_to)

        domain = [
            ('state', '=', 'done'),
            ('date', '>=', fields.Datetime.to_string(date_from)),
            ('date', '<=', fields.Datetime.to_string(date_to)),
            ('picking_type_id.code', '=', 'incoming'),
        ]
        if warehouse_id:
            domain.append(('warehouse_id', '=', warehouse_id))

        moves = self.env['stock.move'].search(domain)

        supplier_data = {}
        for move in moves:
            partner = move.picking_id.partner_id if move.picking_id else False
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
                }

            prod = move.product_id
            qty = move.product_uom_qty
            price = move.price_unit if move.price_unit else 0.0

            supplier_data[partner.id]['total_qty'] += qty
            supplier_data[partner.id]['total_amount'] += qty * price
            supplier_data[partner.id]['move_count'] += 1

            if prod.id not in supplier_data[partner.id]['products']:
                supplier_data[partner.id]['products'][prod.id] = {
                    'product_id': prod.id,
                    'product_name': prod.display_name,
                    'default_code': prod.default_code or '',
                    'qty': 0.0,
                    'amount': 0.0,
                }
            supplier_data[partner.id]['products'][prod.id]['qty'] += qty
            supplier_data[partner.id]['products'][prod.id]['amount'] += qty * price

        # Convert products dict to list
        for sid in supplier_data:
            supplier_data[sid]['products'] = sorted(
                supplier_data[sid]['products'].values(),
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
    def get_inventory_planning_data(self, period='month', date_from=False, date_to=False, warehouse_id=False):
        """Gợi ý tồn kho tối thiểu dựa trên tần suất lưu thông."""
        date_from, date_to = self._compute_date_range(period, date_from, date_to)

        # Calculate total days in period
        total_days = max((date_to - date_from).days, 1)

        domain = [
            ('state', '=', 'done'),
            ('date', '>=', fields.Datetime.to_string(date_from)),
            ('date', '<=', fields.Datetime.to_string(date_to)),
            ('picking_type_id.code', '=', 'outgoing'),
            ('product_id.type', '!=', 'service'),
        ]
        if warehouse_id:
            domain.append(('warehouse_id', '=', warehouse_id))

        moves = self.env['stock.move'].search(domain)

        product_plan = {}
        for move in moves:
            prod = move.product_id
            if prod.id not in product_plan:
                product_plan[prod.id] = {
                    'product_id': prod.id,
                    'product_name': prod.display_name,
                    'default_code': prod.default_code or '',
                    'categ_name': prod.categ_id.name or '',
                    'total_outgoing': 0.0,
                    'move_count': 0,
                    'qty_available': prod.qty_available,
                }
            product_plan[prod.id]['total_outgoing'] += move.product_uom_qty
            product_plan[prod.id]['move_count'] += 1

        planning = []
        for data in product_plan.values():
            avg_daily = data['total_outgoing'] / total_days
            # Lead time mặc định 7 ngày + safety buffer 3 ngày
            lead_time_days = 7
            safety_days = 3
            min_stock = round(avg_daily * (lead_time_days + safety_days), 2)
            reorder_point = round(avg_daily * lead_time_days, 2)

            # Days of stock remaining
            days_remaining = round(data['qty_available'] / avg_daily, 1) if avg_daily > 0 else 9999

            planning.append({
                **data,
                'avg_daily': round(avg_daily, 2),
                'min_stock': min_stock,
                'reorder_point': reorder_point,
                'days_remaining': days_remaining,
                'status': 'danger' if days_remaining <= lead_time_days
                          else 'warning' if days_remaining <= (lead_time_days + safety_days)
                          else 'ok',
            })

        planning.sort(key=lambda x: x['days_remaining'])
        return {
            'planning': planning,
            'date_from': str(date_from),
            'date_to': str(date_to),
            'period': period,
            'total_days': total_days,
            'lead_time_days': 7,
            'safety_days': 3,
        }

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
        unique_suppliers = len(set(
            incoming_moves.mapped('picking_id.partner_id.id')
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
