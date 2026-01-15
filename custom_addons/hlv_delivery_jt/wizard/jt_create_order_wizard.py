# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
from odoo.exceptions import UserError
from ..utils.jt_api_utils import JTApiUtils
import hashlib
import logging

_logger = logging.getLogger(__name__)

class JTCreateOrderWizard(models.TransientModel):
    _name = "jt.create.order.wizard"
    _description = "J&T Create Order Wizard"

    picking_id = fields.Many2one('stock.picking', string="Picking", required=True)
    
    # J&T Specific Fields
    order_type = fields.Selection([
        ('1', 'Đơn bình thường'),
        ('2', 'Đơn chuyển hoàn')
    ], string="Loại đơn đặt", default='1', required=True)
    
    service_type = fields.Selection([
        ('1', 'Pickup'),
        ('6', 'Drop off')
    ], string="Loại dịch vụ", default='1', required=True)
    
    pay_type = fields.Selection([
        ('PP_PM', 'Thanh toán cuối tháng'),
        ('PP_CASH', 'Người gửi thanh toán'),
        ('CC_CASH', 'Người nhận thanh toán')
    ], string="Phương thức thanh toán", default='PP_PM', required=True)
    
    product_type = fields.Selection([
        ('EXPRESS', 'EXPRESS'),
        ('FAST', 'FAST'),
        ('SUPER', 'SUPER')
    ], string="Loại hàng hóa (Dịch vụ)", default='EXPRESS', required=True)
    
    goods_type = fields.Selection([
        ('bm000001', 'Document (bm000001)'),
        ('bm000010', 'Goods (bm000010)'),
        ('bm000011', 'Fresh (bm000011)')
    ], string="Loat hàng hóa", default='bm000010', required=True)

    delivery_type = fields.Selection([
        ('1', 'Phát bình thường'),
        ('2', 'Khách hàng tự đến lấy')
    ], string="Loại phát hàng", default='1', required=True)

    is_insured = fields.Boolean(string="Khai giá?", default=False)
    goods_value = fields.Float(string="Giá trị hàng hóa (VND)")
    cod_money = fields.Float(string="Tiền thu hộ (COD)")
    remark = fields.Text(string="Ghi chú")

    # Weight and Dimensions
    weight = fields.Float(string="Trọng lượng (kg)", default=0.1)
    length = fields.Float(string="Dài (cm)", default=10)
    width = fields.Float(string="Rộng (cm)", default=10)
    height = fields.Float(string="Cao (cm)", default=10)

    # Sender Info (Editable)
    sender_name = fields.Char(string="Tên người gửi", required=True)
    sender_mobile = fields.Char(string="SĐT người gửi", required=True)
    sender_prov = fields.Char(string="Tỉnh/Thành gửi", required=True)
    sender_city = fields.Char(string="Quận/Huyện gửi", required=True)
    sender_area = fields.Char(string="Phường/Xã gửi", required=True)
    sender_address = fields.Char(string="Địa chỉ gửi", required=True)

    # Receiver Info (Editable)
    receiver_name = fields.Char(string="Tên người nhận", required=True)
    receiver_mobile = fields.Char(string="SĐT người nhận", required=True)
    receiver_prov = fields.Char(string="Tỉnh/Thành nhận", required=True)
    receiver_city = fields.Char(string="Quận/Huyện nhận", required=True)
    receiver_area = fields.Char(string="Phường/Xã nhận", required=True)
    receiver_address = fields.Char(string="Địa chỉ nhận", required=True)

    @api.model
    def default_get(self, fields_list):
        res = super(JTCreateOrderWizard, self).default_get(fields_list)
        if self._context.get('active_id'):
            picking = self.env['stock.picking'].browse(self._context.get('active_id'))
            company = picking.company_id
            warehouse = picking.picking_type_id.warehouse_id
            
            sender_partner = warehouse.partner_id or company.partner_id
            receiver_partner = picking.partner_id

            res.update({
                'picking_id': picking.id,
                'cod_money': picking.sale_id.amount_total if (picking.sale_id and picking.sale_id.amount_total > 0) else 0.0,
                'goods_value': picking.sale_id.amount_total if (picking.sale_id and picking.sale_id.amount_total > 0) else 0.0,
                
                'sender_name': sender_partner.name or '',
                'sender_mobile': sender_partner.mobile or sender_partner.phone or '',
                'sender_prov': sender_partner.state_id.name or '',
                'sender_city': sender_partner.city or '',
                'sender_area': sender_partner.street2 or '',
                'sender_address': sender_partner.street or '',

                'receiver_name': receiver_partner.name or '',
                'receiver_mobile': receiver_partner.mobile or receiver_partner.phone or '',
                'receiver_prov': receiver_partner.state_id.name or '',
                'receiver_city': receiver_partner.city or '',
                'receiver_area': receiver_partner.street2 or '',
                'receiver_address': receiver_partner.street or '',
            })
            # Try to get weight from picking/move lines if possible
            total_weight = sum(move.product_id.weight * move.product_uom_qty for move in picking.move_ids)
            if total_weight > 0:
                res['weight'] = total_weight
        return res

    def action_create_jt_order(self):
        self.ensure_one()
        company = self.picking_id.company_id
        get_param = self.env['ir.config_parameter'].sudo().get_param
        api_account = get_param('jnt_apiAccount')
        private_key = get_param('jnt_privateKey')
        jnt_customer_code = get_param('jnt_customerCode')
        # jnt_password is the 32-char MD5 password string provided by J&T
        jnt_password = get_param('jnt_password')

        if api_account:
            api_account = api_account.strip()
        if private_key:
            private_key = private_key.strip()
        if jnt_customer_code:
            jnt_customer_code = jnt_customer_code.strip()
        if jnt_password:
            jnt_password = jnt_password.strip()

        if not api_account or not private_key or not jnt_customer_code or not jnt_password:
            raise UserError(_("Thiếu thông tin cấu hình J&T (apiAccount, privateKey, customerCode, password) trong System Parameters!"))

        _logger.info("J&T Auth Check | Account: %s | Customer: %s | Env: %s", 
                     api_account, jnt_customer_code, company.jt_environment)

        client = JTApiUtils(
            api_account=api_account,
            private_key=private_key,
            environment=company.jt_environment
        )

        # Prepare Sender Info (from current company/warehouse)
        warehouse = self.picking_id.picking_type_id.warehouse_id
        sender_partner = warehouse.partner_id or company.partner_id
        
        # Prepare Receiver Info
        receiver_partner = self.picking_id.partner_id
        if not receiver_partner:
            raise UserError(_("Vui lòng chọn khách hàng cho Phiếu xuất kho này."))

        # J&T requires prov, city, area. Odoo has state_id, city, and maybe street2 as area.
        # This will need mapping if the address structure is different.
        
        # Use the 32-char MD5 password string provided by J&T
        # Must be UPPERCASE as shown in J&T API documentation example
        password_to_send = jnt_password.upper()
        
        _logger.info("J&T Password | customerCode: %s | password: %s", jnt_customer_code, password_to_send)

        _logger.info("J&T Create Order | Account: %s | Customer: %s | Env: %s", 
                     api_account, jnt_customer_code, company.jt_environment)

        def sanitize_name(name, length=40):
            return (name or "")[:length]

        def sanitize_address(addr, length=250):
            return (addr or "")[:length]

        volumetric_weight = (self.length * self.width * self.height) / 6000.0

        # Sanitize txlogisticId (remove / to avoid potential errors)
        txlogistic_id = (self.picking_id.name or "").replace("/", "-")

        biz_params = {
            "customerCode": jnt_customer_code,
            "password": password_to_send,
            "txlogisticId": txlogistic_id,
            "orderType": str(self.order_type),
            "serviceType": str(self.service_type),
            "deliveryType": str(self.delivery_type),
            "selfAddress": 0, 
            "payType": self.pay_type,
            "productType": self.product_type,
            "goodsType": self.goods_type,
            "sender": {
                "name": sanitize_name(self.sender_name),
                "mobile": self.sender_mobile or "",
                "prov": self.sender_prov or "",
                "city": self.sender_city or "",
                "area": self.sender_area or "",
                "address": sanitize_address(self.sender_address)
            },
            "receiver": {
                "name": sanitize_name(self.receiver_name),
                "mobile": self.receiver_mobile or "",
                "prov": self.receiver_prov or "",
                "city": self.receiver_city or "",
                "area": self.receiver_area or "",
                "address": sanitize_address(self.receiver_address)
            },
            "packageInfo": {
                "weight": str(round(max(0.01, self.weight), 2)),
                "length": int(max(1, self.length)),
                "width": int(max(1, self.width)),
                "height": int(max(1, self.height)),
                "volume": str(round(volumetric_weight, 2))
            },
            "isInsured": 1 if self.is_insured else 0,
            "goodsValue": str(int(max(1, self.goods_value))),
            "codMoney": str(int(max(0, self.cod_money))) if self.pay_type == 'CC_CASH' or self.cod_money > 0 else "0",
            "remark": (self.remark or "")[:200],
            "items": [],
            "itemsValue": str(int(sum(move.product_id.list_price * move.product_uom_qty for move in self.picking_id.move_ids))),
            "totalQuantity": int(sum(move.product_uom_qty for move in self.picking_id.move_ids))
        }

        # Add items
        for move in self.picking_id.move_ids:
            biz_params["items"].append({
                "itemName": move.product_id.name[:80],
                "englishName": (move.product_id.name or "Goods")[:80],
                "number": str(int(move.product_uom_qty)),
                "itemValue": str(int(move.product_id.list_price))
            })

        _logger.info("J&T Creating Order for %s", self.picking_id.name)
        result = client.add_order(biz_params)

        if result.get('code') == '1':
            data = result.get('data', {})
            self.picking_id.write({
                'jt_bill_code': data.get('billCode'),
                'jt_sort_line': data.get('sortLine'),
                'jt_cod_fee': data.get('codFee', 0.0),
                'jt_insurance_fee': data.get('insuranceFee', 0.0),
                'jt_total_fee': data.get('inquiryFee', 0.0),
                'jt_order_status': 'Created'
            })
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Thành công',
                    'message': f'Đã tạo đơn J&T thành công! Mã vận đơn: {data.get("billCode")}',
                    'type': 'success',
                }
            }
        else:
            raise UserError(_("Lỗi từ J&T: %s") % result.get('msg', 'Unknown Error'))
