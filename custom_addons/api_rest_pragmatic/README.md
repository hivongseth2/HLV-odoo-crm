# Rest Api Pragmatic

Complete REST API solution for Odoo 18 with OpenAPI/Swagger documentation.

## 🚀 Overview

This module provides a complete REST API implementation for Odoo 18, combining and enhancing the functionality from the original `base_api` and `openapi` modules into a single, unified solution.

## ✨ Features

### Core Functionality
- **Full REST API Implementation**: Complete CRUD operations for all configured models
- **OpenAPI/Swagger Documentation**: Auto-generated API documentation
- **Token Authentication**: Secure API access with token-based authentication
- **Namespace Isolation**: Multiple API integrations with isolated configurations
- **Advanced ORM Methods**: `search_or_create`, `search_read_nested`, `create_or_update_by_external_id`
- **Comprehensive Logging**: Detailed request/response logging system

### API Endpoints
- `GET /api/v1/{namespace}/{model}` - List records
- `GET /api/v1/{namespace}/{model}/{id}` - Get single record  
- `POST /api/v1/{namespace}/{model}` - Create record
- `PUT /api/v1/{namespace}/{model}/{id}` - Update record
- `DELETE /api/v1/{namespace}/{model}/{id}` - Delete record
- `PATCH /api/v1/{namespace}/{model}/call/{method}` - Call model method
- `PATCH /api/v1/{namespace}/{model}/{id}/call/{method}` - Call record method

### Report Generation
- `GET /api/v1/{namespace}/report/pdf/{report_id}/{doc_ids}` - Get PDF report
- `GET /api/v1/{namespace}/report/html/{report_id}/{doc_ids}` - Get HTML report

## 📦 Installation

1. Copy the `pragmatic_engineering_api` folder to your Odoo addons directory
2. Update the addons list in Odoo
3. Install the module from Apps menu

### Dependencies
- Odoo 18.0
- Python packages:
  - `bravado_core`
  - `swagger_spec_validator`
  - `jsonschema`

Install Python dependencies:
```bash
pip install bravado_core swagger_spec_validator jsonschema
```

## 🔧 Configuration

### 1. Create API Namespace
Navigate to `API Configuration → API Namespaces` and create a new namespace:
- **Name**: Unique identifier for your integration (e.g., "ecommerce", "mobile")
- **Description**: Optional description
- **Log Level**: Configure request/response logging

### 2. Configure Model Access
Navigate to `API Configuration → API Access` and configure model permissions:
- **Namespace**: Select the namespace
- **Model**: Choose the model to expose
- **CRUD Operations**: Enable desired operations
- **Methods**: Configure allowed public/private methods
- **Fields**: Define fields for read operations

### 3. User Configuration
Configure users with API access:
- Go to user preferences
- Navigate to "API Configuration" tab
- Copy the API token for authentication
- Assign allowed namespaces

## 🔐 Authentication

The API uses Basic Authentication with token:

```bash
curl -X GET "https://your-odoo.com/api/v1/namespace/res.partner" \
     -H "Authorization: Basic $(echo -n 'your-token' | base64)"
```

For multi-database environments:
```bash
curl -X GET "https://your-odoo.com/api/v1/namespace/res.partner" \
     -H "Authorization: Basic $(echo -n 'database:token' | base64)"
```

## 💻 Usage Examples

### Python Example
```python
import requests
import base64

# Configuration
base_url = "https://your-odoo.com"
namespace = "test"
token = "your-api-token"

# Prepare authentication
auth_string = base64.b64encode(token.encode()).decode()
headers = {
    "Authorization": f"Basic {auth_string}",
    "Content-Type": "application/json"
}

# List partners
response = requests.get(
    f"{base_url}/api/v1/{namespace}/res.partner",
    headers=headers
)
partners = response.json()

# Create a new partner
data = {
    "name": "New Partner",
    "email": "partner@example.com",
    "phone": "+1234567890"
}
response = requests.post(
    f"{base_url}/api/v1/{namespace}/res.partner",
    json=data,
    headers=headers
)
new_partner = response.json()
```

