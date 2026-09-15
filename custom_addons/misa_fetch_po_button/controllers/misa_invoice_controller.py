from odoo import http
from odoo.http import request
import logging

_logger = logging.getLogger(__name__)


class MisaInvoiceController(http.Controller):

    @http.route('/search_invoice', type='http', auth='user', website=True, methods=['GET'])
    def render_search_invoice_page(self, **kwargs):
        """Render the standalone invoice search page"""
        return request.render('misa_fetch_po_button.misa_invoice_search_template', {})

    @http.route('/api/misa/invoice/search', type='json', auth='user', methods=['POST'])
    def api_search_misa_invoice(self, query, **kwargs):
        """API proxy to search MISA invoices"""
        try:
            misa_utils = request.env['misa.api.utils'].sudo()
            resp = misa_utils.search_invoice_api(query)
            if resp.status_code == 200:
                try:
                    return {"status": "success", "data": resp.json()}
                except Exception as e:
                    return {"status": "error", "message": f"Dữ liệu JSON không hợp lệ. {e}"}
            else:
                return {"status": "error", "message": f"MISA API error {resp.status_code}: {resp.text}"}
        except Exception as e:
            _logger.exception("Error searching invoice")
            return {"status": "error", "message": str(e)}

    @http.route('/api/misa/invoice/preview', type='json', auth='user', methods=['POST'])
    def api_preview_misa_invoice(self, refid, date, **kwargs):
        """API proxy to get MISA invoice PDF link"""
        _logger.info(
            "[MISA INVOICE PREVIEW][ODOO REQUEST] refid=%s date=%s kwargs=%s",
            refid,
            date,
            kwargs,
        )
        try:
            misa_utils = request.env['misa.api.utils'].sudo()
            resp = misa_utils.preview_invoice_api(refid, date)
            if resp.status_code == 200:
                try:
                    result = {"status": "success", "data": resp.json()}
                    return result
                except Exception as e:
                    result = {"status": "error", "message": f"Dữ liệu JSON không hợp lệ. {e}"}
                    # _logger.exception("[MISA INVOICE PREVIEW][JSON ERROR]")
                    # _logger.info("[MISA INVOICE PREVIEW][ODOO RESPONSE] %s", result)
                    return result
            else:
                result = {"status": "error", "message": f"MISA API error {resp.status_code}: {resp.text}"}
                # _logger.info("[MISA INVOICE PREVIEW][ODOO RESPONSE] %s", result)
                return result
        except Exception as e:
            _logger.exception("Error previewing invoice")
            result = {"status": "error", "message": str(e)}
            # _logger.info("[MISA INVOICE PREVIEW][ODOO RESPONSE] %s", result)
            return result
