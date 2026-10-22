\# FE YAML Editor



火焰之纹章·文字战记 — 图形化 YAML 数据管理器（P1）。



\## 它是什么



不手写 yaml 的可视化编辑器，只读写 `config/` 下的 5 个核心 YAML：



| 文件 | 编辑器 | 交付阶段 |

|---|---|---|

| `config/status.yaml` | `StatusEditor` | ✅ P1 |

| `config/items.yaml` | `ItemsEditor` | P2 |

| `config/skills.yaml` | `SkillsEditor` | P2 |

| `config/classes.yaml` | `ClassesEditor` | P3 |

| `config/units.yaml` | `UnitsEditor` | P3 |



\## 怎么装



```bash

pip install -r tools/yaml\_editor/requirements.txt

```



\*\*不碰根目录 requirements.txt\*\*（尊重"不改动已有内容"的硬约束）。



\## 怎么跑



```bash

\# 在项目根目录执行

python -m tools.yaml\_editor

```



\## 设计边界（红线）



1\. ✅ 只读写 `config/\*.yaml`，不动 `core/` / `save/` / `main.py`

2\. ✅ \*\*注释保留是硬需求\*\*（ruamel round-trip mode）—— 保存后中文注释、流式风格 `{hp: 20, str: 5}`、引号风格全部保持

3\. ✅ 不新增 yaml 字段、不改 key 名（英文 key 保持不变）

4\. ✅ 保存前自动备份到 `config/.backup/{filename}.{时间戳}.bak`，保留最近 20 份

5\. ✅ 零 `core` 依赖 —— 编辑器不认识 `Unit` / `Game` / `ev()`，只认识"JSON 结构 + 注释节点"

6\. ✅ 未映射的中文字段会记录到 `tools/yaml\_editor/.runtime/unmapped.log`（不污染 `config/`）



\## 注释保留原理



```python

from ruamel.yaml import YAML

yaml = YAML(typ="rt")       # round-trip mode

yaml.preserve\_quotes = True # 保留引号风格

data = yaml.load(f)         # 载入 → CommentedMap（含注释）

\# ...修改...

yaml.dump(data, f)          # 写回 → 注释全部保留

```



\*\*关键不变量\*\*：

\- 修改已有字段用 `set()` 直接改原 `CommentedMap`

\- 新增字段用 `yaml\_io.ensure\_commented(new\_dict)` 递归转 `CommentedMap/CommentedSeq`

\- 任何"手动 `dict()` 构造"的赋值都会退化成块风格 —— 禁用



\## 目录说明



```

tools/yaml\_editor/

├── \_\_main\_\_.py          # python -m tools.yaml\_editor 入口

├── main.py              # 逻辑入口

├── app.py               # QApplication + MainWindow 装配

├── yaml\_io.py           # ruamel 封装（注释保留核心）

├── backup.py            # 备份机制

├── zh\_map.py            # 字段/值中英映射

├── registry.py          # ID 引用注册表

├── widgets/             # 主窗口 + 通用控件

├── editors/             # 每个 yaml 的专用编辑器

└── .runtime/            # 运行时数据（首次启动自动创建）

&#x20;   └── unmapped.log

```



\## 备份目录



`config/.backup/` —— 由方案 6.5 指定，编辑器只写 `.bak`，不动任何 `.yaml`。



\## 版本



\- \*\*P1\*\*（本次）：ruamel 保留注释 + 主窗口骨架 + `status\_editor` 完整实现

\- P2：`items\_editor` / `skills\_editor`

\- P3：`classes\_editor` / `units\_editor`

