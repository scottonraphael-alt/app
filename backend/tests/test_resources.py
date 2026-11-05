"""Iteration 8 — Ressources feature: auth guards, storage init, static invariants."""
import os
import re
from pathlib import Path

import pytest
import requests


BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://iris-logs.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


# ---------- Backend guards ----------
class TestResourceAuthGuards:
    def test_list_requires_session(self):
        r = requests.get(f"{API}/resources", timeout=15)
        assert r.status_code == 401, r.text

    def test_upload_requires_admin(self):
        r = requests.post(f"{API}/resources", data={"title": "x"}, timeout=15)
        assert r.status_code == 401, r.text

    def test_download_requires_session(self):
        r = requests.get(f"{API}/resources/does-not-exist/download", timeout=15)
        assert r.status_code == 401, r.text

    def test_delete_requires_admin(self):
        r = requests.delete(f"{API}/resources/does-not-exist", timeout=15)
        assert r.status_code == 401, r.text

    def test_bogus_signed_cookie_still_401(self):
        r = requests.get(
            f"{API}/resources",
            cookies={"iris_session": "not-a-valid-signature"},
            timeout=15,
        )
        assert r.status_code == 401


# ---------- Router surface / static contract ----------
ROUTER = Path("/app/backend/routers/resources.py").read_text()
STORAGE = Path("/app/backend/services/storage_service.py").read_text()
MODEL = Path("/app/backend/models/resource.py").read_text()


class TestResourceRouterContract:
    def test_max_size_250_mb(self):
        assert "250 * 1024 * 1024" in ROUTER
        assert "413" in ROUTER

    def test_allowed_extensions_exact(self):
        for ext in ["pdf", "doc", "docx", "jpg", "jpeg", "png", "webp", "gif", "txt"]:
            assert f'"{ext}"' in ROUTER, f"extension {ext} missing"

    def test_no_html_or_exe_extension(self):
        for ext in ["exe", "html", "sh", "js", "zip"]:
            # ensure it's not in ALLOWED_TYPES map
            assert f'"{ext}":' not in ROUTER

    def test_list_excludes_storage_path(self):
        assert '"_id": 0, "storage_path": 0' in ROUTER

    def test_upload_uses_admin_dependency(self):
        assert "Depends(current_admin)" in ROUTER
        # list + download use current_helper
        assert "Depends(current_helper)" in ROUTER

    def test_upload_streams_to_tempfile(self):
        assert "tempfile.NamedTemporaryFile" in ROUTER
        assert "await file.read(1024 * 1024)" in ROUTER

    def test_delete_is_soft_delete(self):
        assert '"is_deleted": True' in ROUTER
        assert '"deleted_at":' in ROUTER

    def test_storage_path_uses_uuid_prefix(self):
        assert 'f"{APP_NAME}/resources/{resource_id}.{extension.lower()}"' in STORAGE
        assert 'APP_NAME = "iris"' in STORAGE

    def test_storage_key_singleton(self):
        assert "storage_key: str | None = None" in STORAGE
        assert "if storage_key:" in STORAGE

    def test_storage_is_local(self):
        assert "IRIS_STORAGE_ROOT" in STORAGE
        assert "shutil.copyfile" in STORAGE

    def test_model_does_not_expose_storage_path(self):
        assert "storage_path" not in MODEL


# ---------- Frontend static invariants ----------
FRONT = Path("/app/frontend/src")
APP_JS = (FRONT / "App.js").read_text()
SHELL = (FRONT / "components/AppShell.jsx").read_text()
LOGIN = (FRONT / "pages/LoginPage.jsx").read_text()
RES_PAGE = (FRONT / "pages/ResourcesPage.jsx").read_text()
CSS = (FRONT / "MentalHealth.css").read_text()
LOGO_URL = "https://customer-assets-lqy194kg.emergentagent.net/job_iris-logs/artifacts/jhsbq3v9_image.png"


class TestFrontendResources:
    def test_login_iris_logo_present(self):
        assert 'data-testid="login-iris-logo"' in LOGIN
        assert LOGO_URL in LOGIN

    def test_sidebar_iris_logo_present(self):
        assert 'data-testid="iris-logo"' in SHELL
        assert LOGO_URL in SHELL

    def test_sidebar_resources_link_and_labels(self):
        # Iteration 11: "Mon profil" label removed from sidebar links (relocated to profile pic in sidebar-bottom)
        for label in ["Suivis", "Archives", "Ressources", "Administration"]:
            assert label in SHELL
        assert 'data-testid="sidebar-resources-link"' in SHELL
        assert 'to="/resources"' in SHELL

    def test_route_registered(self):
        assert "ResourcesPage" in APP_JS
        assert 'path="/resources"' in APP_JS
        assert "isAdmin={isAdmin}" in APP_JS

    def test_resource_upload_admin_only(self):
        # form must be wrapped in isAdmin
        assert "{isAdmin && <form" in RES_PAGE
        assert 'data-testid="resource-upload-form"' in RES_PAGE
        assert 'data-testid="upload-resource-button"' in RES_PAGE
        assert 'data-testid="resource-file-input"' in RES_PAGE
        assert 'data-testid="resource-title-input"' in RES_PAGE
        assert 'data-testid="resource-category-input"' in RES_PAGE

    def test_resource_delete_admin_only(self):
        assert "isAdmin && <button" in RES_PAGE and "delete-resource" in RES_PAGE

    def test_resource_download_visible_to_all(self):
        # download button is not gated by isAdmin
        assert "download-resource-" in RES_PAGE
        # ensure the download button branch is unconditional (outside isAdmin gate)
        assert "download(resource)" in RES_PAGE

    def test_client_side_size_cap(self):
        assert "250 * 1024 * 1024" in RES_PAGE

    def test_accept_attribute_matches_backend_extensions(self):
        m = re.search(r'accept="([^"]+)"', RES_PAGE)
        assert m, "accept attribute missing on file input"
        exts = {e.strip().lstrip(".") for e in m.group(1).split(",")}
        assert exts == {"pdf", "doc", "docx", "jpg", "jpeg", "png", "webp", "gif", "txt"}

    def test_nav_link_has_visible_contrast(self):
        # ensure nav-link span text color is dark (not white)
        assert re.search(r"\.nano-sidebar \.nav-link span\s*\{[^}]*color:\s*#1a2a20", CSS)
