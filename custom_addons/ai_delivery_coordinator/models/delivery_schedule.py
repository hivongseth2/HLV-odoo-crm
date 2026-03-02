# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import urllib.parse
import requests
import json
import logging

_logger = logging.getLogger(__name__)


class DeliveryRoute(models.Model):
    _name = 'delivery.route'
    _description = 'Delivery Route'
    _order = 'sequence, name'

    name = fields.Char(string='Tên tuyến', required=True)
    sequence = fields.Integer(string='Sequence', default=10)
    active = fields.Boolean(string='Active', default=True)
    description = fields.Text(string='Mô tả')

class DeliverySchedule(models.Model):
    _name = 'delivery.schedule'
    _description = 'Delivery Schedule from AI'
    _order = 'date desc, id desc'

    name = fields.Char(string='Mã chuyến', required=True, copy=False, readonly=True, default=lambda self: 'New')
    date = fields.Date(string='Ngày giao', required=True, default=fields.Date.context_today)
    route = fields.Char(string='Tuyến giao hàng', required=True)
    warehouse_code = fields.Char(string='Kho xuất')
    vehicle_type = fields.Selection([
        ('tai_lon', 'Xe tải lớn'),
        ('van_xe_may', 'Xe tải Van / Xe máy')
    ], string='Phương tiện', required=True)
    driver_name = fields.Char(string='Tài xế / Ghi chú', help="Tên tài xế hoặc mô tả phương tiện phụ")
    
    line_ids = fields.One2many('delivery.schedule.line', 'schedule_id', string='Chi tiết đơn hàng')
    
    session = fields.Selection([
        ('morning', 'Sáng'),
        ('afternoon', 'Chiều'),
        ('evening', 'Tối'),
        ('other', 'Khác')
    ], string='Phiên giao hàng', default='morning', required=True)
    
    note = fields.Text(string='Ghi chú từ AI')

    def action_create_batch_picking(self):
        self.ensure_one()
        if not self.line_ids:
            raise UserError(_("Lịch trình không có đơn hàng nào."))
            
        picking_ids = []
        for line in self.line_ids:
            # Lấy các phiếu kho (outgoing/pick/pack) của đơn sale chưa hoàn thành
            pickings = line.order_id.picking_ids.filtered(lambda p: p.state not in ['done', 'cancel'])
            picking_ids.extend(pickings.ids)
            
        if not picking_ids:
            raise UserError(_("Không tìm thấy phiếu lấy hàng/giao hàng nào hợp lệ cho các đơn hàng này."))
            
        # Create a new batch picking
        batch_vals = {
            'user_id': self.env.user.id,
            'picking_ids': [(6, 0, picking_ids)],
            # Add any other helpful fields here, for example picking_type_id if required by user config
        }
        batch = self.env['stock.picking.batch'].create(batch_vals)
        
        return {
            'name': _('Batch Giao Hàng'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.picking.batch',
            'res_id': batch.id,
            'view_mode': 'form',
            'target': 'current',
        }

    def action_view_google_map(self):
        self.ensure_one()
        import urllib.parse
        
        # Get origin (warehouse)
        origin = self.warehouse_code or ''
        warehouse = self.env['stock.warehouse'].search([('code', '=', self.warehouse_code)], limit=1)
        if warehouse and warehouse.partner_id.contact_address:
            origin = warehouse.partner_id.contact_address.replace('\n', ', ')
            
        # Get destinations (delivery addresses)
        addresses = []
        for line in self.line_ids:
            if line.order_id.partner_shipping_id:
                addr = line.order_id.partner_shipping_id.contact_address
                if addr:
                    addresses.append(addr.replace('\n', ', '))
                    
        if not addresses:
            raise UserError(str("Không có địa chỉ giao hàng nào trong lịch trình này."))
            
        # Google Maps Dir URL expects: /dir/?api=1&origin=...&destination=...&waypoints=...|...
        # We set origin as warehouse, destination as last address, and waypoints as the rest.
        destination = addresses[-1]
        waypoints = addresses[:-1]
        
        base_url = "https://www.google.com/maps/dir/?api=1"
        url_params = {
            'origin': origin,
            'destination': destination
        }
        if waypoints:
            url_params['waypoints'] = 'optimize:true|' + '|'.join(waypoints)
            
        full_url = f"{base_url}&{urllib.parse.urlencode(url_params)}"
        
        return {
            'type': 'ir.actions.act_url',
            'url': full_url,
            'target': 'new',
        }

    def action_open_kanban_board(self):
        self.ensure_one()
        return {
            'name': _('Bảng Điều Phối Lắp Ghép'),
            'type': 'ir.actions.act_window',
            'res_model': 'delivery.schedule.line',
            'view_mode': 'kanban,list,form',
            'domain': [
                '|',
                ('schedule_id', '=', self.id),
                '&', ('schedule_id', '=', False), ('assigned_date', '=', self.date)
            ],
            'context': {
                'default_schedule_id': self.id,
                'search_default_group_by_schedule': 1
            }
        }

class DeliveryScheduleLine(models.Model):
    _name = 'delivery.schedule.line'
    _description = 'Chi tiết đơn hàng trong Lịch trình'

    schedule_id = fields.Many2one('delivery.schedule', string='Lịch trình', ondelete='set null', index=True)
    assigned_date = fields.Date(string='Ngày giao (Gán cứng)', default=fields.Date.context_today)
    session = fields.Selection(related='schedule_id.session', string='Phiên giao', store=True)
    
    route_id = fields.Many2one('delivery.route', string='Tuyến Giao Thực Tế', group_expand='_read_group_route_ids')
    ai_suggested_route = fields.Char(string='AI Gợi Ý Tuyến')
    
    order_id = fields.Many2one('sale.order', string='Đơn hàng', required=True, ondelete='cascade')
    partner_id = fields.Many2one('res.partner', related='order_id.partner_id', string='Khách hàng', store=True)
    commitment_date = fields.Datetime(related='order_id.commitment_date', string='Ngày hẹn giao', readonly=True)

    @api.model
    def _read_group_route_ids(self, routes, domain, order=None):
        # This allows the Kanban view to show all routes even if empty
        return self.env['delivery.route'].search([])
    
    stock_status = fields.Selection([
        ('ready', 'Đủ hàng'),
        ('waiting', 'Chờ hàng về'),
        ('shortage', 'Thiếu hàng')
    ], string='Tình trạng hàng')
    
    ai_strategy = fields.Char(string='Chiến lược / Ghi chú AI')

    delivery_address = fields.Char(related='order_id.partner_shipping_id.contact_address', string='Địa chỉ giao hàng')
    order_line_ids = fields.One2many(related='order_id.order_line', string='Chi tiết sản phẩm')
    po_expected_date = fields.Date(string='Ngày hàng về dự kiến (PO)', compute='_compute_po_expected_date', store=True)

    @api.depends('order_id')
    def _compute_po_expected_date(self):
        for record in self:
            po_expected_date = False
            if record.order_id:
                # Tìm PO liên quan tới SO (dựa theo tên SO trong trường origin)
                po = self.env['purchase.order'].search([
                    ('origin', '=', record.order_id.name), 
                    ('state', 'not in', ('cancel', 'draft'))
                ], limit=1, order='date_planned desc')
                if po and po.date_planned:
                    po_expected_date = po.date_planned.date()
            record.po_expected_date = po_expected_date

    def write(self, vals):
        for record in self:
            if record.assigned_date and record.assigned_date < fields.Date.context_today(self):
                raise models.ValidationError("Không thể sửa đổi đơn hàng trong Lịch trình của ngày quá khứ.")
        return super().write(vals)

    def unlink(self):
        for record in self:
            if record.assigned_date and record.assigned_date < fields.Date.context_today(self):
                raise models.ValidationError("Không thể xóa đơn hàng trong Lịch trình của ngày quá khứ.")
        return super().unlink()

    # =====================================================
    # AI Route Assignment - Phân tuyến tự động bằng AI
    # =====================================================
    @api.model
    def action_ai_assign_routes(self):
        """Gọi GPT để phân tuyến tự động cho các đơn chưa có route_id."""
        # 1. Lấy API Key
        api_key = self.env['ir.config_parameter'].sudo().get_param('ai_delivery_coordinator.openai_api_key')
        model_name = self.env['ir.config_parameter'].sudo().get_param('ai_delivery_coordinator.openai_model_delivery', 'gpt-4o')
        if not api_key:
            raise UserError(_("Vui lòng cấu hình OpenAI API Key trong Thiết lập > AI Vận Chuyển."))

        # 2. Tìm các line chưa phân tuyến
        unassigned_lines = self.search([
            ('route_id', '=', False),
        ])
        if not unassigned_lines:
            raise UserError(_("Không có đơn hàng nào chưa phân tuyến."))

        # 3. Lấy danh sách tuyến có sẵn
        routes = self.env['delivery.route'].search([('active', '=', True)])
        if not routes:
            raise UserError(_("Chưa cấu hình Tuyến Giao Hàng. Vui lòng tạo tuyến trong menu 'Tuyến Giao Hàng'."))

        route_names = [r.name for r in routes]
        route_map = {r.name.strip().lower(): r.id for r in routes}

        # 4. Chuẩn bị dữ liệu gửi GPT
        order_data = []
        for line in unassigned_lines:
            address = line.delivery_address or ''
            address = ', '.join([part.strip() for part in address.split('\n') if part.strip()])
            order_data.append({
                'line_id': line.id,
                'order_name': line.order_id.name,
                'customer': line.partner_id.name or '',
                'delivery_address': address,
            })

        # 5. Prompt GPT
        system_prompt = f"""Bạn là hệ thống phân tuyến giao hàng.
Nhiệm vụ: Đọc địa chỉ giao hàng của từng đơn hàng và gán vào MỘT trong các tuyến sau:
{json.dumps(route_names, ensure_ascii=False)}

Quy tắc:
- Dựa vào địa chỉ (quận/huyện, tỉnh/thành phố, KCN...) để xác định tuyến phù hợp nhất.
- Nếu không khớp chính xác tuyến nào, hãy chọn tuyến gần nhất về mặt địa lý.
- KHÔNG được bỏ sót bất kỳ đơn hàng nào. Mỗi đơn PHẢI được gán một tuyến.
- Trả về ĐÚNG chuẩn JSON, không có markdown.

Trả về JSON:
{{
  "assignments": [
    {{"line_id": 1, "route_name": "Tuyến ABC", "reason": "Lý do ngắn gọn"}}
  ]
}}
"""
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(order_data, ensure_ascii=False)}
            ],
            "temperature": 0.1,
            "max_tokens": 4000
        }

        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers, json=payload, timeout=90
            )
            if response.status_code != 200:
                raise UserError(_("Lỗi kết nối OpenAI API: %s") % response.text)

            gpt_content = response.json()['choices'][0]['message']['content'].strip()
            # Clean markdown
            if gpt_content.startswith('```json'):
                gpt_content = gpt_content[7:]
            if gpt_content.startswith('```'):
                gpt_content = gpt_content[3:]
            if gpt_content.endswith('```'):
                gpt_content = gpt_content[:-3]

            result = json.loads(gpt_content.strip())
        except json.JSONDecodeError as e:
            raise UserError(_("AI trả về JSON không hợp lệ: %s") % str(e))
        except requests.exceptions.Timeout:
            raise UserError(_("Kết nối OpenAI bị timeout. Vui lòng thử lại."))

        # 6. Gán route_id cho từng line
        assignments = result.get('assignments', [])
        assigned_count = 0
        line_map = {line.id: line for line in unassigned_lines}

        for item in assignments:
            line_id = item.get('line_id')
            route_name = (item.get('route_name') or '').strip()
            reason = item.get('reason', '')

            if line_id not in line_map:
                continue

            line = line_map[line_id]
            # Tìm route_id khớp tên (case-insensitive)
            matched_route_id = route_map.get(route_name.lower())
            if not matched_route_id:
                # Fuzzy fallback: tìm route chứa keyword
                for rname, rid in route_map.items():
                    if rname in route_name.lower() or route_name.lower() in rname:
                        matched_route_id = rid
                        break

            vals = {
                'ai_suggested_route': route_name,
            }
            if matched_route_id:
                vals['route_id'] = matched_route_id
                assigned_count += 1

            if reason:
                vals['ai_strategy'] = reason

            line.write(vals)

        _logger.info("AI Route Assignment: %d/%d lines assigned.", assigned_count, len(unassigned_lines))

        # 7. Reload Kanban
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('AI Phân Tuyến Hoàn Tất'),
                'message': _('Đã phân tuyến %d/%d đơn hàng.') % (assigned_count, len(unassigned_lines)),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    # =====================================================
    # Tải lại danh sách chưa phân tuyến & cập nhật stock
    # =====================================================
    @api.model
    def action_refresh_unassigned(self):
        """Cập nhật lại stock_status cho tất cả đơn chưa phân tuyến."""
        unassigned_lines = self.search([
            ('route_id', '=', False),
        ])
        if not unassigned_lines:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': _('Thông báo'),
                    'message': _('Không có đơn hàng nào chưa phân tuyến.'),
                    'type': 'info',
                    'sticky': False,
                    'next': {'type': 'ir.actions.client', 'tag': 'reload'},
                }
            }

        updated_count = 0
        for line in unassigned_lines:
            order = line.order_id
            if not order:
                continue

            is_ready = True
            is_waiting = False
            for sol in order.order_line:
                if sol.product_id and sol.product_id.type == 'consu':
                    remaining = sol.product_uom_qty - sol.qty_delivered
                    if remaining > 0 and sol.product_id.qty_available < remaining:
                        is_ready = False
                        if sol.product_id.incoming_qty > 0:
                            is_waiting = True

            new_status = 'ready'
            if not is_ready:
                new_status = 'waiting' if is_waiting else 'shortage'

            if line.stock_status != new_status:
                line.write({'stock_status': new_status})
                updated_count += 1

        _logger.info("Refresh Unassigned: %d lines updated out of %d.", updated_count, len(unassigned_lines))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Cập nhật Xong'),
                'message': _('Đã cập nhật tình trạng hàng cho %d/%d đơn chưa phân tuyến.') % (updated_count, len(unassigned_lines)),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }
