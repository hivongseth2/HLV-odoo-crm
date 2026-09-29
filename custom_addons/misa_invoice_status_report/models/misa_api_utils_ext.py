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


def _normalize_inv_no(value):
    """Chuẩn hóa SỐ HÓA ĐƠN để so khớp: bỏ khoảng trắng 2 đầu và số 0 đứng đầu.

    MISA ghi inv_no đủ 8 chữ số ("00007446") ở chỗ này nhưng chỗ khác (người dùng gõ tìm, dữ
    liệu nhập tay) lại là "7446" — bỏ 0 đứng đầu để 2 dạng đó là MỘT.

    Nhận str/None/False. Trả str; '' nếu rỗng; '0' nếu chuỗi toàn số 0.
    """
    raw = (value or '').strip()
    if not raw:
        return ''
    return raw.lstrip('0') or '0'


def _pick_request_for_refno(rows, refno):
    """Chọn đúng dòng "Đề nghị xuất HĐ" cho 1 refno trong kết quả tìm kiếm của MISA.

    MISA tìm theo kiểu CHỨA trên nhiều cột cùng lúc và xếp mới nhất lên đầu, nên tìm
    "KBC/OUT/10278" ra cả "KBC/OUT/10278_1" (đề nghị bổ sung lập sau) đứng TRƯỚC đề nghị chính
    — lấy dòng đầu là gắn phiếu vào đề nghị 2,1tr thay vì đề nghị 57,4tr (case thật).

    Nhận: rows — PageData của sa_invoice_request; refno — tên phiếu/mã cần tra.
    Trả: dòng có refno trùng CHÍNH XÁC; không có thì dòng có journal_memo liệt kê đúng refno
    (phiếu ăn theo đề nghị gộp); không có nữa thì dòng đầu (tìm theo mã đơn hàng, vốn không
    bao giờ trùng refno). rows rỗng trả None.
    """
    if not rows:
        return None
    target = (refno or '').strip()
    for row in rows:
        if (row.get('refno') or '').strip() == target:
            return row
    for row in rows:
        if target in [line.strip() for line in (row.get('journal_memo') or '').splitlines()]:
            return row
    return rows[0]


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

    def _fetch_misa_json_with_session_retry(self, url, payload, context):
        """Gọi 1 API MISA (POST) và tự ĐĂNG NHẬP LẠI + gọi lại ĐÚNG 1 lần nếu request đầu tiên
        lỗi — không chỉ khi MISA trả HTTP 401 (như _fetch_with_retry đã tự xử lý sẵn), mà CẢ
        khi MISA trả lỗi khác.

        Bài học thật: MISA có lúc trả HTTP 500 "Không lấy được thông tin user <uuid>" khi
        phiên/token cache bị MISA "quên" mất phía họ — dù token CHƯA hết hạn theo đồng hồ JWT
        của mình (_get_misa_token_cached() vẫn coi là còn hạn). _fetch_with_retry() chỉ tự
        đăng nhập lại khi status=401 nên bỏ sót ĐÚNG case này — kết quả là cả 1 lô kiểm tra
        MISA (cron/nút quét) lỗi hàng loạt cho tới khi có người vào Odoo shell ép đăng nhập lại
        tay (_get_misa_token_cached(force_refresh=True)). Giờ tự làm y hệt thao tác đó, tự
        động, ngay khi gặp lỗi lần đầu — không cần chờ ai đó phát hiện và chạy tay nữa.

        Dùng cho MỌI lệnh gọi sa_invoice_request/sa_invoice_get/sa_voucher_get trong module
        này thay vì gọi thẳng _fetch_with_retry + _misa_json_or_raise."""
        token = self._get_misa_token_cached()
        headers = self.env['misa.config'].get_default_headers(token)
        resp = self._fetch_with_retry(url, headers, payload)
        try:
            return _misa_json_or_raise(resp, context)
        except Exception:
            _logger.warning(
                "🔁 [MISA] %s lỗi lần 1 (có thể do phiên/token bị MISA 'quên' dù chưa hết hạn "
                "theo đồng hồ của mình) — ép đăng nhập lại và thử lại 1 lần trước khi báo lỗi thật.",
                context,
            )
            token = self._get_misa_token_cached(force_refresh=True)
            headers = self.env['misa.config'].get_default_headers(token)
            resp = self._fetch_with_retry(url, headers, payload)
            return _misa_json_or_raise(resp, context)

    def _misa_invoice_result_from_request(self, req_info):
        """Bước 2 của luồng tra cứu: từ 1 "Đề nghị xuất hóa đơn" (req_info), xác định đã có
        hóa đơn thật phát sinh từ đó chưa.

        Đề nghị TỰ MANG SẴN số hóa đơn: dòng sa_invoice_request (view 65) trả về cả inv_no,
        inv_date, inv_series, inv_refid, invoice_status, publish_status — đúng mấy cột mà trang
        MISA hiển thị ngay trong danh sách "Đề nghị xuất hóa đơn". Nên chỉ cần đọc inv_no ở đây
        là biết đề nghị đã ra hóa đơn hay chưa, rồi tra chứng từ theo SỐ HÓA ĐƠN để lấy số tiền
        chính thức.

        TRƯỚC ĐÂY làm khác và SAI: gọi sa_invoice_get tìm hóa đơn theo TÊN KHÁCH của đề nghị
        rồi lọc client-side theo sa_invoice_request_refid. Hỏng vì tên khách trên hóa đơn có thể
        KHÁC tên khách trên đề nghị — case thật TSN/OUT/13874 (đơn DH125524949236062): đề nghị
        ghi khách 'KHÁCH WEB, ZALO TT COD J&T' còn hóa đơn 00007446 ghi 'J&T Express', nên hóa
        đơn không bao giờ nằm trong tập trả về và phiếu đứng mãi ở 'Đã đề nghị, chờ HĐ' dù hóa
        đơn đã phát hành và vẫn trỏ ĐÚNG refid của đề nghị. Đường cũ còn 2 điểm yếu nữa: chỉ đọc
        TRANG 1 (pageSize=200, không phân trang) nên khách nhiều hóa đơn là bị cắt, và tốn 1 lệnh
        gọi tải về tới 200 hóa đơn chỉ để lấy đúng 1 dòng.

        Số lệnh gọi MISA KHÔNG tăng so với cách cũ: vẫn đúng 1 lệnh, chỉ đổi khóa tra từ "tên
        khách" (không đáng tin) sang "số hóa đơn" (khóa thật).

        Đường cũ VẪN GIỮ làm dự phòng (_misa_invoice_result_from_request_by_customer) và chỉ
        dùng khi req_info KHÔNG có key 'inv_no' — tức MISA đổi view/bớt cột trả về. Không có dự
        phòng này thì một ngày MISA bỏ cột inv_no là MỌI phiếu bị hạ về 'requested' và bị XÓA
        mất số hóa đơn đúng đã lưu (guard chống mất dữ liệu trong action_check_misa_invoice_status
        không đỡ được ca này, vì đề nghị vẫn tìm ra nên request_refid vẫn có)."""
        result = _empty_invoice_status()
        result['request_refid'] = req_info.get("refid")
        result['account_object_name'] = req_info.get("account_object_name")
        result['master_refno'] = (req_info.get("refno") or "").strip() or None
        result['state'] = 'requested'

        if 'inv_no' not in req_info:
            return self._misa_invoice_result_from_request_by_customer(req_info, result)

        inv_no = (req_info.get("inv_no") or "").strip()
        if not inv_no:
            # Đề nghị chưa phát hành hóa đơn — đúng nghĩa "đã đề nghị, chờ HĐ".
            return result

        voucher = self._misa_invoice_voucher_for_inv_no(inv_no)
        if not voucher:
            # Đề nghị có ghi số hóa đơn nhưng không tra ra chứng từ (hóa đơn bị hủy/thay thế,
            # hoặc ngoài khoảng ngày tìm kiếm) — GIỮ 'requested' thay vì tự nhận đã xuất HĐ với
            # số tiền không kiểm chứng được.
            return result

        result['state'] = 'invoiced'
        result['invoice_no'] = voucher.get('inv_no') or inv_no
        result['invoice_date'] = voucher.get('inv_date') or req_info.get('inv_date')
        result['invoice_amount'] = voucher.get('total_amount')
        return result

    def _misa_invoice_result_from_request_by_customer(self, req_info, result):
        """Đường DỰ PHÒNG của _misa_invoice_result_from_request: tìm hóa đơn bằng cách tải danh
        sách hóa đơn theo TÊN KHÁCH của đề nghị rồi lọc theo sa_invoice_request_refid.

        Đây là cách làm CŨ, đã biết là không đáng tin (tên khách trên hóa đơn có thể khác tên
        trên đề nghị, và chỉ đọc trang 1 với pageSize=200) — chỉ chạy khi MISA không trả cột
        inv_no trên dòng đề nghị nữa. Có kết quả vẫn tốt hơn là hạ sạch mọi phiếu về 'requested'.
        """
        target_req_id = req_info.get("refid")
        target_customer = req_info.get("account_object_name")
        if not target_req_id or not target_customer:
            return result

        _logger.warning(
            "⚠️ [MISA INVOICE STATUS] Dòng đề nghị %s không có cột 'inv_no' — quay lại cách tra "
            "cũ theo tên khách (kém tin cậy). Kiểm tra lại view/payload sa_invoice_request.",
            req_info.get("refno"),
        )
        url_inv = "https://actapp.misa.vn/g2/api/sa/v1/sa_invoice_get/paging_filter_v2"
        payload_inv = self.env['misa.config'].get_invoice_full_search_payload(target_customer)
        data_inv = self._fetch_misa_json_with_session_retry(url_inv, payload_inv, "sa_invoice_get")

        matched_invs = [
            inv for inv in (data_inv.get("Data", {}).get("PageData", []) or [])
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
        url_req = "https://actapp.misa.vn/g2/api/sa/v1/sa_invoice_request/paging_filter_v2"
        payload_req = self.env['misa.config'].get_invoice_request_payload(refno)
        data_req = self._fetch_misa_json_with_session_retry(url_req, payload_req, "sa_invoice_request")

        page_data_req = data_req.get("Data", {}).get("PageData", []) or []
        if not page_data_req:
            return _empty_invoice_status()
        return self._misa_invoice_result_from_request(_pick_request_for_refno(page_data_req, refno))

    def get_invoice_requests_for_order(self, order_code):
        """Tìm TẤT CẢ 'Đề nghị xuất hóa đơn' có nhắc tới order_code này (không chỉ lấy đề nghị
        ĐẦU TIÊN như get_invoice_status_for_refno) — get_invoice_request_payload vốn đã search
        theo 7 property cùng lúc (đã xác nhận: truyền order_code vào đây trả về ĐÚNG các đề
        nghị MISA tự hiện khi gõ mã đơn vào ô tìm kiếm "Đơn đặt hàng").

        Dùng để phát hiện case 1 đơn hàng bị CHIA xuất hóa đơn qua NHIỀU đề nghị hoàn toàn
        RIÊNG BIỆT — case thật: KBC/OUT/10714 (đơn DH125524949233673) được xác nhận 1 phần bởi
        đề nghị KBC/OUT/10677 (refid e1e15df5...), phần còn lại bởi KBC/OUT/10877 (refid
        024dc159...) — 2 refid HOÀN TOÀN khác nhau, không phải cùng 1 voucher bị trùng tên.

        Trả về list [{refno, refid, inv_no}, ...] — refid để gọi tiếp get_invoice_request_lines;
        inv_no là số HĐ đã phát hành ('' nếu chưa), None nếu MISA không trả cột này (nơi dùng
        inv_no phải coi là "không biết", không phải "chưa phát hành")."""
        url_req = "https://actapp.misa.vn/g2/api/sa/v1/sa_invoice_request/paging_filter_v2"
        payload_req = self.env['misa.config'].get_invoice_request_payload(order_code)
        data_req = self._fetch_misa_json_with_session_retry(
            url_req, payload_req, "sa_invoice_request (search theo order)",
        )
        page_data_req = data_req.get("Data", {}).get("PageData", []) or []
        return [
            {
                'refno': (item.get('refno') or '').strip(), 'refid': item.get('refid'),
                'inv_no': (item.get('inv_no') or '').strip() if 'inv_no' in item else None,
            }
            for item in page_data_req if item.get('refid')
        ]

    def get_invoice_request_map(self, date_from_iso=False, date_to_iso=False):
        """Tải hàng loạt "Đề nghị xuất hóa đơn" (sa_invoice_request) trong 1 khoảng ngày,
        dùng để kiểm tra nhiều phiếu cùng lúc chỉ với vài lệnh gọi thay vì 1 lệnh/phiếu.

        MISA cho phép 1 đề nghị đại diện cho NHIỀU phiếu xuất kho gộp chung (VD refno chính
        là "KBC/OUT/10935" nhưng journal_memo liệt kê thêm "KBC/OUT/10901" và "KBC/OUT/10938" —
        các phiếu này KHÔNG tự tìm ra được nếu chỉ tra theo đúng refno của chính nó). Vì vậy
        map trả về được đánh chỉ mục theo CẢ refno lẫn từng dòng trong journal_memo, để phiếu
        "ăn theo" vẫn tra đúng ra tình trạng của đề nghị đại diện."""
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
            # Raise thay vì log+break: nếu trang 1 lỗi mà cứ coi map rỗng là "đã tải xong",
            # toàn bộ phiếu đang kiểm tra theo lô sẽ bị hiểu nhầm thành "chưa có đề nghị" và
            # GHI ĐÈ lên trạng thái đúng đã có trước đó — thà cả lô lỗi rõ ràng (được
            # _misa_invoice_check_batch bắt lại và bỏ qua) còn hơn âm thầm sai dữ liệu.
            data = self._fetch_misa_json_with_session_retry(
                url, payload, "sa_invoice_request (map trang %s)" % page,
            )

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
        url = "https://actapp.misa.vn/g2/api/sa/v1/sa_invoice_request/get_paging_detail"

        lines = []
        page = 1
        while page <= MISA_INVOICE_REQUEST_MAP_MAX_PAGES:
            payload = self.env['misa.config'].get_invoice_request_detail_payload(
                request_refid, page_index=page, page_size=MISA_INVOICE_REQUEST_MAP_PAGE_SIZE,
            )
            data = self._fetch_misa_json_with_session_retry(
                url, payload, "sa_invoice_request/get_paging_detail (trang %s)" % page,
            )

            page_data = data.get("Data", {}).get("PageData", []) or []
            lines.extend(page_data)
            if len(page_data) < MISA_INVOICE_REQUEST_MAP_PAGE_SIZE:
                break
            page += 1
        return lines

    def get_vouchers_by_inv_no(self, inv_no):
        """TẤT CẢ chứng từ bán hàng (sa_voucher_get) mà MISA trả về khi tìm theo SỐ HÓA ĐƠN.

        get_voucher_search_payload() tìm theo kiểu CHỨA (operator 1) trên 4 property cùng lúc,
        nên 1 số hóa đơn có thể ra NHIỀU dòng: số hóa đơn khác cùng chứa chuỗi này (gõ "005309"
        ra cả "1005309"), hoặc chính hóa đơn đó tồn tại nhiều bản (thay thế/điều chỉnh). Hàm
        này trả nguyên list để nơi gọi tự lọc/hiển thị hết; cần đúng 1 chứng từ thì dùng
        _misa_invoice_voucher_for_inv_no() bên dưới (lọc khớp chính xác số hóa đơn)."""
        url = "https://actapp.misa.vn/g2/api/sa/v1/sa_voucher_get/paging_filter_v2"
        payload = self.env['misa.config'].get_voucher_search_payload(inv_no)
        data = self._fetch_misa_json_with_session_retry(url, payload, "sa_voucher_get")
        return data.get("Data", {}).get("PageData", []) or []

    def _misa_invoice_voucher_for_inv_no(self, inv_no):
        """Chứng từ bán hàng khớp CHÍNH XÁC số hóa đơn này, hoặc None.

        get_voucher_search_payload tìm theo kiểu CHỨA trên 4 property cùng lúc nên 1 lần gọi có
        thể trả nhiều chứng từ mang số hóa đơn khác (gõ "005309" ra cả "1005309"). Lấy page
        đầu tiên mà không lọc là có ngày gán tiền của hóa đơn NGƯỜI KHÁC lên phiếu — nên phải
        lọc đúng số rồi mới dùng.

        Trả None khi không có dòng nào khớp chính xác (kể cả khi MISA vẫn trả về dòng gần giống).
        """
        target = _normalize_inv_no(inv_no)
        if not target:
            return None
        for row in self.get_vouchers_by_inv_no(inv_no):
            if _normalize_inv_no(row.get('inv_no')) == target:
                return row
        return None

    def get_voucher_lines(self, refid):
        """Chi tiết TỪNG DÒNG HÀNG (mã đơn hàng gốc order_code, mã hàng, số lượng, tiền) của
        1 chứng từ bán hàng theo refid — cho biết CHÍNH XÁC đơn hàng nào + mã hàng nào đã
        được hóa đơn này bao phủ (1 hóa đơn có thể gộp nhiều đơn, và có thể chỉ phủ MỘT PHẦN
        1 đơn nếu xuất kho nhiều đợt)."""
        url = "https://actapp.misa.vn/g2/api/sa/v1/sa_voucher_get/get_paging_detail"

        lines = []
        page = 1
        while page <= MISA_INVOICE_REQUEST_MAP_MAX_PAGES:
            payload = self.env['misa.config'].get_voucher_detail_payload(
                refid, page_index=page, page_size=MISA_INVOICE_REQUEST_MAP_PAGE_SIZE,
            )
            data = self._fetch_misa_json_with_session_retry(
                url, payload, "sa_voucher_get/get_paging_detail (trang %s)" % page,
            )

            page_data = data.get("Data", {}).get("PageData", []) or []
            lines.extend(page_data)
            if len(page_data) < MISA_INVOICE_REQUEST_MAP_PAGE_SIZE:
                break
            page += 1
        return lines
