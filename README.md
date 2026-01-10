# 链接！ 喜欢！ 爱生活！ 剧本智能分块处理工具

为 Visual Novel / Galgame 剧本（特别是 链接！ 喜欢！ 爱生活！）设计的智能预处理工具，旨在生成专为 RAG (Retrieval-Augmented Generation) 和 LangChain 知识库优化的语义分块。

## 🌟 核心特性

- **语义完整性**：基于场景边界、对话组和语义相似度进行分块，而非简单的字符截断。
- **元数据丰富**：自动提取角色、表情、动作、场景、时间、天气、BGM 等元数据。
- **智能对话合并**：自动处理不带语音的旁白和带语音的角色对话，保持上下文连贯。
- **两阶段优化**：包含基础分块和基于 Embedding 的语义优化清洗流程。

## 🛠️ 工作流

本项目采用高效的 **两步工作流**：

### 1. 基础分块 (Chunking)

解析原始剧本文件，根据场景变换和对话组生成基础 Chunks。

```bash
# 基本用法
python3 vn_chunker.py txt/ --fine-grained -o chunks.json 
```

### 2. 语义优化与清洗 (Optimization & Cleaning)

使用 Embedding 模型计算 Chunk 间的语义相似度，合并语义连贯的碎片，并自动清洗冗余数据（如空字段、冗余的动作描述）。

```bash
# 语义合并 + 自动数据清洗
python3 embedding_optimizer.py chunks.json -o optimized_final.json
```

*(注意：此步骤已集成原本独立的 `optimizer.py` 功能，无需额外运行其他脚本)*

推荐在有限上下文窗口内使用的高密度输出方式：

```bash
# 最推荐（信息密度最高）：箭头流时间线（无行号，仅状态序列）
python3 vn_chunker.py txt/ --fine-grained -o timeline_flow_chunks.json --format timeline_flow

# 次推荐：紧凑时间线（短标签，无括号，保留行号便于溯源）
python3 vn_chunker.py txt/ --fine-grained -o timeline_compact_chunks.json --format timeline_compact

# 兼顾可读性：标准时间线（大括号标签，带行号）
python3 vn_chunker.py txt/ --fine-grained -o timeline_chunks.json --format timeline

# 保持单份文本但包含位置行号的高密度格式
python3 vn_chunker.py txt/ --fine-grained -o dense_chunks.json --format dense

# 传统标准/压缩格式
python3 vn_chunker.py txt/ --fine-grained -o chunks.json               # standard
python3 vn_chunker.py txt/ --fine-grained -o optimized_chunks.json --format optimized
```

---

## 🚀 详细使用指南

### 环境准备

