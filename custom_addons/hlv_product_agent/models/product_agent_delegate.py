# -*- coding: utf-8 -*-
"""Model phụ (mặc định Haiku) chạy việc tra cứu mà model chính giao qua giao_viec_tra_cuu.

Chỉ ở chế độ Claude API. Model phụ chỉ có tool tra cứu Odoo CHỈ ĐỌC — không tool tạo / sửa
MISA, không đọc web — nên dù nhiệm vụ bị cài chữ lạ cũng không ghi được gì. Kết quả trả về
model chính là bản tóm tắt chữ, không phải dữ liệu thô: đó là chỗ tiết kiệm token.
"""
import logging
import time

from odoo import models

from ..services.claude_api_payload import (
    WORKER_EFFORT, WORKER_MAX_TOKENS, WORKER_SYSTEM, history_content, reply_text,
    request_extras, tool_result, tool_uses, worker_tools,
)
from .product_agent_api_runner import TurnFailed

_logger = logging.getLogger(__name__)

WORKER_MAX_STEPS = 8
WORKER_DEADLINE_SECONDS = 150
TASK_MAX_CHARS = 2000


class HlvProductAgentDelegate(models.AbstractModel):
    _name = 'hlv.product.agent.delegate'
    _description = "Model phụ tra cứu cho trợ lý (Claude API)"

    def run_task(self, session, task, config, anthropic, client):
        """Chạy một nhiệm vụ tra cứu. Trả dict tool_result cho model chính, luôn có 'status'.

        Lỗi của model phụ (API lỗi, quá bước) trả status 'error' chứ không raise: model chính
        vẫn trả lời được người dùng, hoặc tự tra bằng tool nhẹ.
        """
        task = (task or '').strip()
        if not task:
            return {'status': 'error', 'message': "Thiếu nhiem_vu."}
        Runner = self.env['hlv.product.agent.api.runner']
        Queries = self.env['hlv.product.agent.queries']
        model = config['worker_model']
        params = dict(
            model=model, max_tokens=WORKER_MAX_TOKENS, system=WORKER_SYSTEM, tools=worker_tools(),
            thinking={'type': 'adaptive'}, output_config={'effort': WORKER_EFFORT},
            cache_control={'type': 'ephemeral'}, **request_extras(model),
        )
        messages = [{'role': 'user', 'content': task[:TASK_MAX_CHARS]}]
        started = time.monotonic()
        try:
            for _step in range(WORKER_MAX_STEPS):
                if time.monotonic() - started > WORKER_DEADLINE_SECONDS:
                    raise TurnFailed("trợ lý phụ tra quá %s giây" % WORKER_DEADLINE_SECONDS)
                response = Runner._request(anthropic, client, params, messages, stale_ok=False)
                Runner._record_usage(session, response)
                content = history_content(response.to_dict(mode='json').get('content'))
                messages.append({'role': 'assistant', 'content': content})
                calls = tool_uses(content)
                if response.stop_reason == 'tool_use' and calls:
                    messages.append({'role': 'user', 'content': [
                        tool_result(call['id'], Queries.run(call.get('name'), call.get('input') or {}))
                        for call in calls
                    ]})
                    continue
                answer = reply_text(content)
                if response.stop_reason == 'refusal' or not answer:
                    raise TurnFailed("trợ lý phụ không trả lời được")
                return {'status': 'success', 'ket_qua': answer}
            raise TurnFailed("trợ lý phụ gọi tool quá %s lần" % WORKER_MAX_STEPS)
        except TurnFailed as failure:
            _logger.info("PRODUCT_AGENT model phụ cuộc %s lỗi: %s", session.id, failure)
            return {'status': 'error', 'message': "Tra cứu không xong (%s). Tự tra bằng tool nhẹ "
                                                  "hoặc báo người dùng." % failure}
