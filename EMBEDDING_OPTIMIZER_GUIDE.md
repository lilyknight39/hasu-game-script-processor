# Embedding优化工具使用指南

## 概述

基于语义embedding的智能chunk边界优化工具，利用BGE-M3模型计算语义相似度，自动合并语义相近的小chunks，优化场景边界。

**核心优势：**
- ✅ 将34%的小chunks转化为正面优势
- ✅ 通过语义分析保证合并的chunks语义连贯
- ✅ 提升检索精度和用户体验
- ✅ 保留voice_refs等元数据的潜在价值

## 快速开始

### 1. 环境安装

```bash
# 自动检测并使用conda或venv
bash install_embedding_optimizer.sh
```

脚本会自动：
- 检测系统是否有conda
- 创建名为`vn_chunker_env`的虚拟环境
- 安装所需依赖（numpy, requests, tqdm）

### 2. 激活环境

**使用conda:**
```bash
conda activate vn_chunker_env
```

**使用venv:**
```bash
source vn_chunker_env/bin/activate
```

### 3. 运行优化

```bash
# 基础用法
python embedding_optimizer.py test_chunks_v2.json -o optimized_chunks.json

# 自定义参数
python embedding_optimizer.py test_chunks_v2.json -o optimized_chunks.json \
  --api-url http://192.168.123.113:9997 \
  --model-uid bge-m3 \
  --similarity-threshold 0.85 \
  --min-merge-size 100 \
  --max-merged-size 2000

# 仅分析语义连贯性（不进行优化）
python embedding_optimizer.py test_chunks_v2.json -o analysis --analyze-only
```

## 工作原理

### 优化策略

工具通过以下5个条件判断是否合并相邻chunks：

1. **小chunk条件**: 至少有一个chunk小于100 tokens
2. **语义相似**: 相似度 ≥ 0.85（可配置）
3. **大小限制**: 合并后总大小 ≤ 2000 tokens
4. **同源文件**: 来自同一个剧本文件
5. **场景相邻**: 场景编号相差 ≤ 2

**决策示例：**
```
Chunk A: 45 tokens  (小chunk ✓)
Chunk B: 380 tokens
相似度: 0.89       (超过阈值 ✓)
合并后: 425 tokens  (未超限 ✓)
同一文件 ✓
场景相邻 ✓
→ 执行合并
```

### 合并策略

合并时保留并整合所有有价值信息：

```json
{
  "content": "chunk1内容\n---\nchunk2内容",
  "metadata": {
    "chunk_id": "merged_scene_001",
    "token_count": 425,  // 累加
    "dialogue_count": 28,  // 累加
    "characters": ["慈", "綴理", "梢"],  // 去重合并
    "emotions": {"慈": "EGAO", "綴理": "TUUJO"},  // 合并
    "voice_refs": ["vo_001", "vo_002", "vo_003"],  // 保留全部
    "location": "学校_教室_昼",  // 优先使用后者
    "bgm": "bgm_morning_001"  // 优先使用后者
  },
  "merged_from": ["chunk_a_id", "chunk_b_id"]  // 记录来源
}
```

**voice_refs保留说明：**
- 不影响文本检索召回
- 保留完整语音引用历史
- 支持未来多模态扩展
- 可用于内容验证和溯源

## 语义连贯性分析

### 分析报告

运行后自动生成`_analysis.json`报告：

```json
{
  "total_chunks": 1627,
  "avg_similarity": 0.723,
  "min_similarity": 0.134,
  "max_similarity": 0.982,
  "std_similarity": 0.156,
  "high_similarity_pairs": 234,  // 高度相似对数
  "low_similarity_pairs": 89     // 低相似度对数
}
```

**指标解读：**
- `avg_similarity > 0.7`: 整体语义连贯性良好
- `high_similarity_pairs`: 可合并的候选对数
- `low_similarity_pairs`: 强语义边界数量（应保留）

### 优化前后对比

**预期优化效果：**

| 指标 | 优化前 | 优化后预期 |
|------|--------|------------|
| 总chunks数 | 1,627 | ~1,300-1,400 |
| 小chunks(<100) | 553 (34%) | <200 (15%) |
| 平均大小 | 481 tokens | ~650 tokens |
| 100-500区间 | 480 (29.5%) | ~600 (45%) |

**正面影响：**
1. **减少碎片化**: 小chunks减少50%+
2. **提升检索质量**: 更完整的语义单元
3. **保持边界完整**: 只合并高相似度chunks
4. **元数据增强**: 合并后元数据更全面

## 参数调优指南

### 相似度阈值 (--similarity-threshold)

```bash
# 保守策略（只合并极度相似的chunks）
--similarity-threshold 0.90

# 推荐策略（平衡合并率和质量）
--similarity-threshold 0.85  # 默认

# 激进策略（最大化合并，需谨慎）
--similarity-threshold 0.75
```

