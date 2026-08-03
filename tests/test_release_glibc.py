from scripts.release.check_glibc import parse_version, required_glibc_versions


def test_required_glibc_versions_extracts_and_deduplicates_versions() -> None:
    output = """
      0x00 0x09691a75 0x00 03 GLIBC_2.35
      Name: GLIBC_2.34  Flags: none  Version: 7
      Name: GLIBCXX_3.4.29  Flags: none  Version: 9
      Name: GLIBC_2.35  Flags: none  Version: 10
    """

    assert required_glibc_versions(output) == {(2, 34), (2, 35)}


def test_parse_version_supports_multi_part_versions() -> None:
    assert parse_version("2.35.1") == (2, 35, 1)
