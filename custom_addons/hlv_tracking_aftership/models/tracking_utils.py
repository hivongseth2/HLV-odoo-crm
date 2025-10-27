# -*- coding: utf-8 -*-
import re
import logging

_logger = logging.getLogger(__name__)

# Mapping carrier slug for AfterShip
CARRIER_PATTERNS = {
    # SPX (Shopee Express)
    'spx-vn': [
        r'^SPX',
        r'^SPXVN',
    ],
    # J&T Express
    'jtexpress-vn': [
        r'^JT',
        r'^JTEXP',
    ],
    # Viettel Post
    'viettelpost-vn': [
        r'^VT',
        r'^VTTP',
    ],
    # GHN (Giao Hàng Nhanh)
    'ghn': [
        r'^GHN',
    ],
    # GHTK (Giao Hàng Tiết Kiệm)
    'giaohangtietkiem': [
        r'^GHTK',
    ],
    # Best Express
    'best-express': [
        r'^BEST',
    ],
}

# Mapping platform keywords in customer name or order reference
PLATFORM_CARRIERS = {
    'shopee': 'spx-vn',  # Shopee usually uses SPX
    'tiktok': 'jtexpress-vn',  # TikTok often uses J&T (can be adjusted)
    'lazada': 'lex',  # Lazada Express
}


def guess_carrier_slug(tracking_number, customer_name=None, order_ref=None):
    """
    Detect carrier slug based on tracking number pattern and context.
    
    Args:
        tracking_number: Tracking number string
        customer_name: Customer name (to detect platform like Shopee, TikTok)
        order_ref: Order reference (additional context)
    
    Returns:
        carrier slug string or None
    """
    if not tracking_number:
        return None
    
    number = tracking_number.strip().upper()
    
    # 1. Try to match by tracking number pattern
    for slug, patterns in CARRIER_PATTERNS.items():
        for pattern in patterns:
            if re.match(pattern, number):
                _logger.info(f"Detected carrier '{slug}' from tracking pattern: {number}")
                return slug
    
    # 2. Try to detect by customer name or order ref (platform detection)
    context_text = ' '.join(filter(None, [
        (customer_name or '').lower(),
        (order_ref or '').lower()
    ]))
    
    for platform, slug in PLATFORM_CARRIERS.items():
        if platform in context_text:
            _logger.info(f"Detected carrier '{slug}' from platform '{platform}' in context")
            return slug
    
    # 3. Default fallback for unknown tracking numbers with letters
    if len(number) >= 10 and re.search(r'[A-Z]', number):
        _logger.info(f"Unknown tracking format '{number}', using default J&T Express")
        return 'jtexpress-vn'  # Default for Vietnam
    
    return None


def is_valid_tracking_number(tracking_number):
    """
    Check if a string looks like a valid tracking number.
    
    Args:
        tracking_number: String to validate
    
    Returns:
        Boolean
    """
    if not tracking_number:
        return False
    
    number = tracking_number.strip()
    
    # Must be at least 8 characters
    if len(number) < 8:
        return False
    
    # Should contain at least one letter or be all numeric with min length
    if re.search(r'[A-Za-z]', number) or (number.isdigit() and len(number) >= 10):
        return True
    
    return False


def should_auto_register_tracking(tracking_number, tracking_slug):
    """
    Determine if tracking should be auto-registered with AfterShip.
    
    Args:
        tracking_number: Tracking number
        tracking_slug: Carrier slug
    
    Returns:
        Boolean
    """
    if not tracking_number or not is_valid_tracking_number(tracking_number):
        return False
    
    # Only auto-register if we have a slug or can guess one
    if tracking_slug:
        return True
    
    # Try to guess
    guessed_slug = guess_carrier_slug(tracking_number)
    return bool(guessed_slug)
