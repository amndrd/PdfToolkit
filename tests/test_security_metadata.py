"""Encryption, permissions and document metadata."""

from __future__ import annotations

import pytest

from conftest import make_pdf, page_widths
from recto.core import (
    decrypt,
    describe,
    encrypt,
    inspect_security,
    read_metadata,
    set_metadata,
    strip_metadata,
)
from recto.core.security import PERMISSIONS, permissions_from_names
from recto.errors import (
    InvalidDocument,
    PasswordRequired,
    UnsupportedOperation,
    WrongPassword,
)


class TestEncrypt:
    def test_round_trip(self, sample, out, tmp_path):
        encrypt(sample, out, "s3cret")
        with pytest.raises(PasswordRequired):
            describe(out)
        assert describe(out, password="s3cret")["pages"] == 3

        opened = tmp_path / "open.pdf"
        decrypt(out, opened, password="s3cret")
        assert page_widths(opened) == [200, 201, 202]

    @pytest.mark.parametrize("algorithm", ["AES-256", "AES-128", "RC4-128", "RC4-40"])
    def test_every_algorithm_round_trips(self, sample, tmp_path, algorithm):
        target = tmp_path / f"{algorithm}.pdf"
        encrypt(sample, target, "pw", algorithm=algorithm)
        assert describe(target, password="pw")["pages"] == 3

    def test_algorithm_is_reported_back(self, sample, out):
        encrypt(sample, out, "pw", algorithm="AES-256")
        assert inspect_security(out, password="pw")["algorithm"] == "AES-256"

    def test_unknown_algorithm(self, sample, out):
        with pytest.raises(UnsupportedOperation, match="Unknown algorithm"):
            encrypt(sample, out, "pw", algorithm="ROT13")

    def test_wrong_password_is_rejected(self, sample, out):
        encrypt(sample, out, "s3cret")
        with pytest.raises(WrongPassword):
            describe(out, password="wrong")

    def test_owner_password_only_leaves_it_openable(self, sample, out):
        """An empty user password means anyone can open it; permissions still apply."""
        encrypt(sample, out, "", owner_password="boss", allow=["print"])
        info = inspect_security(out)
        assert info["encrypted"] is True
        assert info["permissions"]["print"] is True
        assert info["permissions"]["modify"] is False

    def test_page_content_survives(self, sample, out, tmp_path):
        encrypt(sample, out, "pw")
        opened = tmp_path / "open.pdf"
        decrypt(out, opened, password="pw")
        assert page_widths(opened) == page_widths(sample)


class TestPermissions:
    def test_named_permissions_are_granted(self, sample, out):
        encrypt(sample, out, "pw", allow=["print", "copy"])
        granted = inspect_security(out, password="pw")["permissions"]
        assert granted["print"] and granted["copy"]
        assert not granted["modify"]

    def test_all_grants_everything(self, sample, out):
        encrypt(sample, out, "pw", allow=["all"])
        assert all(inspect_security(out, password="pw")["permissions"].values())

    def test_none_grants_nothing(self, sample, out):
        encrypt(sample, out, "pw", allow=["none"])
        assert not any(inspect_security(out, password="pw")["permissions"].values())

    def test_unknown_permission_name(self):
        with pytest.raises(InvalidDocument, match="Unknown permission"):
            permissions_from_names(["teleport"])

    def test_every_documented_permission_is_settable(self, sample, tmp_path):
        for name in PERMISSIONS:
            target = tmp_path / f"{name}.pdf"
            encrypt(sample, target, "pw", allow=[name])
            assert inspect_security(target, password="pw")["permissions"][name]


class TestDecrypt:
    def test_needs_the_password(self, sample, out, tmp_path):
        encrypt(sample, out, "s3cret")
        with pytest.raises(WrongPassword):
            decrypt(out, tmp_path / "no.pdf", password="guess")

    def test_unencrypted_input_is_an_error(self, sample, out):
        with pytest.raises(UnsupportedOperation, match="not encrypted"):
            decrypt(sample, out)

    def test_result_is_no_longer_encrypted(self, sample, out, tmp_path):
        encrypt(sample, out, "pw")
        opened = tmp_path / "open.pdf"
        decrypt(out, opened, password="pw")
        assert inspect_security(opened)["encrypted"] is False


class TestInspectSecurity:
    def test_unencrypted_permits_everything(self, sample):
        info = inspect_security(sample)
        assert info["encrypted"] is False
        assert all(info["permissions"].values())


class TestMetadata:
    def test_set_and_read_back(self, sample, out):
        set_metadata(sample, out, {"title": "Q3 Results", "author": "Finance"})
        data = read_metadata(out)
        assert data["title"] == "Q3 Results"
        assert data["author"] == "Finance"

    def test_unlisted_fields_survive(self, tmp_path, out):
        source = make_pdf(tmp_path / "m.pdf", 2, metadata={"/Subject": "Keep me"})
        set_metadata(source, out, {"title": "New"})
        assert read_metadata(out)["subject"] == "Keep me"

    def test_none_clears_a_single_field(self, tmp_path, out):
        source = make_pdf(tmp_path / "m.pdf", 2, metadata={"/Author": "Gone"})
        set_metadata(source, out, {"author": None})
        assert read_metadata(out)["author"] is None

    def test_unknown_field(self, sample, out):
        with pytest.raises(InvalidDocument, match="Unknown metadata field"):
            set_metadata(sample, out, {"colour": "blue"})

    def test_modification_date_is_touched(self, sample, out):
        set_metadata(sample, out, {"title": "x"})
        assert read_metadata(out)["modified"] is not None

    def test_modification_date_can_be_left_alone(self, sample, out):
        set_metadata(sample, out, {"title": "x"}, touch_modified=False)
        assert read_metadata(out)["modified"] is None


class TestStripMetadata:
    def test_removes_everything(self, tmp_path, out):
        source = make_pdf(
            tmp_path / "m.pdf",
            2,
            metadata={"/Title": "Secret", "/Author": "Someone Real"},
        )
        strip_metadata(source, out)
        data = read_metadata(out)
        assert data["title"] is None
        assert data["author"] is None

    def test_keep_producer_leaves_a_marker(self, sample, out):
        strip_metadata(sample, out, keep_producer=True)
        assert "Recto" in (read_metadata(out)["producer"] or "")

    def test_pages_are_untouched(self, sample, out):
        strip_metadata(sample, out)
        assert page_widths(out) == [200, 201, 202]

    def test_reports_what_it_removed(self, sample, out):
        assert "XMP" in strip_metadata(sample, out).details["removed"]


class TestDescribe:
    def test_reports_structure(self, outlined):
        info = describe(outlined)
        assert info["pages"] == 9
        assert info["outline_entries"] == 3
        assert info["has_outline"] is True
        assert info["pdf_version"].startswith("1.")

    def test_reports_page_geometry(self, sample):
        assert sum(describe(sample)["page_sizes"].values()) == 3

    def test_reports_rotation(self, sample, out):
        from recto.core import rotate

        rotate(sample, out, 90, pages="2")
        assert describe(out)["rotated_pages"] == {2: 90}

    def test_reports_security(self, locked):
        info = describe(locked, password="s3cret")
        assert info["security"]["encrypted"] is True

    def test_is_json_serialisable(self, outlined):
        import json

        assert json.loads(json.dumps(describe(outlined), default=str))["pages"] == 9
