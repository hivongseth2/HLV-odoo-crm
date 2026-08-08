import logging
import time

from odoo import models

_logger = logging.getLogger(__name__)

MISA_ACT_TOKEN_PARAM = 'misa.act.cached_token'
MISA_ACT_TOKEN_EXP_PARAM = 'misa.act.cached_token_exp'


class MisaApiUtilsInvoiceStatus(models.AbstractModel):
    _inherit = 'misa.api.utils'

    def _get_misa_token_cached(self, force_refresh=False):
        """Cache token của _get_misa_token() (actapp.misa.vn) để tránh phải
        đăng nhập lại mỗi lần gọi, cùng cơ chế với _fetch_login_crm_token_cached().
        _fetch_with_retry() vẫn tự đăng nhập lại (không cache) khi gặp 401 giữa chừng.
        """
        ICP = self.env['ir.config_parameter'].sudo()
        now = int(time.time())
        if not force_refresh:
            token = (ICP.get_param(MISA_ACT_TOKEN_PARAM) or '').strip()
            exp = int(ICP.get_param(MISA_ACT_TOKEN_EXP_PARAM) or 0)
            if token and exp > now + 300:
                return token

        token = self._get_misa_token()
        exp = self._decode_jwt_exp(token) or (now + 3600)
        ICP.set_param(MISA_ACT_TOKEN_PARAM, token)
        ICP.set_param(MISA_ACT_TOKEN_EXP_PARAM, str(exp))
        return token

    def get_invoice_status_for_refno(self, refno):
        """Tra tình trạng xuất hóa đơn của 1 phiếu xuất kho (refno = stock.picking.name)
        trên MISA. Tái dùng đúng luồng 3 bước của search_invoice_api() (sa_invoice_request
        -> sa_invoice_get theo khách hàng -> lọc theo sa_invoice_request_refid), nhưng tách
        rõ 3 trạng thái mà search_invoice_api() không phân biệt được (cả hai đều trả về
        PageData rỗng):
        - missing: chưa có "Đề nghị xuất hóa đơn" nào khớp refno.
        - requested: đã có đề nghị nhưng chưa có hóa đơn nào phát sinh từ đề nghị đó.
        - invoiced: đã có hóa đơn phát sinh từ đề nghị.
        """
        token = self._get_misa_token_cached()
        headers = self.env['misa.config'].get_default_headers(token)

        result = {
            'state': 'missing',
            'request_refid': None,
            'account_object_name': None,
            'invoice_no': None,
            'invoice_date': None,
            'invoice_amount': None,
        }

        url_req = "https://actapp.misa.vn/g2/api/sa/v1/sa_invoice_request/paging_filter_v2"
        payload_req = self.env['misa.config'].get_invoice_request_payload(refno)
        resp_req = self._fetch_with_retry(url_req, headers, payload_req)
        if resp_req.status_code != 200:
            raise Exception(
                "MISA sa_invoice_request API error %s: %s" % (resp_req.status_code, resp_req.text)
            )

        page_data_req = resp_req.json().get("Data", {}).get("PageData", []) or []
        if not page_data_req:
            return result

        req_info = page_data_req[0]
        target_req_id = req_info.get("refid")
        target_customer = req_info.get("account_object_name")
        result['request_refid'] = target_req_id
        result['account_object_name'] = target_customer
        result['state'] = 'requested'

        if not target_req_id or not target_customer:
            return result

        url_inv = "https://actapp.misa.vn/g2/api/sa/v1/sa_invoice_get/paging_filter_v2"
        payload_inv = self.env['misa.config'].get_invoice_full_search_payload(target_customer)
        resp_inv = self._fetch_with_retry(url_inv, headers, payload_inv)
        if resp_inv.status_code != 200:
            raise Exception(
                "MISA sa_invoice_get API error %s: %s" % (resp_inv.status_code, resp_inv.text)
            )

        page_data_inv = resp_inv.json().get("Data", {}).get("PageData", []) or []
        matched_invs = [
            inv for inv in page_data_inv
            if inv.get("sa_invoice_request_refid") == target_req_id
        ]
        if not matched_invs:
            return result

        matched = matched_invs[0]
        result['state'] = 'invoiced'
        result['invoice_no'] = matched.get('inv_no')
        result['invoice_date'] = matched.get('inv_date')
        result['invoice_amount'] = matched.get('total_amount')
        return result
