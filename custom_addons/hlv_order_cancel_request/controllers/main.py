from odoo import http, _
from odoo.http import request

class CancelRequestController(http.Controller):

    @http.route('/cancel-request', type='http', auth='public', website=True)
    def index(self, **kwargs):
        """Redirect to form if logged in, else login"""
        if request.session.get('cancel_request_authenticated'):
            return request.redirect('/cancel-request/form')
        return request.redirect('/cancel-request/login')

    @http.route('/cancel-request/login', type='http', auth='public', website=True)
    def login(self, **kwargs):
        """Render login page"""
        error = None
        if request.httprequest.method == 'POST':
            password = kwargs.get('password')
            stored_password = request.env['ir.config_parameter'].sudo().get_param('hlv_order_cancel_request.website_password')
            if password == stored_password:
                request.session['cancel_request_authenticated'] = True
                return request.redirect('/cancel-request/form')
            else:
                error = _("Mật khẩu không đúng. Vui lòng thử lại.")
        
        return request.render('hlv_order_cancel_request.cancel_request_login', {'error': error})

    @http.route('/cancel-request/form', type='http', auth='public', website=True)
    def form(self, **kwargs):
        """Render request form"""
        if not request.session.get('cancel_request_authenticated'):
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
            
            if not error:
                # Create request
                try:
                    CancelRequest = request.env['sale.order.cancel.request'].sudo()
                    # Check duplicate? Maybe not strictly necessary.
                    
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

    @http.route('/cancel-request/success', type='http', auth='public', website=True)
    def success(self, req_id=None, **kwargs):
        """Render success page"""
        if not request.session.get('cancel_request_authenticated'):
            return request.redirect('/cancel-request/login')
        
        req = None
        if req_id:
            req = request.env['sale.order.cancel.request'].sudo().browse(int(req_id))
            
        return request.render('hlv_order_cancel_request.cancel_request_success', {'request': req})
