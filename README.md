# 链接！ 喜欢！ 爱直播！ 剧本智能分块工具使用指南

## 概述

本工具为 链接！ 喜欢！ 爱直播！ 剧本文档提供智能分块预处理，专为 LangChain 知识库优化。通过语义感知的分块策略，保持剧本的场景完整性、对话连贯性和叙事性。

## 快速开始

### 基本用法

# 1. 智能分块

```bash
# 处理单个目录下的所有txt文件
python3 vn_chunker.py txt/ -o chunks.json

# 自定义参数
python3 vn_chunker.py txt/ \
  --output chunks.json \
  --target-size 2000 \
  --max-size 3000 \
  --overlap 200
```

# 2.（可选） 基于语义的智能合并

```bash
python embedding_optimizer.py chunks.json -o optimized_chunks.json
```

# 3.（可选） 删除冗余数据

```bash
python3 optimizer.py optimized_chunks.json optimized_optimized_chunks.json
```

### 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `input_dir` | 必需 | 输入目录（包含txt剧本文件） |
| `-o, --output` | `chunks_output.json` | 输出JSON文件路径 |
| `--target-size` | `2000` | 目标chunk大小（tokens） |
| `--min-size` | `400` | 最小chunk大小（tokens） |
| `--max-size` | `3000` | 最大chunk大小（tokens） |
| `--overlap` | `200` | 重叠token数 |

## 验证工具

使用验证工具分析生成的chunks质量：

```bash
python3 validate_chunks.py output_chunks.json
```

输出包括：
- Chunk大小分布统计
- 元数据覆盖分析
- 对话分布分析
- 场景完整性检查
- 随机chunk内容抽样

## 处理结果

### 当前测试结果（346个文件，5.8MB）

| 指标 | 结果 |
|------|------|
| 总chunks数 | 1,627 |
| 总tokens数 | 783,086 |
| 平均chunk大小 | 481 tokens |
| 对话覆盖率 | 81.9% |
| 元数据覆盖率 | 78.2%（角色）, 71.8%（场景） |
| 场景完整保留率 | 98.8%（339/343文件） |

### 对比原配置

| 项目 | 原配置 | 优化后 | 改进 |
|------|--------|--------|------|
| 分段数 | 129,178 | 1,627 | **-98.7%** ✓ |
| 平均大小 | ~360 tokens | ~481 tokens | +34% |
| 场景完整性 | 低 | 高（98.8%） | ✓ |

## 输出格式

生成的JSON文件格式：

```json
{
  "chunk_id": "story_main_10250101_scene_004",
  "content": "慈: あーもう……最悪\n藤島慈，15歳。少女はこの世の終わりのように...",
  "metadata": {
    "chunk_id": "story_main_10250101_scene_004",
    "scene_id": "scene_04",
    "source_file": "story_main_10250101.txt",
    "characters": ["慈"],
    "location": "学校_教室_昼",
    "bgm": "bgm_adv_morning_0001",
    "emotions": {"慈": "NORMAL_NEMUI"},
    "voice_refs": ["vo_adv_10250101_0008_m1023_01@megumi"],
    "chunk_type": "scene",
    "token_count": 156,
    "dialogue_count": 15
  },
  "parent_chunk_id": null,
  "overlap_prev": ""
}
```

## LangChain集成

生成的JSON文件可直接用于LangChain知识库，格式完全兼容。每个chunk包含：
- `content`: 剧本内容
- `metadata`: 丰富的元数据（角色、场景、BGM等）
- `chunk_id`: 唯一标识符

推荐配置：
- **分块策略**: 已预分块，无需再次分割
- **检索模式**: 语义检索（Semantic Search）
- **Embedding模型**: 推荐中日文模型（如BGE-M3）

### Dify导入

如需导入Dify，请使用CSV格式：
```bash
python3 convert_to_dify_csv.py final_chunks.json -o dify_import.csv
```
详见完整工作流章节。

## 核心功能

### 1. 场景边界检测

自动识别以下场景标记：
- `#场面転換#` / `#場面転換#`
- `[暗転_イン ... 完了待ち]`
- 背景切换命令

### 2. 对话提取

支持多种对话格式：
- `[ノベルテキスト追加 内容 vo_xxx]` - 带语音的对话
- `[ノベルテキスト追加 内容]` - 纯叙述文本
- `[メッセージ表示 角色 vo_xxx 内容]` - 角色消息

