from odoo import fields, models, api
from odoo.exceptions import ValidationError
from ..utils.ghn_api_utils import GHNApiUtils
import logging
import math

_logger = logging.getLogger(__name__)

class GHNCreateOrderWizard(models.TransientModel):
    _name = "ghn.create.order.wizard"
    _description = "GHN Create Shipping Order Wizard"

    picking_id = fields.Many2one("stock.picking", string="Phiếu xuất kho", required=True)
    client_order_code = fields.Char(string="Mã đơn hàng khách", help="Sử dụng Số báo giá/Sale Order làm mã tham chiếu sang GHN")
    ghn_order_code = fields.Char(string="Mã đơn GHN")
    
    # Receiver Info
    to_name = fields.Char(string="Tên người nhận", required=True)
    to_phone = fields.Char(string="Số điện thoại", required=True)
    to_address = fields.Char(string="Địa chỉ chi tiết", required=True)
    
    province_id = fields.Many2one("ghn.province", string="Tỉnh/Thành nhận", required=True)
    district_id = fields.Many2one("ghn.district", string="Quận/Huyện nhận", required=True, 
                                domain="[('province_id', '=', province_id)]")
    ward_id = fields.Many2one("ghn.ward", string="Phường/Xã nhận", required=True,
                             domain="[('district_id', '=', district_id)]")
    
    # Package Info
    weight = fields.Integer(string="Khối lượng (gram)", default=1000)
    length = fields.Integer(string="Chiều dài (cm)", default=20)
    width = fields.Integer(string="Chiều rộng (cm)", default=20)
    height = fields.Integer(string="Chiều cao (cm)", default=20)
    
    # Payment & Service
    cod_amount = fields.Integer(string="Tiền thu hộ (COD)", default=0)
    insurance_value = fields.Integer(string="Giá trị bảo hiểm", default=0)
    
    payment_type_id = fields.Selection([
        ('1', 'Người bán trả phí'),
        ('2', 'Người mua trả phí')
    ], string="Người trả phí", default='2', required=True)
    
    required_note = fields.Selection([
        ('CHOTHUHANG', 'Cho thử hàng'),
        ('CHOXEMHANGKHONGTHU', 'Cho xem hàng không thử'),
        ('KHONGCHOXEMHANG', 'Không cho xem hàng')
    ], string="Ghi chú bắt buộc", default='KHONGCHOXEMHANG', required=True)
    
    service_type_id = fields.Selection([
        ('1', 'Dịch vụ Chuẩn (Truyền thống)'),
        ('2', 'Dịch vụ Thương mại điện tử (E-commerce)'),
        ('3', 'Dịch vụ Tiết kiệm')
    ], string="Loại dịch vụ", default='2', required=True)
    
    service_id = fields.Selection(selection='_get_service_selection', string="Dịch vụ cụ thể", required=True)
    
    def _get_service_selection(self):
        """Fetch available services from GHN based on districts."""
        return [
            ('53320', 'Chuyển phát Chuẩn'),
            ('53321', 'Chuyển phát Nhanh'),
            ('53322', 'Chuyển phát Tiết kiệm'),
            ('53325', 'Chuyển phát Tiết kiệm (Small)'),
            ('0', 'Tự động chọn')
        ]

    @api.onchange('district_id', 'service_type_id')
    def _onchange_services(self):
        """Fetch available services from GHN when district or type changes."""
        if not self.district_id:
            return
        
        # Get sender district from warehouse
        warehouse = self.picking_id.picking_type_id.warehouse_id
        from_district = warehouse.ghn_district_id.district_id if warehouse and warehouse.ghn_district_id else None
        
        if not from_district:
            return
            
        client = self._get_ghn_client()
        result = client.get_services(from_district, self.district_id.district_id)
        
        if result.get('success'):
            services = result['data']
            # Filter by service_type_id if selected
            selection = []
            selected_type = int(self.service_type_id) if self.service_type_id else 0
            for s in services:
                if s.get('service_type_id') == selected_type or not selected_type:
                    selection.append((str(s['service_id']), s['short_name'] or s['name']))
            
            if selection and self.service_id not in [s[0] for s in selection]:
                self.service_id = selection[0][0]
    
    note = fields.Text(string="Ghi chú cho shipper")
    content = fields.Char(string="Nội dung hàng hóa")

    @api.model
    def default_get(self, fields_list):
        res = super(GHNCreateOrderWizard, self).default_get(fields_list)
        picking_id = self._context.get('active_id') or self._context.get('default_picking_id')
        if picking_id:
            picking = self.env['stock.picking'].browse(picking_id)
            partner = picking.partner_id
            
            # Auto-fill receiver info
            res.update({
                'picking_id': picking.id,
                'ghn_order_code': picking.ghn_order_code,
                'client_order_code': (picking.sale_id and picking.sale_id.name) or picking.origin or picking.name,
                'to_name': partner.name or '',
                'to_phone': partner.phone or partner.mobile or '',
                'to_address': f"{partner.street or ''}, {partner.street2 or ''}".strip(', '),
                'province_id': picking.ghn_receiver_province_id.id,
                'district_id': picking.ghn_receiver_district_id.id,
                'ward_id': picking.ghn_receiver_ward_id.id,
                'payment_type_id': picking.ghn_payment_type_id or '2',
                'required_note': picking.ghn_required_note or 'KHONGCHOXEMHANG',
                'cod_amount': picking.ghn_cod_amount,
                'insurance_value': picking.ghn_insurance_value,
                'service_id': str(picking.ghn_service_id or 0),
                'service_type_id': str(picking.ghn_service_type_id or 2),
                'note': picking.ghn_shipping_notes or 'Giao hàng',
                'content': f"Đơn hàng {picking.name}",
            })
            
            # Dimensions & Weight using default logic first
            weight, l, w, h = picking._calculate_ghn_dimensions()
            res.update({
                'weight': weight,
                'length': l,
                'width': w,
                'height': h,
            })

            # Check if this is an update, if so fetch data from GHN
            if picking.ghn_order_code:
                try:
                    company = picking.company_id
                    client = GHNApiUtils(
                        token=company.ghn_api_token,
                        shop_id=company.ghn_shop_id,
                        environment=company.ghn_environment
                    )
                    api_res = client.get_order_detail(picking.ghn_order_code)
                    if api_res.get('success'):
                        data = api_res.get('data')
                        # Map API data back to wizard fields
                        if data.get('to_name'): res['to_name'] = data.get('to_name')
                        if data.get('to_phone'): res['to_phone'] = data.get('to_phone')
                        if data.get('to_address'): res['to_address'] = data.get('to_address')
                        
                        # Note: GHN API might return IDs that don't match our local DB if not synced, 
                        # but we try our best. For now we trust Odoo's location mapping unless we want to do heavy reverse lookup.
                        # Mapping basic fields that are safe:
                        if data.get('note'): res['note'] = data.get('note')
                        if data.get('required_note'): res['required_note'] = data.get('required_note')
                        if data.get('payment_type_id'): res['payment_type_id'] = str(data.get('payment_type_id'))
                        if data.get('service_type_id'): res['service_type_id'] = str(data.get('service_type_id'))
                        if data.get('service_id'): res['service_id'] = str(data.get('service_id'))
                        
                        if data.get('weight'): res['weight'] = data.get('weight')
                        if data.get('length'): res['length'] = data.get('length')
                        if data.get('width'): res['width'] = data.get('width')
                        if data.get('height'): res['height'] = data.get('height')
                        
                        if data.get('cod_amount') is not None: res['cod_amount'] = data.get('cod_amount')
                        if data.get('insurance_value') is not None: res['insurance_value'] = data.get('insurance_value')
                        
                except Exception as e:
                    _logger.warning("Failed to fetch GHN Order Details for %s: %s", picking.ghn_order_code, e)
            
        return res

    def _get_ghn_client(self):
        company = self.env.company
        warehouse = self.picking_id.picking_type_id.warehouse_id
        is_heavy = self.weight > 10000
        
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

    def action_confirm(self):
        self.ensure_one()
        client = self._get_ghn_client()
        picking = self.picking_id
        
        # Prepare items
        items = []
        for move in picking.move_ids_without_package:
            product = move.product_id
            items.append({
                "name": product.name[:100],
                "code": product.default_code or str(product.id),
                "quantity": int(move.product_uom_qty),
                "price": int(product.lst_price or 0),
                "weight": int((product.weight or 0) * 1000) or 100,
                "length": int(product.product_length or 10),
                "width": int(product.product_width or 10),
                "height": int(product.product_height or 10),
                "category": {"level1": "Hàng tiêu dùng"}
            })

        warehouse = picking.picking_type_id.warehouse_id
        payload = {
            "payment_type_id": int(self.payment_type_id),
            "note": str(self.note or "Giao hàng"),
            "required_note": str(self.required_note),
            "to_name": str(self.to_name),
            "to_phone": str(self.to_phone),
            "to_address": str(self.to_address),
            "to_ward_code": str(self.ward_id.ward_code),
            "to_district_id": int(self.district_id.district_id),
            "cod_amount": int(self.cod_amount),
            "content": str(self.content or f"Đơn hàng {picking.name}"),
            "weight": int(self.weight),
            "length": int(self.length),
            "width": int(self.width),
            "height": int(self.height),
            "insurance_value": int(self.insurance_value),
            "service_id": int(self.service_id),
            "service_type_id": int(self.service_type_id),
            "items": items,
            "client_order_code": str(self.client_order_code or picking.name)
        }

        # Sender Info
        if warehouse:
            if warehouse.ghn_province_id: payload["from_province_name"] = str(warehouse.ghn_province_id.name)
            if warehouse.ghn_district_id: payload["from_district_name"] = str(warehouse.ghn_district_id.name)
            if warehouse.ghn_ward_id: payload["from_ward_name"] = str(warehouse.ghn_ward_id.name)
            if warehouse.partner_id:
                payload["from_name"] = str(warehouse.partner_id.name)
                payload["from_phone"] = str(warehouse.partner_id.phone or warehouse.partner_id.mobile or '')
                payload["from_address"] = str(f"{warehouse.partner_id.street or ''}, {warehouse.partner_id.street2 or ''}")
            else:
                payload["from_name"] = str(picking.company_id.name)
                payload["from_phone"] = str(picking.company_id.phone or '')
                payload["from_address"] = str(f"{picking.company_id.street or ''}, {picking.company_id.street2 or ''}")

        if self.ghn_order_code:
            payload["order_code"] = self.ghn_order_code
            result = client.update_order(payload)
            action_type = "Cập nhật"
        else:
            result = client.create_order(payload)
            action_type = "Tạo"

        if result.get("success"):
            data = result["data"]
            # Convert ISO 8601 (2026-01-15T16:59:59Z) to Odoo format (2026-01-15 16:59:59)
            # Note: Update API might not return expected_delivery_time or total_fee depending on what changed
            vals = {
                "ghn_order_status": "ready_to_pick"
            }
            
            if data:
                if data.get("order_code"): vals["ghn_order_code"] = data.get("order_code")
                if data.get("total_fee"): vals["ghn_total_fee"] = data.get("total_fee")
                
                expected_time = data.get("expected_delivery_time")
                if expected_time and isinstance(expected_time, str):
                    expected_time = expected_time.replace('T', ' ').replace('Z', '')
                    vals["ghn_expected_delivery_time"] = expected_time
            
            picking.write(vals)
            
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Thành công',
                    'message': f'Đã {action_type} đơn GHN thành công!',
                    'sticky': False,
                    'type': 'success',
                }
            }
        else:
            raise ValidationError(f"Lỗi từ GHN: {result.get('error')}")
