"""
tests/test_desktop_ui_drawers_and_views.py

Verification suite for Phase 1 Milestone 7, Step 4: Desktop UI Drawers & Views.
Validates:
1. Static files delivery and index.html DOM structure (navigation, top project chip, action approval modal).
2. JavaScript module exports and integration in pages.js and app.js.
3. CSS design system tokens and styling rules for Projects, Tasks, Learning, and Scoped Approval.
4. Active project selection and chat payload propagation.
5. Scoped action approval UI workflow and audit history contract.
"""

from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from backend.main import app
from backend.security.auth import session_token_manager

client = TestClient(app)
ROOT_DIR = Path(__file__).resolve().parent.parent


def test_index_html_contains_m7_step4_elements():
    """Confirms that index.html contains all necessary Step 4 navigation buttons, chips, and modals."""
    res = client.get("/")
    assert res.status_code == 200
    html = res.text

    # Sidebar footer navigation buttons
    assert 'id="projects-toggle-btn"' in html
    assert 'id="tasks-toggle-btn"' in html
    assert 'id="learning-toggle-btn"' in html

    # Page sidebar navigation buttons
    assert 'data-page="projects"' in html
    assert 'data-page="tasks"' in html
    assert 'data-page="learning"' in html

    # Top bar project chip and dropdown
    assert 'id="top-project-chip"' in html
    assert 'id="top-project-text"' in html
    assert 'id="project-dropdown-menu"' in html

    # Scoped action approval modal
    assert 'id="action-approval-modal"' in html
    assert 'id="approval-task-title"' in html
    assert 'id="approval-action-category"' in html
    assert 'id="approval-target-resource"' in html
    assert 'id="approval-scope-params"' in html
    assert 'id="approval-action-hash"' in html
    assert 'id="approval-confirm-checkbox"' in html
    assert 'id="approval-authorize-btn"' in html
    assert 'id="approval-cancel-btn"' in html
    assert 'id="approval-invalidation-notice"' in html

    # Task audit history modal
    assert 'id="task-history-modal"' in html
    assert 'id="task-history-title"' in html
    assert 'id="task-history-body"' in html
    assert 'id="task-history-close-btn"' in html


def test_static_files_served_successfully():
    """Confirms that static assets are mounted and served without 404s."""
    assets = [
        "/static/app.js",
        "/static/js/pages.js",
        "/static/style.css",
        "/static/css/pages.css",
        "/static/css/tokens_and_shell.css",
    ]
    for asset in assets:
        res = client.get(asset)
        assert res.status_code == 200, f"Failed to fetch {asset}"
        assert len(res.text) > 0


def test_pages_js_exports_step4_views():
    """Confirms that ui/js/pages.js exports the required render functions."""
    pages_js_path = ROOT_DIR / "ui" / "js" / "pages.js"
    assert pages_js_path.exists()
    content = pages_js_path.read_text(encoding="utf-8")

    assert "export function renderProjectsPage" in content
    assert "export function renderTasksPage" in content
    assert "export function renderLearningPage" in content

    # Check for critical action approval trigger
    assert "onApprove" in content
    # Check for task transition trigger
    assert "btn-transition" in content
    # Check for repository indexing trigger
    assert "btn-index-repo" in content
    # Check for double-confirmation learning wipe
    assert "WIPE_LEARNING_DATA" in content
    assert "confirm_wipe" in content
    assert "acknowledge_data_loss" in content


def test_app_js_wires_step4_logic():
    """Confirms that ui/app.js wires active project selection, approval modal, and chat payload."""
    app_js_path = ROOT_DIR / "ui" / "app.js"
    assert app_js_path.exists()
    content = app_js_path.read_text(encoding="utf-8")

    # Imported renderers
    assert "renderProjectsPage" in content
    assert "renderTasksPage" in content
    assert "renderLearningPage" in content

    # State properties
    assert "activeProjectId" in content
    assert "activeProjectName" in content
    assert "activeProjectConfidentiality" in content

    # Active project handling
    assert "setActiveProject" in content
    assert "toggleProjectDropdown" in content

    # Chat payload includes project_id
    assert "project_id: state.activeProjectId || null" in content

    # Scoped action approval modal functions
    assert "openApprovalModal" in content
    assert "closeApprovalModal" in content
    assert "openTaskHistoryModal" in content


def test_css_rules_for_step4_views():
    """Confirms that ui/css/pages.css contains required styling rules."""
    pages_css_path = ROOT_DIR / "ui" / "css" / "pages.css"
    assert pages_css_path.exists()
    css = pages_css_path.read_text(encoding="utf-8")

    # Confidentiality badges
    assert ".badge-conf-internal" in css
    assert ".badge-conf-confidential" in css
    assert ".badge-conf-restricted" in css

    # Task status and priority badges
    assert ".badge-task-status-pending_approval" in css
    assert ".badge-priority-critical" in css
    assert ".task-card-pending-approval" in css

    # Critical action flag and approval modal
    assert ".critical-action-flag" in css
    assert ".approval-modal-container" in css
    assert ".approval-code-block" in css
    assert ".approval-hash" in css

    # State transition timeline
    assert ".timeline-container" in css
    assert ".timeline-item" in css

    # Danger zone wipe
    assert ".danger-zone-container" in css
    assert ".wipe-disclosure-grid" in css
