# -*- coding: utf-8 -*-
from odoo.osv import expression

# Fields the OR-per-token domain is built against, per model. Each model's
# actual field list must match the ones used by its own core search view's
# filter_domain (`ir_model_fields`/`ir_ui_view.arch_db` were checked directly
# against the DB) — a field that doesn't exist on the model would crash
# every search() call on it, so keep these two lists model-specific.
PRODUCT_SEARCH_FIELDS = ('name', 'default_code', 'barcode')
TEMPLATE_SEARCH_FIELDS = ('name', 'default_code', 'barcode', 'product_variant_ids.default_code')

ILIKE_OPERATORS = ('ilike', '=ilike', 'like')


def tokenize_or_domain(text, fields=PRODUCT_SEARCH_FIELDS):
    """Split `text` on whitespace; a record must match ALL tokens, but each
    token can match ANY of `fields` (OR). Same tokenizing logic as the
    /search_stock route (website_public_inventory_18/controllers/main.py)."""
    tokens = [t for t in text.split() if t]
    bars = ['|'] * (len(fields) - 1)
    domains_per_token = [
        bars + [(field, 'ilike', token) for field in fields]
        for token in tokens
    ]
    return expression.AND(domains_per_token) if domains_per_token else []


def _is_free_text_leaf(item, fields):
    return (
        isinstance(item, (list, tuple)) and len(item) == 3
        and item[0] in fields and item[1] in ILIKE_OPERATORS
        and isinstance(item[2], str) and ' ' in item[2].strip()
    )


def rewrite_free_text_domain(domain, fields=PRODUCT_SEARCH_FIELDS):
    """Odoo's default product search views (`product.product_search_form_view`,
    `product.product_template_search_view`) build a plain domain like
    ['|', ('default_code', 'ilike', V), ('name', 'ilike', V), ('barcode', 'ilike', V)]
    whenever a user types free text in the top search bar (this bypasses
    name_search entirely). Detect that pattern and rewrite it into a
    tokenized AND(OR-per-field) domain, so multi-word queries behave like
    OR-per-token instead of one big substring match."""
    result = []
    i, n = 0, len(domain)
    while i < n:
        item = domain[i]
        if item == '|':
            j = i
            while j < n and domain[j] == '|':
                j += 1
            leaf_count = (j - i) + 1
            leaves = domain[j:j + leaf_count]
            values = {leaf[2] for leaf in leaves if _is_free_text_leaf(leaf, fields)}
            if len(leaves) == leaf_count and len(values) == 1 and all(_is_free_text_leaf(l, fields) for l in leaves):
                result.extend(tokenize_or_domain(values.pop(), fields))
                i = j + leaf_count
                continue
        elif _is_free_text_leaf(item, fields):
            result.extend(tokenize_or_domain(item[2], fields))
            i += 1
            continue
        result.append(item)
        i += 1
    return result
