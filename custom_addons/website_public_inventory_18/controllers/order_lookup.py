# -*- coding: utf-8 -*-
import logging
import math
import time
from collections import defaultdict
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# ===== CONFIGURATION =====
PAGE_SIZE = 20
RATE_LIMIT_REQUESTS = 30
RATE_LIMIT_WINDOW = 300  # 5 minutes in seconds

# In-memory rate limiting (simple fallback; for production use Redis or ir.cache)
# TODO: Replace with Redis or Odoo caching for multi-worker environments
_rate_limit_store = defaultdict(list)


# ===== RATE LIMITING =====
def _rate_limit_check(ip):
    """
    Simple in-memory rate limiter.
    Allow RATE_LIMIT_REQUESTS requests per RATE_LIMIT_WINDOW seconds per IP.
    Returns True if allowed, False if rate limit exceeded.
    """
    global _rate_limit_store
    now = time.time()
    
    # Clean old entries
    _rate_limit_store[ip] = [t for t in _rate_limit_store[ip] if now - t < RATE_LIMIT_WINDOW]
    
    # Check limit
    if len(_rate_limit_store[ip]) >= RATE_LIMIT_REQUESTS:
        _logger.warning("Rate limit exceeded for IP: %s (masked)", _mask_ip_for_log(ip))
        return False
    
    # Add current request
    _rate_limit_store[ip].append(now)
    return True


def _mask_ip_for_log(ip):
    """Mask IP address for logging to avoid PII leakage."""
    if not ip:
        return "unknown"
    parts = str(ip).split('.')
    if len(parts) == 4:
        return f"{parts[0]}.{parts[1]}.***.**"
    return "***"


# ===== PII MASKING HELPERS =====
def _mask_name(name):
    """
    Mask individual names, keep company names as-is.
    Company names are considered less sensitive PII.
    """
    if not name:
        return ""
    
    name = name.strip()
    
    # Company indicators
    company_indicators = [
        'công ty', 'cty', 'company', 'co.', 'ltd', 'tnhh', 
        'cổ phần', 'corporation', 'corp'
    ]
    
    name_lower = name.lower()
    is_company = any(indicator in name_lower for indicator in company_indicators)
    
    if is_company:
        return name  # Keep company name fully visible
    
    # Mask individual names
    words = name.split()
    masked_words = []
    
    for word in words:
        if len(word) == 1:
            masked_words.append(word)
        else:
            masked = word[0] + '*' * (len(word) - 1)
            masked_words.append(masked)
    
    return ' '.join(masked_words)

def _mask_phone(phone):
    """
    Mask phone: keep last 3 digits, mask rest with *.
    Example: "0987654321" → "*******321"
    """
    if not phone:
        return ""
    
    phone_str = str(phone).strip()
    if len(phone_str) <= 3:
        return phone_str
    
    return '*' * (len(phone_str) - 3) + phone_str[-3:]


def _mask_email(email):
    """
    Mask email: keep first char and domain, mask rest of local part with *.
    Example: "jessie.nguyen@gmail.com" → "j********@gmail.com"
    """
    if not email:
        return ""
    
    email_str = str(email).strip()
    if '@' not in email_str:
        return email_str
    
    local, domain = email_str.split('@', 1)
    if len(local) <= 1:
        return email_str
    
    masked_local = local[0] + '*' * (len(local) - 1)
    return f"{masked_local}@{domain}"


def _mask_address(address):
    """
    Mask address: mask street, keep ward/district/city.
    Handles both structured and unstructured addresses.
    
    Examples:
    - "123 Đường ABC, P.5, Q.3, HCM" → "***, P.5, Q.3, HCM"
    - "123 Nguyen Trai Street, Ward 5, District 3, HCMC" → "***, Ward 5, District 3, HCMC"
    - "Simple address" → "***"
    """
    if not address:
        return ""
    
    address_str = str(address).strip()
    
    # Split by comma
    parts = [p.strip() for p in address_str.split(',')]
    
    if len(parts) == 0:
        return ""
    
    # If only one part (no commas), mask everything
    if len(parts) == 1:
        # For single part, mask it entirely
        return "***"
    
    # Mask first part (street/detailed address)
    masked_parts = ['***']
    
    # Keep remaining parts (ward, district, city, country)
    # These usually contain administrative divisions that are less sensitive
    if len(parts) > 1:
        masked_parts.extend(parts[1:])
    
    return ', '.join(masked_parts)


