from odoo import models, fields, api, _

class SaleOrderCancelRequest(models.Model):
    _name = 'sale.order.cancel.request'
    _description = 'Yêu cầu Hủy Đơn Hàng'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'

    name = fields.Char(string='Mã Yêu Cầu', required=True, copy=False, readonly=True, index=True, default=lambda self: _('Mới'))
    salesperson_name = fields.Char(string='Mã Sale', required=True, tracking=True)
    salesperson_zalo_uid = fields.Char(string='Zalo UID Sale', tracking=True, help="Zalo User ID của Sale để nhận thông báo kết quả")
    order_reference = fields.Char(string='Mã Đơn Hàng', required=True, tracking=True, help="Mã đơn hàng được nhập bởi Sale, ví dụ: SO12345")
    
    order_id = fields.Many2one('sale.order', string='Đơn Bán Hàng', compute='_compute_order_id', store=True, readonly=False)
    
    type = fields.Selection([
        ('cancel', 'Hủy Đơn'),
        ('modify', 'Chỉnh Sửa')
    ], string='Loại Yêu Cầu', default='cancel', required=True, tracking=True)
    
    reason = fields.Text(string='Lý do', required=True, tracking=True)
    
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('submitted', 'Đã Gửi'),
        ('accountant_confirmed', 'KT Đã Xác Nhận'),
        ('done', 'Hoàn Thành'),
        ('rejected', 'Đã Từ Chối')
    ], string='Trạng Thái', default='draft', tracking=True, group_expand='_expand_states')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Mới')) == _('Mới'):
                vals['name'] = self.env['ir.sequence'].next_by_code('sale.order.cancel.request') or _('Mới')
        return super(SaleOrderCancelRequest, self).create(vals_list)

    @api.depends('order_reference')
    def _compute_order_id(self):
        for rec in self:
            if rec.order_reference:
                order = self.env['sale.order'].search([('name', '=', rec.order_reference)], limit=1)
                rec.order_id = order.id if order else False
            else:
                rec.order_id = False

    def action_submit(self):
        """Sale submits the request."""
        self.ensure_one()
        self.state = 'submitted'
        self._send_zalo_notification_on_submit()

    def action_accountant_confirm(self):
        """Accountant confirms they have processed the request in external system."""
        self.ensure_one()
        self.state = 'accountant_confirmed'
        self._send_zalo_notification_on_accountant_confirm()

    def action_warehouse_confirm(self):
        """Warehouse confirms they have handled the goods (stopped packing or updated)."""
        self.ensure_one()
        self.state = 'done'
        self._send_zalo_notification_on_warehouse_confirm()

    def action_reject(self):
        self.state = 'rejected'
        
    def action_draft(self):
        self.state = 'draft'

    def _expand_states(self, states, domain, order):
        return [key for key, val in type(self).state.selection]

    # ============ Zalo Notification Helpers ============

    def _get_warehouse_recipients(self):
        """Get Warehouse Zalo UIDs from config."""
        Config = self.env['ir.config_parameter'].sudo()
        warehouse_uid = Config.get_param('hlv_order_cancel_request.warehouse_zalo_uid')
        if warehouse_uid:
            return [u.strip() for u in warehouse_uid.split(',') if u.strip()]
        return []

    def _get_accountant_recipients(self):
        """Get Accountant Zalo UIDs from config."""
        Config = self.env['ir.config_parameter'].sudo()
        accountant_uid = Config.get_param('hlv_order_cancel_request.accountant_zalo_uid')
        if accountant_uid:
            return [u.strip() for u in accountant_uid.split(',') if u.strip()]
        return []

    def _get_sale_recipients(self):
        """Get Sale's Zalo UID from the request record itself."""
        if self.salesperson_zalo_uid:
            return [u.strip() for u in self.salesperson_zalo_uid.split(',') if u.strip()]
        return []

    def _get_backend_url(self):
        """Get backend URL for this request."""
        action_id = self.env.ref('hlv_order_cancel_request.action_sale_order_cancel_request').id
        base_url = self.env['ir.config_parameter'].sudo().get_param('web.base.url')
        return f"{base_url}/odoo/action-{action_id}/{self.id}"

    def _get_type_label(self):
        """Get human-readable type label (Hủy Đơn / Chỉnh Sửa)."""
        return dict(self._fields['type'].selection).get(self.type, self.type)

    def _send_zalo_to_recipients(self, recipients, message):
        """Send Zalo notification to specific recipients."""
        if not recipients:
            return

        zalo_config = self.env['hlv.zalo.stock.notification'].sudo()._get_active_config()
        if not zalo_config:
            return

        for uid in recipients:
            try:
                zalo_config.send_notification_message(uid, message)
            except Exception:
                pass

    # ============ Notification Methods ============

    def _send_zalo_notification_on_submit(self):
        """
        Step 1: Sale submits request.
        Recipients: Accountant (to process in external system) + Warehouse (to pause packing)
        """
        self.ensure_one()
        type_label = self._get_type_label().upper()
        
        # Message for Accountant - to process the request
        msg_accountant = f"🔔 YÊU CẦU {type_label}\n"
        msg_accountant += f"• Sale: {self.salesperson_name}\n"
        msg_accountant += f"• Mã Đơn: {self.order_reference}\n"
        if self.order_id:
            msg_accountant += f"• Đơn Odoo: {self.order_id.name}\n"
        msg_accountant += f"• Lý do: {self.reason}\n"
        msg_accountant += f"• Mã YC: {self.name}\n"
        msg_accountant += f"👉 {self._get_backend_url()}"
        
        # Message for Warehouse - to pause packing
        msg_warehouse = f"⏸️ TẠM DỪNG ĐÓNG GÓI - YÊU CẦU {type_label}\n"
        msg_warehouse += f"• Mã Đơn: {self.order_reference}\n"
        if self.order_id:
            msg_warehouse += f"• Đơn Odoo: {self.order_id.name}\n"
        msg_warehouse += f"• Lý do: {self.reason}"
        
        self._send_zalo_to_recipients(self._get_accountant_recipients(), msg_accountant)
        self._send_zalo_to_recipients(self._get_warehouse_recipients(), msg_warehouse)

    def _send_zalo_notification_on_accountant_confirm(self):
        """
        Step 2: Accountant confirms they processed in external system.
        Recipients: Only Warehouse (to inform them to confirm after handling goods)
        """
        self.ensure_one()
        type_label = self._get_type_label().upper()
        
        if self.type == 'cancel':
            msg = f"📋 KẾ TOÁN ĐÃ XÁC NHẬN HỦY ĐƠN\n"
            msg += f"Vui lòng xác nhận đã ngừng đóng gói.\n"
        else:
            msg = f"📋 KẾ TOÁN ĐÃ XÁC NHẬN CHỈNH SỬA\n"
            msg += f"Vui lòng kiểm tra và xác nhận.\n"
        
        msg += f"• Mã Đơn: {self.order_reference}\n"
        if self.order_id:
            msg += f"• Đơn Odoo: {self.order_id.name}\n"
        msg += f"• Mã YC: {self.name}\n"
        msg += f"👉 {self._get_backend_url()}"
        
        self._send_zalo_to_recipients(self._get_warehouse_recipients(), msg)

    def _send_zalo_notification_on_warehouse_confirm(self):
        """
        Step 3: Warehouse confirms they handled the goods.
        Recipients: Only the Sale who created the request (to notify completion)
        """
        self.ensure_one()
        
        if self.type == 'cancel':
            msg = f"✅ YÊU CẦU HỦY ĐƠN ĐÃ HOÀN TẤT\n"
        else:
            msg = f"✅ YÊU CẦU CHỈNH SỬA ĐÃ HOÀN TẤT\n"
        
        msg += f"• Mã Đơn: {self.order_reference}\n"
        if self.order_id:
            msg += f"• Đơn Odoo: {self.order_id.name}\n"
        msg += f"• Mã YC: {self.name}\n"
        msg += "Kế toán và Kho đã xử lý xong."
        
        self._send_zalo_to_recipients(self._get_sale_recipients(), msg)
