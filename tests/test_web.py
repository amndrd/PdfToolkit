"""The offline web interface.

Two things are being checked: that every registered tool is reachable through
the API, and that the guards which keep the server local actually hold.
"""

from __future__ import annotations

import io
import zipfile

import pytest

fastapi = pytest.importorskip("fastapi", reason="requires the 'web' extra")
from fastapi.testclient import TestClient  # noqa: E402

from recto.web.app import create_app  # noqa: E402
from recto.web.tools import TOOLS, get_tool  # noqa: E402


@pytest.fixture
def client(tmp_path):
    # base_url must look local, or the host guard (correctly) rejects it.
    with TestClient(create_app(tmp_path / "workspace"), base_url="http://localhost") as c:
        yield c


def upload(client, *paths):
    files = [("files", (p.name, p.read_bytes(), "application/pdf")) for p in paths]
    response = client.post("/api/files", files=files)
    assert response.status_code == 200, response.text
    return [item["id"] for item in response.json()["files"]]


def run(client, tool, file_ids, **options):
    return client.post(
        "/api/run", json={"tool": tool, "files": file_ids, "options": options}
    )


class TestStaticSurface:
    def test_health(self, client):
        assert client.get("/api/health").json()["status"] == "ok"

    def test_index_is_served(self, client):
        response = client.get("/")
        assert response.status_code == 200
        assert "Recto" in response.text

    def test_assets_are_served(self, client):
        assert client.get("/static/styles.css").status_code == 200
        assert client.get("/static/app.js").status_code == 200

    def test_page_loads_no_external_resources(self, client):
        """The UI must render with the network unplugged.

        What matters is that nothing is *fetched* from another origin — no
        CDN script, no web font, no remote image. A plain hyperlink the user
        may choose to click is not a fetch and does not stop the page working
        offline, so anchors are deliberately not covered here.
        """
        import re

        offenders: list[str] = []
        for path in ("/", "/static/styles.css", "/static/app.js"):
            body = client.get(path).text
            offenders += [
                f"{path}: {match}"
                for pattern in (
                    r'src\s*=\s*["\']https?://[^"\']+',  # scripts, images
                    r'<link[^>]+href\s*=\s*["\']https?://[^"\']+',  # stylesheets, fonts
                    r"url\(\s*['\"]?https?://[^)]+",  # CSS url()
                    r'@import\s+["\']?https?://[^;]+',  # CSS imports
                    r'fetch\(\s*["\']https?://[^"\']+',  # XHR to elsewhere
                )
                for match in re.findall(pattern, body, re.IGNORECASE)
            ]

        assert not offenders, f"page fetches from another origin: {offenders}"

    def test_the_only_external_link_is_an_anchor(self, client):
        """And it opens safely: a new tab, with no window.opener handle."""
        body = client.get("/").text
        assert 'href="https://github.com/amndrd"' in body
        assert 'rel="noopener noreferrer"' in body

    def test_security_headers(self, client):
        headers = client.get("/").headers
        assert "default-src 'none'" in headers["content-security-policy"]
        assert headers["x-content-type-options"] == "nosniff"
        assert headers["referrer-policy"] == "no-referrer"


class TestGuards:
    def test_non_local_host_is_refused(self, client):
        response = client.get("/api/health", headers={"host": "evil.example.com"})
        assert response.status_code == 421

    def test_cross_origin_is_refused(self, client):
        response = client.get(
            "/api/health", headers={"origin": "https://evil.example.com"}
        )
        assert response.status_code == 403

    def test_same_origin_is_allowed(self, client):
        response = client.get("/api/health", headers={"origin": "http://localhost:8765"})
        assert response.status_code == 200

    def test_empty_upload_is_rejected(self, client):
        response = client.post(
            "/api/files", files=[("files", ("empty.pdf", b"", "application/pdf"))]
        )
        assert response.status_code == 400


class TestCatalogue:
    def test_lists_every_tool(self, client):
        ids = {tool["id"] for tool in client.get("/api/tools").json()["tools"]}
        assert ids == {tool.id for tool in TOOLS}

    def test_declarations_are_complete(self, client):
        """The browser builds its form from this; missing keys break the UI."""
        for tool in client.get("/api/tools").json()["tools"]:
            assert tool["label"] and tool["description"] and tool["group"]
            assert tool["inputs"] in ("one", "two", "many")
            for field in tool["fields"]:
                assert field["name"] and field["label"]
                assert field["kind"] in (
                    "pages",
                    "text",
                    "number",
                    "bool",
                    "select",
                    "multiselect",
                    "password",
                )
                if field["kind"] in ("select", "multiselect"):
                    assert field["choices"], (
                        f"{tool['id']}.{field['name']} has no choices"
                    )

    def test_conditional_fields_reference_real_siblings(self):
        """A `when` pointing at a field that does not exist would never show."""
        for tool in TOOLS:
            names = {field.name for field in tool.fields}
            for field in tool.fields:
                for key in field.when or {}:
                    assert key in names, f"{tool.id}.{field.name} depends on {key}"

    def test_every_tool_has_a_runner(self):
        assert all(callable(tool.run) for tool in TOOLS)