**建议：**
- 初次运行使用默认0.85
- 查看分析报告后调整
- `avg_similarity - 0.1` 是个好起点

### 最小合并大小 (--min-merge-size)

```bash
# 只处理极小chunks
--min-merge-size 50

# 标准配置
--min-merge-size 100  # 默认

# 更激进的合并
--min-merge-size 200
```

### 最大合并大小 (--max-merged-size)

```bash
# 保守（避免产生超大chunks）
--max-merged-size 1500

# 推荐
--max-merged-size 2000  # 默认

# 允许更大chunks
--max-merged-size 2500
```

## API配置

### 确认XInference服务

```bash
# 测试API是否可访问
curl http://192.168.123.113:9997/v1/models

# 应返回包含bge-m3的模型列表
```

### 自定义API地址

```bash
python embedding_optimizer.py input.json -o output.json \
  --api-url http://your-api-server:port \
  --model-uid your-model-name
```

## 使用场景

### 场景1: 全量优化

```bash
# 对所有chunks进行优化
python embedding_optimizer.py test_chunks_v2.json \
  -o optimized_full.json \
  --similarity-threshold 0.85
```

### 场景2: 仅优化小chunks

通过调整参数focus on小chunks：

```bash
python embedding_optimizer.py test_chunks_v2.json \
  -o optimized_small.json \
  --min-merge-size 150 \
  --max-merged-size 1500
```

### 场景3: 语义边界分析

先分析，再根据报告决定参数：

```bash
# 1. 仅分析
python embedding_optimizer.py test_chunks_v2.json \
  -o temp --analyze-only

# 2. 查看analysis报告
cat temp_analysis.json

# 3. 根据avg_similarity调整阈值后优化
python embedding_optimizer.py test_chunks_v2.json \
  -o final.json \
  --similarity-threshold <基于报告>
```

## 集成到工作流

### 完整处理流程

```bash
# 1. 原始分块
python vn_chunker.py txt/ -o raw_chunks.json

# 2. Embedding优化
python embedding_optimizer.py raw_chunks.json \
  -o optimized_chunks.json

# 3. 验证质量
python validate_chunks.py optimized_chunks.json

# 4. 导入Dify
# 使用optimized_chunks.json
```

## 性能说明

### 处理时间

| Chunks数量 | Embedding时间 | 优化时间 | 总时间 |
|-----------|--------------|---------|--------|
| 100 | ~10s | ~1s | ~11s |
| 500 | ~45s | ~3s | ~48s |
| 1,627 | ~2.5min | ~8s | ~3min |

**批处理优化:**
- 使用batch_size=10可加速3-5倍
- 本地部署XInference响应更快
- 建议在后台运行大批量任务

### 内存占用

- 1,627 chunks: ~150MB
- Embedding缓存: ~50MB
- 总计: ~200MB

## 故障排除

### 问题1: API连接失败

```
错误: 获取embedding失败: Connection refused
```

**解决方案:**
```bash
# 1. 检查XInference服务
curl http://192.168.123.113:9997/v1/models

# 2. 确认模型已加载
# 访问XInference WebUI查看bge-m3状态

# 3. 修改为可访问的API地址
--api-url http://localhost:9997
```

### 问题2: 依赖缺失

```
ModuleNotFoundError: No module named 'numpy'
```

**解决方案:**
```bash
# 确保激活了虚拟环境
conda activate vn_chunker_env
# 或
source vn_chunker_env/bin/activate

# 重新安装依赖
pip install numpy requests tqdm
```

### 问题3: 处理超时

```
Timeout error after 30s
```

**解决方案:**
```python
# 修改embedding_optimizer.py中的timeout参数
# 第71行和111行
timeout=60  # 增加到60秒
```

## 高级用法

### 自定义相似度计算

如需使用其他相似度度量，修改`cosine_similarity`方法：

```python
def euclidean_distance(self, vec1, vec2):
    """欧氏距离（需反转：1 - distance）"""
    return 1.0 / (1.0 + np.linalg.norm(vec1 - vec2))
```

### 导出合并记录

```python
# 在optimize_chunks中添加
merge_log = []
for merged in optimized_chunks:
    if 'merged_from' in merged:
        merge_log.append({
            'new_id': merged['chunk_id'],
            'source_ids': merged['merged_from'],
            'tokens': merged['metadata']['token_count']
        })

# 保存合并日志
with open('merge_log.json', 'w') as f:
    json.dump(merge_log, f, indent=2)
```

## 总结

✅ **将小chunks问题转化为优势:**
- 保留语义边界完整性
- 通过embedding智能合并
- 提升整体检索质量

✅ **voice_refs的价值:**
- 元数据不影响检索
- 保留多模态扩展能力
- 支持内容溯源验证

✅ **优化效果预期:**
- 小chunks减少50%+
- 平均大小提升35%
- 语义连贯性保持或提升

---

**下一步:** 运行安装脚本并测试优化效果！