# ===== SEARCH HELPERS =====
def _extract_order_code_search(order_code_input):
    """
    Extract order code for searching.
    Supports both full order code and last 6 digits.
    
    Examples:
    - "S00012" → search by "S00012" (full)
    - "000012" → search by "%000012" (last 6 digits)
    - "S" → search by "S" (as-is)
    """
    if not order_code_input:
        return None
    
    code_str = str(order_code_input).strip()
    
    # If input contains only digits and <= 6 digits, treat as last 6 digits search
    digits_only = ''.join(c for c in code_str if c.isdigit())
    non_digits = ''.join(c for c in code_str if not c.isdigit())
    
    # If it's pure digits (max 6), search by last 6 digits (suffix match)
    if not non_digits and len(digits_only) <= 6:
        # Return tuple (search_type, value)
        return ('last6', digits_only)
    
    # Otherwise, search by full code (includes letters like "S")
    return ('full', code_str)


def _build_search_domain(order_code, phone, email):
    """
    Build search domain for sale.order based on provided filters.
    Returns domain list.
    
    Supports:
    - order_code: Full order code or last 6 digits (auto-detect)
    - phone: Full phone number
    - email: Email search
    """
    domain = []
    
    # Search by order code (auto-detect full vs last 6 digits)
    if order_code:
        search_result = _extract_order_code_search(order_code)
        if search_result:
            search_type, search_value = search_result
            if search_type == 'last6':
                # Last 6 digits search
                order_code_domain = [('name', '=like', f'%{search_value}')]
            else:
                # Full code search
                order_code_domain = [('name', 'ilike', search_value)]
            
            if domain:
                domain = ['&'] + domain + order_code_domain
            else:
                domain = order_code_domain
    
    # Search by full phone number
    if phone:
        phone_domain = [
            '|',
            ('partner_id.phone', 'ilike', phone.strip()),
            ('partner_id.mobile', 'ilike', phone.strip()),
        ]
        if domain:
            domain = ['&'] + domain + phone_domain
        else:
            domain = phone_domain
    
    # Search by email
    if email:
        email_domain = [('partner_id.email', 'ilike', email.strip())]
        if domain:
            domain = ['&'] + domain + email_domain
        else:
            domain = email_domain
    
    # Only show orders in valid states
    state_domain = [('state', 'in', ['draft', 'sent', 'sale', 'done', 'cancel'])]
    if domain:
        domain = ['&'] + domain + state_domain
    else:
        domain = state_domain
    
    return domain


def _get_combo_product_display(order_line):
    """
    Get product display for combo products.
    Returns a string like "Product A (Combo: X, Y, Z)"
    """
    product = order_line.product_id
    if not product or not hasattr(product.product_tmpl_id, 'is_combo'):
        return product.name if product else ""
    
    # Check if it's a combo
    if not getattr(product.product_tmpl_id, 'is_combo', False):
        return product.name
    
    # Get combo components
    try:
        ComboLine = request.env['combo.product'].sudo()
        combo_lines = ComboLine.search([
            ('product_template_id', '=', product.product_tmpl_id.id)
        ])
        
        if combo_lines:
            component_names = [line.product_id.name for line in combo_lines if line.product_id]
            if component_names:
                components_str = ", ".join(component_names)  # Show all components
                return f"{product.name} (Combo: {components_str})"
    except Exception as e:
        _logger.debug(f"Could not fetch combo components: {e}")
    
    return product.name


def _get_order_products_summary(order):
    """
    Get a summary of products in the order, respecting combo logic.
    Returns a string summarizing all products.
    """
    if not order.order_line:
        return ""
    
    product_names = []
    for line in order.order_line:  # Show all products
        product_names.append(_get_combo_product_display(line))
    
    summary = ", ".join(product_names)
    return summary


def _get_delivery_status(order):
    """
    Get delivery status for an order.
    Returns: 'delivered', 'partial', 'pending', 'no_delivery', or ''
    """
    if not order.picking_ids:
        return 'no_delivery'
    
    pickings = order.picking_ids.filtered(lambda p: p.state != 'cancel')
    if not pickings:
        return 'no_delivery'
    
    done_count = len(pickings.filtered(lambda p: p.state == 'done'))
    total_count = len(pickings)
    
    if done_count == total_count:
        return 'delivered'
    elif done_count > 0:
        return 'partial'
    else:
        return 'pending'


