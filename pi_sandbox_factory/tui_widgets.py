"""Shared terminal controls."""
from textual.content import Content
from textual.widgets import Checkbox as TextualCheckbox


class Checkbox(TextualCheckbox):
    """Distinguish both states by shape, including in monochrome terminals."""
    @property
    def _button(self):
        return Content('[✓]' if self.value else '[ ]').stylize(self.get_visual_style('toggle--button'))

