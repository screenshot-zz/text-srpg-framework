# Text Chronicles

A pure-text SRPG framework rendered with `rich`. Maps, units, skills, stories, and formulas are all driven by YAML under `config/` — extend by editing config, almost no Python changes needed.

**中文**：[README.md](README.md)  
**Scripting Guide**: [docs/scripting.md](docs/scripting.md) (events, variables, actions, triggers)

---

## Features

- **Pure-text tactical RPG**: maps, units, and battle animations rendered in terminal
- **Config-driven**: maps / classes / skills / items / stories / terrain / shops / AI all in YAML
- **Visual YAML editor**: built-in `tools/yaml_editor` for GUI config editing

---

## Requirements

- **Python 3.10+**
- **Required**: `rich` / `PyYAML` / `simpleeval`
- **Music (optional)**: `pygame` — game runs fine without it, just no BGM
- **YAML editor (optional)**: `PySide6` + `ruamel.yaml`

---

## Installation

```bash
# Install required dependencies
pip install -r requirements.txt

# Optional: enable music
pip install pygame

# Optional: enable YAML editor
pip install PySide6 ruamel.yaml

##Running

# Start the game
python main.py
# Start the YAML editor (GUI)
python -m tools.yaml_editor

##Feedback & Contributions
Found a bug? Want a new feature? Want to translate?
Send the relevant source code and a description to an AI (DeepSeek / ChatGPT / Claude, etc.) for modification. The project is fully config-driven — AI can extend content by editing YAML, or add systems by editing Python.
