# Changelog

All notable changes to ProjectForge will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2025-01-01

### Added

#### Authentication & Authorization
- User registration with email validation and secure password hashing
- Login and logout with JWT-based session management
- Role-based access control (RBAC) with roles: super_admin, project_manager, team_lead, developer, viewer
- Protected routes with permission checks enforced at both API and UI levels
- Password reset functionality via email token

#### Department & User Management
- Full CRUD operations for departments with name, description, and manager assignment
- User management with profile details, role assignment, and department association
- User listing with search, filter by role, and filter by department
- User profile editing with avatar support

#### Project Management
- Full CRUD operations for projects with name, description, status, and date tracking
- Project statuses: planning, active, on_hold, completed, archived
- Project member management with role-based assignments
- Project dashboard with summary statistics and recent activity

#### Sprint Management
- Sprint creation and editing within projects with start and end dates
- Sprint statuses: planning, active, completed
- Sprint backlog management with ticket assignment
- Sprint velocity tracking and progress indicators

#### Ticket Management
- Full CRUD operations for tickets with title, description, type, priority, and status
- Ticket types: bug, feature, task, improvement, epic
- Ticket priorities: critical, high, medium, low
- Ticket statuses: open, in_progress, in_review, resolved, closed, reopened
- Ticket assignment to project members
- Sprint association for tickets
- Parent-child ticket relationships for sub-task tracking

#### Label System
- Create, edit, and delete labels with custom name and color
- Assign multiple labels to tickets for categorization
- Filter tickets by label across project views

#### Comments
- Add, edit, and delete comments on tickets
- Threaded replies for nested comment discussions
- Markdown support in comment content

#### Time Entries
- Log time spent on tickets with description and date
- Edit and delete time entries
- Time tracking summaries per ticket, per user, and per sprint
- Reporting on total hours across projects

#### Kanban Board
- Interactive Kanban board view per project and per sprint
- Drag-and-drop ticket status transitions
- Swimlane grouping by assignee or priority
- Real-time board state updates

#### Admin Dashboard
- System-wide statistics: total users, projects, tickets, and active sprints
- Recent activity feed showing latest actions across all projects
- User and department management from a centralized admin panel
- System health and usage metrics overview

#### Audit Logging
- Automatic logging of all create, update, and delete operations
- Audit log entries include user, action, entity type, entity ID, and timestamp
- Audit log viewer with filtering by user, action type, entity, and date range
- Immutable audit trail for compliance and traceability

#### Responsive UI
- Fully responsive design built with Tailwind CSS utility classes
- Jinja2 server-side rendered templates with consistent base layout
- Sidebar navigation with collapsible menu for mobile viewports
- Dark mode support via Tailwind dark: prefix classes
- Accessible form components with proper labels and ARIA attributes
- Toast notifications for success, error, and informational messages

#### API & Infrastructure
- RESTful API built with FastAPI and async SQLAlchemy 2.0
- SQLite database with async support via aiosqlite
- Pydantic v2 schemas for request validation and response serialization
- CORS middleware configured for cross-origin requests
- Structured logging throughout the application
- Environment-based configuration via pydantic-settings and .env file