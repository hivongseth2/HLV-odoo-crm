# -*- coding: utf-8 -*-
from odoo import fields, models, api, _
from odoo.exceptions import UserError, ValidationError
from ..utils.jt_api_utils import JTApiUtils
from markupsafe import Markup
import hashlib
import logging

_logger = logging.getLogger(__name__)

class JTCreateOrderWizard(models.TransientModel):
    _name = "jt.create.order.wizard"
    _description = "J&T Create Order Wizard"

    picking_id = fields.Many2one('stock.picking', string="Picking", required=True)
    warehouse_id = fields.Many2one('stock.warehouse', string="Kho hàng", related='picking_id.picking_type_id.warehouse_id', readonly=True)
    
    # J&T Specific Fields
    order_type = fields.Selection([
        ('1', 'Đơn bình thường'),
        ('2', 'Đơn chuyển hoàn')
    ], string="Loại đơn đặt", default='1', required=True)
    
    service_type = fields.Selection([
        ('1', 'Lấy hàng tận nơi (Pickup)'),
        ('6', 'Gửi hàng tại bưu cục (Drop off)')
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
        ('bm000001', 'Tài liệu (bm000001)'),
        ('bm000010', 'Hàng hóa (bm000010)'),
        ('bm000011', 'Đồ tươi sống (bm000011)')
    ], string="Loại hàng hóa", default='bm000010', required=True)

    delivery_type = fields.Selection([
        ('1', 'Phát bình thường'),
        ('2', 'Khách hàng tự đến lấy')
    ], string="Loại phát hàng", default='1', required=True)

    is_insured = fields.Boolean(string="Khai giá?", default=False)
    goods_value = fields.Float(string="Giá trị hàng hóa (VND)")
    cod_money = fields.Float(string="Tiền thu hộ (COD)")
    remark = fields.Text(string="Ghi chú")

    part_sign = fields.Boolean(string="Ký nhận một phần?", help="0: ký nhận toàn phần, 1: ký nhận một phần")

    # Note Checkboxes
    note_thu_hang = fields.Boolean(string="Cho khách thử hàng")
    note_xem_hang_khong_thu = fields.Boolean(string="Cho khách xem hàng, không cho thử")
    note_de_vo = fields.Boolean(string="Hàng dễ vỡ, vui lòng nhẹ tay")
    note_giao_hang_mot_phan = fields.Boolean(string="Giao hàng một phần, nhận lại sản phẩm từ khách")
    note_khong_giao_duoc_lh = fields.Boolean(string="Không giao được liên hệ SĐT shop, không tự ý hủy đơn")
    # Package Quantity Control
    manual_package_qty = fields.Integer(string="Số lượng kiện hàng", compute='_compute_manual_package_qty', store=True, readonly=False, help="Nhập số lượng kiện hàng thực tế. Nếu để 0, hệ thống sẽ tự động tính toán.")
    
    @api.depends('picking_id', 'picking_id.move_line_ids', 'picking_id.move_line_ids.result_package_id')
    def _compute_manual_package_qty(self):
        for rec in self:
            if rec.picking_id:
                # Count unique packages
                package_ids = rec.picking_id.move_line_ids.mapped('result_package_id')
                rec.manual_package_qty = len(package_ids) if package_ids else 1
            else:
                rec.manual_package_qty = 1
    note_goi_dien_truoc_khi_giao = fields.Boolean(string="Gọi điện thoại cho khách trước khi giao")
    note_giao_gio_hanh_chinh = fields.Boolean(string="Giao hàng vào giờ hành chính")
    note_khong_cho_xem = fields.Boolean(string="Không cho xem hàng")
    note_khac = fields.Boolean(string="Khác")
    note_khac_input = fields.Char(string="Nội dung khác")

    @api.onchange('note_thu_hang', 'note_xem_hang_khong_thu', 'note_de_vo', 
                 'note_giao_hang_mot_phan', 'note_khong_giao_duoc_lh', 
                 'note_goi_dien_truoc_khi_giao', 'note_giao_gio_hanh_chinh', 
                 'note_khong_cho_xem', 'note_khac', 'note_khac_input')
    def _onchange_note_selections(self):
        notes = []
        if self.note_thu_hang:
            notes.append("Cho khách thử hàng")
        if self.note_xem_hang_khong_thu:
            notes.append("Cho khách xem hàng, không cho thử")
        if self.note_de_vo:
            notes.append("Hàng dễ vỡ, vui lòng nhẹ tay")
        if self.note_giao_hang_mot_phan:
            notes.append("Giao hàng một phần, nhận lại sản phẩm từ khách")
        if self.note_khong_giao_duoc_lh:
            notes.append("Không giao được liên hệ SĐT shop, không tự ý hủy đơn")
        if self.note_goi_dien_truoc_khi_giao:
            notes.append("Gọi điện thoại cho khách trước khi giao")
        if self.note_giao_gio_hanh_chinh:
            notes.append("Giao hàng vào giờ hành chính")
        if self.note_khong_cho_xem:
            notes.append("Không cho xem hàng")
        
        if self.note_khac and self.note_khac_input:
            notes.append(self.note_khac_input)
            
        self.remark = ", ".join(notes)

    # Weight and Dimensions
    weight = fields.Float(string="Trọng lượng (kg)", default=0.1)
    length = fields.Float(string="Dài (cm)", default=10)
    width = fields.Float(string="Rộng (cm)", default=10)
    height = fields.Float(string="Cao (cm)", default=10)

    # Fee Calculation
    estimated_fee = fields.Float(string="Phí vận chuyển dự kiến (VND)", readonly=True)
    estimated_cod_fee = fields.Float(string="Phí COD dự kiến (VND)", readonly=True)
    estimated_insurance_fee = fields.Float(string="Phí bảo hiểm dự kiến (VND)", readonly=True)

    currency_id = fields.Many2one('res.currency', string='Tiền tệ', default=lambda self: self.env.company.currency_id)
    product_html = fields.Html(compute='_compute_product_html', string="Danh sách sản phẩm", sanitize=False, readonly=True)

    @api.depends('picking_id', 'picking_id.move_ids_without_package')
    def _compute_product_html(self):
        for rec in self:
            html = '<div class="jt-product-list">'
            if rec.picking_id:
                moves = rec.picking_id.move_ids_without_package or rec.picking_id.move_ids
                for move in moves:
                    if not move.product_id:
                        continue
                    product = move.product_id
                    qty = int(move.product_uom_qty or 0)
                    weight = int((product.weight or 0) * 1000) or 500
                    sku = product.default_code or 'N/A'
                    html += f'''
                        <div class="jt-product-item">
                            <div class="jt-product-icon">📦</div>
                            <div class="jt-product-details">
                                <div class="jt-product-name"><b>{product.name}</b></div>
                                <div class="jt-product-meta">
                                    <span>KL (gram): {weight}</span>
                                    <span>Số lượng: {qty}</span>
                                </div>
                                <div class="jt-product-sku">Mã SP: {sku}</div>
                            </div>
                        </div>
                    '''
            if html == '<div class="jt-product-list">':
                html += '<div class="text-muted p-3">Không có thông tin sản phẩm.</div>'
            html += '</div>'
            rec.product_html = html

    @api.onchange('goods_value')
    def _onchange_goods_value(self):
        if self.goods_value > 30000000:
            return {
                'warning': {
                    'title': "Cảnh báo giá trị hàng hóa",
                    'message': "J&T Express giới hạn giá trị hàng hóa tối đa là 30,000,000 VNĐ. Vui lòng kiểm tra lại."
                }
            }

    @api.constrains('goods_value')
    def _check_goods_value(self):
        for rec in self:
            if rec.is_insured and rec.goods_value > 30000000:
                raise ValidationError("J&T Express không nhận đơn hàng có giá trị vượt quá 30,000,000 VNĐ.")

    # Sender Info (Editable)
    sender_config_id = fields.Many2one("stock.warehouse", string="Cấu hình gửi/Kho")
    sender_name = fields.Char(string="Tên người gửi", required=True)
    sender_mobile = fields.Char(string="SĐT người gửi", required=True)
    sender_prov_id = fields.Many2one("jnt.province", string="Tỉnh/Thành gửi", ondelete='set null')
    sender_city_id = fields.Many2one("jnt.district", string="Quận/Huyện gửi", ondelete='set null',
                                    domain="[('province_id', '=', sender_prov_id)]")
    sender_area_id = fields.Many2one("jnt.ward", string="Phường/Xã gửi", ondelete='set null',
                                    domain="[('district_id', '=', sender_city_id)]")
    sender_address = fields.Char(string="Địa chỉ gửi", required=True)

    @api.onchange('sender_config_id')
    def _onchange_sender_config_id(self):
        if self.sender_config_id:
            warehouse = self.sender_config_id
            sender_partner = warehouse.partner_id or self.picking_id.company_id.partner_id
            
            self.sender_name = warehouse.jnt_sender_name or sender_partner.name
            self.sender_mobile = warehouse.jnt_sender_mobile or (sender_partner.mobile or sender_partner.phone or '').replace(' ', '').replace('+84', '0')
            self.sender_address = warehouse.jnt_sender_address or sender_partner.street
            
            if warehouse.jnt_prov_id:
                self.sender_prov_id = warehouse.jnt_prov_id
            if warehouse.jnt_city_id:
                self.sender_city_id = warehouse.jnt_city_id
            if warehouse.jnt_area_id:
                self.sender_area_id = warehouse.jnt_area_id
        else:
            # Revert to warehouse defaults if config is cleared
            warehouse = self.warehouse_id
            if warehouse:
                sender_partner = warehouse.partner_id or self.picking_id.company_id.partner_id
                self.sender_name = warehouse.jnt_sender_name or sender_partner.name
                self.sender_mobile = warehouse.jnt_sender_mobile or (sender_partner.mobile or sender_partner.phone or '').replace(' ', '').replace('+84', '0')
                self.sender_address = warehouse.jnt_sender_address or sender_partner.street
                self.sender_prov_id = warehouse.jnt_prov_id
                self.sender_city_id = warehouse.jnt_city_id
                self.sender_area_id = warehouse.jnt_area_id

    @api.onchange('sender_prov_id')
    def _onchange_sender_prov_id(self):
        if self.sender_prov_id:
            return {'domain': {'sender_city_id': [('province_id', '=', self.sender_prov_id.id)]}}
        else:
            return {'domain': {'sender_city_id': []}}

    @api.onchange('sender_city_id')
    def _onchange_sender_city_id(self):
        if self.sender_city_id:
            return {'domain': {'sender_area_id': [('district_id', '=', self.sender_city_id.id)]}}
        else:
            return {'domain': {'sender_area_id': []}}

    # Receiver Info (Editable)
    receiver_name = fields.Char(string="Tên người nhận", required=True)
    receiver_mobile = fields.Char(string="SĐT người nhận", required=True)
    receiver_prov_id = fields.Many2one("jnt.province", string="Tỉnh/Thành nhận", ondelete='set null')
    receiver_city_id = fields.Many2one("jnt.district", string="Quận/Huyện nhận", ondelete='set null', 
                                      domain="[('province_id', '=', receiver_prov_id)]")
    receiver_area_id = fields.Many2one("jnt.ward", string="Phường/Xã nhận", ondelete='set null',
                                      domain="[('district_id', '=', receiver_city_id)]")
    receiver_address = fields.Char(string="Địa chỉ nhận", required=True)

    @api.onchange('sender_area_id')
    def _onchange_sender_area_id(self):
        pass
    
    @api.onchange('receiver_prov_id')
    def _onchange_receiver_prov_id(self):
        if self.receiver_prov_id:
            # If prov selected, filter dists. Also reset ward.
            return {'domain': {
                'receiver_city_id': [('province_id', '=', self.receiver_prov_id.id)],
                'receiver_area_id': [('district_id.province_id', '=', self.receiver_prov_id.id)] # Allow searching all wards in prov initially?
            }}
        else:
            return {'domain': {'receiver_city_id': [], 'receiver_area_id': []}}

    @api.onchange('receiver_city_id')
    def _onchange_receiver_city_id(self):
        if self.receiver_city_id:
            return {'domain': {'receiver_area_id': [('district_id', '=', self.receiver_city_id.id)]}}
        elif self.receiver_prov_id:
            # If Dist cleared but Prov remains, show all Wards in Prov (for 2-level manual selection)
            return {'domain': {'receiver_area_id': [('district_id.province_id', '=', self.receiver_prov_id.id)]}}
        else:
            return {'domain': {'receiver_area_id': []}}

    # ... (fields def) ...

    @api.onchange('receiver_address')
    def _onchange_receiver_address_parse(self):
        """
        Auto-parse address using J&T API.
        Calls getAreaStreetBySearchKey API to get Province/District/Ward info.
        """
        if not self.receiver_address or len(self.receiver_address) < 10:
            return

        # Get authToken from System Parameters
        get_param = self.env['ir.config_parameter'].sudo().get_param
        auth_token = get_param('jnt_authToken')
        
        if not auth_token:
            _logger.warning("J&T authToken not configured. Cannot auto-parse address.")
            return
        
        try:
            # Call J&T API
            result = JTApiUtils.search_address(auth_token, self.receiver_address)
            
            # Rule: If API fails or returns no data, clear the fields to force manual user check
            if result.get('code') != 1 or not result.get('data'):
                _logger.warning("J&T Address Search returned no results for: %s", self.receiver_address)
                self.receiver_prov_id = False
                self.receiver_city_id = False
                self.receiver_area_id = False
                return

            if result.get('code') == 1 and result.get('data'):
                data = result['data'][0]  # Take first result
                
                # Extract data from API response
                province_name = data.get('provinceName', '')
                province_id_api = data.get('provinceId')
                district_name = data.get('cityName', '') or ''
                district_id_api = data.get('cityId')
                ward_name = data.get('areaName', '')  # Format: "Phường Tân Quý-028QTP04"
                ward_id_api = data.get('areaId')
                
                # Find or create Province
                province = self.env['jnt.province'].search([('name', '=ilike', province_name)], limit=1)
                if not province and province_name:
                    province = self.env['jnt.province'].create({'name': province_name})
                
                if province:
                    self.receiver_prov_id = province.id
                    
                    # ---------------------------------------------------------
                    # HANDLE 2-LEVEL ADDRESS LOGIC (J&T Quirk)
                    # If API returns Ward in 'cityName' field and 'areaName' is empty for 2-level addresses.
                    # ---------------------------------------------------------
                    if not ward_name and district_name:
                        # Check if district_name looks like a Ward (starts with Phường, Xã, Thị trấn)
                        # to avoid shifting actual Districts (e.g., "Quận 1") to Ward.
                        d_lower = district_name.lower()
                        ward_prefixes = ['phường', 'xã', 'thị trấn', 'p.', 'x.']
                        if any(d_lower.strip().startswith(p) for p in ward_prefixes):
                            ward_name = district_name
                            district_name = ""
                    
                    # Find or create District
                    district = False
                    if district_name:
                        district = self.env['jnt.district'].search([
                            ('province_id', '=', province.id),
                            ('name', '=ilike', district_name)
                        ], limit=1)
                        if not district:
                            district = self.env['jnt.district'].create({
                                'name': district_name,
                                'province_id': province.id
                            })
                    
                    if district:
                        self.receiver_city_id = district.id
                        
                        # Find or create Ward logic (standard 3-level)
                        ward = self.env['jnt.ward'].search([
                            ('district_id', '=', district.id),
                            ('name', '=ilike', ward_name)
                        ], limit=1)
                        if not ward and ward_name:
                            # Extract code from ward name
                            jnt_code = ''
                            if '-' in ward_name:
                                jnt_code = ward_name.split('-')[-1]
                            ward = self.env['jnt.ward'].create({
                                'name': ward_name,
                                'district_id': district.id,
                                'jnt_code': jnt_code
                            })
                        
                        if ward:
                            self.receiver_area_id = ward.id
                        else:
                            self.receiver_area_id = False
                            
                    else:
                        # District is empty (2-level case) or not found
                        self.receiver_city_id = False
                        
                        if ward_name:
                            # 2-level case: Ward exists but no District
                            # Try to find if this ward exists in this province (via any district? NO, we don't know the district)
                            # Or just create a Ward with NO District?
                            # Search for existing orphan ward or ward in this province?
                            # Searching by name in DB is risky if duplicates exist across districts. 
                            # But if it's 2-level, maybe it doesn't have a district.
                            
                            # Let's try to find a ward with this name in the province if possible
                            # This is complex because jnt.ward doesn't link to province directly.
                            
                            # Simple approach: Create/Use an orphan ward (district_id=False)
                            # Or check if we can find it via name in the province logic?
                            # For simplicity and correctness of "saving what we have":
                            
                            ward = self.env['jnt.ward'].search([
                                ('name', '=ilike', ward_name),
                                ('district_id', '=', False) 
                            ], limit=1)
                            
                            if not ward:
                                # Fallback: if we can't find an orphan, maybe we find one attached to a district but we don't know which one?
                                # Better to create a new one or use orphan to distinguish.
                                jnt_code = ''
                                if '-' in ward_name:
                                    jnt_code = ward_name.split('-')[-1]
                                    
                                ward = self.env['jnt.ward'].create({
                                    'name': ward_name,
                                    'district_id': False, # Orphan ward for 2-level address
                                    'jnt_code': jnt_code
                                })
                                
                            self.receiver_area_id = ward.id
                        else:
                             self.receiver_area_id = False

                else:
                    self.receiver_prov_id = False
                    self.receiver_city_id = False
                    self.receiver_area_id = False
                    
                _logger.info("J&T Address parsed: Province=%s, District=%s, Ward=%s", 
                            province_name, district_name, ward_name)
            else:
                _logger.warning("J&T Address Search returned no results for: %s", self.receiver_address)
                
        except Exception as e:
            _logger.error("Error parsing address via J&T API: %s", e)
            # Clear on exception too for safety
            self.receiver_prov_id = False
            self.receiver_city_id = False
            self.receiver_area_id = False
            


    @api.onchange('receiver_area_id')
    def _onchange_receiver_area_id(self):
        # Auto-calculate fee when location changes
        self._auto_calculate_fee()

    @api.onchange('weight', 'goods_value', 'cod_money', 'is_insured')
    def _onchange_fee_params(self):
        # Auto-calculate fee when weight or values change
        self._auto_calculate_fee()

    def _auto_calculate_fee(self):
        """Auto-calculate shipping fee when all required fields are filled"""
        if not (self.weight and self.sender_area_id and self.receiver_area_id):
            return

        try:
            get_param = self.env['ir.config_parameter'].sudo().get_param
            api_account = get_param('jnt_apiAccount')
            private_key = get_param('jnt_privateKey')
            jnt_customer_code = get_param('jnt_customerCode')
            jnt_password = get_param('jnt_password')
            company = self.picking_id.company_id if self.picking_id else self.env.company

            if not all([api_account, private_key, jnt_customer_code, jnt_password]):
                return

            client = JTApiUtils(
                api_account=api_account,
                private_key=private_key,
                environment=company.jt_environment
            )

            biz_params = {
                "customerCode": jnt_customer_code,
                "password": jnt_password.upper(),
                "weight": self.weight,
                "productType": self.product_type or 'EXPRESS',
                "goodsType": self.goods_type or 'bm000010',
                "goodsValue": max(self.goods_value, 1.0),
                "codMoney": str(int(self.cod_money)) if self.cod_money else "0",
                "isInsured": 1 if self.is_insured else 0,
                "sender": {
                    "prov": (self.sender_prov_id.name or "").strip(),
                    "city": (self.sender_city_id.name or "").strip(),
                    "area": self.sender_area_id.name if self.sender_area_id else ""
                },
                "receiver": {
                    "prov": (self.receiver_prov_id.name or "").strip(),
                    "city": (self.receiver_city_id.name or "").strip(),
                    "area": self.receiver_area_id.name if self.receiver_area_id else ""
                }
            }

            result = client.calculate_fee(biz_params)
            if result.get('code') == '1' and result.get('data'):
                data = result['data']
                self.estimated_fee = float(data.get('price', 0))
                self.estimated_cod_fee = float(data.get('codfee', 0) or data.get('codFee', 0))
                self.estimated_insurance_fee = float(data.get('insurancefee', 0) or data.get('insuranceFee', 0))
                _logger.info("J&T Fee calculated: %s VND (COD: %s, Insurance: %s)", 
                            self.estimated_fee, self.estimated_cod_fee, self.estimated_insurance_fee)
            else:
                _logger.warning("J&T Fee calculation failed: %s", result.get('msg'))
        except Exception as e:
            _logger.error("Error calculating J&T fee: %s", e)

    @api.onchange('receiver_prov_id')
    def _onchange_receiver_prov_id(self):
        if self.receiver_prov_id:
            return {'domain': {'receiver_city_id': [('province_id', '=', self.receiver_prov_id.id)]}}
        else:
            return {'domain': {'receiver_city_id': []}}

    @api.onchange('receiver_city_id')
    def _onchange_receiver_city_id(self):
        if self.receiver_city_id:
            return {'domain': {'receiver_area_id': [('district_id', '=', self.receiver_city_id.id)]}}
        else:
            return {'domain': {'receiver_area_id': []}}

    def _normalize_name(self, name):
        if not name: return ""
        name = str(name).lower().strip()
        prefixes = [
            'tỉnh ', 'thành phố ', 'quận ', 'huyện ', 'thị xã ', 
            'phường ', 'xã ', 'thị trấn ', 'tp. ', 'tp ', 'q. ', 'h. ', 'p. ', 'x. '
        ]
        for p in prefixes:
            if name.startswith(p):
                name = name[len(p):]
        return name.strip()

    @api.model
    def action_sync_jnt_codes(self):
        """Sync J&T dedicated locations from the local JSON data file."""
        import json
        import os
        import logging
        from odoo import _
        from odoo.exceptions import UserError
        from odoo.modules.module import get_module_resource

        _logger = logging.getLogger(__name__)

        json_path = get_module_resource('hlv_delivery_jt', 'data', 'jnt_mapping.json')
        if not json_path or not os.path.exists(json_path):
            raise UserError(_("Không tìm thấy file dữ liệu mapping J&T!"))

        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                mapping_data = json.load(f)
        except Exception as e:
            raise UserError(_("Lỗi đọc file mapping: %s") % e)

        # Cleanup old wizards to avoid foreign key constraints blocking sync
        self.env['jt.create.order.wizard'].sudo().search([]).unlink()

        created_p = 0
        created_d = 0
        created_w = 0

        for item in mapping_data:
            # item format from our converter: {'p': 'norm_p', 'd': 'norm_d', 'w': 'full_ward_name', 'c': 'code'}
            # Wait, the converter used normalize for prov and dist too. 
            # I should probably use the raw names for the records.
            pass

        # RE-IMPLEMENTING SYNC TO USE NEW MODELS PROPERLY
        # I'll need to re-read the Excel or update the JSON converter to include raw names.
        # Actually, let's just use the normalized for now or better, re-read JSON if I update it.
        # Let's update the JSON converter first to be more robust.
        return self._sync_from_mapping_data(mapping_data)

    def _sync_from_mapping_data(self, mapping_data):
        Province = self.env['jnt.province']
        District = self.env['jnt.district']
        Ward = self.env['jnt.ward']

        prov_map = {p.name: p.id for p in Province.search([])}
        dist_map = {} # (prov_id, name): id
        for d in District.search([]):
            dist_map[(d.province_id.id, d.name)] = d.id
        
        ward_map = {} # (dist_id, name): id
        for w in Ward.search([]):
            ward_map[(w.district_id.id, w.name)] = w.id

        updated = 0
        for item in mapping_data:
            p_name = item.get('pn', item['p']) # Use 'pn' for raw name if I update converter
            d_name = item.get('dn', item['d'])
            w_name = item['w'] # This is "Phường...-code"
            code = item['c']

            p_id = prov_map.get(p_name)
            if not p_id:
                p_id = Province.create({'name': p_name}).id
                prov_map[p_name] = p_id
            
            d_id = dist_map.get((p_id, d_name))
            if not d_id:
                d_id = District.create({'name': d_name, 'province_id': p_id}).id
                dist_map[(p_id, d_name)] = d_id
            
            w_id = ward_map.get((d_id, w_name))
            if not w_id:
                Ward.create({'name': w_name, 'jnt_code': code, 'district_id': d_id})
                updated += 1
                ward_map[(d_id, w_name)] = True # Just mark as exists

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Thành công',
                'message': f'Đã đồng bộ {updated} Phường/Xã vào danh mục J&T.',
                'type': 'success',
                'sticky': True,
            }
        }

    client_order_code = fields.Char(string="Mã đơn hàng khách", help="Ưu tiên lấy mã SO, nếu không có lấy mã phiếu xuất")

    @api.model
    def default_get(self, fields_list):
        res = super(JTCreateOrderWizard, self).default_get(fields_list)
        if self._context.get('active_id'):
            picking = self.env['stock.picking'].browse(self._context.get('active_id'))
            company = picking.company_id
            warehouse = picking.picking_type_id.warehouse_id
            
            sender_partner = warehouse.partner_id or company.partner_id
            receiver_partner = picking.partner_id

            # Cache Jnt records for faster mapping
            JntProvince = self.env['jnt.province']
            JntDistrict = self.env['jnt.district']
            JntWard = self.env['jnt.ward']

            def get_jnt_ids(prov_name, dist_name, ward_name):
                p = JntProvince.search([('name', 'ilike', self._normalize_name(prov_name))], limit=1)
                if not p:
                    p = JntProvince.search([('name', 'ilike', prov_name.strip())], limit=1)
                
                d = JntDistrict.browse()
                if p:
                    d = JntDistrict.search([('province_id', '=', p.id), ('name', 'ilike', self._normalize_name(dist_name))], limit=1)
                    if not d:
                        d = JntDistrict.search([('province_id', '=', p.id), ('name', 'ilike', dist_name.strip())], limit=1)
                
                w = JntWard.browse()
                if d:
                    w = JntWard.search([('district_id', '=', d.id), ('name', 'ilike', ward_name.strip())], limit=1)
                
                return p.id, d.id, w.id

            # Receiver Address from Picking/Partner - REMOVED GHN MAPPING
            r_prov_name = receiver_partner.state_id.name or ''
            r_dist_name = receiver_partner.city or ''
            r_ward_name = receiver_partner.street2 or ''
            
            r_p, r_d, r_w = get_jnt_ids(r_prov_name, r_dist_name, r_ward_name)

            # Sender Address from Company/Warehouse
            s_name = sender_partner.name or ''
            s_mobile = (sender_partner.mobile or sender_partner.phone or '').replace(' ', '').replace('+84', '0')
            s_address = sender_partner.street or ''
            
            s_prov_name = sender_partner.state_id.name or ''
            s_dist_name = sender_partner.city or ''
            s_ward_name = sender_partner.street2 or ''
            
            s_p, s_d, s_w = get_jnt_ids(s_prov_name, s_dist_name, s_ward_name)

            # Override with Warehouse J&T specific fields if set
            if warehouse:
                if warehouse.jnt_sender_name: s_name = warehouse.jnt_sender_name
                if warehouse.jnt_sender_mobile: s_mobile = warehouse.jnt_sender_mobile
                if warehouse.jnt_sender_address: s_address = warehouse.jnt_sender_address
                
                if warehouse.jnt_prov_id: s_p = warehouse.jnt_prov_id.id
                if warehouse.jnt_city_id: s_d = warehouse.jnt_city_id.id
                if warehouse.jnt_area_id: s_w = warehouse.jnt_area_id.id

            res.update({
                'picking_id': picking.id,
                'sender_config_id': warehouse.id if warehouse else False,
                'client_order_code': (picking.sale_id.name or picking.name) if picking else '',
                'cod_money': picking.sale_id.amount_total if (picking.sale_id and picking.sale_id.amount_total > 0) else 0.0,
                'goods_value': picking.sale_id.amount_total if (picking.sale_id and picking.sale_id.amount_total > 0) else 0.0,
                
                'sender_name': s_name,
                'sender_mobile': s_mobile,
                'sender_prov_id': s_p,
                'sender_city_id': s_d,
                'sender_area_id': s_w,
                'sender_address': s_address,

                'receiver_name': receiver_partner.name or '',
                'receiver_mobile': (picking.x_studio_sdt_giao_hng or picking.x_studio_st_giao_hng_1 or receiver_partner.mobile or receiver_partner.phone or '').replace(' ', '').replace('+84', '0'),
                'receiver_prov_id': r_p,
                'receiver_city_id': r_d,
                'receiver_area_id': r_w,
                'receiver_address': picking.x_studio_dia_chi_giao_hang or receiver_partner.street or '',
            })
            # Try to get weight from picking/move lines if possible
            total_weight = sum(move.product_id.weight * move.product_uom_qty for move in picking.move_ids)
            if total_weight > 0:
                res['weight'] = total_weight
        return res

    def action_create_jt_order(self):
        self.ensure_one()
        # Locations are now dedicated records, no need to save codes back to GHN/Partner

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

        if not self.sender_area_id or not self.receiver_area_id:
            raise UserError(_("Vui lòng chọn đầy đủ Tỉnh/Thành, Quận/Huyện, Phường/Xã cho cả người gửi và người nhận."))

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

        # J&T Vietnam uses specific string formats for many fields
        # Ensure goodsValue is at least 1 as J&T rejects 0
        goods_val = max(self.goods_value, 1.0)
        goods_val_str = str(int(goods_val))
        cod_money_str = str(int(self.cod_money))
        # Ensure weight is at least 0.01 to satisfy J&T requirements
        weight_val = max(self.weight, 0.01)
        weight_str = "{:.2f}".format(weight_val)

        # Payload
        picking = self.picking_id

        # REF: Fix J&T Delivery Quantity Logic - Use package quantity instead of product quantities
        # Calculate package quantity (ensure at least 1)
        pkg_qty = self.manual_package_qty if self.manual_package_qty > 0 else (len(picking.move_line_ids.mapped('result_package_id')) or 1)
        
        # Concatenate product names
        product_names = ", ".join([line.product_id.name for line in picking.move_ids_without_package if line.product_id])
        product_names = (product_names or "Hàng hóa")[:199] # Truncate to avoid limit

        customer_code = jnt_customer_code # Use the already defined jnt_customer_code
        biz_params = {
            "customerCode": customer_code,
            "password": password_to_send,
            "txlogisticId": self.client_order_code.replace("/", "-"),
            "orderType": self.order_type,
            "serviceType": self.service_type,
            "deliveryType": self.delivery_type,
            "selfAddress": 0,
            "productType": self.product_type,
            "goodsType": self.goods_type,
            "sender": {
                "name": sanitize_name(self.sender_name),
                "mobile": self.sender_mobile or "",
                "prov": (self.sender_prov_id.name or "").strip(),
                "city": (self.sender_city_id.name or "").strip(),
                "area": (self.sender_area_id.name or "").strip(),
                "address": sanitize_address(self.sender_address)
            },
            "receiver": {
                "name": sanitize_name(self.receiver_name),
                "mobile": self.receiver_mobile or "",
                "prov": (self.receiver_prov_id.name or "").strip(),
                "city": (self.receiver_city_id.name or "").strip(),
                "area": (self.receiver_area_id.name or "").strip(),
                "address": sanitize_address(self.receiver_address)
            },
            "payType": self.pay_type,
            "partSign": "1" if self.part_sign else "0",
            "isInsured": 1 if self.is_insured else 0,
            "goodsValue": goods_val_str,
            "codMoney": cod_money_str,
            "remark": self.remark or "",
            "packageInfo": {
                "weight": weight_str,
                "length": int(self.length),
                "width": int(self.width),
                "height": int(self.height),
                "volume": str(int(max(self.length * self.width * self.height / 6000.0, 1.0)))
            },
            "itemsValue": goods_val_str,
            "totalQuantity": pkg_qty,
            "items": [{
                "itemName": product_names[:79],
                "englishName": product_names[:79],
                "number": str(int(pkg_qty)),
                "itemValue": str(int(max(self.goods_value, 1.0))) # Ensure value is valid
            }]
        }

        _logger.info("J&T Creating Order for %s", self.picking_id.name)
        _logger.info("J&T Request Payload: %s", biz_params)
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
            
            
            # Map display values for pay_type and service_type
            pay_type_labels = {
                'PP_PM': 'Thanh toán cuối tháng',
                'PP_CASH': 'Người gửi thanh toán',
                'CC_CASH': 'Người nhận thanh toán',
            }
            service_type_labels = {
                '1': 'Lấy hàng tận nơi (Pickup)',
                '6': 'Gửi hàng tại bưu cục (Drop off)',
            }

            bill_code = data.get('billCode', '')
            shipping_fee = data.get('inquiryFee', 0.0)
            cod_fee = data.get('codFee', 0.0)
            insurance_fee = data.get('insuranceFee', 0.0)
            sort_line = data.get('sortLine', '')

            msg_body = f"""
                <p><strong>🚚 Đã tạo đơn J&amp;T Express thành công!</strong></p>
                <table class="table table-sm" style="width:100%">
                <tbody>
                    <tr><td><strong>Mã vận đơn (Bill Code)</strong></td><td>{bill_code}</td></tr>
                    <tr><td><strong>Tuyến phân loại</strong></td><td>{sort_line}</td></tr>
                    <tr><td><strong>Dịch vụ</strong></td><td>{service_type_labels.get(self.service_type, self.service_type)}</td></tr>
                    <tr><td><strong>Phương thức thanh toán</strong></td><td>{pay_type_labels.get(self.pay_type, self.pay_type)}</td></tr>
                    <tr><td><strong>Người nhận</strong></td><td>{self.receiver_name} — {self.receiver_mobile}</td></tr>
                    <tr><td><strong>Địa chỉ nhận</strong></td><td>{self.receiver_address}, {self.receiver_area_id.name or ''}, {self.receiver_city_id.name or ''}, {self.receiver_prov_id.name or ''}</td></tr>
                    <tr><td><strong>Tiền thu hộ (COD)</strong></td><td>{'{:,.0f}'.format(self.cod_money)} VNĐ</td></tr>
                    <tr><td><strong>Giá trị hàng hóa</strong></td><td>{'{:,.0f}'.format(self.goods_value)} VNĐ</td></tr>
                    <tr><td><strong>Trọng lượng</strong></td><td>{self.weight} kg</td></tr>
                    <tr><td><strong>Phí vận chuyển</strong></td><td>{'{:,.0f}'.format(shipping_fee)} VNĐ</td></tr>
                    <tr><td><strong>Phí COD</strong></td><td>{'{:,.0f}'.format(cod_fee)} VNĐ</td></tr>
                    <tr><td><strong>Phí bảo hiểm</strong></td><td>{'{:,.0f}'.format(insurance_fee)} VNĐ</td></tr>
                </tbody>
                </table>
                """
            self.picking_id.message_post(body=Markup(msg_body), subtype_xmlid='mail.mt_note')

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Thành công',
                    'message': f'Đã tạo đơn J&T thành công! Mã vận đơn: {data.get("billCode")}',
                    'type': 'success',
                    'next': {'type': 'ir.actions.act_window_close'},
                }
            }
        else:
            raise UserError(_("Lỗi từ J&T: %s") % result.get('msg', 'Unknown Error'))
