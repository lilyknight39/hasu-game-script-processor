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

## 📝 开发日志

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