class TestUpload:
    def test_reports_page_counts(self, client, sample):
        response = client.post(
            "/api/files",
            files=[("files", (sample.name, sample.read_bytes(), "application/pdf"))],
        )
        assert response.json()["files"][0]["pages"] == 3

    def test_flags_encrypted_files(self, client, locked):
        response = client.post(
            "/api/files",
            files=[("files", (locked.name, locked.read_bytes(), "application/pdf"))],
        )
        assert response.json()["files"][0]["encrypted"] is True

    def test_path_traversal_in_the_filename_is_neutralised(self, client, sample):
        response = client.post(
            "/api/files",
            files=[
                ("files", ("../../escape.pdf", sample.read_bytes(), "application/pdf"))
            ],
        )
        assert response.json()["files"][0]["name"] == "escape.pdf"

    def test_files_can_be_forgotten(self, client, sample):
        [file_id] = upload(client, sample)
        assert client.delete(f"/api/files/{file_id}").status_code == 200
        assert run(client, "repair", [file_id]).status_code == 404


class TestRunning:
    def test_merge(self, client, sample, other):
        ids = upload(client, sample, other)
        payload = run(client, "merge", ids).json()
        assert payload["pages"] == 5
        assert len(payload["outputs"]) == 1

    def test_split_produces_several_outputs(self, client, sample):
        ids = upload(client, sample)
        payload = run(client, "split", ids, mode="every", every=1).json()
        assert len(payload["outputs"]) == 3

    def test_results_can_be_downloaded(self, client, sample, other):
        ids = upload(client, sample, other)
        payload = run(client, "merge", ids).json()
        response = client.get(f"/api/result/{payload['job']}/0")
        assert response.status_code == 200
        assert response.content.startswith(b"%PDF-")

    def test_results_can_be_zipped(self, client, sample):
        ids = upload(client, sample)
        payload = run(client, "split", ids, mode="every", every=1).json()
        response = client.get(f"/api/result/{payload['job']}/archive/all.zip")
        assert response.status_code == 200
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            assert len(archive.namelist()) == 3

    def test_encrypted_input_with_a_password(self, client, locked):
        ids = upload(client, locked)
        assert run(client, "repair", ids, password="s3cret").status_code == 200

    @pytest.mark.parametrize(
        ("tool_id", "options"),
        [
            ("rotate", {"degrees": "90"}),
            ("extract", {"pages": "1"}),
            ("delete", {"pages": "2"}),
            ("reorder", {"order": "2,1"}),
            ("reverse", {}),
            ("duplicate", {"pages": "1", "times": 2}),
            ("encrypt", {"user_password": "pw", "allow": ["print"]}),
            ("meta-set", {"title": "Hello"}),
            ("meta-strip", {}),
            ("compress", {"preset": "lossless"}),
            ("repair", {}),
            ("to-images", {"dpi": 48, "format": "png"}),
        ],
    )
    def test_single_input_tools(self, client, sample, tool_id, options):
        ids = upload(client, sample)
        response = run(client, tool_id, ids, **options)
        assert response.status_code == 200, response.text
        assert response.json()["outputs"]

    def test_two_input_tool(self, client, sample, other):
        ids = upload(client, sample, other)
        response = run(client, "insert", ids, at=1)
        assert response.status_code == 200
        assert response.json()["pages"] == 5


