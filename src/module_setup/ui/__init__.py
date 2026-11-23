"""The Setup and Secrets panels, drawn with gradio inside an app's own page (specs/ui.md).
Needs the ``ui`` extra.

```python
model = AppModel(APP, ConfigFolder(default_folder(APP.name), APP.default_config))
with gr.Blocks() as page:
    with gr.Tab("Setup"):
        setup = setup_panel(model)
    with gr.Tab("Secrets"):
        secrets_panel(model, setup.draft)
```
"""

from __future__ import annotations

from module_setup.ui.panels import SetupPanel, secrets_panel, setup_panel

__all__ = ["SetupPanel", "secrets_panel", "setup_panel"]
