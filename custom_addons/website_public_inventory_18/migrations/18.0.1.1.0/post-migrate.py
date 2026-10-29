"""Gỡ chatbot AI cũ của trang tra tồn: xoá tham số cấu hình của nó. Code đã bỏ, nhưng tham số
(trong đó có khoá API OpenAI) không có xmlid nên Odoo không tự xoá khi nâng cấp."""
import logging

_logger = logging.getLogger(__name__)

CHATBOT_PARAMS = (
    "website_public_inventory_18.chatbot_enabled",
    "website_public_inventory_18.chatbot_max_tokens",
    "website_public_inventory_18.chatbot_temperature",
    "website_public_inventory_18.openai_api_key",
    "website_public_inventory_18.openai_model",
    "website_public_inventory_18.product_vector_store_id",
    "website_public_inventory_18.web_search_enabled",
)


def migrate(cr, version):
    cr.execute("DELETE FROM ir_config_parameter WHERE key IN %s", (CHATBOT_PARAMS,))
    _logger.info("Đã xoá %s tham số của chatbot cũ", cr.rowcount)