class TestErrors:
    def test_unknown_tool(self, client, sample):
        assert run(client, "teleport", upload(client, sample)).status_code == 404

    def test_unknown_file_id(self, client):
        assert run(client, "repair", ["deadbeef"]).status_code == 404

    def test_no_files(self, client):
        assert run(client, "repair", []).status_code == 400

    def test_wrong_number_of_files(self, client, sample, other):
        ids = upload(client, sample, other)
        response = run(client, "rotate", ids, degrees="90")
        assert response.status_code == 400
        assert "exactly 1 file" in response.json()["detail"]

    def test_merge_needs_two(self, client, sample):
        response = run(client, "merge", upload(client, sample))
        assert response.status_code == 400

    def test_core_errors_become_400_with_a_type(self, client, sample):
        response = run(client, "extract", upload(client, sample), pages="99")
        assert response.status_code == 400
        assert response.json()["error"] == "InvalidPageRange"
        assert "out of bounds" in response.json()["detail"]

    def test_missing_password_is_reported(self, client, locked):
        response = run(client, "repair", upload(client, locked))
        assert response.status_code == 400
        assert response.json()["error"] == "PasswordRequired"

    def test_unknown_result(self, client):
        assert client.get("/api/result/nope/0").status_code == 404

    def test_options_must_be_an_object(self, client, sample):
        ids = upload(client, sample)
        response = client.post(
            "/api/run", json={"tool": "repair", "files": ids, "options": "nope"}
        )
        assert response.status_code == 400


class TestToolRegistry:
    def test_lookup(self):
        assert get_tool("merge") is not None
        assert get_tool("teleport") is None


class TestThumbnails:
    """Page previews — the UI shows the document rather than describing it."""

    def test_renders_a_page(self, client, sample):
        [file_id] = upload(client, sample)
        response = client.get(f"/api/files/{file_id}/page/0?width=240")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.content.startswith(b"\x89PNG")

    def test_every_page_is_reachable(self, client, sample):
        [file_id] = upload(client, sample)
        for page in range(3):
            assert client.get(f"/api/files/{file_id}/page/{page}").status_code == 200

    def test_out_of_range_page(self, client, sample):
        [file_id] = upload(client, sample)
        response = client.get(f"/api/files/{file_id}/page/99")
        assert response.status_code == 400
        assert "does not exist" in response.json()["detail"]

    def test_negative_page(self, client, sample):
        [file_id] = upload(client, sample)
        assert client.get(f"/api/files/{file_id}/page/-1").status_code == 404

    def test_unknown_file(self, client):
        assert client.get("/api/files/deadbeef/page/0").status_code == 404

    def test_width_is_snapped_to_a_known_size(self, client, sample):
        """An arbitrary width must not become an arbitrary render."""
        from recto.web.preview import THUMBNAIL_WIDTHS, nearest_width

        assert nearest_width(9999) == max(THUMBNAIL_WIDTHS)
        assert nearest_width(1) == min(THUMBNAIL_WIDTHS)
        [file_id] = upload(client, sample)
        assert client.get(f"/api/files/{file_id}/page/0?width=99999").status_code == 200

    def test_second_request_is_served_from_cache(self, client, sample, tmp_path):
        [file_id] = upload(client, sample)
        client.get(f"/api/files/{file_id}/page/0?width=240")
        cached = list((tmp_path / "workspace" / "thumbs" / file_id).glob("*.png"))
        assert len(cached) == 1
        stamp = cached[0].stat().st_mtime_ns
        client.get(f"/api/files/{file_id}/page/0?width=240")
        assert cached[0].stat().st_mtime_ns == stamp

    def test_encrypted_file_needs_the_password(self, client, locked):
        [file_id] = upload(client, locked)
        assert client.get(f"/api/files/{file_id}/page/0").status_code == 400
        with_password = client.get(f"/api/files/{file_id}/page/0?password=s3cret")
        assert with_password.status_code == 200

    def test_catalogue_advertises_preview_support(self, client):
        assert client.get("/api/tools").json()["previews"] is True


class TestInterfaceShell:
    """The static page has to carry the pieces app.js expects to find."""

    def test_every_element_the_script_looks_up_exists(self, client):
        """app.js resolves all of its elements by id as it loads.

        Deriving the list from the script rather than hard-coding it means
        this cannot quietly go stale: rename an id in one file and forget the
        other, and the mismatch shows up here instead of as a dead interface
        in the browser.
        """
        import re

        script = client.get("/static/app.js").text
        body = client.get("/").text

        ids = set(re.findall(r'\bel\("([^"]+)"\)', script))
        assert ids, "expected app.js to resolve its elements through el(...)"

        missing = sorted(name for name in ids if f'id="{name}"' not in body)
        assert not missing, f"app.js looks up ids index.html does not define: {missing}"

    def test_the_shell_carries_the_navigation_bar(self, client):
        body = client.get("/").text
        assert 'class="navbar"' in body
        assert 'id="navtabs"' in body
        assert 'id="restart"' in body

    def test_workspace_starts_hidden(self, client):
        body = client.get("/").text
        assert 'id="workspace" class="workspace hidden"' in body
