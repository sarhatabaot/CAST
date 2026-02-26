# CAST Permission System Changes

## 2026-02-26: Custom Permission Implementation

### Overview
Implemented a custom permission-based authentication system for the Candidates module to replace hardcoded group-based access control. This allows flexible permission management through Django's admin interface.

### Changes Made

#### 1. Application Configuration (`app/candidates/apps.py`)
- Added `ready()` method to import signals for permission creation
- Enables automatic permission setup during app initialization

#### 2. Permission Signals (`app/candidates/signals.py`) - NEW FILE
- Created signal handler to automatically create `can_view_candidates` permission
- Runs after migrations to ensure permission exists in the database
- Uses Django's built-in permission system for consistency

#### 3. View Decorators (`app/candidates/views.py`)
- Replaced `@user_passes_test(lambda user: user.groups.filter(name='LAST general').exists())` 
- With `@permission_required('candidates.can_view_candidates', raise_exception=True)`
- Applied to the following views:
  - `candidate_list_view`
  - `update_followup_view`
  - `send_tns_report_view`
  - `tns_report_view`

#### 4. Navigation Template (`app/templates/tom_common/navbar_content.html`)
- Updated Candidates menu visibility logic
- Changed from: `{% if request.user.is_superuser %}`
- To: `{% if request.user.is_superuser or request.user.has_perm('candidates.can_view_candidates') %}`
- Now shows Candidates menu to users with the permission, not just superusers

### Benefits
- **Flexibility**: Any group can be granted access without code changes
- **Scalability**: Easy to add/remove permissions as team structure changes
- **Maintainability**: No hardcoded group names in views
- **Security**: Fine-grained control through Django's built-in permission system
- **Admin Control**: Permissions can be managed through Django admin interface

### Implementation Notes
- The permission `candidates.can_view_candidates` is automatically created when the app starts
- Superusers retain access to all functionality (unchanged)
- The permission system is backward compatible with existing superuser access
- No database migration is required as permissions are created via signals

### Next Steps
1. Run Django migrations to apply any database changes
2. Grant the `can_view_candidates` permission to appropriate user groups in Django admin
3. Test the implementation to ensure proper access control

## 2026-02-26: Template Organization & Enhanced Features

### Overview
Comprehensive refactoring of the Candidates module including template reorganization, enhanced frontend features, and improved authentication system.

### Changes Made

#### 1. Template Organization
- **Moved candidate templates** from `app/templates/candidates/` to `app/candidates/templates/candidates/`
- **Created dedicated candidates app structure** for better organization
- **Removed redundant base_candidates.html template**
- **Enhanced base template structure** with responsive layout and Bootstrap grid system

#### 2. Authentication & Security
- **Enhanced permission system** with custom template filter `has_candidates_permission`
- **Improved navigation template** to use new permission-based checks
- **Added CSRF token handling** for htmx requests
- **Implemented AlpineJS support** for enhanced frontend interactivity

#### 3. New Features
- **Added django_gravatar** to INSTALLED_APPS for user profile images
- **Implemented responsive layout** structure with Bootstrap grid system
- **Enhanced base template** with theme support via `get_theme` template tag
- **Improved template inheritance** and organization

#### 4. Code Quality & Documentation
- **Created comprehensive CHANGELOG.md** documenting all changes
- **Added PERMISSIONS.md** for centralized permission reference
- **Enhanced template structure** for better maintainability
- **Improved file organization** throughout the candidates app

#### 5. Technical Improvements
- **Removed static/ from .gitignore** (now properly organized)
- **Added theme support** with get_theme template tag
- **Enhanced base template structure** for better maintainability
- **Improved template organization** and inheritance

### Benefits
- **Better Organization**: Templates now properly organized within their respective app
- **Enhanced Security**: Improved CSRF protection and permission handling
- **Modern Frontend**: AlpineJS support for interactive UI components
- **Responsive Design**: Bootstrap grid system for better mobile experience
- **User Experience**: Gravatar integration for user profile images
- **Maintainability**: Centralized documentation and improved code structure

### Breaking Changes
- **Template paths changed**: All candidate templates moved to app-specific directory
- **Permission system updated**: Now requires explicit permission assignment instead of hardcoded groups

### Implementation Notes
- All changes maintain backward compatibility where possible
- New template structure follows Django best practices
- Enhanced security measures implemented throughout
- Responsive design improvements for better user experience
