# -*- coding: utf-8 -*-
"""Gửi request Product lên MISA CRM, tự đổi cổng g1 / g2 khi một cổng lỗi máy chủ.

Mở rộng ``misa.api.utils`` ở file riêng (misa_api_utils.py đã quá dài). Quy tắc chọn cổng
nằm ở hàm thuần trong crm_gateway.
"""
import logging

from odoo import models

from .crm_gateway import crm_url, gateway_order, is_gateway_failure

_logger = logging.getLogger(__name__)

# Cổng chạy được lần gần nhất (theo process). Chỉ là gợi ý thứ tự thử, sai cũng không sao.
_last_good_gateway = {"value": None}


class MisaCrmGateway(models.AbstractModel):
    _inherit = 'misa.api.utils'

    def _crm_post(self, path, payload, headers, timeout=30):
        """POST lên ``api/business/<path>``, thử lần lượt các cổng.

        Trả ``(response, data)`` của lần thử cuối: data là body đã parse, hoặc None nếu
        body không phải JSON. Không raise vì lỗi CRM — người gọi tự đọc Success / status
        (kể cả 401 / 403 để đổi token: hết phiên thì đổi cổng cũng vô ích).

        Tạo hàng không bị nhân đôi khi thử sang cổng khác: mã hàng là duy nhất trên CRM,
        nếu cổng trước thật ra đã tạo thì cổng sau bị từ chối vì trùng mã.
        Raise lỗi mạng của lần thử cuối nếu cổng nào cũng không kết nối được.
        """
        session = self._get_retry_session()
        order = gateway_order(_last_good_gateway["value"])
        response = data = network_error = None
        for gateway in order:
            try:
                response = session.post(crm_url(gateway, path), headers=headers, json=payload, timeout=timeout)
            except Exception as error:  # noqa: BLE001 — thử cổng khác trước khi chịu thua
                _logger.warning("MISA CRM cổng %s không kết nối được (%s): %s", gateway, path, error)
                network_error = error
                continue
            network_error = None
            try:
                data = response.json()
            except ValueError:
                data = None
            if not is_gateway_failure(response.status_code, data):
                _last_good_gateway["value"] = gateway
                return response, data
            _logger.warning("MISA CRM cổng %s lỗi máy chủ (%s, HTTP %s): %s",
                            gateway, path, response.status_code, (response.text or "")[:300])
        if network_error is not None and response is None:
            raise network_error
        return response, data
