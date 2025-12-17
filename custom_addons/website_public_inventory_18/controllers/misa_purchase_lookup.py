from odoo import http
from odoo.http import request
import logging
import hmac

_logger = logging.getLogger(__name__)

PW_PARAM_KEY = "website_public_inventory_18.search_password"
SESSION_KEY_OK = "inv_pw_ok"
SESSION_KEY_ERR = "inv_pw_err"

def _get_search_password():
    return request.env["ir.config_parameter"].sudo().get_param(PW_PARAM_KEY, default="") or ""

def _consteq(a, b):
    return hmac.compare_digest(str(a or ""), str(b or ""))

class MisaPurchaseLookupController(http.Controller):
    """Controller cho trang web tra cứu chứng từ MISA công khai"""

    # Mapping các giá trị trạng thái
    PAID_STATUS_MAP = {
        0: {'label': 'Chưa thanh toán', 'class': 'badge-danger'},
        1: {'label': 'Đã thanh toán', 'class': 'badge-success'},
        2: {'label': 'Thanh toán một phần', 'class': 'badge-warning'},
    }
    
    INCLUDE_INVOICE_MAP = {
        0: {'label': 'Chưa nhận HĐ', 'class': 'badge-secondary'},
        1: {'label': 'Đã nhận HĐ', 'class': 'badge-info'},
    }
    
    REFTYPE_MAP = {
        301: 'Đơn mua hàng',
        302: 'Chứng từ nhập kho',
    }

    def _format_currency(self, amount):
        """Format số tiền theo định dạng VN"""
        if amount is None:
            return "0"
        try:
            return "{:,.0f}".format(float(amount)).replace(",", ".")
        except:
            return str(amount)

    def _format_date(self, date_str):
        """Format ngày từ ISO sang dd/mm/yyyy"""
        if not date_str:
            return ""
        try:
            from datetime import datetime
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.strftime("%d/%m/%Y")
        except:
            return date_str

    def _map_voucher_data(self, voucher):
        """Map và format dữ liệu chứng từ để hiển thị"""
        paid_status = voucher.get('paid_status', 0)
        include_invoice = voucher.get('include_invoice', 0)
        reftype = voucher.get('reftype', 302)
        
        return {
            'refid': voucher.get('refid', ''),
            'refno_finance': voucher.get('refno_finance', voucher.get('refno', '')),
            'inv_no': voucher.get('inv_no') or '', # Số hóa đơn
            'refdate': self._format_date(voucher.get('refdate')),
            'posted_date': self._format_date(voucher.get('posted_date')),
            'journal_memo': voucher.get('journal_memo', ''),
            'account_object_code': voucher.get('account_object_code', ''),
            'account_object_name': voucher.get('account_object_name', ''),
            'total_amount': self._format_currency(voucher.get('total_amount', 0)),
            'total_amount_raw': voucher.get('total_amount', 0),
            'currency_id': voucher.get('currency_id', 'VND'),
            'paid_status': self.PAID_STATUS_MAP.get(paid_status, self.PAID_STATUS_MAP[0]),
            'paid_status_raw': paid_status,
            'include_invoice': self.INCLUDE_INVOICE_MAP.get(include_invoice, self.INCLUDE_INVOICE_MAP[0]),
            'include_invoice_raw': include_invoice,
            'reftype': self.REFTYPE_MAP.get(reftype, str(reftype)),
            'reftype_raw': reftype,
            'employee_name': voucher.get('employee_name', ''),
            'employee_code': voucher.get('employee_code', ''),
            'branch_name': voucher.get('branch_name', ''),
            'custom_field1': voucher.get('custom_field1', ''),
            'custom_field2': voucher.get('custom_field2', ''),
            'in_outward_refno': voucher.get('in_outward_refno', ''),
            'created_by': voucher.get('created_by', ''),
            'modified_by': voucher.get('modified_by', ''),
        }

    @http.route(['/misa/purchase/lookup', '/misa/purchase/lookup/page/<int:page>'], type='http', auth='public', website=True)
    def misa_purchase_lookup(self, page=1, **kwargs):
        """Trang tra cứu chứng từ mua hàng MISA (có phân trang)"""
        
        # 1. AUTHENTICATION LOGIC (Shared with Inventory Lookup)
        conf_pw = _get_search_password()
        if conf_pw:
            # Check if session has auth
            if not request.session.get(SESSION_KEY_OK):
                # Handle POST Login attempt
                if request.httprequest.method == "POST" and kwargs.get('inv_password'):
                    inp = (kwargs.get("inv_password") or "").strip()
                    if _consteq(inp, conf_pw):
                        request.session[SESSION_KEY_OK] = True
                        request.session.pop(SESSION_KEY_ERR, None)
                        return request.redirect(request.httprequest.path)
                    else:
                        request.session[SESSION_KEY_ERR] = True
                        return request.render('website_public_inventory_18.misa_purchase_lookup', {"pw_ok": False, "pw_err": True})
                # Not logged in
                else:
                    return request.render('website_public_inventory_18.misa_purchase_lookup', {"pw_ok": False, "pw_err": False})

        # --- LOGGED IN ---
        journal_memo = kwargs.get('journal_memo', '').strip()
        vouchers = []
        error = None
        searched = False
        pager = {}
        items_per_page = 20
        count = 0
        
        if journal_memo:
            searched = True
            try:
                misa_utils = request.env['misa.api.utils'].sudo()
                # Fetch more results to allow aggregation/pagination (e.g., 200 items max)
                raw_vouchers = misa_utils.search_purchase_voucher(journal_memo, limit=200)
                all_vouchers = [self._map_voucher_data(v) for v in raw_vouchers]
                
                # Pagination Logic
                count = len(all_vouchers)
                pager = request.website.pager(
                    url='/misa/purchase/lookup',
                    total=count,
                    page=page,
                    step=items_per_page,
                    scope=7,
                    url_args={'journal_memo': journal_memo}
                )
                
                # Slice current page
                offset = (page - 1) * items_per_page
                vouchers = all_vouchers[offset: offset + items_per_page]
                
            except Exception as e:
                _logger.exception("Error searching MISA purchase voucher")
                error = str(e)
        
        return request.render('website_public_inventory_18.misa_purchase_lookup', {
            'journal_memo': journal_memo,
            'vouchers': vouchers,
            'error': error,
            'searched': searched,
            'voucher_count': count,
            'pager': pager,
            'pw_ok': True, # Authenticated
        })
