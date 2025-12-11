# Visual Novel剧本智能分块工具使用指南

## 概述

本工具为Visual Novel/Galgame剧本文档提供智能分块预处理，专为Dify知识库优化。通过语义感知的分块策略，保持剧本的场景完整性、对话连贯性和叙事性。

## 快速开始

### 基本用法

```bash
# 处理单个目录下的所有txt文件
python3 vn_chunker.py txt/ -o output_chunks.json

# 自定义参数
python3 vn_chunker.py txt/ \
  --output optimized_chunks.json \
  --target-size 2000 \
  --max-size 3000 \
  --overlap 200
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

生成的JSON文件格式（Dify兼容）：

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

## Dify集成

### 方法1：直接导入JSON

1. 在Dify知识库中选择"上传文件"
2. 上传生成的JSON文件
3. 配置参数：
   - 分块策略：自定义（不再分块）
   - 检索模式：语义检索
   - Embedding模型：推荐中日文模型

### 方法2：转换为文本文件

如需要每个chunk作为单独文件：

```python
import json

with open('output_chunks.json', 'r', encoding='utf-8') as f:
    chunks = json.load(f)

for chunk in chunks:
    filename = f"chunks/{chunk['chunk_id']}.txt"
    with open(filename, 'w', encoding='utf-8') as f:
        # 写入内容
        f.write(chunk['content'])
        f.write('\n\n---METADATA---\n')
        # 写入元数据
        f.write(f"Characters: {', '.join(chunk['metadata']['characters'])}\n")
        f.write(f"Location: {chunk['metadata']['location']}\n")
        f.write(f"Dialogues: {chunk['metadata']['dialogue_count']}\n")
```

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
python embedding_optimizer.py test_chunks_v2.json -o optimized_chunks.json
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

## 后续优化

可选的改进方向：

1. **小Chunk过滤/合并**：
   ```python
   # 合并相邻的小chunks
   MIN_MERGE_SIZE = 100
   # 实现逻辑...
   ```

2. **基于embedding的场景边界检测**：
   使用向量相似度辅助判断语义边界

3. **多线程处理**：
   并行处理大量文件提升速度

## 技术支持

如遇到问题：
1. 检查txt文件编码是否为UTF-8
2. 确认文件格式与示例一致
3. 查看validation工具的详细报告

---

**最后更新**: 2025-12-11

---

## 项目文件结构

### 核心文件

```
game-script-processor/
├── 核心工具
│   ├── vn_chunker.py              # 智能分块工具
│   ├── embedding_optimizer.py     # 语义优化器
│   ├── optimize_for_dify.py       # Dify优化
│   └── convert_to_dify_csv.py     # CSV转换
│
├── 输出文件
│   ├── final_chunks.json.zip      # 最终chunks（版本控制）
│   ├── dify_import.csv            # Dify导入文件
│   └── chunks.json                # 当前版本（不追踪）
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

### 版本控制策略

`.gitignore` 已配置为：
- ✅ **追踪**: Python脚本、配置文件、文档、压缩包
- ❌ **忽略**: 测试文件、大JSON文件、Python缓存、虚拟环境

大文件建议：
- 使用 `final_chunks.json.zip` (2MB) 而非 `final_chunks.json` (18MB)
- CSV文件可选择性追踪（根据团队需求）

---

## 完整Dify导入工作流

```bash
# 步骤1: 生成标准格式chunks (完整metadata)
python3 vn_chunker.py txt/ -o chunks_standard.json
# 输出: 1636 chunks, 18.4 MB

# 步骤2: Embedding语义优化 (合并相似chunks)
python3 embedding_optimizer.py chunks_standard.json -o final_chunks.json
# 输出: ~1626 chunks, 语义合并优化

# 步骤3: 转换为Dify CSV (元数据显性化)
python3 convert_to_dify_csv.py final_chunks.json -o dify_import.csv
# 输出: 4.4 MB CSV, 可直接导入Dify Knowledge Base
```

### CSV格式说明
- **text**: 包含环境上下文(时间、地点、角色) + 剧本内容(含表情/动作标注)
- **keywords**: 场景ID、角色名、地点等,用于检索
- **scene_id**: chunk唯一标识符

### 优化效果
- 原始数据: 18.4 MB → 最终CSV: 4.4 MB (减少76%)
- 元数据显性化: LLM可完美理解场景环境和角色情绪
- 支持精准检索: 基于keywords定位相关场景