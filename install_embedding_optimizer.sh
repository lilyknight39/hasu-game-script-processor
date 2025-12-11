#!/bin/bash
# Embedding优化工具环境安装脚本

set -e

echo "========================================="
echo "Embedding优化工具环境配置"
echo "========================================="

# 检测conda是否可用
if command -v conda &> /dev/null; then
    echo "✓ 检测到conda环境管理器"
    USE_CONDA=true
else
    echo "⚠ 未检测到conda，将使用venv"
    USE_CONDA=false
fi

# 环境名称
ENV_NAME="vn_chunker_env"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ "$USE_CONDA" = true ]; then
    echo ""
    echo "使用conda创建环境..."
    
    # 检查环境是否已存在
    if conda env list | grep -q "^${ENV_NAME} "; then
        echo "环境 ${ENV_NAME} 已存在"
        read -p "是否重新创建？(y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            conda env remove -n ${ENV_NAME}
            conda create -n ${ENV_NAME} python=3.9 -y
        fi
    else
        conda create -n ${ENV_NAME} python=3.9 -y
    fi
    
    echo ""
    echo "激活conda环境..."
    source "$(conda info --base)/etc/profile.d/conda.sh"
    conda activate ${ENV_NAME}
    
else
    echo ""
    echo "使用venv创建环境..."
    
    # 创建venv环境
    if [ -d "${SCRIPT_DIR}/${ENV_NAME}" ]; then
        echo "环境目录已存在"
        read -p "是否重新创建？(y/N): " -n 1 -r
        echo
        if [[ $REPLY =~ ^[Yy]$ ]]; then
            rm -rf "${SCRIPT_DIR}/${ENV_NAME}"
            python3 -m venv "${SCRIPT_DIR}/${ENV_NAME}"
        fi
    else
        python3 -m venv "${SCRIPT_DIR}/${ENV_NAME}"
    fi
    
    echo ""
    echo "激活venv环境..."
    source "${SCRIPT_DIR}/${ENV_NAME}/bin/activate"
fi

echo ""
echo "========================================="
echo "安装Python依赖包"
echo "========================================="

# 升级pip
pip install --upgrade pip

# 安装依赖
echo ""
echo "安装核心依赖..."
pip install numpy requests tqdm

echo ""
echo "========================================="
echo "安装完成！"
echo "========================================="

if [ "$USE_CONDA" = true ]; then
    echo ""
    echo "使用方法："
    echo "1. 激活环境："
    echo "   conda activate ${ENV_NAME}"
    echo ""
    echo "2. 运行优化工具："
    echo "   python embedding_optimizer.py test_chunks_v2.json -o optimized_chunks.json"
    echo ""
    echo "3. 仅分析语义连贯性："
    echo "   python embedding_optimizer.py test_chunks_v2.json -o analysis --analyze-only"
    echo ""
    echo "4. 退出环境："
    echo "   conda deactivate"
else
    echo ""
    echo "使用方法："
    echo "1. 激活环境："
    echo "   source ${SCRIPT_DIR}/${ENV_NAME}/bin/activate"
    echo ""
    echo "2. 运行优化工具："
    echo "   python embedding_optimizer.py test_chunks_v2.json -o optimized_chunks.json"
    echo ""
    echo "3. 仅分析语义连贯性："
    echo "   python embedding_optimizer.py test_chunks_v2.json -o analysis --analyze-only"
    echo ""
    echo "4. 退出环境："
    echo "   deactivate"
fi

echo ""
echo "参数说明："
echo "  --api-url            XInference API地址 (默认: http://192.168.123.113:9997)"
echo "  --model-uid          模型UID (默认: bge-m3)"
echo "  --similarity-threshold 相似度阈值 (默认: 0.85)"
echo "  --min-merge-size     最小合并大小 (默认: 100 tokens)"
echo "  --max-merged-size    合并后最大大小 (默认: 2000 tokens)"
echo ""
