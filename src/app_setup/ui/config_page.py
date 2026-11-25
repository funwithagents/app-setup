"""A config app's page: a config file edited with the Setup and Secrets panels, and no
session (specs/config-file.md, "A config app").

```python
model = open_config_app(options, APP)  # a writable ConfigFile, its .env loaded
config_page(model).launch(server_name=options.host, server_port=options.port)
```
"""

from __future__ import annotations

import gradio as gr

from app_setup.app import AppModel
from app_setup.ui.panels import secrets_panel, setup_panel

__all__ = ["config_page"]


def config_page(model: AppModel) -> gr.Blocks:
    """A page of two tabs, **Setup** and **Secrets**, editing *model*'s config: Save writes
    it back to its source, Revert reads it again. Nothing runs: the page has no session."""
    with gr.Blocks(title=model.title) as page:
        gr.Markdown(f"## {model.title}\n\nEditing `{model.source.config_path}`.")
        with gr.Tab("Setup"):
            setup = setup_panel(model)
        with gr.Tab("Secrets"):
            secrets_panel(model, setup.draft)
    return page
