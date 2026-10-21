import json

import pytest

from app.services.file_ingestion import FileIngestionError, parse_requirement_file, safe_filename


def parse(filename: str, content: bytes):
    return parse_requirement_file(filename, content, max_bytes=10_000, max_requirements=10)


def test_markdown_file_becomes_one_requirement_with_stable_identity() -> None:
    items = parse("../Password_Reset.md", b"# Password reset\nUsers must receive an expiring link.")

    assert len(items) == 1
    assert items[0].title == "Password reset"
    assert items[0].description == "Users must receive an expiring link."
    assert items[0].external_id.startswith("file:")
    assert items[0].metadata["upload_filename"] == "Password_Reset.md"
    assert len(items[0].metadata["upload_sha256"]) == 64


def test_csv_and_json_parse_multiple_requirements() -> None:
    csv_items = parse(
        "requirements.csv",
        b"external_id,title,description\nAUTH-1,Login,Users can sign in\nAUTH-2,Logout,Users can sign out\n",
    )
    json_items = parse(
        "requirements.json",
        json.dumps({"requirements": [{"title": "Reset", "description": "Users reset passwords"}]}).encode(),
    )

    assert [item.external_id for item in csv_items] == ["AUTH-1", "AUTH-2"]
    assert json_items[0].title == "Reset"


@pytest.mark.parametrize(
    ("filename", "content", "message"),
    [
        ("requirements.pdf", b"pdf", "Supported file types"),
        ("requirements.txt", b"", "empty"),
        ("requirements.txt", b"abc\x00def", "Binary"),
        ("requirements.csv", b"name,body\na,b\n", "title and description"),
    ],
)
def test_invalid_files_fail_closed(filename: str, content: bytes, message: str) -> None:
    with pytest.raises(FileIngestionError, match=message):
        parse(filename, content)


def test_size_and_count_limits_are_enforced() -> None:
    with pytest.raises(FileIngestionError, match="byte limit"):
        parse_requirement_file("large.txt", b"a" * 20, max_bytes=10, max_requirements=10)
    with pytest.raises(FileIngestionError, match="requirement limit"):
        parse_requirement_file(
            "many.json",
            json.dumps([{"title": str(index), "description": "description"} for index in range(3)]).encode(),
            max_bytes=10_000,
            max_requirements=2,
        )


def test_filename_is_reduced_to_basename() -> None:
    assert safe_filename("../../private/requirements.csv") == "requirements.csv"
