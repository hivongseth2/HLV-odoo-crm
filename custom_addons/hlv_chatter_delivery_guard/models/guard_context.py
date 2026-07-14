from contextvars import ContextVar


# Server-side execution marker. Unlike an Odoo context key, it cannot be
# forged by a client RPC to bypass the standalone message deletion guard.
parent_thread_unlink = ContextVar(
    "hlv_chatter_delivery_guard_parent_thread_unlink",
    default=False,
)
