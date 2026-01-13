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

    def action_open_ghn_fee_wizard(self):
        self.ensure_one()
        # Calculate total weight and dimensions
        total_weight = 0
        p_length = 0
        p_width = 0
        p_height = 0
        
        for move in self.move_ids_without_package:
            product = move.product_id
            total_weight += (product.weight or 0) * move.product_uom_qty
            
            # Aggregate dimensions (Sum height, max length/width)
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

    def _get_ghn_client(self):
        company = self.env.company
        warehouse = self.picking_type_id.warehouse_id
        
        # Calculate total weight to decide Shop ID
        total_weight = sum((move.product_id.weight or 0) * move.product_uom_qty for move in self.move_ids_without_package) * 1000
        is_heavy = total_weight > 10000
        
        shop_id = company.ghn_shop_id
        if is_heavy:
            shop_id = (warehouse and warehouse.ghn_shop_id_heavy) or company.ghn_shop_id_heavy or shop_id
        else:
            shop_id = (warehouse and warehouse.ghn_shop_id) or company.ghn_shop_id
            
        return GHNApiUtils(
            token=company.ghn_api_token,
            shop_id=shop_id,
            environment=company.ghn_environment
        )

    def action_create_ghn_order(self):
        self.ensure_one()
        client = self._get_ghn_client()
        
        # Validation
        if not self.ghn_receiver_province_id or not self.ghn_receiver_district_id or not self.ghn_receiver_ward_id:
            raise ValidationError("Vui lòng điền đầy đủ thông tin địa chỉ nhận (Tỉnh/Huyện/Xã) của GHN.")
        
        if not self.partner_id.phone:
            raise ValidationError("Vui lòng điền số điện thoại của khách hàng.")

        # Prepare items
        items = []
        total_weight = 0
        p_length = 0
        p_width = 0
        p_height = 0
        
        for move in self.move_ids_without_package:
            product = move.product_id
            weight = int((product.weight or 0) * 1000) or 100 # Default 100g if 0
            qty = int(move.product_uom_qty)
            
            items.append({
                "name": product.name[:100],
                "code": product.default_code or str(product.id),
                "quantity": qty,
                "price": int(product.lst_price),
                "weight": weight,
                "length": int(product.product_length or 10),
                "width": int(product.product_width or 10),
                "height": int(product.product_height or 10),
            })
            
            total_weight += weight * qty
            p_length = max(p_length, int(product.product_length or 10))
            p_width = max(p_width, int(product.product_width or 10))
            p_height += int(product.product_height or 10) * qty

        # Fallback values
        if total_weight == 0: total_weight = 1000
        if p_length == 0: p_length = 20
        if p_width == 0: p_width = 20
        if p_height == 0: p_height = 20

        warehouse = self.picking_type_id.warehouse_id
        
        payload = {
            "payment_type_id": int(self.ghn_payment_type_id),
            "note": self.ghn_shipping_notes or "Giao hàng",
            "required_note": self.ghn_required_note,
            "to_name": self.partner_id.name,
            "to_phone": self.partner_id.phone,
            "to_address": f"{self.partner_id.street or ''}, {self.partner_id.street2 or ''}",
            "to_ward_code": self.ghn_receiver_ward_id.ward_code,
            "to_district_id": self.ghn_receiver_district_id.district_id,
            "cod_amount": self.ghn_cod_amount,
            "content": f"Đơn hàng {self.name}",
            "weight": int(total_weight),
            "length": int(p_length),
            "width": int(p_width),
            "height": int(p_height),
            "insurance_value": self.ghn_insurance_value,
            "service_id": int(self.ghn_service_id),
            "service_type_id": int(self.ghn_service_type_id),
            "items": items,
            "client_order_code": self.name
        }

        # Sender Info from Warehouse if available
        if warehouse:
            if warehouse.ghn_province_id: payload["from_province_name"] = warehouse.ghn_province_id.name
            if warehouse.ghn_district_id: payload["from_district_name"] = warehouse.ghn_district_id.name
            if warehouse.ghn_ward_id: payload["from_ward_name"] = warehouse.ghn_ward_id.name
            # If warehouse has a partner address, use it
            if warehouse.partner_id:
                payload["from_name"] = warehouse.partner_id.name
                payload["from_phone"] = warehouse.partner_id.phone or warehouse.partner_id.mobile
                payload["from_address"] = f"{warehouse.partner_id.street or ''}, {warehouse.partner_id.street2 or ''}"

        result = client.create_order(payload)
        if result.get("success"):
            data = result["data"]
            self.write({
                "ghn_order_code": data.get("order_code"),
                "ghn_total_fee": data.get("total_fee"),
                "ghn_expected_delivery_time": data.get("expected_delivery_time"),
                "ghn_order_status": "ready_to_pick" # GHN initial status
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Thành công',
                    'message': f'Đã tạo đơn GHN: {data.get("order_code")}',
                    'sticky': False,
                    'type': 'success',
                }
            }
        else:
            raise ValidationError(f"Lỗi từ GHN: {result.get('error')}")
