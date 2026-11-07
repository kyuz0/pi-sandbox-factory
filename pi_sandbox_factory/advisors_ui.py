"""Shared advisor selection and explicit host-login import controls."""
from textual import on
from textual.containers import Vertical
from .advisor_credentials import LABELS
from .tui_widgets import Checkbox


class AdvisorChoices(Vertical):
    DEFAULT_CSS = """
    AdvisorChoices { height: auto; }
    """

    def __init__(self, providers, prefix):
        super().__init__()
        self.providers = providers
        self.prefix = prefix

    def compose(self):
        for provider, label in LABELS.items():
            with Vertical(classes='setting'):
                yield Checkbox(label, value=provider in self.providers, id=self.prefix + provider)
                copy = Checkbox('Copy credentials from host', id=self.prefix + 'copy-' + provider,
                                disabled=provider not in self.providers, classes='copy-login')
                copy.display = provider in self.providers
                yield copy

    @on(Checkbox.Changed)
    def changed(self, event):
        for provider in LABELS:
            if event.checkbox.id == self.prefix + provider:
                field = self.query_one('#' + self.prefix + 'copy-' + provider, Checkbox)
                field.disabled = not event.value
                field.display = event.value
                if not event.value:
                    field.value = False

    def selected(self):
        return [p for p in LABELS if self.query_one('#' + self.prefix + p, Checkbox).value]

    def imports(self):
        return [p for p in self.selected() if self.query_one('#' + self.prefix + 'copy-' + p, Checkbox).value]
