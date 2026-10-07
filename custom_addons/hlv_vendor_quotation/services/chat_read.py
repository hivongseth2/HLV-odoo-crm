# -*- coding: utf-8 -*-
"""Đã xem / chưa xem trên các cuộc trao đổi với NCC (mốc lưu ở hlv.vendor.chat.read).

reader là res.users (người xem trang sale) hoặc hlv.vendor.quote.access (link NCC). "Tin
chưa xem" là tin của BÊN KIA sau mốc của reader: sale đếm tin NCC, NCC đếm tin bên mua.
Ghi mốc bằng sudo: NCC là khách công khai, sale không có quyền trên model mốc.
"""

from .vendor_chat import chat_messages

READ_MODEL = "hlv.vendor.chat.read"


def _is_vendor(reader):
    return reader._name == "hlv.vendor.quote.access"


def _reader_field(reader):
    return "access_id" if _is_vendor(reader) else "user_id"


def _key(record):
    return (record._name, record.id)


def seen_markers(records, reader):
    """{(model, id): id tin cuối đã xem} cho các record (list, được lẫn model) đã mở ít
    nhất một lần. Record chưa mở không có trong dict."""
    if not records:
        return {}
    Read = reader.env[READ_MODEL].sudo()
    by_model = {}
    for record in records:
        by_model.setdefault(record._name, []).append(record.id)
    domain = [(_reader_field(reader), "=", reader.id)]
    markers = {}
    for model, ids in by_model.items():
        for read in Read.search(domain + [("res_model", "=", model), ("res_id", "in", ids)]):
            key = (read.res_model, read.res_id)
            markers[key] = max(markers.get(key, 0), read.last_message_id)
    return markers


def mark_seen(records, reader):
    """Đánh dấu reader đã xem hết tin hiện có trên các record (mốc chỉ tiến, không lùi)."""
    Read = reader.env[READ_MODEL].sudo()
    field = _reader_field(reader)
    for record in records:
        messages = chat_messages(record)
        last_id = messages[-1]["id"] if messages else 0
        read = Read.search([
            (field, "=", reader.id), ("res_model", "=", record._name), ("res_id", "=", record.id),
        ], limit=1)
        if not read:
            Read.create({field: reader.id, "res_model": record._name, "res_id": record.id,
                         "last_message_id": last_id})
        elif read.last_message_id < last_id:
            read.last_message_id = last_id


def unread_messages(record, reader, markers, messages=None):
    """Tin của bên kia trên record mà reader chưa xem (markers: kết quả seen_markers;
    messages: chat_messages(record) nếu đã có sẵn)."""
    seen_id = markers.get(_key(record), 0)
    other_side_is_vendor = not _is_vendor(reader)
    return [
        message for message in (chat_messages(record) if messages is None else messages)
        if message["from_vendor"] == other_side_is_vendor and message["id"] > seen_id
    ]


def chat_stats(record, reader, markers=None):
    """(tổng số tin, số tin bên kia reader chưa xem) — cho badge "N tin mới"."""
    markers = seen_markers([record], reader) if markers is None else markers
    messages = chat_messages(record)
    return len(messages), len(unread_messages(record, reader, markers, messages))


def is_seen(record, markers):
    """reader đã mở record này lần nào chưa (markers của chính reader)."""
    return _key(record) in markers