### 3. 元数据提取

每个chunk包含丰富元数据：
- **角色列表**：场景中出现的所有角色
- **场景位置**：背景场景ID
- **BGM信息**：背景音乐
- **角色表情**：角色情绪状态
- **语音引用**：关联的语音文件ID

### 4. 智能分块策略

- **场景优先**：以完整场景为主要分块单元
- **动态调整**：场景过长自动按对话组分割
- **重叠策略**：保留200 tokens重叠确保上下文连贯
- **大小控制**：目标2000 tokens，范围400-3000

## 常见问题

### Q: 为什么有些chunks很小（<100 tokens）？

A: 这些通常是纯视觉场景或场景转换，不包含对话内容。可以通过后处理合并相邻的小chunks，或在Dify中使用检索后过滤。

### Q: 如何处理超大chunks（>3000 tokens）？

A: 脚本会自动按对话组分割超大场景。如果仍超限，可以降低`--max-size`参数值。

### Q: 对话计数准确吗？

A: 脚本统计所有`[ノベルテキスト追加]`和`[メッセージ表示]`标记的内容，覆盖率达81.9%。

### Q: 能处理其他格式的剧本吗？

A: 当前版本专为清理后的txt格式设计。如需支持其他格式，需要修改正则表达式pattern。

## 性能建议

- **大批量处理**：346个文件约需8秒处理
- **内存占用**：约100MB（处理5.8MB剧本）
- **建议配置**：Python 3.7+，8GB RAM

## Embedding优化（进阶）

### 基于语义的智能合并

使用本地部署的BGE-M3模型进一步优化chunks：

```bash
# 1. 安装环境（自动检测conda/venv）
bash install_embedding_optimizer.sh

# 2. 激活环境
conda activate vn_chunker_env  # 或 source vn_chunker_env/bin/activate

# 3. 运行优化
python embedding_optimizer.py chunks.json -o optimized_chunks.json

```

**优化效果：**
- 小chunks(<100 tokens)减少 50%+
- 通过语义相似度智能合并
- 保留所有元数据（包括voice_refs）
- 提升检索精度

**详细文档：** 参见 [EMBEDDING_OPTIMIZER_GUIDE.md](EMBEDDING_OPTIMIZER_GUIDE.md)

### 配置要求

- 本地XInference服务运行中
- BGE-M3模型已加载
- API地址：http://192.168.123.113:9997（可配置）

---

**最后更新**: 2025-12-11

---

## 项目文件结构

### 核心文件

```
hasu-game-script-processor/
├── 核心工具
│   ├── vn_chunker.py              # 智能分块工具
│   ├── embedding_optimizer.py     # 语义优化器
│   ├── optimizer.py               # 冗余数据优化
│   └── convert_to_dify_csv.py     # CSV转换
│
├── 输出文件
│   ├── final_chunks.json.zip      # 最终chunks（版本控制）
│   ├── dify_import.csv            # Dify导入文件
│   └── chunks.json                # 当前版本
│
├── 配置文件
│   ├── config.yaml                # 工具配置
│   └── motion_mappings.yaml       # 动作映射
│
├── 文档
│   ├── README.md                  # 本文档
│   ├── PROJECT_FILES.md           # 文件清单
│   ├── EMBEDDING_OPTIMIZER_GUIDE.md
│   ├── OPTIMIZED_WORKFLOW.md
│   └── recall_test_questions.md   # 召回测试问题集
│
└── docs/                          # 归档和分析文件
    ├── analysis/
    ├── archived_scripts/
    └── test_data/
```

详细的文件说明请参阅 [PROJECT_FILES.md](PROJECT_FILES.md)。

### 清理旧文件

如需清理测试生成的临时文件：

```bash
# 预览将要清理的文件（推荐）
bash cleanup_old_files.sh --dry-run

# 执行清理（会自动创建备份）
bash cleanup_old_files.sh

# 不创建备份直接清理
bash cleanup_old_files.sh --no-backup
```

清理脚本会：
- 删除空的测试文件
- 归档测试JSON到 `docs/test_data/archived/`
- 删除中间版本chunks
- 移动分析文件到 `docs/analysis/`
- 自动创建备份（除非使用 `--no-backup`）