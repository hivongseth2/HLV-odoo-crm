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
        pending_orders = orders.filtered(lambda o: not all(l.qty_delivered >= l.product_uom_qty for l in o.order_line if l.product_id.type == 'product'))

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

        for order in pending_orders:
            # Determine List A/B/C simplified logic
            is_ready = True
            is_waiting = False
            for line in order.order_line:
                if line.product_id.type == 'product':
                    if line.product_id.qty_available < (line.product_uom_qty - line.qty_delivered):
                        is_ready = False
                        if line.product_id.incoming_qty > 0:
                            is_waiting = True
            
            list_status = "List A (Sẵn sàng)"
            if not is_ready:
                if is_waiting:
                    list_status = "List B (Chờ nhập)"
                else:
                    list_status = "List C (Tạm hoãn)"
            
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
                'commitment_date': str(order.commitment_date.date()) if order.commitment_date else 'Unknown'
            })

        if not order_data:
            raise UserError(_("Tất cả đơn hàng đang chờ (nếu có) đều không đủ tồn kho để giao. Vui lòng kiểm tra lại."))


        # 4. Prepare GPT prompt
        system_prompt = """
        Bạn là hệ thống điều phối giao hàng (AI Coordinator). 
        Quy trình điều phối như sau:
        1. Phân loại đơn hàng List A (Sẵn sàng), List B (Chờ nhập buổi sáng), List C (Tạm hoãn - bỏ qua không xếp lịch).
        2. Phân tuyến giao: Nhơn Trạch, Long Thành, Mỹ Xuân - Phú Mỹ, hoặc Nội thành.
        3. Quy tắc ưu tiên:
           - Priority 1: Nếu cùng tuyến có >= 9 đơn (List A + B), ưu tiên xếp giao ngay theo tuyến đó. Xe tải lớn (tai_lon) nếu full tuyến.
           - Priority 2: Xe tải Van/Xe máy (van_xe_may) cho đơn lẻ hoặc gần nội thành.
        4. Tình huống:
           - Thiếu đơn (<9) cho 1 tuyến xa: chờ gom hoặc chuyển đi lẻ gần công ty trước.
           - Hàng về trưa (List B): Chọn 3 địa điểm gần công ty nhất cho tài xế đi giao sớm và quay lại 10h để lấy hàng đóng gói (early_trip). Sau 10h chia ca chiều.
           - Quá tải: tải lớn đi xa, xe máy/van xử lý gần.
        
        Dữ liệu đầu vào là danh sách các đơn hàng (với id, địa chỉ, List status).
        Trả về kết quả bằng ĐÚNG chuẩn JSON sau:
        {
          "schedules": [
             {
               "route": "nhon_trach | long_thanh | my_xuan_phu_my | noi_thanh | khac",
               "vehicle_type": "tai_lon | van_xe_may",
               "order_ids": [1, 2, ...],
               "note": "Giải thích tóm tắt quyết định của bạn đối với chuyến đi này (vd: early trip cho List B, full line route...)",
               "driver_name": "Tài xế 1 (hoặc dặn dò hỗ trợ)"
             }, ...
          ]
        }
        Chỉ trả về chuỗi JSON hợp lệ, không có các ký tự markdown bao bọc như ```json hoặc phản hồi khác.
        """

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(order_data, ensure_ascii=False)}
            ],
            "temperature": 0.2
        }

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }

        response = requests.post("https://api.openai.com/v1/chat/completions", headers=headers, json=payload, timeout=60)
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

        # 5. Create Delivery Schedules
        schedule_ids = []
        for sched in result_json.get('schedules', []):
            vals = {
                'date': self.date,
                'route': sched.get('route', 'khac'),
                'vehicle_type': sched.get('vehicle_type', 'van_xe_may'),
                'sale_order_ids': [(6, 0, sched.get('order_ids', []))],
                'note': sched.get('note', ''),
                'driver_name': sched.get('driver_name', ''),
                'state': 'draft',
            }
            new_sched = self.env['delivery.schedule'].create(vals)
            new_sched.name = f"DC-{new_sched.id:04d}"
            schedule_ids.append(new_sched.id)

        # 6. Return action to view created schedules
        return {
            'name': _('Lịch trình AI tạo'),
            'type': 'ir.actions.act_window',
            'res_model': 'delivery.schedule',
            'view_mode': 'list,form',
            'domain': [('id', 'in', schedule_ids)],
        }
