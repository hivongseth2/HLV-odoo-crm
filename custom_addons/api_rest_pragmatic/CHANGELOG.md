# Changelog

All notable changes to Rest Api Pragmatic will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [18.0.1.0.0] - 2025-01-01

### Added
- Initial release for Odoo 18.0
- Complete REST API implementation with OpenAPI/Swagger documentation
- Token-based authentication system
- Namespace isolation for multiple API integrations
- Advanced ORM methods (search_or_create, search_read_nested, create_or_update_by_external_id)
- Comprehensive request/response logging system
- Full CRUD operations for configured models
- Custom method calling via API
- Report generation (PDF/HTML) via API
- External ID management system
- Field-level access control
- Method whitelisting/blacklisting
- Support for nested field reading with configurable depth
- Parallel query execution support
- Transaction isolation for read operations

### Security
- Implemented secure token-based authentication
- Added namespace-level access control
- Added user-level permissions management
- Added field-level security restrictions

### Documentation
- Complete API documentation with Swagger UI
- Comprehensive README with usage examples
- Python and JavaScript implementation examples
- Migration guide from original base_api and openapi modules

### Credits
- Developed and maintained by Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.

---

Copyright © 2025 Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.
License: AGPL-3 (GNU Affero General Public License v3.0)