def _get_payment_status(order):
    """
    Get payment status for an order.
    Returns: 'paid', 'partial', 'unpaid', or ''
    """
    if not order.invoice_ids:
        return 'unpaid'
    
    invoices = order.invoice_ids.filtered(
        lambda inv: inv.state not in ['cancel', 'draft'] and inv.move_type == 'out_invoice'
    )
    
    if not invoices:
        return 'unpaid'
    
    total_paid = sum(inv.amount_total for inv in invoices.filtered(lambda i: i.payment_state == 'paid'))
    total_amount = sum(inv.amount_total for inv in invoices)
    
    if total_paid >= total_amount and total_amount > 0:
        return 'paid'
    elif total_paid > 0:
        return 'partial'
    else:
        return 'unpaid'


def _get_order_lines(order):
    """
    Build order lines payload with VAT-included amounts.
    Returns: list of dicts for rendering.
    """
    order_lines = []
    if not order.order_line:
        return order_lines

    # ---- Chuẩn bị mapping combo (như code cũ) ----
    component_to_parent_map = {}
    parent_combo_lines = {}

    for line in order.order_line:
        product = line.product_id
        if product and hasattr(product.product_tmpl_id, 'is_combo'):
            if getattr(product.product_tmpl_id, 'is_combo', False):
                parent_combo_lines[line.id] = line
                ComboLine = request.env['combo.product'].sudo()
                combo_lines = ComboLine.search([
                    ('product_template_id', '=', product.product_tmpl_id.id)
                ])
                for combo_line in combo_lines:
                    if combo_line.product_id:
                        component_to_parent_map[combo_line.product_id.id] = line.id

    currency = order.currency_id
    partner = order.partner_id

    for line in order.order_line:
        product = line.product_id
        product_name = product.name if product else ""
        is_combo = False
        is_component = False
        parent_combo_name = ""
        is_fully_delivered = False
        
        if product and not product.active:
            continue

        # component?
        if product and product.id in component_to_parent_map:
            is_component = True
            parent_line_id = component_to_parent_map[product.id]
            if parent_line_id in parent_combo_lines:
                parent_line = parent_combo_lines[parent_line_id]
                parent_combo_name = parent_line.product_id.name if parent_line.product_id else ""

        # combo parent?
        if product and hasattr(product.product_tmpl_id, 'is_combo') and getattr(product.product_tmpl_id, 'is_combo', False):
            is_combo = True
            # check all components delivered
            all_components_delivered = True
            for check_line in order.order_line:
                check_product = check_line.product_id
                if check_product and check_product.id in component_to_parent_map:
                    if component_to_parent_map[check_product.id] == line.id:
                        qty_ordered = check_line.product_uom_qty or 0
                        qty_delivered = check_line.qty_delivered or 0
                        if qty_delivered < qty_ordered:
                            all_components_delivered = False
            is_fully_delivered = all_components_delivered
        else:
            qty_ordered = line.product_uom_qty or 0
            qty_delivered = line.qty_delivered or 0
            if qty_ordered > 0 and qty_delivered >= qty_ordered:
                is_fully_delivered = True

        # ====== TÍNH TIỀN ĐÃ GỒM VAT (per-line) ======
        qty = float(line.product_uom_qty or 0.0)
        # 1) ưu tiên field có sẵn trên line
        ltotal_inc = (getattr(line, 'price_total', None))
        ltax = getattr(line, 'price_tax', None)

        if ltotal_inc is None or ltotal_inc == 0.0:
            # 2) tính qua compute_all để chính xác (kể cả thuế price_include/khác %)
            try:
                tax_res = line.tax_id._origin.compute_all(
                    line.price_unit,
                    currency=currency,
                    quantity=qty or 1.0,  # quantity=0 thì total_included=0
                    product=product,
                    partner=partner
                ) if line.tax_id else None
            except Exception:
                tax_res = None

            if tax_res and isinstance(tax_res, dict):
                ltotal_inc = float(tax_res.get('total_included', 0.0))
                total_excl = float(tax_res.get('total_excluded', 0.0))
                ltax = ltotal_inc - total_excl

        # 3) fallback cộng tay
        if not ltotal_inc:
            ltotal_inc = float(line.price_subtotal or 0.0) + float(ltax or 0.0)

        # 4) fallback cuối cùng (không có thuế)
        if not ltotal_inc:
            ltotal_inc = float(line.price_subtotal or 0.0)

        # Đơn giá đã VAT (an toàn khi qty=0)
        unit_inc = (ltotal_inc / qty) if qty else float(line.price_unit or 0.0)

        order_lines.append({
            'product_name': product_name,
            'description': line.name or "",
            'qty': line.product_uom_qty,
            'qty_delivered': line.qty_delivered,
            'uom': line.product_uom.name if line.product_uom else 'cái',

            # Giá/thuế gốc để tham khảo
            'price_unit': line.price_unit,
            'price_subtotal': line.price_subtotal,

            # ===== Giá đã gồm VAT trả ra để template dùng =====
            'price_total': ltotal_inc,     # THÀNH TIỀN đã VAT
            'price_tax': ltax or (ltotal_inc - float(line.price_subtotal or 0.0)),
            'unit_price_inc': unit_inc,    # ĐƠN GIÁ đã VAT

            'is_combo': is_combo,
            'is_component': is_component,
            'parent_combo_name': parent_combo_name,
            'is_fully_delivered': is_fully_delivered,
        })

    return order_lines


