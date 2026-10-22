# 文字战记

纯文字 + `rich` 渲染的 SRPG 战棋游戏框架。地图、人物、技能、剧情、公式全部由 `config/` 下的 YAML 驱动，改配置即可扩展，几乎不需要改 Python。

**English**：[README.en.md](README.en.md)  
**脚本编写指南**：[docs/scripting.md](docs/scripting.md)（事件变量 / 动作 / 触发条件速查）

---

## 特性

- **纯文字战棋**：终端渲染地图、单位、战斗动画，无需图形库
- **配置驱动**：地图 / 职业 / 技能 / 道具 / 剧情 / 地形 / 商店 / AI 全部 YAML
- **可视化 YAML 编辑器**：内置 `tools/yaml_editor`，图形界面编辑配置

---

## 环境要求

- **Python 3.10+**
- **必需依赖**：`rich` / `PyYAML` / `simpleeval`
- **音乐（可选）**：`pygame` —— 不装也能玩，只是没有 BGM
- **YAML 编辑器（可选）**：`PySide6` + `ruamel.yaml`

---

## 安装

```bash
# 安装游戏必需依赖
pip install -r requirements.txt

# 可选：启用音乐
pip install pygame

# 可选：启用 YAML 编辑器
pip install PySide6 ruamel.yaml

## 运行

# 启动游戏
python main.py
# 启动 YAML 编辑器（图形界面）
python -m tools.yaml_editor

##反馈与贡献
有 Bug？想要新功能？想翻译？
直接把相关源码和需求描述发给 AI（DeepSeek / ChatGPT / Claude 等）进行修改。本项目完全配置驱动，AI 改 YAML 就能扩展内容，改 Python 就能加系统。



