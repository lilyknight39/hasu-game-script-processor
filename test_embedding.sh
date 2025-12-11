# 测试Embedding优化器的快速命令
# =====================================

# 1. 安装环境
bash install_embedding_optimizer.sh

# 2. 激活环境（二选一）
# conda activate vn_chunker_env
# source vn_chunker_env/bin/activate

# 3. 测试API连接
curl http://192.168.123.113:9997/v1/models

# 4. 仅分析语义连贯性（无需等待优化）
python embedding_optimizer.py test_chunks_v2.json -o test_analysis --analyze-only

# 5. 优化少量chunks测试（取前100个）
# 首先创建测试数据
python -c "
import json
with open('test_chunks_v2.json', 'r', encoding='utf-8') as f:
    chunks = json.load(f)
# 取同一文件的相邻chunks
test_chunks = [c for c in chunks if 'story_main_10250101' in c['chunk_id']][:20]
with open('test_small.json', 'w', encoding='utf-8') as f:
    json.dump(test_chunks, f, ensure_ascii=False, indent=2)
print(f'Created test_small.json with {len(test_chunks)} chunks')
"

# 然后优化
python embedding_optimizer.py test_small.json -o test_optimized.json

# 6. 验证结果
python validate_chunks.py test_optimized.json

# 7. 对比优化前后
echo "优化前："
python -c "import json; data=json.load(open('test_small.json')); print(f'Chunks: {len(data)}')"
echo "优化后："
python -c "import json; data=json.load(open('test_optimized.json')); print(f'Chunks: {len(data)}')"
