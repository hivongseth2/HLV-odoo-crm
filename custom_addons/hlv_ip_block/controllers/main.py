import logging
import re
import time
import ipaddress
from collections import defaultdict
from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

# ============================================================
# Default configuration (overridden by DB settings at runtime)
# ============================================================
CACHE_TTL = 60  # How often to refresh caches and flush counters (seconds)

# Defaults - will be replaced by DB values after first cache refresh
_cfg = {
    'rate_limit_per_second': 5,   # Max req/s before auto-block
    'rate_window': 10,            # Window in seconds to measure rate
    'rate_limit': 50,             # = rate_limit_per_second * rate_window
    'suspicious_threshold': 20,   # Suspicious path hits before auto-block
    'suspect_window': 30,         # Window for suspicious path counting
}

# ============================================================
# Suspicious path patterns - Odoo NEVER serves these
# ============================================================
SUSPICIOUS_PATTERNS = re.compile(
    r'(?i)'
    r'\.php|\.asp|\.aspx|\.jsp|\.cgi|\.env|\.git|\.svn|\.DS_Store'
    r'|/etc/passwd|/etc/shadow|/proc/self'
    r'|/wp-admin|/wp-content|/wp-includes|/wp-login|/wp-config'
    r'|/xmlrpc\.php|/administrator|/admin\.php'
    r'|\.\./|\.\.\\|%2e%2e|%252e'           # path traversal
    r'|/phpmyadmin|/pma|/myadmin|/mysql'
    r'|/shell|/cmd|/exec|/eval'
    r'|/config\.json|/package\.json|/composer\.json'
    r'|/\.well-known/security\.txt'
    r'|/debug/|/console|/server-status'
    r'|/nacos/|/actuator|/druid'
    r'|/vendor/|/node_modules/'
    r'|/login\.action|/struts|/solr'
    r'|/tmp\.|/temp\.|/backup\.'
    r'|\.sql|\.sqlite|\.db$|\.bak$|\.old$|\.zip$|\.tar|\.7z$|\.rar$'
)

# Known Odoo valid path prefixes
ODOO_VALID_PREFIXES = (
    '/web', '/website', '/shop', '/my', '/pos', '/mail',
    '/longpolling', '/websocket', '/base', '/report',
    '/web/image', '/web/content', '/web/assets',
    '/odoo', '/favicon.ico', '/robots.txt', '/sitemap.xml',
    '/web/webclient', '/web/dataset', '/web/action',
    '/web/session', '/web/bundle',
    '/web/login', '/web/logout', '/web/signup',
    '/_odoo/',
)

# ============================================================
# In-memory state (per worker process)
# ============================================================
_blocked_ips_cache = set()
_whitelisted_ips_cache = set()
_cache_timestamp = 0

_hit_counters = defaultdict(int)        # blocked IP -> hit count (flush to DB)
_rate_tracker = {}                       # ip -> [timestamps] for rate limiting
_suspect_tracker = defaultdict(list)     # ip -> [timestamps] for suspicious paths
_auto_block_queue = []                   # [(ip, reason, detection_type), ...]


class IPBlockMiddleware(http.Controller):

    @http.route('/hlv_ip_block/refresh', type='json', auth='user')
    def refresh_cache(self):
        """Manual refresh of blocked IP cache."""
        _do_cache_refresh(force=True)
        return {
            'status': 'ok',
            'blocked_count': len(_blocked_ips_cache),
            'whitelisted_count': len(_whitelisted_ips_cache),
        }

    @http.route('/hlv_ip_block/stats', type='json', auth='user')
    def get_stats(self):
        """Get current in-memory stats."""
        return {
            'blocked_ips': len(_blocked_ips_cache),
            'whitelisted_ips': len(_whitelisted_ips_cache),
            'tracked_ips': len(_rate_tracker),
            'suspect_ips': len(_suspect_tracker),
            'pending_auto_blocks': len(_auto_block_queue),
            'pending_hit_flushes': dict(_hit_counters),
        }


def _get_db_cursor():
    """Get a database cursor safely."""
    try:
        import odoo
        db_name = odoo.tools.config['db_name']
        if db_name:
            from odoo.sql_db import db_connect
            return db_connect(db_name).cursor(), db_name
    except Exception:
        pass
    return None, None


def _table_exists(cr, table_name):
    cr.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = %s",
        (table_name,)
    )
    return cr.fetchone() is not None


