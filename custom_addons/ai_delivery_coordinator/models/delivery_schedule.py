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
    trip_id = fields.Many2one('delivery.trip', string='Chuyến giao', ondelete='set null', index=True)
    is_selected = fields.Boolean(string='Đã chọn', default=False)
    
    order_id = fields.Many2one('sale.order', string='Đơn hàng', required=True, ondelete='cascade')
    partner_id = fields.Many2one('res.partner', related='order_id.partner_id', string='Khách hàng', store=True)
    commitment_date = fields.Datetime(related='order_id.commitment_date', string='Ngày hẹn giao', readonly=True)

    @api.model
    def _read_group_route_ids(self, routes, domain, order=None):
        # This allows the Kanban view to show all routes even if empty
        return self.env['delivery.route'].search([])
    
    stock_status = fields.Selection([
        ('ready', 'Đủ hàng'),
        ('partial', 'Có 1 phần'),
        ('waiting', 'Chờ hàng về'),
        ('shortage', 'Thiếu hàng')
    ], string='Tình trạng hàng')
    
    ai_strategy = fields.Char(string='Chiến lược / Ghi chú AI')

    delivery_address = fields.Char(related='order_id.partner_shipping_id.street', string='Địa chỉ giao hàng')
    order_line_ids = fields.One2many(related='order_id.order_line', string='Chi tiết sản phẩm')

    # Sale Order info cho thủ kho
    order_tag_ids = fields.Many2many(related='order_id.tag_ids', string='Thẻ đơn hàng')
    order_origin = fields.Char(related='order_id.origin', string='Nguồn gốc (Origin)')
    order_htgh = fields.Text(related='order_id.x_studio_htgh', string='Hình thức giao hàng')
    distance_km = fields.Float(string='Khoảng cách (km)', digits=(10, 1), help='Ước lượng khoảng cách từ kho đến điểm giao')
    kho_xuat = fields.Char(related='order_id.x_studio_kho_xuat', string='Kho xuất', store=True)
    picking_status = fields.Char(string='Trạng thái kho', compute='_compute_picking_status')

    @api.depends('order_id')
    def _compute_picking_status(self):
        """Trạng thái kho theo chiến lược 3 bước: Pick → Pack → Out.
        Chỉ tính 'Giao 1 phần' khi có ít nhất 1 phiếu OUT done.
        """
        for line in self:
            if not line.order_id:
                line.picking_status = ''
                continue

            all_pickings = self.env['stock.picking'].search([
                ('origin', 'like', line.order_id.name),
                ('state', '!=', 'cancel'),
            ])

            if not all_pickings:
                line.picking_status = 'Chưa có phiếu'
                continue

            # Tách theo loại
            out_ops = all_pickings.filtered(lambda p: p.picking_type_code == 'outgoing')
            active_pickings = all_pickings.filtered(lambda p: p.state not in ('done', 'cancel'))

            # Tất cả phiếu done (kể cả pick/pack/out) = Hoàn tất
            if not active_pickings:
                line.picking_status = 'Hoàn tất'
                continue

            # Kiểm tra giao 1 phần: CHỈ khi có OUT done
            out_done = out_ops.filtered(lambda p: p.state == 'done')
            has_partial_delivery = bool(out_done)

            # Tìm bước hiện tại (đang xử lý)
            pick = active_pickings.sorted(key=lambda p: p.id)[0]
            pick_type = pick.picking_type_id.name or ''
            state_label = {
                'draft': 'Nháp',
                'waiting': 'Chờ',
                'confirmed': 'Chờ xử lý',
                'assigned': 'Sẵn sàng',
            }.get(pick.state, pick.state)

            if pick.picking_type_code == 'internal':
                if 'Pick' in pick_type or 'pick' in pick_type:
                    step_name = 'Lấy hàng'
                elif 'Pack' in pick_type or 'pack' in pick_type:
                    step_name = 'Đóng gói'
                else:
                    step_name = pick_type
            elif pick.picking_type_code == 'outgoing':
                step_name = 'Xuất kho'
            else:
                step_name = pick_type

            status = f'{step_name}: {state_label}'
            if has_partial_delivery:
                status = f'Giao 1 phần | {status}'

            line.picking_status = status

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
        # Cho phép thay đổi is_selected, stock_status trên đơn cũ
        safe_fields = {'is_selected', 'stock_status'}
        if not safe_fields.issuperset(vals.keys()):
            for record in self:
                if record.assigned_date and record.assigned_date < fields.Date.context_today(self):
                    raise models.ValidationError("Không thể sửa đổi đơn hàng trong Lịch trình của ngày quá khứ.")
        return super().write(vals)

    def unlink(self):
        # Cho phép xóa từ refresh (context flag)
        if not self.env.context.get('force_unlink'):
            for record in self:
                if record.assigned_date and record.assigned_date < fields.Date.context_today(self):
                    raise models.ValidationError("Không thể xóa đơn hàng trong Lịch trình của ngày quá khứ.")
        return super().unlink()

    # =====================================================
    # Helper: Sửa JSON bị cắt ngắn từ GPT
    # =====================================================
    @api.model
    def _repair_truncated_json(self, text):
        """Cố gắng sửa JSON bị cắt ngắn do GPT hết token."""
        # Tìm vị trí cuối cùng của một object hoàn chỉnh trong array
        last_complete = text.rfind('}')
        if last_complete == -1:
            return text

        # Cắt tại object hoàn chỉnh cuối cùng
        truncated = text[:last_complete + 1]

        # Đếm brackets chưa đóng
        open_brackets = truncated.count('[') - truncated.count(']')
        open_braces = truncated.count('{') - truncated.count('}')

        # Đóng brackets/braces còn thiếu
        truncated += ']' * max(0, open_brackets)
        truncated += '}' * max(0, open_braces)

        _logger.info("JSON repair: closed %d brackets, %d braces", max(0, open_brackets), max(0, open_braces))
        return truncated

    # =====================================================
    # Helper: Gọi GPT cho 1 batch đơn hàng
    # =====================================================
    @api.model
    def _call_gpt_for_routes(self, api_key, model_name, route_names, batch_data, wh_address=''):
        """Gọi GPT phân tuyến cho 1 batch nhỏ. Trả về list of {id, r, km}."""
        wh_info = f"\nĐịa chỉ kho xuất phát: {wh_address}" if wh_address else ""
        system_prompt = f"""Phân tuyến giao hàng. Gán mỗi đơn vào 1 tuyến:
{json.dumps(route_names, ensure_ascii=False)}{wh_info}

Input: [{{"id":1,"addr":"địa chỉ"}}]
Output JSON: {{"a":[{{"id":1,"r":"Tên tuyến","km":25}}]}}
km = ước lượng khoảng cách lái xe (km) từ kho đến điểm giao.
Dùng key ngắn. Mỗi đơn PHẢI có tuyến + km. Không bỏ sót."""

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(batch_data, ensure_ascii=False)}
            ],
            "temperature": 0.1,
            "max_tokens": 8000,
            "response_format": {"type": "json_object"},
        }

        try:
            response = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers, json=payload, timeout=120
            )
            if response.status_code != 200:
                _logger.error("OpenAI API error: %s", response.text[:300])
                raise UserError(_("Lỗi kết nối OpenAI API: %s") % response.text[:200])

            resp_json = response.json()
            gpt_content = resp_json['choices'][0]['message']['content'].strip()
            finish_reason = resp_json['choices'][0].get('finish_reason', '')

            if finish_reason == 'length':
                _logger.warning("GPT batch response truncated. Repairing...")
                gpt_content = self._repair_truncated_json(gpt_content)

            result = json.loads(gpt_content)
            return result.get('a', result.get('assignments', []))

        except json.JSONDecodeError as e:
            _logger.error("GPT batch JSON error: %s | Content: %s", str(e), gpt_content[:300] if gpt_content else 'EMPTY')
            # Trả về list rỗng thay vì crash — batch sau vẫn chạy
            return []
        except requests.exceptions.Timeout:
            _logger.error("GPT batch timeout")
            return []

    # =====================================================
    # Auto-assign route bằng Tags (không cần AI)
    # =====================================================
    def action_auto_assign_by_tags(self):
        """Tự động gán route_id nếu tag đơn hàng khớp tên tuyến."""
        lines = self.browse(self.env.context.get('active_ids', [])) if self.env.context.get('active_ids') else self
        if not lines:
            lines = self.search([('route_id', '=', False)])
        lines = lines.filtered(lambda l: not l.route_id)
        if not lines:
            raise UserError(_('Không có đơn hàng nào chưa phân tuyến.'))

        routes = self.env['delivery.route'].search([('active', '=', True)])
        # Map tên tuyến (lowercase) -> route id
        route_map = {}
        for r in routes:
            route_map[r.name.strip().lower()] = r.id

        assigned_count = 0
        for line in lines:
            if not line.order_tag_ids:
                continue
            for tag in line.order_tag_ids:
                tag_lower = tag.name.strip().lower()
                matched_id = route_map.get(tag_lower)
                if not matched_id:
                    # Fuzzy: tag chứa tên tuyến hoặc ngược lại
                    for rname, rid in route_map.items():
                        if rname in tag_lower or tag_lower in rname:
                            matched_id = rid
                            break
                if matched_id:
                    line.write({
                        'route_id': matched_id,
                        'ai_suggested_route': tag.name,
                    })
                    assigned_count += 1
                    break  # 1 tag khớp là đủ

        _logger.info('Tag auto-assign: %d/%d lines.', assigned_count, len(lines))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Phân Tuyến Theo Tags Hoàn Tất'),
                'message': _('Đã phân tuyến %d/%d đơn (khớp tag).') % (assigned_count, len(lines)),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    # =====================================================
    # Kanban Selection
    # =====================================================
    def action_toggle_select(self):
        """Toggle is_selected cho Kanban checkbox."""
        for line in self:
            line.is_selected = not line.is_selected
        # Return False = Odoo chỉ reload 1 record, không reload cả trang
        return False

    def action_clear_selection(self):
        """Bỏ chọn tất cả."""
        self.search([('is_selected', '=', True)]).write({'is_selected': False})
        return {'type': 'ir.actions.client', 'tag': 'soft_reload'}

    # =====================================================
    # AI Route Assignment - Phân tuyến tự động bằng AI
    # =====================================================
    def action_ai_assign_routes(self):
        """Gọi GPT để phân tuyến tự động + ước lượng km."""
        lines = self.browse(self.env.context.get('active_ids', [])) if self.env.context.get('active_ids') else self
        if not lines:
            lines = self.search([('route_id', '=', False)])
        lines = lines.filtered(lambda l: not l.route_id)
        if not lines:
            raise UserError(_('Không có đơn hàng nào chưa phân tuyến trong danh sách đã chọn.'))

        api_key = self.env['ir.config_parameter'].sudo().get_param('ai_delivery_coordinator.openai_api_key')
        model_name = self.env['ir.config_parameter'].sudo().get_param('ai_delivery_coordinator.openai_model_delivery', 'gpt-4o')
        if not api_key:
            raise UserError(_('Vui lòng cấu hình OpenAI API Key trong Thiết lập > AI Vận Chuyển.'))

        routes = self.env['delivery.route'].search([('active', '=', True)])
        if not routes:
            raise UserError(_('Chưa cấu hình Tuyến Giao Hàng.'))

        route_names = [r.name for r in routes]
        route_map = {r.name.strip().lower(): r.id for r in routes}

        # Lấy địa chỉ kho xuất phát từ cấu hình
        wh_id = self.env['ir.config_parameter'].sudo().get_param('ai_delivery_coordinator.warehouse_id')
        warehouse = self.env['stock.warehouse'].browse(int(wh_id)) if wh_id else self.env['stock.warehouse'].search([], limit=1)
        wh_address = ''
        if warehouse and warehouse.partner_id and warehouse.partner_id.street:
            wh_address = warehouse.partner_id.street

        order_data = []
        for line in lines:
            address = line.delivery_address or ''
            address = ', '.join([p.strip() for p in address.split('\n') if p.strip()])
            order_data.append({'id': line.id, 'addr': address})

        BATCH_SIZE = 50
        all_assignments = []
        total_batches = (len(order_data) + BATCH_SIZE - 1) // BATCH_SIZE

        for batch_idx in range(total_batches):
            start = batch_idx * BATCH_SIZE
            batch = order_data[start:start + BATCH_SIZE]
            _logger.info('AI Route: Batch %d/%d (%d items)', batch_idx + 1, total_batches, len(batch))
            batch_result = self._call_gpt_for_routes(api_key, model_name, route_names, batch, wh_address)
            all_assignments.extend(batch_result)

        assigned_count = 0
        line_map = {line.id: line for line in lines}

        for item in all_assignments:
            line_id = item.get('id')
            route_name = (item.get('r') or '').strip()
            km = item.get('km', 0)

            if line_id not in line_map:
                continue

            line = line_map[line_id]
            matched_route_id = route_map.get(route_name.lower())
            if not matched_route_id:
                for rname, rid in route_map.items():
                    if rname in route_name.lower() or route_name.lower() in rname:
                        matched_route_id = rid
                        break

            vals = {'ai_suggested_route': route_name}
            if matched_route_id:
                vals['route_id'] = matched_route_id
                assigned_count += 1
            try:
                vals['distance_km'] = float(km) if km else 0
            except (ValueError, TypeError):
                vals['distance_km'] = 0

            line.write(vals)

        _logger.info('AI Route Assignment: %d/%d lines assigned.', assigned_count, len(lines))

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('AI Phân Tuyến Hoàn Tất'),
                'message': _('Đã phân tuyến %d/%d đơn hàng.') % (assigned_count, len(lines)),
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }

    # =====================================================
    # Tải lại & cập nhật stock + xóa đơn đã giao xong
    # =====================================================
    def action_refresh_unassigned(self):
        """Fetch đơn mới, xóa đơn hủy/giao xong, cập nhật stock_status."""
        # 1. Fetch đơn hàng mới (confirmed/sale) chưa có trong kanban
        existing_order_ids = self.search([]).mapped('order_id').ids
        schedule = self.env['delivery.schedule'].search([], limit=1)
        if not schedule:
            schedule = self.env['delivery.schedule'].create({
                'name': _('Bảng Điều Phối'),
                'date': fields.Date.context_today(self),
            })

        new_orders = self.env['sale.order'].search([
            ('state', 'in', ('sale', 'done')),
            ('id', 'not in', existing_order_ids),
        ])

        new_count = 0
        for order in new_orders:
            # Chỉ thêm đơn chưa giao hết
            is_fully_delivered = all(
                sol.qty_delivered >= sol.product_uom_qty
                for sol in order.order_line
                if sol.product_id and sol.product_id.type == 'consu'
            )
            if not is_fully_delivered:
                self.create({
                    'schedule_id': schedule.id,
                    'order_id': order.id,
                    'assigned_date': fields.Date.context_today(self),
                })
                new_count += 1

        # 2. Xóa đơn bị hủy
        cancelled_lines = self.search([
            ('order_id.state', 'in', ('cancel',)),
        ])
        cancelled_count = len(cancelled_lines)
        if cancelled_lines:
            _logger.info('Removing %d cancelled order lines.', cancelled_count)
            cancelled_lines.sudo().with_context(force_unlink=True).unlink()

        # 3. Xóa đơn đã giao hết + Cập nhật stock cho các đơn còn lại
        lines = self.search([])
        updated_count = 0
        delivered_lines = self.env['delivery.schedule.line']

        for line in lines:
            order = line.order_id
            if not order:
                continue

            is_fully_delivered = all(
                sol.qty_delivered >= sol.product_uom_qty
                for sol in order.order_line
                if sol.product_id and sol.product_id.type == 'consu'
            )
            if is_fully_delivered:
                delivered_lines |= line
                continue

            # Cập nhật stock_status
            total_lines = 0
            ready_lines = 0
            has_incoming = False
            for sol in order.order_line:
                if sol.product_id and sol.product_id.type == 'consu':
                    remaining = sol.product_uom_qty - sol.qty_delivered
                    if remaining > 0:
                        total_lines += 1
                        if sol.product_id.qty_available >= remaining:
                            ready_lines += 1
                        elif sol.product_id.incoming_qty > 0:
                            has_incoming = True

            if total_lines == 0 or ready_lines == total_lines:
                new_status = 'ready'
            elif ready_lines > 0:
                new_status = 'partial'
            elif has_incoming:
                new_status = 'waiting'
            else:
                new_status = 'shortage'

            if line.stock_status != new_status:
                line.write({'stock_status': new_status})
                updated_count += 1

        delivered_count = len(delivered_lines)
        if delivered_lines:
            _logger.info('Removing %d fully delivered lines.', delivered_count)
            delivered_lines.sudo().with_context(force_unlink=True).unlink()

        _logger.info('Refresh: +%d new, -%d cancelled, -%d delivered, %d stock updated.',
                      new_count, cancelled_count, delivered_count, updated_count)

        msg = _('Tải lại xong! +%d đơn mới') % new_count
        if cancelled_count:
            msg += _(', -%d hủy') % cancelled_count
        if delivered_count:
            msg += _(', -%d đã giao') % delivered_count
        msg += _(', cập nhật %d đơn.') % updated_count

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Cập nhật Xong'),
                'message': msg,
                'type': 'success',
                'sticky': False,
                'next': {'type': 'ir.actions.client', 'tag': 'reload'},
            }
        }
