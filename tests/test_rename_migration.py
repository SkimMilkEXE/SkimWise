from PySide6.QtCore import QSettings

from skimwise.main import OLD_NAME, copy_old_settings, move_old_data_dir
from skimwise.ui.settings import APP_NAME


def test_old_data_folder_moves_once(tmp_path):
    old_dir, new_dir = tmp_path / OLD_NAME, tmp_path / APP_NAME
    old_dir.mkdir()
    (old_dir / "budget.db").write_text("my data")

    move_old_data_dir(new_dir)
    assert (new_dir / "budget.db").read_text() == "my data" and not old_dir.exists()

    # Running again changes nothing (and never overwrites newer data).
    (new_dir / "budget.db").write_text("newer data")
    move_old_data_dir(new_dir)
    assert (new_dir / "budget.db").read_text() == "newer data"


def test_old_settings_copied_once(tmp_path):
    # Temp .ini files, never the real registry.
    old = QSettings(str(tmp_path / "old.ini"), QSettings.Format.IniFormat)
    new = QSettings(str(tmp_path / "new.ini"), QSettings.Format.IniFormat)
    old.setValue("theme", "Dark")

    copy_old_settings(old, new)
    assert new.value("theme") == "Dark"

    new.setValue("theme", "Light")  # the user changes it under the new name
    copy_old_settings(old, new)
    assert new.value("theme") == "Light"  # not overwritten by the old value
