from __future__ import annotations


class TmsWmsDatabaseRouter:
    legacy_app_label = "legacy_integrations"

    def db_for_read(self, model, **hints):
        if model._meta.app_label == self.legacy_app_label:
            return "litecore"
        return "default"

    def db_for_write(self, model, **hints):
        if model._meta.app_label == self.legacy_app_label:
            return None
        return "default"

    def allow_relation(self, obj1, obj2, **hints):
        labels = {obj1._meta.app_label, obj2._meta.app_label}
        if self.legacy_app_label in labels:
            return False
        return None

    def allow_migrate(self, db, app_label, model_name=None, **hints):
        if app_label == self.legacy_app_label:
            return False
        return db == "default"
