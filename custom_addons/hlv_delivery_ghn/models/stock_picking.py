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

    @api.model
    def _get_ghn_status_map(self):
        """Map GHN status code to Vietnamese description."""
        return {
            'ready_to_pick': 'Mới tạo đơn',
            'picking': 'Nhân viên đang lấy hàng',
            'cancel': 'Hủy đơn hàng',
            'money_collect_picking': 'Đang thu tiền người gửi',
            'picked': 'Nhân viên đã lấy hàng',
            'storing': 'Hàng đang nằm ở kho',
            'transporting': 'Đang luân chuyển hàng',
            'sorting': 'Đang phân loại',
            'delivering': 'Nhân viên đang giao cho khách',
            'money_collect_delivering': 'Nhân viên đang thu tiền người nhận',
            'delivered': 'Giao hàng thành công',
            'delivery_fail': 'Giao hàng thất bại',
            'waiting_to_return': 'Chờ trả hàng',
            'return': 'Trả hàng',
            'return_transporting': 'Đang luân chuyển hàng trả',
            'return_sorting': 'Đang phân loại hàng trả',
            'returning': 'Nhân viên đang đi trả hàng',
            'return_fail': 'Trả hàng thất bại',
            'returned': 'Nhân viên trả hàng thành công',
            'exception': 'Đơn hàng ngoại lệ',
            'damage': 'Hàng bị hư hỏng',
            'lost': 'Hàng bị mất'
        }

    @api.depends('ghn_tracking_ids')
    def _compute_ghn_timeline(self):
        for record in self:
            html = '<div class="o_ghn_timeline" style="margin-left: 10px; border-left: 2px solid #ddd; padding-left: 20px;">'
            if not record.ghn_tracking_ids:
                html = '<div class="text-muted">Chưa có thông tin hành trình.</div>'
            else:
                for log in record.ghn_tracking_ids:
                    time_str = log.time_log.strftime("%d/%m/%Y %H:%M") if log.time_log else ""
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
        """Guess GHN locations and calculate dimensions based on Odoo data."""
        self.ensure_one()
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

        # 3. Try to match Ward
        # Note: Ward is harder because it's rarely a separate field in standard Odoo.
        # We might skip auto-matching ward or search in street/street2 if needed.

        # 4. Auto-calculate dimensions and weight
        weight, l, w, h = self._calculate_ghn_dimensions()

        # Set values to picking fields (assuming we might want to store them or just use them)
        # For now, let's just trigger the dimension logic inside action_open_ghn_fee_wizard logic
        # and ensure COD matches order total if 0
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
