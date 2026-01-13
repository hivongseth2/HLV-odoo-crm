from odoo import models, api, fields
from odoo.exceptions import ValidationError, UserError
from ..utils.ghn_api_utils import GHNApiUtils

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

    @api.onchange('ghn_receiver_district_id')
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
        total_weight = 0
        p_length = 0
        p_width = 0
        p_height = 0
        
        for move in self.move_ids_without_package:
            product = move.product_id
            total_weight += (product.weight or 0) * move.product_uom_qty
            p_length = max(p_length, product.product_length or 0)
            p_width = max(p_width, product.product_width or 0)
            p_height += (product.product_height or 0) * move.product_uom_qty

        # Set values to picking fields (assuming we might want to store them or just use them)
        # For now, let's just trigger the dimension logic inside action_open_ghn_fee_wizard logic
        # and ensure COD matches order total if 0
        if self.ghn_cod_amount == 0 and self.sale_id:
            self.ghn_cod_amount = int(self.sale_id.amount_total)
            
        return True

    def action_open_ghn_fee_wizard(self):
        self.ensure_one()
        # Ensure latest dimensions are mapped
        total_weight = 0
        p_length = 0
        p_width = 0
        p_height = 0
        
        for move in self.move_ids_without_package:
            product = move.product_id
            total_weight += (product.weight or 0) * move.product_uom_qty
            p_length = max(p_length, product.product_length or 0)
            p_width = max(p_width, product.product_width or 0)
            p_height += (product.product_height or 0) * move.product_uom_qty

        total_weight = total_weight * 1000 # Convert KG to Grams
        if total_weight == 0: total_weight = 1000
        if p_length == 0: p_length = 20
        if p_width == 0: p_width = 20
        if p_height == 0: p_height = 20
            
        return {
            "name": "Tính cước GHN",
            "type": "ir.actions.act_window",
            "res_model": "ghn.fee.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_picking_id": self.id,
                "default_weight": int(total_weight),
                "default_length": int(p_length),
                "default_width": int(p_width),
                "default_height": int(p_height),
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
