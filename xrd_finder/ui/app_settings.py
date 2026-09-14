from __future__ import annotations

from PySide6.QtCore import QSettings

from xrd_finder.services.cache_paths import default_data_root


def configure_app_settings_storage() -> None:
    settings_root = default_data_root() / "settings" / "qt"
    settings_root.mkdir(parents=True, exist_ok=True)
    QSettings.setDefaultFormat(QSettings.Format.IniFormat)
    QSettings.setPath(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        str(settings_root),
    )


def app_settings() -> QSettings:
    configure_app_settings_storage()
    return QSettings(
        QSettings.Format.IniFormat,
        QSettings.Scope.UserScope,
        "Xrdfinder",
        "Standalone",
    )