def _do_cache_refresh(force=False):
    """Refresh caches, flush counters, load settings, and insert auto-blocked IPs."""
    global _blocked_ips_cache, _whitelisted_ips_cache, _cache_timestamp
    global _hit_counters, _auto_block_queue, _cfg

    now = time.time()
    if not force and (now - _cache_timestamp) < CACHE_TTL:
        return

    cr, db_name = _get_db_cursor()
    if not cr:
        _cache_timestamp = now
        return

    try:
        if not _table_exists(cr, 'hlv_blocked_ip'):
            _cache_timestamp = now
            return

        # 1) Load settings from DB
        if _table_exists(cr, 'hlv_ip_block_settings'):
            cr.execute(
                "SELECT rate_limit_per_second, rate_window, suspicious_threshold, suspect_window "
                "FROM hlv_ip_block_settings ORDER BY id LIMIT 1"
            )
            row = cr.fetchone()
            if row:
                rps, rw, st, sw = row
                _cfg['rate_limit_per_second'] = rps
                _cfg['rate_window'] = rw
                _cfg['rate_limit'] = rps * rw
                _cfg['suspicious_threshold'] = st
                _cfg['suspect_window'] = sw

        # 2) Insert auto-blocked IPs
        queue = list(_auto_block_queue)
        _auto_block_queue.clear()
        for ip, reason, det_type in queue:
            cr.execute("SELECT 1 FROM hlv_blocked_ip WHERE name = %s", (ip,))
            if not cr.fetchone():
                cr.execute(
                    "INSERT INTO hlv_blocked_ip (name, reason, active, is_auto, detection_type, "
                    "hit_count, create_uid, write_uid, create_date, write_date) "
                    "VALUES (%s, %s, TRUE, TRUE, %s, 0, 1, 1, "
                    "NOW() AT TIME ZONE 'UTC', NOW() AT TIME ZONE 'UTC')",
                    (ip, reason, det_type)
                )
                _logger.warning("Auto-blocked IP: %s - Reason: %s", ip, reason)

        # 3) Flush hit counters
        counters = dict(_hit_counters)
        _hit_counters.clear()
        for ip, count in counters.items():
            if count > 0:
                cr.execute(
                    "UPDATE hlv_blocked_ip SET hit_count = hit_count + %s, "
                    "last_hit = NOW() AT TIME ZONE 'UTC' "
                    "WHERE name = %s AND active = TRUE",
                    (count, ip)
                )

        cr.commit()

        # 4) Refresh blocked IPs cache
        cr.execute("SELECT name FROM hlv_blocked_ip WHERE active = TRUE")
        _blocked_ips_cache = {row[0] for row in cr.fetchall()}

        # 5) Refresh whitelist cache
        if _table_exists(cr, 'hlv_whitelisted_ip'):
            cr.execute("SELECT name FROM hlv_whitelisted_ip")
            _whitelisted_ips_cache = {row[0] for row in cr.fetchall()}

        _cache_timestamp = now

    except Exception as e:
        _logger.error("IP Block cache refresh error: %s", e)
        _cache_timestamp = now
    finally:
        cr.close()


def _extract_ip(environ):
    """
    Extract and validate the real client IP from environ.
    Always validates against ipaddress to prevent header injection / XSS.
    Falls back to REMOTE_ADDR if no valid IP found in proxy headers.
    Returns (ip_str, header_was_injected) tuple.
    """
    def is_valid_ip(s):
        try:
            ipaddress.ip_address(s.strip())
            return True
        except ValueError:
            return False

    injected = False

    # Check X-Forwarded-For (may contain multiple IPs: client, proxy1, proxy2)
    xff = environ.get('HTTP_X_FORWARDED_FOR', '')
    if xff:
        candidates = [p.strip() for p in xff.split(',')]
        # Detect injection: any candidate that is NOT a valid IP
        invalid = [c for c in candidates if c and not is_valid_ip(c)]
        if invalid:
            injected = True
            _logger.warning(
                "Header injection attempt in X-Forwarded-For: %s",
                xff[:200]
            )
        # Take first valid IP (original client)
        for candidate in candidates:
            if is_valid_ip(candidate):
                return candidate.strip(), injected

    # Check X-Real-IP
    xri = environ.get('HTTP_X_REAL_IP', '').strip()
    if xri and is_valid_ip(xri):
        return xri, injected

    # Fall back to REMOTE_ADDR (always set by the server, trustworthy)
    remote = environ.get('REMOTE_ADDR', '').strip()
    if remote and is_valid_ip(remote):
        return remote, injected

    return '', injected


def _is_whitelisted(ip):
    """Check if IP is in whitelist (exact or prefix match for CIDR-like)."""
    if ip in _whitelisted_ips_cache:
        return True
    # Support simple prefix matching: e.g. "10.0." whitelists all 10.0.x.x
    for w in _whitelisted_ips_cache:
        if w.endswith('.') and ip.startswith(w):
            return True
    return False


def _is_suspicious_path(path):
    """Check if the requested path is suspicious (never served by Odoo)."""
    return bool(SUSPICIOUS_PATTERNS.search(path))