### JavaScript Example
```javascript
const baseUrl = 'https://your-odoo.com';
const namespace = 'test';
const token = 'your-api-token';

// Prepare authentication
const authString = btoa(token);
const headers = {
    'Authorization': `Basic ${authString}`,
    'Content-Type': 'application/json'
};

// List partners
fetch(`${baseUrl}/api/v1/${namespace}/res.partner`, {
    method: 'GET',
    headers: headers
})
.then(response => response.json())
.then(partners => console.log(partners));

// Create a new partner
const data = {
    name: 'New Partner',
    email: 'partner@example.com',
    phone: '+1234567890'
};

fetch(`${baseUrl}/api/v1/${namespace}/res.partner`, {
    method: 'POST',
    headers: headers,
    body: JSON.stringify(data)
})
.then(response => response.json())
.then(newPartner => console.log(newPartner));
```

## 🔄 Advanced Features

### Nested Field Reading
Read related fields in a single API call:
```python
# Using nested field paths
fields = ["name", "partner_id/name", "partner_id/country_id/name"]
```

### External ID Management
Use external IDs for record synchronization:
```python
data = {
    "id": "external_ref_001",  # Your external reference
    "name": "Test Partner",
    "email": "test@example.com"
}
```

### Custom Method Calling
Call custom methods on models or records:
```python
# Call method on model
response = requests.patch(
    f"{base_url}/api/v1/{namespace}/res.partner/call/search_read",
    json={
        "args": [],
        "kwargs": {"domain": [["is_company", "=", True]]}
    },
    headers=headers
)

# Call method on specific record
response = requests.patch(
    f"{base_url}/api/v1/{namespace}/res.partner/1/call/message_post",
    json={
        "kwargs": {
            "body": "Message from API",
            "subject": "API Test"
        }
    },
    headers=headers
)
```

## 📊 OpenAPI/Swagger Documentation

Access the OpenAPI specification for your namespace:
```
https://your-odoo.com/api/v1/{namespace}/swagger.json?token={namespace_token}&db={database}
```

You can use this URL with Swagger UI or other OpenAPI tools for interactive API exploration.

## 🛡️ Security

### Access Control
- **User-level**: API tokens per user
- **Namespace-level**: Isolated configurations
- **Model-level**: Granular CRUD permissions
- **Method-level**: Whitelist/blacklist for methods
- **Field-level**: Control readable/writable fields

### Best Practices
1. Use HTTPS always
2. Rotate API tokens regularly
3. Limit namespace access to required users
4. Configure minimal required permissions
5. Enable logging for audit trails
6. Use field-level restrictions for sensitive data

## 🐛 Troubleshooting

### Common Issues

1. **Authentication Failed**
   - Verify token is correct
   - Check user has namespace access
   - Ensure token is properly base64 encoded

2. **Model Not Found**
   - Verify model has API access configured
   - Check namespace configuration
   - Ensure model name is correct (use technical name)

3. **Method Not Allowed**
   - Check method is whitelisted in API access
   - Verify CRUD permissions are enabled
   - Ensure method exists on the model

4. **Performance Issues**
   - Use field restrictions to limit data
   - Enable caching where appropriate
   - Monitor and optimize database queries
   - Use pagination for large datasets

## 📝 Migration from Original Modules

If migrating from the original `base_api` and `openapi` modules:

1. **Backup your database**
2. **Export configurations** from old modules
3. **Uninstall** old modules
4. **Install** pragmatic_engineering_api
5. **Recreate configurations** with new naming:
   - `openapi.namespace` → `api.namespace`
   - `openapi.access` → `api.access`
   - `openapi.log` → `api.log`
   - `openapi_token` → `api_token` in res.users

## 🤝 Support

- **Developer**: Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.
- **Website**: https://www.pragmaticingenieria.com/
- **Email**: api@pragmaticingenieria.com
- **License**: AGPL-3 (GNU Affero General Public License v3.0)

## 📄 License

Copyright © 2025 Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.  
Licensed under AGPL-3 (GNU Affero General Public License v3.0)

## 🙏 Credits

Developed by Pragmatic Ingeniería S.A.S. - Soluciones integrales Tic para las Pyme.

---

**Version**: 18.0.1.0.0  
**Last Updated**: 2025
