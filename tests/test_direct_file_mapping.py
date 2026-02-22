from __future__ import annotations

from pathlib import Path

from smartswitch_core.direct_file import (
    infer_package_from_apk_filename,
    map_direct_file_to_item_ids,
    message_item_ids_from_filename,
)


def test_message_item_ids_from_filename() -> None:
    assert message_item_ids_from_filename("!@ssm@!sms_restore.bk") == {"messages:sms"}
    assert message_item_ids_from_filename("!@ssm@!PART_1_image.jpg") == {"messages:attachments"}
    assert message_item_ids_from_filename("!@ssm@!RCSMESSAGE!@ssm@!RcsMessage.edb") == {"messages:rcs"}


def test_infer_package_from_apk_filename() -> None:
    packages = {"com.example.app", "com.other.app"}
    assert infer_package_from_apk_filename("com.example.app_split_config.en.apk", packages) == "com.example.app"
    assert infer_package_from_apk_filename("com.example.app.apk", packages) == "com.example.app"
    assert infer_package_from_apk_filename("unknown.apk", packages) is None


def test_map_direct_file_to_item_ids(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    (backup / "MESSAGE").mkdir(parents=True)
    (backup / "APKFILE").mkdir(parents=True)
    (backup / "CONTACT").mkdir(parents=True)
    (backup / "CALLLOG").mkdir(parents=True)

    smem = backup / "MESSAGE" / "Message.smem"
    sms = backup / "MESSAGE" / "!@ssm@!sms_restore.bk"
    app_data = backup / "APKFILE" / "com.example.app.data"
    app_penc = backup / "APKFILE" / "com.example.app.penc"
    app_split = backup / "APKFILE" / "com.example.app_split_config.en.apk"
    contacts_csv = backup / "CONTACT" / "Contact.csv"
    contacts_spbm = backup / "CONTACT" / "Contact.spbm"
    calllog_zip = backup / "CALLLOG" / "CALLLOG.zip"
    unsupported = backup / "MESSAGE" / "not_supported.bin"

    for path in (smem, sms, app_data, app_penc, app_split, contacts_csv, contacts_spbm, calllog_zip, unsupported):
        path.write_bytes(b"x")

    available_ids = {
        "messages:sms",
        "messages:mms",
        "messages:attachments",
        "messages:rcs",
        "app_data:com.example.app",
        "app_apk:com.example.app",
        "contacts",
        "calllog",
    }

    assert map_direct_file_to_item_ids(smem, backup, available_ids)[0] == {
        "messages:sms",
        "messages:mms",
        "messages:attachments",
        "messages:rcs",
    }
    assert map_direct_file_to_item_ids(sms, backup, available_ids)[0] == {"messages:sms"}
    assert map_direct_file_to_item_ids(app_data, backup, available_ids)[0] == {"app_data:com.example.app"}
    assert map_direct_file_to_item_ids(app_penc, backup, available_ids)[0] == {"app_apk:com.example.app"}
    assert map_direct_file_to_item_ids(app_split, backup, available_ids)[0] == {"app_apk:com.example.app"}
    assert map_direct_file_to_item_ids(contacts_csv, backup, available_ids)[0] == {"contacts"}
    assert map_direct_file_to_item_ids(contacts_spbm, backup, available_ids)[0] == {"contacts"}
    assert map_direct_file_to_item_ids(calllog_zip, backup, available_ids)[0] == {"calllog"}

    selected, reason = map_direct_file_to_item_ids(unsupported, backup, available_ids)
    assert selected == set()
    assert reason


def test_map_smem_outside_message_dir(tmp_path: Path) -> None:
    backup = tmp_path / "backup"
    weird_dir = backup / "random" / "nested"
    weird_dir.mkdir(parents=True)
    smem = weird_dir / "foo.smem"
    smem.write_bytes(b"x")

    available_ids = {
        "messages:sms",
        "messages:mms",
        "messages:attachments",
        "messages:rcs",
    }
    selected, reason = map_direct_file_to_item_ids(smem, backup, available_ids)
    assert not reason
    assert selected == available_ids
