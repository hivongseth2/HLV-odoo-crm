# -*- coding: utf-8 -*-
"""Bản 18.0.1.22.0 đánh dấu 'đã đọc' cả lô tên loại dù câu trả lời của Claude bị cắt (chạm
max_tokens, JSON cụt, không lưu được cách gọi nào). Bỏ dấu để cron đọc lại."""


def migrate(cr, version):
    cr.execute("UPDATE hlv_product_name_type SET studied_at = NULL")
