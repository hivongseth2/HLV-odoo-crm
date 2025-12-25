from odoo import http, _
from odoo.http import request
import json
import hmac

# Use same session key as website_public_inventory_18 for shared auth
SESSION_KEY_OK = "inv_pw_ok"
PW_PARAM_KEY = "website_public_inventory_18.search_password"

def _get_search_password():
    return request.env["ir.config_parameter"].sudo().get_param(PW_PARAM_KEY, default="") or ""

def _consteq(a, b):
    return hmac.compare_digest(str(a or ""), str(b or ""))

def _pw_allowed():
    conf = _get_search_password()
    return not conf or bool(request.session.get(SESSION_KEY_OK))

class CancelRequestController(http.Controller):

    @http.route('/cancel-request', type='http', auth='public', website=True)
    def index(self, **kwargs):
        """Redirect to form if logged in, else login"""
        if _pw_allowed():
            return request.redirect('/cancel-request/form')
        return request.redirect('/cancel-request/login')

    @http.route('/cancel-request/login', type='http', auth='public', website=True)
    def login(self, **kwargs):
        """Render login page - uses same password as search_stock"""
        # If already authenticated with search_stock, redirect to form directly
        if _pw_allowed():
            return request.redirect('/cancel-request/form')
            
        error = None
        if request.httprequest.method == 'POST':
            password = kwargs.get('password', '').strip()
            stored_password = _get_search_password()
            if _consteq(password, stored_password):
                request.session[SESSION_KEY_OK] = True
                return request.redirect('/cancel-request/form')
            else:
                error = _("Mật khẩu không đúng. Vui lòng thử lại.")
        
        return request.render('hlv_order_cancel_request.cancel_request_login', {'error': error})

    @http.route('/cancel-request/form', type='http', auth='public', website=True)
    def form(self, **kwargs):
        """Render request form"""
        if not _pw_allowed():
            return request.redirect('/cancel-request/login')

        values = {}
        error = {}
        if request.httprequest.method == 'POST':
            salesperson_name = kwargs.get('salesperson_name')
            order_reference = kwargs.get('order_reference')
            reason = kwargs.get('reason')
            req_type = kwargs.get('type')

            if not salesperson_name: error['salesperson_name'] = 'Bắt buộc'
            if not order_reference: error['order_reference'] = 'Bắt buộc'
            if not reason: error['reason'] = 'Bắt buộc'
            
            # Validate: salesperson must match the order's saler code
            if not error:
                SaleOrder = request.env['sale.order'].sudo()
                order = SaleOrder.search([('name', '=', order_reference)], limit=1)
                
                if not order:
                    error['main'] = f'Không tìm thấy đơn hàng với mã: {order_reference}'
                elif order.x_studio_misa_saler_code:
                    # Compare (case-insensitive)
                    if order.x_studio_misa_saler_code.upper() != salesperson_name.upper():
                        error['main'] = f'Mã Sale không khớp với đơn hàng. Đơn {order_reference} thuộc về Sale khác.'
            
            if not error:
                # Create request
                try:
                    CancelRequest = request.env['sale.order.cancel.request'].sudo()
                    
                    req = CancelRequest.create({
                        'salesperson_name': salesperson_name,
                        'order_reference': order_reference,
                        'reason': reason,
                        'type': req_type or 'cancel',
                    })
                    req.action_submit()
                    return request.redirect('/cancel-request/success?req_id=%s' % req.id)
                except Exception as e:
                    error['main'] = str(e)
            
            values = kwargs

        return request.render('hlv_order_cancel_request.cancel_request_form', {'values': values, 'error': error})

    @http.route('/cancel-request/autocomplete/saler', type='http', auth='public', website=True)
    def autocomplete_saler(self, term='', **kwargs):
        """Autocomplete for salesperson based on x_studio_misa_saler_code"""
        if not _pw_allowed():
             return json.dumps([])
        
        # Build domain - if term is empty, get all; otherwise filter
        if term:
            domain = [('x_studio_misa_saler_code', 'ilike', term)]
        else:
            domain = [('x_studio_misa_saler_code', '!=', False)]
        
        orders = request.env['sale.order'].sudo().search(domain, limit=100)
        
        # Use set to get distinct codes
        values = set()
        for o in orders:
            if o.x_studio_misa_saler_code:
                values.add(o.x_studio_misa_saler_code)
                
        return json.dumps(sorted(list(values)))

    @http.route('/cancel-request/success', type='http', auth='public', website=True)
    def success(self, req_id=None, **kwargs):
        """Render success page"""
        if not _pw_allowed():
            return request.redirect('/cancel-request/login')
        
        req = None
        if req_id:
            req = request.env['sale.order.cancel.request'].sudo().browse(int(req_id))
            
        return request.render('hlv_order_cancel_request.cancel_request_success', {'cancel_req': req})
