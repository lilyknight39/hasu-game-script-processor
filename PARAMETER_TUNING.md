# 参数调整说明

## 背景

由于`vn_chunker.py`新增了`--fine-grained`模式，产生的chunks特征发生变化：
- 平均大小更小（481 → 403 tokens）
- 更多细粒度的语义单元
- 更清晰但更碎片化的边界

因此`embedding_optimizer.py`的默认参数需要相应调整以达到最佳效果。

---

## 参数调整对照表

### Embedding Optimizer参数变化

| 参数 | 旧默认值 | 新默认值 | 原因 |
|------|---------|---------|------|
| `similarity_threshold` | 0.85 | **0.82** | chunks更细，需要更宽松的阈值 |
| `max_merged_size` | 2000 | **1800** | 避免合并出超大chunks |
| `min_merge_size` | 100 | 100 | 保持不变 |

### VN Chunker排序优化

**新增功能：** 按故事顺序处理文件

```python
# 自动排序：story_main_102xxx -> 103xxx -> 104xxx -> 105xxx
txt_files.sort(key=get_story_number)
```

**好处：**
- chunks顺序与故事剧情一致
- 便于调试和验证
- 更好的可读性

---

## 使用场景对比

### 场景1：细粒度模式（推荐）

```bash
# 步骤1: 细粒度分块
python vn_chunker.py txt/ -o raw.json --fine-grained

# 步骤2: Embedding优化（使用新默认参数）
python embedding_optimizer.py raw.json -o final.json
# 默认使用 similarity_threshold=0.82, max_merged_size=1800
```

**适用：** 追求最优检索效果

---

### 场景2：默认chunker模式

```bash
# 步骤1: 默认分块
python vn_chunker.py txt/ -o raw.json

# 步骤2: Embedding优化（建议手动调高参数）
python embedding_optimizer.py raw.json -o final.json \
  --similarity-threshold 0.88 \
  --max-merged-size 2200
```

**适用：** 不想产生太多小chunks

---

## 参数调整原理

### 1. similarity_threshold: 0.85 → 0.82

**原因：**
- 细粒度模式产生更多小chunks
- 这些chunks虽小但语义边界更清晰
- 略微降低阈值可以合并更多相关chunks
- 但仍保持较高标准（0.82仍是高相似度）

**效果预测：**
```
旧参数 (0.85): 合并率 ~15%
新参数 (0.82): 合并率 ~25-30%
```

### 2. max_merged_size: 2000 → 1800

**原因：**
- 细粒度模式的chunks平均403 tokens
- 合并时更容易达到上限
- 降低限制避免产生过大chunks
- 保持在理想区间（500-1800）

**效果预测：**
```
旧参数 (2000): 可能产生1500-2000的大chunks
新参数 (1800): 控制在1200-1800的适中区间
```

---

## 实际效果验证

### 测试命令

```bash
# 使用新参数（默认）
python embedding_optimizer.py test_finegrained.json -o optimized_new.json

# 对比旧参数
python embedding_optimizer.py test_finegrained.json -o optimized_old.json \
  --similarity-threshold 0.85 \
  --max-merged-size 2000

# 验证两者差异
python validate_chunks.py optimized_new.json
python validate_chunks.py optimized_old.json
```

### 预期差异

| 指标 | 新参数(0.82/1800) | 旧参数(0.85/2000) |
|------|------------------|------------------|
| 合并率 | ~30% | ~15% |
| 最终chunks数 | ~1,080 | ~1,310 |
| 平均大小 | ~680 tokens | ~550 tokens |
| 大chunks(>1500) | 5-8% | 10-12% |

---

## 微调建议

根据实际效果，可以进一步调整：

### 如果chunks还是太碎

```bash
# 更激进的合并
--similarity-threshold 0.78
--max-merged-size 2000
```

### 如果chunks太大

```bash
# 更保守的合并
--similarity-threshold 0.85
--max-merged-size 1500
```

### 如果想最大化检索精度

```bash
# 高标准合并
--similarity-threshold 0.88
--max-merged-size 1600
```

---

## 总结

**核心理念：** 参数要匹配上游chunker的输出特征

| Chunker模式 | 推荐Embedding参数 |
|------------|-----------------|
| `--fine-grained` | `threshold=0.82, max=1800` (新默认) |
| 默认模式 | `threshold=0.85-0.88, max=2000-2200` |

**建议先用默认参数测试，然后根据分析报告微调！**
