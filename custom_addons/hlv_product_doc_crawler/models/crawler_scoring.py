"""GPT QC Scoring Utility — shared across all crawler websites.

Hàm chấm điểm dùng GPT (nhẹ, ít token) để kiểm tra xem kết quả tìm kiếm
từ website bên ngoài có đúng là sản phẩm đang tìm trong Odoo.

Usage (trong Odoo model method):
    from .crawler_scoring import gpt_qc_score
    score = gpt_qc_score(api_key, odoo_name, candidate_name, model="gpt-4o-mini")
"""

import json
import logging

import requests

_logger = logging.getLogger(__name__)

# Prompt system cố định — ngắn gọn, ít token
_SYSTEM_PROMPT = (
    "Bạn là chuyên gia kiểm tra sản phẩm công nghiệp. "
    "So sánh 2 tên sản phẩm và trả về JSON {\"score\": float, \"reason\": str}. "
    "score: 0.0 (hoàn toàn khác) đến 1.0 (cùng sản phẩm). "
    "Ưu tiên: loại SP > kích thước > vật liệu > tiêu chuẩn. "
    "Chỉ trả JSON, không giải thích thêm."
)


def gpt_qc_score(api_key, odoo_name, candidate_name, model="gpt-4o-mini"):
    """Gọi OpenAI API để chấm điểm QC giữa tên SP Odoo và tên SP từ website.

    Args:
        api_key: OpenAI API key.
        odoo_name: Tên sản phẩm trong Odoo (tiếng Việt).
        candidate_name: Tên sản phẩm từ website ngoài.
        model: Model GPT (mặc định gpt-4o-mini — rẻ, nhanh).

    Returns:
        dict: {"score": float 0.0-1.0, "reason": str} hoặc None nếu lỗi.
    """
    if not api_key:
        _logger.warning("GPT QC: Thiếu API key, bỏ qua.")
        return None

    user_msg = (
        f"Sản phẩm Odoo: {odoo_name}\n"
        f"Sản phẩm website: {candidate_name}"
    )

    try:
        resp = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": _SYSTEM_PROMPT},
                    {"role": "user", "content": user_msg},
                ],
                "max_tokens": 120,
                "temperature": 0.0,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        content = data["choices"][0]["message"]["content"].strip()
        # Parse JSON from response — handle markdown code blocks
        if content.startswith("```"):
            content = content.split("```")[1]
            if content.startswith("json"):
                content = content[4:]
            content = content.strip()

        result = json.loads(content)
        score = float(result.get("score", 0.0))
        reason = str(result.get("reason", ""))
        return {"score": max(0.0, min(1.0, score)), "reason": reason}

    except requests.exceptions.Timeout:
        _logger.warning("GPT QC: timeout cho '%s' vs '%s'", odoo_name, candidate_name)
        return None
    except (json.JSONDecodeError, KeyError, ValueError) as e:
        _logger.warning("GPT QC: response parse error: %s", e)
        return None
    except requests.exceptions.RequestException as e:
        _logger.warning("GPT QC: API error: %s", e)
        return None
