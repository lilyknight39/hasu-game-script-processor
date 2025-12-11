# 项目文件清单

本文档说明项目中各文件的用途和状态。

## 📁 核心生产文件

### Python脚本

| 文件 | 用途 | 状态 |
|------|------|------|
| `vn_chunker.py` | Visual Novel剧本智能分块工具 | ✅ 保留 |
| `embedding_optimizer.py` | 基于BGE-M3的语义优化器 | ✅ 保留 |
| `optimize_for_dify.py` | Dify格式优化脚本 | ✅ 保留 |
| `convert_to_dify_csv.py` | CSV转换工具 | ✅ 保留 |
| `validate_chunks.py` | Chunks质量验证工具 | ✅ 保留 |

### 最终输出文件

| 文件 | 大小 | 用途 | Git版本控制 |
|------|------|------|-------------|
| `final_chunks.json.zip` | 2.0MB | 最终chunks压缩包 | ✅ 是 |
| `final_chunks.json` | 18MB | 最终chunks完整版 | ❌ 否（.gitignore） |
| `dify_import.csv` | 4.2MB | Dify知识库导入文件 | ⚠️ 可选 |
| `chunks.json` | 12MB | 当前版本chunks | ❌ 否（.gitignore） |
| `raw_chunks.json` | 18MB | 原始未优化chunks | ❌ 否（.gitignore） |

### 配置文件

| 文件 | 用途 | 状态 |
|------|------|------|
| `config.yaml` | 工具配置文件 | ✅ 保留 |
| `motion_mappings.yaml` | 角色动作映射（YAML） | ✅ 保留 |
| `motion_mappings.json` | 角色动作映射（JSON） | ✅ 保留 |

### 文档

| 文件 | 用途 | 状态 |
|------|------|------|
| `README.md` | 项目主文档 | ✅ 保留并更新 |
| `EMBEDDING_OPTIMIZER_GUIDE.md` | Embedding优化器使用指南 | ✅ 保留 |
| `OPTIMIZED_WORKFLOW.md` | 优化工作流文档 | ✅ 保留 |
| `PARAMETER_TUNING.md` | 参数调优指南 | ✅ 保留 |
| `FINAL_TEST_REPORT.md` | 最终测试报告 | ✅ 保留 |
| `recall_test_questions.md` | Dify召回测试问题集 | ✅ 保留 |
| `PROJECT_FILES.md` | 本文件 | ✅ 保留 |

### 工具脚本

| 文件 | 用途 | 状态 |
|------|------|------|
| `install_embedding_optimizer.sh` | 环境安装脚本 | ✅ 保留 |
| `test_embedding.sh` | 测试脚本 | ✅ 保留 |
| `cleanup_old_files.sh` | 清理脚本（新创建） | ✅ 保留 |

---

## 🗑️ 已清理文件

### 测试JSON文件（已删除/归档）

以下文件已移至 `docs/test_data/archived/` 或删除：

```
test_chunks.json (5.3MB)
test_chunks_v2.json (5.3MB)
test_finegrained.json (4.4MB)
test_sorted.json (4.4MB)
test_optimized_v3.json (5.6MB)
test_sample_raw.json (195KB)
test_sample_enhanced.json (195KB)
test_sample_priority.json (195KB)
final_test_chunks.json (388KB)
test_chunk_sample.json (5.7KB)
test_chunk_with_dialogues.json (17KB)
test_standard.json (79KB)
test_standard_v2.json (78KB)
test_optimized.json (59KB)
test_optimized_v2.json (55KB)
```

### 空文件（已删除）

```
test_fix.json (2B)
test_fix_error.json (2B)
test_all_fixes.json (2B)
test_parser.json (2B)
test_structured.json (2B)
final_test_output.json (2B)
```

### 中间版本文件（已删除）

```
chunks_cleaned.json (18MB) - 被final_chunks.json替代
chunks_standard.json (18MB) - 被final_chunks.json替代
```

### 分析文件（已移至docs/analysis/）

```
chunk_structure_analysis.json (20KB)
metadata_inheritance_example.json (884B)
final_chunks_analysis.json (235B)
```

### 旧版本脚本（已移至docs/archived_scripts/）

```
old_script_converter.py (6.6KB)
```

---

## 📊 清理统计

| 项目 | 数量/大小 |
|------|----------|
| **删除的测试JSON** | 18个文件 |
| **删除的空文件** | 6个文件 |
| **删除的中间版本** | 2个文件 (36MB) |
| **归档的分析文件** | 3个文件 |
| **归档的旧脚本** | 1个文件 |
| **节省的磁盘空间** | ~55-60MB |

---

## 📂 目录结构

```
hasu-game-script-processor/
├── txt/                          # 源文件目录（346个txt文件）
├── docs/                         # 文档和归档目录
│   ├── analysis/                # 分析结果
│   ├── archived_scripts/        # 旧版本脚本
│   └── test_data/              # 测试数据归档
│       └── archived/           # 已归档的测试JSON
├── test_sample/                 # 测试样本（保留）
├── final_test/                  # 最终测试（保留）
│
├── vn_chunker.py               # 核心工具
├── embedding_optimizer.py      # 优化器
├── optimize_for_dify.py        # Dify优化
├── convert_to_dify_csv.py      # CSV转换
├── validate_chunks.py          # 验证工具
│
├── final_chunks.json.zip       # 最终输出（版本控制）
├── dify_import.csv             # Dify导入文件
│
├── config.yaml                 # 配置
├── motion_mappings.yaml        # 动作映射
│
└── README.md                   # 主文档
```

---

## 📝 版本控制策略

### Git追踪文件
- ✅ 所有Python脚本和Shell脚本
- ✅ 所有配置文件（.yaml, .json配置）
- ✅ 所有Markdown文档
- ✅ 压缩包（final_chunks.json.zip）
- ⚠️ CSV文件（可选，根据需求）

### Git忽略文件
- ❌ 测试JSON文件（test_*.json）
- ❌ 大的chunks文件（>10MB）
- ❌ Python缓存（__pycache__/）
- ❌ 虚拟环境（.venv/）
- ❌ 系统文件（.DS_Store等）

详见 `.gitignore` 文件。

---

**最后更新**: 2025-12-11
**清理执行**: cleanup_old_files.sh
