# 最终测试报告

## 测试配置

### 测试文件选择

随机从每个系列选取2个文件（种子=42）：

**102系列 (story_main_1025):**
- 待测试运行结果填充

**103系列 (story_main_103):**
- 待测试运行结果填充

**104系列 (story_main_104):**
- 待测试运行结果填充

**105系列 (story_main_105):**
- 待测试运行结果填充

**总计:** 8个文件

---

## 测试流程

### 阶段1: 智能分块（细粒度模式）

```bash
python vn_chunker.py test_sample/ -o test_sample_raw.json --fine-grained
```

**参数:**
- target_chunk_size: 1500
- min_chunk_size: 200
- max_chunk_size: 2000
- fine_grained_mode: True

### 阶段2: Embedding优化

```bash
python embedding_optimizer.py test_sample_raw.json -o test_sample_final.json
```

**参数:**
- similarity_threshold: 0.82
- min_merge_size: 100
- max_merged_size: 1800

### 阶段3: 质量验证

```bash
python validate_chunks.py test_sample_final.json
```

---

## 测试结果

### 阶段1结果 - 智能分块

待填充...

### 阶段2结果 - Embedding优化

待填充...

### 阶段3结果 - 最终验证

待填充...

---

## 对比分析

### 不同系列表现

| 系列 | Chunks数 | 平均大小 | 对话覆盖率 | 空chunks |
|------|---------|---------|-----------|---------|
| 102 | - | - | - | - |
| 103 | - | - | - | - |
| 104 | - | - | - | - |
| 105 | - | - | - | - |

### 优化效果

| 指标 | 智能分块 | Embedding优化 | 改善 |
|------|---------|--------------|------|
| 总chunks | - | - | - |
| 平均大小 | - | - | - |
| 小chunks比例 | - | - | - |
| 对话覆盖率 | - | - | - |

---

## 样本chunks展示

### 102系列示例

待填充...

### 103系列示例

待填充...

---

## 结论

待测试完成后填充...
