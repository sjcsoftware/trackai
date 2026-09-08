"""Background collection; GTK publication and settings reads run on main."""
import threading
from datetime import datetime, timezone
from .settings import Settings
from .providers import PROVIDERS, collect


class AppState:
    def __init__(self, settings=None):
        self.settings = settings or Settings.shared()
        self.accounts = []
        self.selected_account_id = None
        self.last_refresh = None
        self.is_refreshing = False
        self.dispatch = lambda fn: fn()
        self._listeners = []
        self._providers = {p.kind: p() for p in PROVIDERS}
        self._worker = None

    def add_listener(self, callback):
        self._listeners.append(callback)

    def _notify(self):
        for callback in self._listeners:
            callback()

    @property
    def selected_account(self):
        return next((d for d in self.accounts if d.id == self.selected_account_id),
                    self.accounts[0] if self.accounts else None)

    @property
    def menu_bar_account(self):
        return next((d for d in self.accounts if d.id == self.settings.default_account_id),
                    self.selected_account)

    def icon_percent(self):
        mode = self.settings.icon_mode
        data = self.accounts
        if mode == "single":
            data = [self.menu_bar_account] if self.menu_bar_account else []
        else:
            data = [d for d in data if d.kind in self.settings.icon_providers]
        values = [d.metric_percent(self.settings.color_metric) for d in data]
        values = [v for v in values if v is not None]
        return (max(values) if mode == "highest" else sum(values) / len(values)) if values else None

    def select(self, account_id):
        self.selected_account_id = account_id
        self._notify()

    def start(self):
        self.refresh()

    def refresh(self, force=False, completion=None):
        if self.is_refreshing:
            return
        self.is_refreshing = True
        settings = self.settings.snapshot()
        self._notify()

        def work():
            results = collect(self._providers, settings, force)

            def publish():
                self.accounts = results
                self.last_refresh = datetime.now(timezone.utc)
                self.is_refreshing = False
                self._notify()
                if completion:
                    completion()
            self.dispatch(publish)

        self._worker = threading.Thread(target=work, name="trackai-refresh", daemon=True)
        self._worker.start()
