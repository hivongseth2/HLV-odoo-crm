# Estructura del Módulo Rest Api Pragmatic

## 📁 Estructura de Carpetas Final

```
/model_to_publish/pragmatic_engineering_api/
├── __init__.py                        # Inicialización con post_load
├── __manifest__.py                     # Configuración del módulo Odoo 18
├── README.md                           # Documentación completa
├── STRUCTURE.md                        # Este archivo
│
├── controllers/                        # Controladores REST API
│   ├── __init__.py
│   ├── api_controller.py              # Controlador principal API v1
│   ├── main.py                        # Controlador OpenAPI/Swagger
│   └── pinguin_controller.py          # Utilidades de controlador
│
├── lib/                                # Librerías compartidas
│   ├── __init__.py
│   └── pinguin.py                     # Librería pinguin unificada
│
├── models/                             # Modelos de datos
│   ├── __init__.py
│   ├── api_access.py                  # Configuración de acceso API
│   ├── api_log.py                     # Registro de logs
│   ├── api_namespace.py               # Namespaces de API
│   ├── base.py                        # Métodos base extendidos
│   ├── ir_exports.py                  # Extensión de exports
│   ├── ir_model.py                    # Extensión de modelos
│   └── res_users.py                   # Extensión de usuarios
│
├── security/                           # Configuración de seguridad
│   ├── api_security.xml               # Grupos y reglas de registro
│   └── ir.model.access.csv            # Control de acceso
│
├── views/                              # Vistas de interfaz
│   ├── api_access_view.xml            # Vista de configuración de acceso
│   ├── api_log_view.xml               # Vista de logs
│   ├── api_namespace_view.xml         # Vista de namespaces
│   ├── ir_model_view.xml              # Extensión vista de modelos
│   ├── menu_view.xml                  # Menús principales
│   └── res_users_view.xml             # Extensión vista de usuarios
│
├── demo/                               # Datos de demostración
│   ├── api_demo.xml                   # Configuraciones demo
│   └── api_security_demo.xml          # Usuarios y permisos demo
│
├── static/                             # Archivos estáticos
│   ├── description/
│   │   └── index.html                 # Descripción HTML del módulo
│   └── src/
│       └── css/
│           └── api_style.css          # Estilos personalizados
│
└── tests/                              # Pruebas unitarias
    ├── __init__.py
    ├── test_api_access.py              # Tests de acceso
    ├── test_api_controllers.py         # Tests de controladores
    └── test_api_namespace.py           # Tests de namespaces
```

## 🔄 Integración de Módulos

### Módulos Originales Unificados:
1. **base_api** → Funcionalidades base integradas en:
   - `models/base.py` (métodos ORM extendidos)
   - `lib/pinguin.py` (funciones core)

2. **openapi** → Funcionalidades OpenAPI integradas en:
   - `models/api_namespace.py` (antes openapi.namespace)
   - `models/api_access.py` (antes openapi.access)
   - `controllers/api_controller.py` (rutas API)
   - `controllers/main.py` (OpenAPI spec)

## 🔧 Cambios Clave para Odoo 18

### 1. Actualización de Nombres de Modelos
- `openapi.namespace` → `api.namespace`
- `openapi.access` → `api.access`
- `openapi.log` → `api.log`
- `openapi.access.create.context` → `api.access.create.context`

### 2. Actualización de Campos
- `openapi_token` → `api_token` en res.users
- `openapi_*` → `api_*` en todos los campos relacionados

### 3. Compatibilidad con Odoo 18
- Uso de `@api.model_create_multi` para creación en lote
- Actualización de vistas con widgets modernos (`boolean_toggle`)
- Uso de `tree` en lugar de `list` en vistas (Odoo 18)
- Actualización de relaciones Many2many con tablas intermedias explícitas

### 4. Mejoras de Código
- Type hints donde es aplicable
- Docstrings en formato Google
- Manejo de errores mejorado
- Soporte para Python 3.8+
- Eliminación de dependencias obsoletas

## 🎯 Funcionalidades Principales

### Funciones Core Unificadas:
1. **Autenticación**: Token por usuario con Basic Auth
2. **Namespaces**: Aislamiento de configuraciones
3. **CRUD Completo**: Create, Read, Update, Delete
4. **Métodos Personalizados**: Llamada a métodos públicos/privados
5. **OpenAPI/Swagger**: Documentación automática
6. **Logging**: Sistema de registro configurable
7. **Métodos ORM Avanzados**:
   - `search_or_create`
   - `search_read_nested`
   - `create_or_update_by_external_id`

## 📝 Notas de Implementación

### Identificación del Módulo:
- **Nombre Técnico**: `pragmatic_engineering_api`
- **Autor**: Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.
- **Website**: https://www.pragmaticingenieria.com/
- **Versión**: 18.0.1.0.0
- **Licencia**: AGPL-3

### Configuración Requerida:
1. Instalar dependencias Python:
   ```bash
   pip install bravado_core swagger_spec_validator jsonschema
   ```

2. Configurar en Odoo:
   - Instalar el módulo
   - Crear namespace
   - Configurar acceso a modelos
   - Asignar usuarios

### URLs de API:
- Base: `/api/v1/{namespace}/{model}`
- Swagger: `/api/v1/{namespace}/swagger.json`
- Reports: `/api/v1/{namespace}/report/{type}/{id}/{docids}`

## ✅ Estado de Completitud

Todos los componentes han sido:
- ✅ Migrados de los módulos originales
- ✅ Adaptados a Odoo 18.0
- ✅ Unificados en una solución coherente
- ✅ Documentados completamente
- ✅ Preparados para producción

---
**Copyright © 2025 Pragmatic Ingeniería S.A.S. Soluciones integrales Tic para las Pyme.**