def _cleanup_old_entries(tracker, window, now):
    """Remove entries older than window from tracker dict."""
    expired = []
    for ip, timestamps in tracker.items():
        tracker[ip] = [t for t in timestamps if now - t < window]
        if not tracker[ip]:
            expired.append(ip)
    for ip in expired:
        del tracker[ip]


def _check_and_auto_block(ip, path, now):
    """Evaluate if an IP should be auto-blocked. Returns True if just blocked."""
    global _auto_block_queue

    suspicious_threshold = _cfg['suspicious_threshold']
    suspect_window = _cfg['suspect_window']
    rate_limit = _cfg['rate_limit']
    rate_window = _cfg['rate_window']

    # --- Suspicious path detection ---
    if _is_suspicious_path(path):
        _suspect_tracker[ip].append(now)
        _suspect_tracker[ip] = [t for t in _suspect_tracker[ip] if now - t < suspect_window]

        count = len(_suspect_tracker[ip])
        if count >= suspicious_threshold:
            reason = (
                f"Tự động chặn: {count} path đáng ngờ trong {suspect_window}s. "
                f"Path cuối: {path[:200]}"
            )
            _auto_block_queue.append((ip, reason, 'suspicious_path'))
            _blocked_ips_cache.add(ip)
            del _suspect_tracker[ip]
            _logger.warning("AUTO-BLOCK (suspicious path): %s after %d hits", ip, count)
            return True

    # --- Rate limiting ---
    if ip not in _rate_tracker:
        _rate_tracker[ip] = []
    _rate_tracker[ip].append(now)
    _rate_tracker[ip] = [t for t in _rate_tracker[ip] if now - t < rate_window]

    req_count = len(_rate_tracker[ip])
    if req_count >= rate_limit:
        reason = (
            f"Tự động chặn: {req_count} requests trong {rate_window}s "
            f"(ngưỡng: {rate_limit} = {_cfg['rate_limit_per_second']} req/s × {rate_window}s). "
            f"Path cuối: {path[:200]}"
        )
        _auto_block_queue.append((ip, reason, 'rate_limit'))
        _blocked_ips_cache.add(ip)
        del _rate_tracker[ip]
        _logger.warning(
            "AUTO-BLOCK (rate limit): %s with %d req in %ds", ip, req_count, rate_window
        )
        return True

    return False


# ============================================================
# WSGI Monkey-patch
# ============================================================
_original_dispatch = http.root.__class__.__call__


def _patched_call(self, environ, start_response):
    """Intercept requests: block known IPs, auto-detect bots."""
    global _blocked_ips_cache, _cache_timestamp

    # Safe IP extraction - validates against ipaddress, detects header injection
    ip, header_injected = _extract_ip(environ)
    path = environ.get('PATH_INFO', '/')
    now = time.time()

    # Periodic maintenance
    if now - _cache_timestamp > CACHE_TTL:
        _cleanup_old_entries(_rate_tracker, _cfg['rate_window'], now)
        _cleanup_old_entries(_suspect_tracker, _cfg['suspect_window'], now)
        _do_cache_refresh()

    # Block immediately on header injection attempt (XSS in X-Forwarded-For etc.)
    if header_injected:
        if ip:
            _hit_counters[ip] += 1
            # Queue auto-block for the real IP behind the injection
            if ip not in _blocked_ips_cache:
                _auto_block_queue.append((
                    ip,
                    f"Header injection / XSS attack in X-Forwarded-For. Path: {path[:200]}",
                    'suspicious_path'
                ))
                _blocked_ips_cache.add(ip)
        status = '302 Found'
        headers = [('Location', 'https://www.google.com'), ('Content-Type', 'text/html')]
        start_response(status, headers)
        return [b'<html><body>Redirecting...</body></html>']

    # Skip checks for whitelisted IPs
    if ip and _is_whitelisted(ip):
        return _original_dispatch(self, environ, start_response)

    # Already blocked → redirect
    if ip and ip in _blocked_ips_cache:
        _hit_counters[ip] += 1
        status = '302 Found'
        headers = [('Location', 'https://www.google.com'), ('Content-Type', 'text/html')]
        start_response(status, headers)
        return [b'<html><body>Redirecting...</body></html>']

    # Auto-detect bots
    if ip:
        just_blocked = _check_and_auto_block(ip, path, now)
        if just_blocked:
            _hit_counters[ip] += 1
            status = '302 Found'
            headers = [('Location', 'https://www.google.com'), ('Content-Type', 'text/html')]
            start_response(status, headers)
            return [b'<html><body>Redirecting...</body></html>']

    return _original_dispatch(self, environ, start_response)


# Apply the patch
http.root.__class__.__call__ = _patched_call
_logger.info("HLV IP Block middleware with auto-detection installed successfully")
