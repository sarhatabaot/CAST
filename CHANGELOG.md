# CAST Changes

## 2026-02-26
- Implement custom permission-based authentication system for Candidates module: replace hardcoded group-based access with flexible permission system using `candidates.can_view_candidates` permission
- Create permission signals in app/candidates/signals.py for automatic permission creation during app initialization
- Update 4 candidate views to use `@permission_required('candidates.can_view_candidates', raise_exception=True)` decorators instead of group checks
- Modify navigation template to use new permission system with `has_candidates_permission` template filter
- Move candidate templates from app/templates/candidates/ to app/candidates/templates/candidates/ for better organization
- Remove redundant base_candidates.html template and enhance base template structure with responsive layout
- Add django_gravatar to INSTALLED_APPS for user profile images and implement AlpineJS support for enhanced frontend interactivity
- Add CSRF token handling for htmx requests and theme support with get_theme template tag
- Restructure Candidates module with modular architecture: split models.py into dedicated files (alert.py, candidate.py, data_product.py, photometry.py)
- Create new service layer at app/candidates/services/ for business logic separation (enrichment.py, identity.py, parsing.py, tns_public_catalog.py)
- Add new management commands: download_tns_public_objects.py, match_candidates_to_tns.py
- Reorganize static files: proper structure for LAST and CAST modules with custom CSS, JS, and branding assets
- Update ClickHouse dependency from clickhouse-connect to clickhouse_connect
- Add comprehensive CAST candidates configuration in settings.py
- Enhance TNS integration with improved cone search and object matching capabilities
- Improve static file handling with Django finders integration
- Update import paths to reflect new module structure
