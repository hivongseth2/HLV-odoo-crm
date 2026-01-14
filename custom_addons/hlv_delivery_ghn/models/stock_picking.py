from odoo import models, api, fields
from odoo.exceptions import ValidationError, UserError
from ..utils.ghn_api_utils import GHNApiUtils
import math

class StockPicking(models.Model):
    _inherit = "stock.picking"

    ghn_order_code = fields.Char(string="Mã đơn GHN", readonly=True, copy=False)
    ghn_order_status = fields.Char(string="Trạng thái GHN", readonly=True, copy=False)
    ghn_total_fee = fields.Float(string="Phí vận chuyển GHN", readonly=True, copy=False)
    ghn_expected_delivery_time = fields.Datetime(string="Ngày giao dự kiến (GHN)", readonly=True, copy=False)
    
    ghn_required_note = fields.Selection([
        ('CHOTHUHANG', 'Cho thử hàng'),
        ('CHOXEMHANGKHONGTHU', 'Cho xem hàng không thử'),
        ('KHONGCHOXEMHANG', 'Không cho xem hàng')
    ], string="Ghi chú bắt buộc", default='KHONGCHOXEMHANG')
    
    ghn_payment_type_id = fields.Selection([
        ('1', 'Người bán trả phí'),
        ('2', 'Người mua trả phí')
    ], string="Người trả phí", default='2')

    ghn_shipping_notes = fields.Text(string="Ghi chú vận chuyển")
    ghn_insurance_value = fields.Integer(string="Giá trị bảo hiểm (VNĐ)")
    ghn_cod_amount = fields.Integer(string="Tiền thu hộ COD (VNĐ)")

    ghn_receiver_province_id = fields.Many2one("ghn.province", string="Tỉnh/Thành nhận (GHN)")
    ghn_receiver_district_id = fields.Many2one("ghn.district", string="Quận/Huyện nhận (GHN)",
                                              domain="[('province_id', '=', ghn_receiver_province_id)]")
    ghn_receiver_ward_id = fields.Many2one("ghn.ward", string="Phường/Xã nhận (GHN)",
                                            domain="[('district_id', '=', ghn_receiver_district_id)]")
    
    ghn_service_id = fields.Integer(string="Mã dịch vụ GHN", default=0)
    ghn_service_type_id = fields.Integer(string="Mã loại dịch vụ GHN", default=2)

    ghn_tracking_ids = fields.One2many("ghn.tracking.log", "picking_id", string="Lịch sử hành trình")
    ghn_tracking_timeline = fields.Html(string="Hành trình đơn hàng", compute="_compute_ghn_timeline")
    
    ghn_order_status_display = fields.Char(string="Trạng thái GHN (VN)", compute="_compute_ghn_status_display", store=False)

    @api.depends('ghn_order_status')
    def _compute_ghn_status_display(self):
        status_map = self._get_ghn_status_map()
        for record in self:
            record.ghn_order_status_display = status_map.get(record.ghn_order_status, record.ghn_order_status)

    @api.model
    def _get_ghn_status_map(self):
        """Map GHN status code to Vietnamese description."""
        return {
            'ready_to_pick': 'Chờ lấy hàng',
            'picking': 'Đang lấy hàng',
            'cancel': 'Đơn hủy',
            'money_collect_picking': 'Đang tương tác với người gửi',
            'picked': 'Lấy hàng thành công',
            'storing': 'Nhập kho',
            'transporting': 'Đang trung chuyển',
            'sorting': 'Đang phân loại',
            'delivering': 'Đang giao hàng',
            'money_collect_delivering': 'Đang tương tác với người nhận',
            'delivered': 'Giao hàng thành công',
            'delivery_fail': 'Giao hàng không thành công',
            'waiting_to_return': 'Chờ xác nhận giao lại',
            'return': 'Chuyển hoàn',
            'return_transporting': 'Đang trung chuyển hàng hoàn',
            'return_sorting': 'Đang phân loại hàng hoàn',
            'returning': 'Đang hoàn hàng',
            'return_fail': 'Hoàn hàng không thành công',
            'returned': 'Hoàn hàng thành công',
            'exception': 'Đơn hàng ngoại lệ',
            'damage': 'Đơn hàng bị hư hỏng',
            'lost': 'Đơn hàng thất lạc'
        }

    @api.depends('ghn_tracking_ids')
    def _compute_ghn_timeline(self):
        for record in self:
            html = '<div class="o_ghn_timeline" style="margin-left: 10px; border-left: 2px solid #ddd; padding-left: 20px;">'
            if not record.ghn_tracking_ids:
                html = '<div class="text-muted">Chưa có thông tin hành trình.</div>'
            else:
                user_tz = self.env.user.tz or 'Asia/Ho_Chi_Minh'
                import pytz
                for log in record.ghn_tracking_ids:
                    time_str = ""
                    if log.time_log:
                        # Convert UTC to User TZ (or VN default)
                        try:
                            utc = pytz.UTC
                            dest_tz = pytz.timezone(user_tz)
                            # time_log is naive UTC in Odoo
                            local_dt = utc.localize(log.time_log).astimezone(dest_tz)
                            time_str = local_dt.strftime("%d/%m/%Y %H:%M")
                        except:
                            time_str = log.time_log.strftime("%d/%m/%Y %H:%M") # Fallback
                    status_vn = log.status_name or log.status_code
                    desc = log.description or ""
                    
                    # Color based on status keyword
                    color = "#17a2b8" # Info blue
                    if 'delivered' in (log.status_code or ''): color = "#28a745" # Success
                    elif 'cancel' in (log.status_code or ''): color = "#dc3545" # Danger
                    elif 'fail' in (log.status_code or ''): color = "#dc3545"
                    elif 'pick' in (log.status_code or ''): color = "#ffc107" # Warning
                    
                    html += f'''
                    <div style="position: relative; margin-bottom: 20px;">
                        <div style="position: absolute; left: -26px; top: 0; width: 12px; height: 12px; border-radius: 50%; background: {color}; border: 2px solid white; box-shadow: 0 0 0 1px {color};"></div>
                        <div style="font-weight: bold; color: {color}">{status_vn} <span style="font-weight: normal; color: #666; font-size: 0.9em;">- {time_str}</span></div>
                        <div style="font-size: 0.9em; color: #333; margin-top: 4px;">{desc}</div>
                    </div>
                    '''
            
            html += '</div>'
            record.ghn_tracking_timeline = html
    def _onchange_ghn_receiver_district_id(self):
        """Fetch wards from GHN when receiver district changes."""
        if not self.ghn_receiver_district_id:
            return
        
        company = self.env.company
        client = GHNApiUtils(
            token=company.ghn_api_token,
            shop_id=company.ghn_shop_id,
            environment=company.ghn_environment
        )
        
        wards = client.get_wards(self.ghn_receiver_district_id.district_id)
        WardModel = self.env['ghn.ward']
        for w in wards:
            exist = WardModel.search([
                ('ward_code', '=', w['WardCode']),
                ('district_id', '=', self.ghn_receiver_district_id.id)
            ], limit=1)
            if not exist:
                WardModel.create({
                    'ward_code': w['WardCode'],
                    'name': w['WardName'],
                    'district_id': self.ghn_receiver_district_id.id
                })

    def _calculate_ghn_dimensions(self):
        """
        Estimate parcel dimensions using a Cubic Box approximation.
        This avoids 'tower' shapes by distributing volume into a balanced box.
        """
        total_weight = 0
        total_volume = 0
        max_l = max_w = max_h = 0
        
        for move in self.move_ids_without_package:
            product = move.product_id
            qty = move.product_uom_qty
            l = product.product_length or 10
            w = product.product_width or 10
            h = product.product_height or 10
            weight = product.weight or 0.1 # 100g
            
            total_weight += weight * qty * 1000 # to gram
            total_volume += (l * w * h) * qty
            max_l = max(max_l, l)
            max_w = max(max_w, w)
            max_h = max(max_h, h)

        if total_volume <= 0:
            return 1000, 20, 20, 20
            
        # Apply Packing Efficiency Factor (Buffer for void space)
        # Rigid items don't pack 100% efficiently. We add 30% buffer.
        buffered_volume = total_volume * 1.3
            
        # Cubic Box Approximation
        ideal_side = buffered_volume ** (1/3.0)
        final_l = max(max_l, ideal_side)
        final_w = max(max_w, ideal_side)
        
        # Calculate height from buffered volume
        final_h = buffered_volume / (final_l * final_w)
        final_h = max(max_h, final_h)
        
        return int(total_weight), math.ceil(final_l), math.ceil(final_w), math.ceil(final_h)

    def action_ghn_auto_fill_info(self):
        """
        - If Order Code exists: Sync status, fees, timeline from GHN API.
        - If No Order Code: Guess locations and calculate dimensions from Odoo data.
        """
        self.ensure_one()
        
        # --- CASE 1: Sync Live Data from GHN ---
        if self.ghn_order_code:
            company = self.company_id or self.env.company
            client = GHNApiUtils(
                token=company.ghn_api_token,
                shop_id=company.ghn_shop_id,
                environment=company.ghn_environment
            )
            result = client.get_order_detail(self.ghn_order_code)
            
            if result.get("success"):
                data = result.get("data", {})
                if not data: return True
                
                vals = {}
                if data.get("status"):
                    vals["ghn_order_status"] = data.get("status")
                if data.get("total_fee"):
                    vals["ghn_total_fee"] = data.get("total_fee")
                if data.get("cod_amount"):
                    vals["ghn_cod_amount"] = data.get("cod_amount")
                
                expected_time = data.get("expected_delivery_time")
                if expected_time and isinstance(expected_time, str):
                    try:
                        expected_time = expected_time.replace('T', ' ').replace('Z', '')
                        vals["ghn_expected_delivery_time"] = expected_time
                    except: pass
                
                # Update fields
                if vals:
                    self.write(vals)
                
                # Sync Timeline/Logs
                logs = data.get("log") or []
                if logs:
                    # Clear old logs to avoid duplicates or merge? 
                    # Re-creating is safer to ensure order/updates. 
                    # But if we rely on webhook, we might duplicate. 
                    # Strategy: Check if log exists by timestamp + status, formatted safely.
                    
                    TrackingModel = self.env['ghn.tracking.log']
                    status_map = self._get_ghn_status_map()
                    
                    for l in logs:
                        status_code = l.get("status")
                        updated_date = l.get("updated_date") # "2021-11-11T03:52:50.158Z"
                        
                        log_time = fields.Datetime.now()
                        if updated_date:
                            try:
                                t_str = updated_date.replace('T', ' ').replace('Z', '').split('.')[0]
                                log_time = fields.Datetime.from_string(t_str)
                            except: pass
                            
                        # Check exist
                        exist = TrackingModel.search([
                            ('picking_id', '=', self.id),
                            ('status_code', '=', status_code),
                            ('time_log', '=', log_time)
                        ], limit=1)
                        
                        if not exist:
                            status_vn = status_map.get(status_code, status_code)
                            TrackingModel.create({
                                'picking_id': self.id,
                                'status_code': status_code,
                                'status_name': status_vn,
                                'description': l.get("payment_type_ids") or "Cập nhật từ hệ thống GHN", # Log info is sparse in API usually
                                'time_log': log_time
                            })
                            
                self.message_post(body="Đã đồng bộ thông tin mới nhất từ GHN.")
                return {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                }
            else:
                 raise ValidationError(f"Không lấy được thông tin từ GHN: {result.get('error')}")

        # --- CASE 2: Guess Local Data (If not yet created) ---
        partner = self.partner_id
        if not partner:
            return

        # 1. Try to match Province
        if not self.ghn_receiver_province_id and partner.state_id:
            province = self.env['ghn.province'].search([
                ('name', 'ilike', partner.state_id.name)
            ], limit=1)
            if province:
                self.ghn_receiver_province_id = province

        # 2. Try to match District
        if self.ghn_receiver_province_id and not self.ghn_receiver_district_id and partner.city:
            district = self.env['ghn.district'].search([
                ('province_id', '=', self.ghn_receiver_province_id.id),
                ('name', 'ilike', partner.city)
            ], limit=1)
            if district:
                self.ghn_receiver_district_id = district

        # 3. Auto-calculate dimensions and weight (Refresh)
        weight, l, w, h = self._calculate_ghn_dimensions()

        if self.ghn_cod_amount == 0 and self.sale_id:
            self.ghn_cod_amount = int(self.sale_id.amount_total)
            
        return True

    def action_open_ghn_fee_wizard(self):
        self.ensure_one()
        # Ensure latest dimensions are mapped
        weight, l, w, h = self._calculate_ghn_dimensions()
            
        return {
            "name": "Tính cước GHN",
            "type": "ir.actions.act_window",
            "res_model": "ghn.fee.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_picking_id": self.id,
                "default_weight": int(weight),
                "default_length": int(l),
                "default_width": int(w),
                "default_height": int(h),
                "default_province_id": self.ghn_receiver_province_id.id,
                "default_district_id": self.ghn_receiver_district_id.id,
                "default_ward_id": self.ghn_receiver_ward_id.id,
                "default_cod_value": self.ghn_cod_amount,
                "default_insurance_value": self.ghn_insurance_value,
            }
        }

    def action_create_ghn_order(self):
        """Open the wizard to review and create GHN order."""
        self.ensure_one()
        # Initial auto-fill if nothing mapped yet
        if not self.ghn_receiver_province_id:
            self.action_ghn_auto_fill_info()
            
        return {
            "name": "Kiểm tra và Tạo đơn GHN",
            "type": "ir.actions.act_window",
            "res_model": "ghn.create.order.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_picking_id": self.id,
            }
        }
