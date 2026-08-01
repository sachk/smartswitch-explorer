from __future__ import annotations

from urllib.parse import parse_qs, urlparse

from gui.diagnostics import anonymize_diagnostic_text, build_anonymized_report, build_issue_url


def test_anonymize_diagnostic_text_removes_personal_identifiers() -> None:
    source = (
        r"Failed for com.tozelabs.tvshowtime at C:\Users\artho\Backup\file.data "
        "/home/artho/export artho@example.com IMEI 123456789012345 "
        "key AABBCCDDEEFF00112233445566778899"
    )

    sanitized = anonymize_diagnostic_text(source)

    for secret in (
        "com.tozelabs.tvshowtime",
        "artho",
        "artho@example.com",
        "123456789012345",
        "AABBCCDDEEFF00112233445566778899",
    ):
        assert secret not in sanitized
    assert "<package-id>" in sanitized
    assert sanitized.count("<path>") == 2
    assert "<email>" in sanitized
    assert "<number>" in sanitized
    assert "<redacted-hex>" in sanitized


def test_issue_url_contains_only_anonymized_report() -> None:
    report = build_anonymized_report(
        [r"Failure for com.example.private at C:\Users\person\backup"],
        ["Contact person@example.com"],
    )

    issue_url = build_issue_url(report)
    parsed = urlparse(issue_url)
    query = parse_qs(parsed.query)
    body = query["body"][0]

    assert parsed.netloc == "github.com"
    assert parsed.path == "/sachk/smartswitch-explorer/issues/new"
    assert query["title"] == ["Backup export failed"]
    assert "<package-id>" in body
    assert "<path>" in body
    assert "<email>" in body
    assert "com.example.private" not in issue_url
    assert "person@example.com" not in issue_url
    assert "No backup files or backup metadata are included." in body


def test_issue_url_truncates_oversized_reports() -> None:
    issue_url = build_issue_url("x" * 10_000)
    body = parse_qs(urlparse(issue_url).query)["body"][0]

    assert "report truncated for URL" in body
    assert len(body) < 6500
