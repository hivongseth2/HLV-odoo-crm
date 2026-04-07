import logging
import time
from collections import defaultdict
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# Cache for blocked IPs - refreshed periodically
_blocked_ips_cache = set()
_cache_timestamp = 0
CACHE_TTL = 60  # Refresh cache every 60 seconds

# In-memory hit counters - flushed to DB together with cache refresh
_hit_counters = defaultdict(int)


class IPBlockMiddleware(http.Controller):

    @http.route('/hlv_ip_block/refresh', type='json', auth='user')
    def refresh_cache(self):
        """Manual refresh of blocked IP cache."""
        _refresh_blocked_ips_cache()
        return {'status': 'ok', 'blocked_count': len(_blocked_ips_cache)}


def _refresh_blocked_ips_cache():
    """Refresh the in-memory blocked IPs cache from database."""
    global _blocked_ips_cache, _cache_timestamp
    import time
    try:
        cr = http.root.registry_manager.cursor() if hasattr(http.root, 'registry_manager') else None
        if cr is None:
            from odoo.sql_db import db_connect
            db_name = http.root.session_store.path.split('/')[-1] if hasattr(http.root, 'session_store') else None
            if db_name:
                cr = db_connect(db_name).cursor()
        if cr:
            try:
                cr.execute("SELECT name FROM hlv_blocked_ip WHERE active = TRUE")
                _blocked_ips_cache = {row[0] for row in cr.fetchall()}
                _cache_timestamp = time.time()
            finally:
                cr.close()
    except Exception:
        pass


def _get_remote_ip():
    """Get the real remote IP, considering proxies."""
    if not request:
        return None
    # Check X-Forwarded-For header (from reverse proxy / load balancer)
    forwarded_for = request.httprequest.headers.get('X-Forwarded-For')
    if forwarded_for:
        # Take the first IP (original client)
        return forwarded_for.split(',')[0].strip()
    # Check X-Real-IP header
    real_ip = request.httprequest.headers.get('X-Real-IP')
    if real_ip:
        return real_ip.strip()
    return request.httprequest.remote_addr


# Monkey-patch the Odoo HTTP dispatch to intercept blocked IPs
_original_dispatch = http.root.__class__.__call__


def _patched_call(self, environ, start_response):
    """Intercept requests and block IPs before Odoo processes them."""
    global _blocked_ips_cache, _cache_timestamp, _hit_counters

    # Get remote IP from environ
    ip = environ.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
    if not ip:
        ip = environ.get('HTTP_X_REAL_IP', '')
    if not ip:
        ip = environ.get('REMOTE_ADDR', '')

    # Refresh cache + flush hit counters periodically
    now = time.time()
    if now - _cache_timestamp > CACHE_TTL:
        try:
            import odoo
            db_name = odoo.tools.config['db_name']
            if db_name:
                from odoo.sql_db import db_connect
                cr = db_connect(db_name).cursor()
                try:
                    cr.execute(
                        "SELECT 1 FROM information_schema.tables WHERE table_name = 'hlv_blocked_ip'"
                    )
                    if cr.fetchone():
                        # Flush accumulated hit counters to DB
                        counters_to_flush = dict(_hit_counters)
                        _hit_counters.clear()
                        for blocked_ip, count in counters_to_flush.items():
                            if count > 0:
                                cr.execute(
                                    "UPDATE hlv_blocked_ip SET hit_count = hit_count + %s, "
                                    "last_hit = NOW() AT TIME ZONE 'UTC' "
                                    "WHERE name = %s AND active = TRUE",
                                    (count, blocked_ip)
                                )
                        cr.commit()

                        # Refresh cache
                        cr.execute("SELECT name FROM hlv_blocked_ip WHERE active = TRUE")
                        _blocked_ips_cache = {row[0] for row in cr.fetchall()}
                    _cache_timestamp = now
                finally:
                    cr.close()
        except Exception:
            _cache_timestamp = now

    # Check if IP is blocked
    if ip and ip in _blocked_ips_cache:
        _logger.warning("Blocked request from IP: %s - Path: %s", ip, environ.get('PATH_INFO', '/'))
        # Increment in-memory counter (no DB hit)
        _hit_counters[ip] += 1

        # Redirect to google.com
        status = '302 Found'
        headers = [
            ('Location', 'https://www.google.com'),
            ('Content-Type', 'text/html'),
        ]
        start_response(status, headers)
        return [b'<html><body>Redirecting...</body></html>']

    return _original_dispatch(self, environ, start_response)


# Apply the patch
http.root.__class__.__call__ = _patched_call
_logger.info("HLV IP Block middleware installed successfully")