确保已安装 Python 3.8+ 及相关依赖。
对于第二步的语义优化，建议配置 [XInference](https://inference.readthedocs.io/en/latest/) 或兼容 OpenAI API 的 Embedding 服务（默认使用 `bge-m3` 模型）。

### Step 1: 运行分块器 (`vn_chunker.py`)

```bash
python3 vn_chunker.py [输入目录] [参数] --fine-grained
```

**常用参数：**
- `--target-size`: 目标 Chunk 大小 (默认 2000 tokens, 细粒度模式下自动设为 600)
- `--max-size`: 最大 Chunk 大小 (默认 3000 tokens, 细粒度模式下自动设为 800)
- `--overlap`: 上下文重叠窗口 (默认 200 tokens，现按 token 数计算并回溯足够的对话组)
- `--fine-grained`: 细粒度模式 (推荐！生成 600-800 token 的小碎片，为后续语义合并提供基础)

### Step 2: 运行优化器 (`embedding_optimizer.py`)

```bash
python3 embedding_optimizer.py [输入文件] -o [输出文件] [参数]
```

**常用参数：**
- `--api-url`: Embedding API 地址 (默认 `http://192.168.123.113:9997`)
- `--model-uid`: 模型及其 ID (默认 `bge-m3`)
- `--similarity-threshold`: 相似度阈值 (默认 0.84，适合合并细粒度碎片)
- `--min-merge-size`: 最小合并大小 (默认 150)
- `--max-merged-size`: 合并后最大大小 (默认 2000)
- `--no-clean`: 仅合并但不执行数据清洗 (不推荐)
- `--keep-voice-refs` / `--keep-emotions`: 清理时保留语音 / 情绪元数据（默认已保留）
- `--drop-voice-refs` / `--drop-emotions`: 如需精简输出可显式删除对应字段
- `--analyze`: 优化后生成语义连贯性报告（默认不生成，需显式开启）

默认行为：嵌入文本会携带全部可用的结构化元数据（场景/时间/天气/场景类型/BGM/角色、对话级与场景级的表情、动作、state_changes、voice_refs），并在字段冲突时使用 `value1 | value2` 串联保留全部线索；若对话缺少动作描述，会自动从 state_changes 补回最后一次动作描述。
时间线模式下，元数据同样保留在 `ctx` 中（角色、表情、动作、场景、时间、天气、BGM、voice_refs、state_changes），并在 `timeline` 中用箭头序列呈现情感/动作演变；`timeline_flow` 去掉行号，用 `A -> B` 纯状态序列进一步提升信息密度。

### 辅助工具

- **Dify 格式转换**: 将最终 JSON 转换为 Dify 知识库支持的 CSV 格式。
  ```bash
  python3 convert_to_dify_csv.py optimized_final.json -o dify_import.csv
  ```

---

## 📂 项目结构

```
.
├── vn_chunker.py              # [核心] 剧本解析与基础分块器
├── embedding_optimizer.py     # [核心] 基于语义的合并与数据清洗器
├── convert_to_dify_csv.py     # [工具] Dify 格式转换工具
├── validate_chunks.py         # [工具] Chunk 质量验证工具
├── cleanup_old_files.sh       # [工具] 清理临时文件脚本
├── motion_mappings.json       # 动作 ID 到描述的映射表
├── txt/                       # 原始剧本存放目录
└── docs/                      # 文档与归档
    └── archived_docs/         # 旧版本文档归档
```

## 📊 数据结构示例

处理后的 JSON Chunk 结构示例：

```json
{
  "id": "story_main_104_scene_001_merged",
  "content": "...剧本正文内容...",
  "meta": {
    "scene": "story_main_104_scene_001",
    "chars": ["梢", "花帆"],
    "loc": "学校_中庭",
    "tokens": 450,
    "dlgs": [
      {
        "char": "梢",
        "text": "早上好，花帆同学。",
        "e_bef": "happy"
      },
      ...
    ]
  }
}
```

高密度结构 (`--format dense`) 示例：使用短键名和单份文本表示，减少冗余字段并提升窗口信息密度。

```json
{
  "id": "story_main_104_scene_001",
  "scene": "story_main_104_scene_001",
  "src": "story_main_104.txt",
  "ctx": {
    "loc": "学校_中庭",
    "time": "morning",
    "bgm": "bgm_023",
    "chars": ["梢", "花帆"],
    "voices": ["vo_adv_..."],
    "state": [["梢", "emotion", "happy"]],
    "emo": {"梢": "happy"}
  },
  "stats": {"tok": 450, "dlg": 8},
  "script": [
    {"c": "梢", "t": "早上好，花帆同学。", "e": "happy"},
    {"c": "花帆", "t": "早上好，梢！"},
    {"c": "narrator", "t": "晨光洒在学院中庭。"}
  ],
  "text": "[story_main_104_scene_001] loc:学校_中庭 | time:morning | bgm:bgm_023\n梢: 早上好，花帆同学。 [emo:happy]\n花帆: 早上好，梢！\n晨光洒在学院中庭。"
}
```

关键帧时间线结构 (`--format timeline`) 示例：行内仅标注本行发生的关键帧，末尾附角色时间线，减少重复帧，提升信息密度并兼顾可读性。

```json
{
  "id": "story_main_104_scene_001",
  "scene": "story_main_104_scene_001",
  "src": "story_main_104.txt",
  "ctx": { "loc": "学校_中庭", "time": "morning", "chars": ["梢", "花帆"] },
  "stats": { "tok": 450, "dlg": 8 },
  "script": [
    { "c": "梢", "t": "早上好，花帆同学。", "kf": ["emo:happy"] },
    { "c": "花帆", "t": "早上好，梢！" },
    { "c": "narrator", "t": "晨光洒在学院中庭。" }
  ],
  "timeline": {
    "梢": { "emo": [["happy", 1]] }
  },
  "text": "[story_main_104_scene_001] loc:学校_中庭 | time:morning\n梢: 早上好，花帆同学。 {emo:happy}\n花帆: 早上好，梢！\n晨光洒在学院中庭。\n\n梢 timeline: emo happy@1"
}
```

极简标签 (`--format timeline_compact`) 示例：去掉大括号，使用短前缀 `^emo:happy;act:wave` 以降低括号/引号占用。

箭头序列 (`--format timeline_flow`) 示例：时间线只保留状态演变，用 `->` 串联，无行号，便于模型自行推断节奏。

## 📝 开发日志

- **v2.4 (now)**:
  - 新增关键帧时间线三档输出：`timeline`（行号+大括号）、`timeline_compact`（短标签无括号）、`timeline_flow`（箭头序列无行号），默认推荐使用 flow 以提升信息密度。
  - 时间线格式下元数据无损保留在 `ctx`（角色、表情、动作、场景、时间、天气、BGM、voice_refs、state_changes），并用 `timeline` 表达情感/动作演变。
  - 优化器/CSV 转换工具兼容新格式，行内/尾部时间线均可用于嵌入。
- **v2.3**:
  - chunker 解析支持 `#` 注释式指令，新增场景级 actions/state_changes，统一规范化地点/时间/表情/动作等字段。
  - embedding_optimizer 现在默认使用全量元数据（含 voice_refs、state_changes、场景级表情/动作），冲突字段用 `A | B` 串联保留信息，并在清洗时从 state_changes 补回缺失的动作描述。
  - 语义报告改为显式开启 (`--analyze`)，避免默认长时间运行。
- **v2.2**: 
  - 分块重叠按 token 数和对话组自动回溯，减少上下文断层。
  - 合并后重新计数 token / 对话数，保证嵌入长度准确。
  - 语义连贯性报告改为逐文件、使用与优化一致的 meta+content 嵌入，并输出最低相似度对提示复查。
  - 数据清洗可选择保留 voice_refs / emotions，便于多模态或情绪维度的后处理。
- **v2.1**: 强化数据解析与合并质量：支持日文角色/动作匹配与“キャラモーション即時再生”，修正无语音对话的情感误贴问题，合并 Chunk 时同步角色/场景元数据并清洗优化格式残留的空字段。
- **v2.0**: 优化工作流。将数据清洗 (`optimizer.py`) 逻辑集成至语义优化器中，修复了合并 Chunk 时的对话丢失 Bug。
