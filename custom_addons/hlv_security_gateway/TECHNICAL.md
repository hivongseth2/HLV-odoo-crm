# HLV Security Gateway Technical Documentation

## Overview
This module provides a security interception layer at the Odoo application level to block malicious requests and specific IP addresses. It acts as a secondary defense after the infrastructure-level firewall (Nginx/WAF).

## Directory Structure
```
hlv_security_gateway/
├── models/
│   ├── __init__.py
│   ├── ir_http.py          ← Core interception logic (override _dispatch)
│   └── security_rule.py    ← Dynamic rule definitions
├── security/
│   └── ir.model.access.csv ← Access rights
├── views/
│   └── security_rule_views.xml ← UI for managing rules
└── __init__.py
```

## Core Logic: ir.http._dispatch
The module inherits `ir.http` and overrides `_dispatch` to:
1.  Identify the client's IP via `request.httprequest.remote_addr`.
2.  Inspect the requested URL path.
3.  Compare them against:
    -   Hardcoded high-risk patterns (PHP, WP, LFI, and the current attacker IP).
    -   (To be implemented) Dynamic rules from the `hlv.security.rule` model.
4.  If a match is found, it raises `werkzeug.exceptions.Forbidden` (403), terminating the request before deeper Odoo processing.

## Current Blocked Patterns (Hardcoded for immediate safety)
-   Extensions: `.php`, `.jsp`, `.asp`, `.swp`, `.swo`, `.war`, `.bkp`, `.bak`
-   Specific files: `wp-config.php`, `etc/passwd`
-   Folders: `/wp-admin/`, `/wp-content/` (common in scans)
-   Specific IP: `34.87.32.244` (current attacker)

## Extension Points
To add new blocking logic, modify `DEFAULT_BLOCKED_PATTERNS` in `models/ir_http.py` or extend the `_dispatch` method to check the `hlv.security.rule` model.