# ===== CONTROLLER =====
class OrderLookupController(http.Controller):
    
    @http.route(['/saleorder-lookup'], type='http', auth='public', website=True, csrf=False, sitemap=True)
    def order_lookup(self, order_code="", phone="", email="", page=1, **kw):
        """
        Public sales order lookup page.
        GET: Show search form
        POST/GET with params: Perform search and show results
        
        Parameters:
        - order_code: Order code (full like "S00012" or last 6 digits like "000012")
        - phone: Full phone number (e.g., "0987654321")
        - email: Customer email
        - page: Page number
        """
        # Rate limiting
        # ip = request.httprequest.environ.get('REMOTE_ADDR', 'unknown')
        # if not _rate_limit_check(ip):
        #     return request.render('website_public_inventory_18.order_lookup_page', {
        #         'error': 'rate_limit',
        #         'error_message': 'Bạn đã vượt quá giới hạn số lần tra cứu. Vui lòng thử lại sau 5 phút.',
        #     })
        
        # Sanitize inputs
        order_code = (order_code or "").strip()
        phone = (phone or "").strip()
        email = (email or "").strip()
        
        try:
            page = int(page or 1)
            if page < 1:
                page = 1
        except (ValueError, TypeError):
            page = 1
        
        # Log search attempt (masked)
        if order_code or phone or email:
            _logger.info(
                "Order lookup: order_code=%s, phone=%s, email=%s",
                "***" if order_code else "",
                "***" if phone else "",
                "***" if email else ""
            )
        
        # Build search domain
        if not (order_code or phone or email):
            # No search criteria, just show form
            return request.render('website_public_inventory_18.order_lookup_page', {
                'query': {
                    'order_code': order_code,
                    'phone': phone,
                    'email': email,
                },
                'records': [],
                'masked_results': [],
                'page': page,
                'page_count': 0,
                'total': 0,
            })
        
        domain = _build_search_domain(order_code, phone, email)
        
        # Search orders
        SaleOrder = request.env['sale.order'].sudo()
        
        # Get total count
        total = SaleOrder.search_count(domain)
        page_count = max(1, math.ceil(total / PAGE_SIZE)) if total > 0 else 1
        
        # Ensure page is within bounds
        if page > page_count:
            page = page_count
        
        # Get orders for current page
        offset = (page - 1) * PAGE_SIZE
        orders = SaleOrder.search(
            domain,
            limit=PAGE_SIZE,
            offset=offset,
            order='date_order desc, id desc'
        )
        
        # Prepare masked results
        masked_results = []
        for order in orders:
            partner = order.partner_id
            
            # Mask PII
            masked_name = _mask_name(partner.name) if partner.name else ""
            masked_phone = _mask_phone(partner.phone or partner.mobile or "")
            masked_email = _mask_email(partner.email) if partner.email else ""
            
            # Build full address and mask it
            # Case 1: If street already contains commas (imported full address), use it directly
            # Case 2: If fields are separated, build from parts
            full_address = ""
            if partner.street and ',' in partner.street:
                # Address already formatted with commas (e.g., from PO import)
                full_address = partner.street
                # Append additional parts if they exist and not already in street
                if partner.street2 and partner.street2 not in partner.street:
                    full_address += f", {partner.street2}"
                if partner.city and partner.city not in partner.street:
                    full_address += f", {partner.city}"
            else:
                # Build from separate fields
                address_parts = []
                if partner.street:
                    address_parts.append(partner.street)
                if partner.street2:
                    address_parts.append(partner.street2)
                if partner.city:
                    address_parts.append(partner.city)
                if partner.state_id:
                    address_parts.append(partner.state_id.name)
                if partner.country_id:
                    address_parts.append(partner.country_id.name)
                full_address = ", ".join(address_parts) if address_parts else ""
            
            masked_address = _mask_address(full_address) if full_address else ""
            
            # Get order info
            products_summary = _get_order_products_summary(order)
            delivery_status = _get_delivery_status(order)
            payment_status = _get_payment_status(order)
            order_lines = _get_order_lines(order)
            
            masked_results.append({
                'id': order.id,
                'name': order.name,
                'date_order': order.date_order,
                'state': order.state,
                'customer_name': masked_name,
                'customer_phone': masked_phone,
                'customer_email': masked_email,
                'customer_address': masked_address,
                'products_summary': products_summary,
                'order_lines': order_lines,
                'amount_total': order.amount_total,
                'amount_untaxed': order.amount_untaxed,
                'amount_tax': order.amount_tax,
                'currency': order.currency_id.name if order.currency_id else 'VND',
                'delivery_status': delivery_status,
                'payment_status': payment_status,
            })
        
        return request.render('website_public_inventory_18.order_lookup_page', {
            'query': {
                'order_code': order_code,
                'phone': phone,
                'email': email,
            },
            'records': orders,
            'masked_results': masked_results,
            'page': page,
            'page_count': page_count,
            'total': total,
            'search_warning': total > 1 and order_code,  # Warning if multiple results from order code search
        })
    
    @http.route(['/saleorder-lookup/<int:order_id>'], type='http', auth='public', website=True, csrf=False)
    def order_detail(self, order_id, **kw):
        """
        Public sales order detail page.
        Shows detailed information for a specific order.
        
        Parameters:
        - order_id: Sale order ID
        """
        # Get order
        SaleOrder = request.env['sale.order'].sudo()
        order = SaleOrder.browse(order_id)
        
        # Check if order exists
        if not order.exists():
            return request.render('website.404')
        
        partner = order.partner_id
        
        # Mask PII
        masked_name = _mask_name(partner.name) if partner.name else ""
        masked_phone = _mask_phone(partner.phone or partner.mobile or "")
        masked_email = _mask_email(partner.email) if partner.email else ""
        
        # Build full address and mask it
        full_address = ""
        if partner.street and ',' in partner.street:
            full_address = partner.street
            if partner.street2 and partner.street2 not in partner.street:
                full_address += f", {partner.street2}"
            if partner.city and partner.city not in partner.street:
                full_address += f", {partner.city}"
        else:
            address_parts = []
            if partner.street:
                address_parts.append(partner.street)
            if partner.street2:
                address_parts.append(partner.street2)
            if partner.city:
                address_parts.append(partner.city)
            if partner.state_id:
                address_parts.append(partner.state_id.name)
            if partner.country_id:
                address_parts.append(partner.country_id.name)
            full_address = ", ".join(address_parts) if address_parts else ""
        
        masked_address = _mask_address(full_address) if full_address else ""
        
        # Get order info
        delivery_status = _get_delivery_status(order)
        payment_status = _get_payment_status(order)
        order_lines = _get_order_lines(order)
        
        order_data = {
            'id': order.id,
            'name': order.name,
            'date_order': order.date_order,
            'state': order.state,
            'customer_name': masked_name,
            'customer_phone': masked_phone,
            'customer_email': masked_email,
            'customer_address': masked_address,
            'order_lines': order_lines,
            'amount_total': order.amount_total,
            'amount_untaxed': order.amount_untaxed,
            'amount_tax': order.amount_tax,
            'currency': order.currency_id.name if order.currency_id else 'VND',
            'delivery_status': delivery_status,
            'payment_status': payment_status,
        }
        
        return request.render('website_public_inventory_18.order_detail_page', {
            'order': order_data,
        })
