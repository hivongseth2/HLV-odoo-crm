import logging
import time
from datetime import datetime

from odoo import models

_logger = logging.getLogger(__name__)

MISA_ACT_TOKEN_PARAM = 'misa.act.cached_token'
MISA_ACT_TOKEN_EXP_PARAM = 'misa.act.cached_token_exp'

# Trần số trang tải khi quét hàng loạt sa_invoice_request theo khoảng ngày (an toàn, tránh
# vòng lặp vô hạn nếu MISA trả dữ liệu bất thường).
MISA_INVOICE_REQUEST_MAP_MAX_PAGES = 30
MISA_INVOICE_REQUEST_MAP_PAGE_SIZE = 100


def _empty_invoice_status():
    return {
        'state': 'missing',
        'request_refid': None,
        'account_object_name': None,
        'invoice_no': None,
        'invoice_date': None,
        'invoice_amount': None,
        'master_refno': None,
    }


def _misa_json_or_raise(resp, context):
    """MISA có thể trả HTTP 200 kèm {"Success": false, ...} khi phiên/cookie hết hạn (không
    chỉ 401) — nếu chỉ kiểm tra status_code thì các API bên dưới sẽ ÂM THẦM đọc ra PageData
    rỗng và hiểu nhầm thành "chưa có đề nghị xuất HĐ" cho toàn bộ phiếu đang kiểm tra, dù
    thực tế đề nghị vẫn tồn tại trên MISA. Raise rõ ràng ở đây để lỗi phiên không bị hiểu
    nhầm thành dữ liệu hợp lệ."""
    try:
        data = resp.json()
    except ValueError:
        data = None
    if resp.status_code != 200 or not data or not data.get("Success"):
        raise Exception(
            "MISA %s lỗi (status=%s): %s" % (context, resp.status_code, (resp.text or "")[:500])
        )
    return data


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

    def _misa_invoice_result_from_request(self, req_info):
        """Bước 2+3 của luồng tra cứu: từ 1 "Đề nghị xuất hóa đơn" (req_info), tìm xem đã
        có hóa đơn thật phát sinh từ đó chưa (sa_invoice_get, lọc theo sa_invoice_request_refid)."""
        result = _empty_invoice_status()
        target_req_id = req_info.get("refid")
        target_customer = req_info.get("account_object_name")
        result['request_refid'] = target_req_id
        result['account_object_name'] = target_customer
        result['master_refno'] = (req_info.get("refno") or "").strip() or None
        result['state'] = 'requested'

        if not target_req_id or not target_customer:
            return result

        token = self._get_misa_token_cached()
        headers = self.env['misa.config'].get_default_headers(token)
        url_inv = "https://actapp.misa.vn/g2/api/sa/v1/sa_invoice_get/paging_filter_v2"
        payload_inv = self.env['misa.config'].get_invoice_full_search_payload(target_customer)
        resp_inv = self._fetch_with_retry(url_inv, headers, payload_inv)
        data_inv = _misa_json_or_raise(resp_inv, "sa_invoice_get")

        page_data_inv = data_inv.get("Data", {}).get("PageData", []) or []
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

    def get_invoice_status_for_refno(self, refno):
        """Tra tình trạng xuất hóa đơn của 1 phiếu xuất kho (refno = stock.picking.name)
        trên MISA — dùng cho kiểm tra đơn lẻ (nút trên form / gọi ngoài batch), gọi thẳng
        1 API tìm đúng refno này, không tải hàng loạt."""
        token = self._get_misa_token_cached()
        headers = self.env['misa.config'].get_default_headers(token)

        url_req = "https://actapp.misa.vn/g2/api/sa/v1/sa_invoice_request/paging_filter_v2"
        payload_req = self.env['misa.config'].get_invoice_request_payload(refno)
        resp_req = self._fetch_with_retry(url_req, headers, payload_req)
        data_req = _misa_json_or_raise(resp_req, "sa_invoice_request")

        page_data_req = data_req.get("Data", {}).get("PageData", []) or []
        if not page_data_req:
            return _empty_invoice_status()
        return self._misa_invoice_result_from_request(page_data_req[0])

    def get_invoice_request_map(self, date_from_iso=False, date_to_iso=False):
        """Tải hàng loạt "Đề nghị xuất hóa đơn" (sa_invoice_request) trong 1 khoảng ngày,
        dùng để kiểm tra nhiều phiếu cùng lúc chỉ với vài lệnh gọi thay vì 1 lệnh/phiếu.

        MISA cho phép 1 đề nghị đại diện cho NHIỀU phiếu xuất kho gộp chung (VD refno chính
        là "KBC/OUT/10935" nhưng journal_memo liệt kê thêm "KBC/OUT/10901" và "KBC/OUT/10938" —
        các phiếu này KHÔNG tự tìm ra được nếu chỉ tra theo đúng refno của chính nó). Vì vậy
        map trả về được đánh chỉ mục theo CẢ refno lẫn từng dòng trong journal_memo, để phiếu
        "ăn theo" vẫn tra đúng ra tình trạng của đề nghị đại diện."""
        token = self._get_misa_token_cached()
        headers = self.env['misa.config'].get_default_headers(token)
        url = "https://actapp.misa.vn/g2/api/sa/v1/sa_invoice_request/paging_filter_v2"

        if not date_from_iso:
            date_from_iso = "2025-12-31T17:00:00.00Z"
        if not date_to_iso:
            date_to_iso = datetime.utcnow().isoformat() + "Z"

        by_refno = {}
        memo_extra = {}
        page = 1
        while page <= MISA_INVOICE_REQUEST_MAP_MAX_PAGES:
            payload = self.env['misa.config'].get_invoice_request_bulk_payload(
                date_from_iso, date_to_iso, page_index=page, page_size=MISA_INVOICE_REQUEST_MAP_PAGE_SIZE,
            )
            resp = self._fetch_with_retry(url, headers, payload)
            # Raise thay vì log+break: nếu trang 1 lỗi mà cứ coi map rỗng là "đã tải xong",
            # toàn bộ phiếu đang kiểm tra theo lô sẽ bị hiểu nhầm thành "chưa có đề nghị" và
            # GHI ĐÈ lên trạng thái đúng đã có trước đó — thà cả lô lỗi rõ ràng (được
            # _misa_invoice_check_batch bắt lại và bỏ qua) còn hơn âm thầm sai dữ liệu.
            data = _misa_json_or_raise(resp, "sa_invoice_request (map trang %s)" % page)

            page_data = data.get("Data", {}).get("PageData", []) or []
            if not page_data:
                break

            for item in page_data:
                refno = (item.get("refno") or "").strip()
                if refno:
                    by_refno[refno] = item
                memo = item.get("journal_memo") or ""
                for line in memo.splitlines():
                    code = line.strip()
                    if code and code not in memo_extra:
                        memo_extra[code] = item

            if len(page_data) < MISA_INVOICE_REQUEST_MAP_PAGE_SIZE:
                break
            page += 1

        for code, item in memo_extra.items():
            by_refno.setdefault(code, item)
        return by_refno

    def get_invoice_status_from_map(self, refno, request_map):
        """Như get_invoice_status_for_refno() nhưng tra trong map đã tải sẵn (không gọi
        API tìm đề nghị nữa) — dùng khi kiểm tra theo lô (xem get_invoice_request_map)."""
        req_info = (request_map or {}).get(refno)
        if not req_info:
            return _empty_invoice_status()
        return self._misa_invoice_result_from_request(req_info)

    def get_invoice_request_lines(self, request_refid):
        """Chi tiết TỪNG DÒNG HÀNG (mã hàng, số lượng, đơn giá, thành tiền chưa VAT, mã đơn
        bán gốc) của 1 "Đề nghị xuất hóa đơn" theo refid — dùng để đối chiếu từng dòng sản
        phẩm giữa Odoo và MISA (xem stock_picking.get_misa_invoice_line_reconciliation).
        Phân trang y hệt get_invoice_request_map() phòng khi 1 đề nghị có rất nhiều dòng."""
        token = self._get_misa_token_cached()
        headers = self.env['misa.config'].get_default_headers(token)
        url = "https://actapp.misa.vn/g2/api/sa/v1/sa_invoice_request/get_paging_detail"

        lines = []
        page = 1
        while page <= MISA_INVOICE_REQUEST_MAP_MAX_PAGES:
            payload = self.env['misa.config'].get_invoice_request_detail_payload(
                request_refid, page_index=page, page_size=MISA_INVOICE_REQUEST_MAP_PAGE_SIZE,
            )
            resp = self._fetch_with_retry(url, headers, payload)
            data = _misa_json_or_raise(resp, "sa_invoice_request/get_paging_detail (trang %s)" % page)

            page_data = data.get("Data", {}).get("PageData", []) or []
            lines.extend(page_data)
            if len(page_data) < MISA_INVOICE_REQUEST_MAP_PAGE_SIZE:
                break
            page += 1
        return lines
