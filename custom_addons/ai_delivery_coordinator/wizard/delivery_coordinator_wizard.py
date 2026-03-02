# -*- coding: utf-8 -*-
from odoo import models, fields, api, _
from odoo.exceptions import UserError
import requests
import json
from datetime import timedelta

class DeliveryCoordinatorWizard(models.TransientModel):
    _name = 'delivery.coordinator.wizard'
    _description = 'AI Delivery Coordinator Wizard'

    date = fields.Date('Ngày lên lịch (Mặc định: Ngày mai)', default=lambda self: fields.Date.context_today(self) + timedelta(days=1))
    warehouse_id = fields.Many2one('stock.warehouse', string='Kho xuất phát', required=True)

    def action_run_ai_coordinator(self):
        # 1. Fetch settings
        api_key = self.env['ir.config_parameter'].sudo().get_param('ai_delivery_coordinator.openai_api_key')
        model = self.env['ir.config_parameter'].sudo().get_param('ai_delivery_coordinator.openai_model_delivery', 'gpt-4o')
        if not api_key:
            raise UserError(_("Vui lòng cấu hình OpenAI API Key trong Settings."))

        # 2. Get Orders (Include backlogs up to the selected date)
        domain = [
            ('commitment_date', '<', self.date + timedelta(days=1)),
            ('state', 'in', ['sale', 'done'])
        ]
        orders = self.env['sale.order'].search(domain)
        
        # Filter out completely delivered orders or cancelled lines
        pending_orders = orders.filtered(lambda o: not all(l.qty_delivered >= l.product_uom_qty for l in o.order_line if l.product_id.type == 'consu'))

        if not pending_orders:
            raise UserError(_("Không có đơn hàng nào chờ giao tính đến ngày %s.") % self.date)

        # 3. Classify and prepare data for AI
        order_data = []
        report_data = {
            'total_pending_orders': len(pending_orders),
            'orders_ready_to_ship': 0,
            'orders_insufficient_stock': [],
            'orders_backlog': []
        }
        
        today = fields.Date.context_today(self)
        warehouse_map = {'KBC': 'KBC', 'KHD': 'KHD', 'TSN': 'TSN', 'TSNSR': 'TSNSR'}

        # Get Starting Address
        starting_address = self.warehouse_id.partner_id.contact_address or self.warehouse_id.name
        warehouse_code = self.warehouse_id.code

        for order in pending_orders:
            # --- XÁC ĐỊNH KHO XUẤT ---
            results = []
            pickings = order.picking_ids.filtered(lambda p: p.state != 'cancel')
            if pickings:
                for p in pickings:
                    raw_loc = p.location_id.display_name or ""
                    if raw_loc:
                        code = raw_loc.split('/')[0].strip()
                        if code in warehouse_map:
                            results.append(warehouse_map.get(code))
            
            if not results and order.warehouse_id:
                raw_code = order.warehouse_id.code or ""
                results.append(warehouse_map.get(raw_code, raw_code))
                
            order_warehouse_codes = [c.strip() for c in results if c]
            
            # Filter by exactly the selected warehouse (or if unmapped, fallback)
            if warehouse_code not in order_warehouse_codes and results:
                continue # Skip orders that clearly belong to another warehouse

            # Determine List A/B/C simplified logic
            is_ready = True
            is_waiting = False
            for line in order.order_line:
                if line.product_id.type == 'consu':
                    if line.product_id.qty_available < (line.product_uom_qty - line.qty_delivered):
                        is_ready = False
                        if line.product_id.incoming_qty > 0:
                            is_waiting = True
            
            po_info = ""
            if not is_ready:
                # Find PO using origin
                po = self.env['purchase.order'].search([
                    ('origin', '=', order.name),
                    ('state', 'not in', ['cancel'])
                ], limit=1)
                if po and po.date_planned:
                    po_info = f" (Dự kiến hàng về: {po.date_planned.strftime('%d/%m/%Y')})"
            
            list_status = "List A (Sẵn sàng)"
            stock_status = "ready"
            if not is_ready:
                if is_waiting:
                    list_status = f"List B (Chờ nhập){po_info}"
                    stock_status = "waiting"
                else:
                    list_status = f"List C (Tạm hoãn){po_info}"
                    stock_status = "shortage"
            
            # Additional strategy from origin or x_studio_htgh
            strategy = 'Không rõ'
            htgh_val = ''
            if hasattr(order, 'x_studio_htgh') and order.x_studio_htgh:
                htgh_val = order.x_studio_htgh
                if order._fields['x_studio_htgh'].type == 'selection':
                    strategy = dict(order._fields['x_studio_htgh'].selection).get(order.x_studio_htgh, order.x_studio_htgh)
                else:
                    strategy = order.x_studio_htgh
            elif not hasattr(order, 'x_studio_htgh'):
                strategy = 'Không ưu tiên'
                
            origin_val = order.origin or ''
            
            # Rule 2: Strict filtering: skip if not ready AND strategy/origin is not 'giao có gì thì giao' / 'có gì giao nấy'
            is_flexible_delivery = 'có gì' in strategy.lower() or 'có gì' in origin_val.lower()
            
            if order.commitment_date and order.commitment_date.date() < today:
                report_data['orders_backlog'].append(order.name)

            if not is_ready and not is_flexible_delivery:
                report_data['orders_insufficient_stock'].append(order.name)
                continue # Skip this order from AI scheduling

            report_data['orders_ready_to_ship'] += 1

            order_data.append({
                'order_id': order.id,
                'order_name': order.name,
                'customer_address': order.partner_shipping_id.contact_address or '',
                'list_status': list_status,
                'strategy': strategy,
                'origin': origin_val,
                'commitment_date': str(order.commitment_date.date()) if order.commitment_date else 'Unknown',
                'stock_status': stock_status
            })

        if not order_data:
            raise UserError(_("Không có đơn hàng nào hợp lệ cho Kho được chọn (%s). Vui lòng kiểm tra lại.") % self.warehouse_id.name)

        # 4. Prepare GPT prompt
        system_prompt = f"""
        Bạn là hệ thống điều phối giao hàng (AI Coordinator) và tối ưu hóa tuyến đường (Route Optimization). 
        Quy trình điều phối như sau:
        1. ĐỊA CHỈ XUẤT PHÁT CỦA XE (KHO HÀNG): {starting_address}
        2. Dựa vào địa chỉ xuất phát và địa chỉ khách hàng nhận trong danh sách, hãy tự ước lượng khoảng cách (TSP) để ghép các đơn hàng nằm trên cùng tuyến đường đi, hoặc các khách hàng ở gần nhau vào cùng một chuyến xe.
        3. Phân loại đơn hàng List A (Sẵn sàng), List B (Chờ nhập buổi sáng), List C (Tạm hoãn - BẮT BUỘC BỎ QUA KHÔNG XẾP VÀO LỊCH TRÌNH).
        4. Phân tuyến giao: Nhơn Trạch, Long Thành, Mỹ Xuân - Phú Mỹ, hoặc Nội thành.
        5. Quy tắc ưu tiên phương tiện:
           - Priority 1: Nếu cùng tuyến đi giao thông suốt có >= 9 đơn (List A + B), bắt buộc gán Xe tải lớn (tai_lon).
           - Priority 2: Nếu giao lẻ tẻ, đi nhiều địa điểm cách xa nhau hoặc giao nội thành, ưu tiên Xe tải Van/Xe máy (van_xe_may).
        6. Tình huống:
           - Cùng 1 chuyến đi hãy xếp thứ tự các điểm dừng logic nhất tính từ kho xuất phát. Có thể ghi chú trong ai_strategy.
           - Nếu hàng List B (chờ nhập trưa về): Chọn các đơn cực kỳ gần kho để đi giao trước 10h sáng, sau đó quay lại kho lấy hàng.
        """
        
        system_prompt += """
        Dữ liệu đầu vào là danh sách các đơn hàng.
        TRẢ LỜI NGHIÊM NGẶT BẰNG TIẾNG VIỆT CHO TẤT CẢ GIÁ TRỊ GHI CHÚ VÀ CHIẾN LƯỢC.
        Trả về kết quả bằng ĐÚNG chuẩn JSON sau:
        {
          "schedules": [
             {
               "route": "Nhơn Trạch | Long Thành | Mỹ Xuân - Phú Mỹ | Nội Thành / Gần Công Ty | Khác",
               "vehicle_type": "tai_lon | van_xe_may",
               "order_ids": [
                 {
                   "id": 1,
                   "ai_strategy": "Sử dụng Tiếng Việt -> Giải thích độ ưu tiên / khoảng cách (vd: Đơn A gần Kho nhất (2km), Giao đơn A trước rồi qua đơn B)"
                 }
               ],
               "note": "Sử dụng Tiếng Việt -> Mô tả lộ trình di chuyển tối đa quãng đường (Ví dụ: Xe dời kho đi Giao Quận 1 -> sang Phú Nhuận -> quay về)",
               "driver_name": "Tài xế 1"
             }
          ]
        }
        Chỉ trả về chuỗi JSON hợp lệ, không có các ký tự markdown.
        """

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        # 5. Create Delivery Schedules
        schedule_ids = []
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(order_data, ensure_ascii=False)}
            ],
            "temperature": 0.2
        }

        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=90)
        if response.status_code != 200:
            raise UserError(_("Lỗi kết nối OpenAI API: %s") % response.text)

        response_data = response.json()
        gpt_content = response_data['choices'][0]['message']['content']
        
        # Clean JSON if it contains markdown code block
        gpt_content = gpt_content.strip()
        if gpt_content.startswith('```json'):
            gpt_content = gpt_content[7:]
        if gpt_content.endswith('```'):
            gpt_content = gpt_content[:-3]
        
        try:
            result_json = json.loads(gpt_content.strip())
        except Exception as e:
            raise UserError(_("OpenAI trả về định dạng JSON không hợp lệ: %s") % str(e))

        # Create records
        for sched in result_json.get('schedules', []):
            vals = {
                'date': self.date,
                'warehouse_code': warehouse_code,
                'route': sched.get('route', 'Khác'),
                'vehicle_type': sched.get('vehicle_type', 'van_xe_may'),
                'note': sched.get('note', ''),
                'driver_name': sched.get('driver_name', ''),
                'state': 'draft',
            }
            new_sched = self.env['delivery.schedule'].create(vals)
            new_sched.name = f"DC-{new_sched.id:04d}"
            schedule_ids.append(new_sched.id)
            
            # Create lines
            lines_data = []
            for o_item in sched.get('order_ids', []):
                # Find origin record
                origin_order = next((o for o in order_data if o['order_id'] == o_item['id']), None)
                if origin_order:
                    lines_data.append({
                        'schedule_id': new_sched.id,
                        'order_id': origin_order['order_id'],
                        'stock_status': origin_order['stock_status'],
                        'ai_strategy': o_item.get('ai_strategy', '')
                    })
            if lines_data:
                self.env['delivery.schedule.line'].create(lines_data)

        # 6. Save Report
        report_vals = {
            'date': self.date,
            'total_pending_orders': report_data['total_pending_orders'],
            'orders_ready_to_ship': report_data['orders_ready_to_ship'],
            'orders_backlog_text': '\n'.join(list(set(report_data['orders_backlog']))) if report_data['orders_backlog'] else 'Không có đơn nợ',
            'orders_insufficient_stock_text': '\n'.join(report_data['orders_insufficient_stock']) if report_data['orders_insufficient_stock'] else 'Không có đơn thiếu hàng'
        }
        report_rec = self.env['delivery.coordinator.report'].create(report_vals)

        # 7. Return action to view created schedules alongside report
        schedule_action = {
            'name': _('Lịch trình AI tạo'),
            'type': 'ir.actions.act_window',
            'res_model': 'delivery.schedule',
            'view_mode': 'list,form',
            'domain': [('id', 'in', schedule_ids)],
        }
        
        return {
            'name': _('Báo cáo Tổng hợp (AI Điều Phối)'),
            'type': 'ir.actions.act_window',
            'res_model': 'delivery.coordinator.report',
            'res_id': report_rec.id,
            'view_mode': 'form',
            'target': 'new',
        }
