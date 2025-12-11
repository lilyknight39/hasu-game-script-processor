#!/bin/bash

# cleanup_old_files.sh
# 自动清理Visual Novel剧本处理项目中的测试文件和中间版本

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 默认模式
DRY_RUN=false
CREATE_BACKUP=true
BACKUP_DIR="backup_$(date +%Y%m%d_%H%M%S)"

# 解析参数
while [[ $# -gt 0 ]]; do
    case $1 in
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --no-backup)
            CREATE_BACKUP=false
            shift
            ;;
        *)
            echo "未知参数: $1"
            echo "用法: $0 [--dry-run] [--no-backup]"
            exit 1
            ;;
    esac
done

echo -e "${GREEN}=== Visual Novel项目清理工具 ===${NC}"
echo ""

if [ "$DRY_RUN" = true ]; then
    echo -e "${YELLOW}[DRY RUN模式] 不会实际删除文件${NC}"
fi

if [ "$CREATE_BACKUP" = true ] && [ "$DRY_RUN" = false ]; then
    echo -e "${GREEN}将创建备份目录: $BACKUP_DIR${NC}"
fi

echo ""

# 创建目录结构
create_dirs() {
    if [ "$DRY_RUN" = false ]; then
        mkdir -p docs/analysis
        mkdir -p docs/archived_scripts
        mkdir -p docs/test_data/archived
        if [ "$CREATE_BACKUP" = true ]; then
            mkdir -p "$BACKUP_DIR"
        fi
        echo -e "${GREEN}✓ 创建了docs目录结构${NC}"
    else
        echo -e "${YELLOW}[DRY RUN] 将创建docs目录结构${NC}"
    fi
}

# 删除文件
delete_file() {
    local file=$1
    if [ -f "$file" ]; then
        if [ "$DRY_RUN" = false ]; then
            if [ "$CREATE_BACKUP" = true ]; then
                cp "$file" "$BACKUP_DIR/"
            fi
            rm "$file"
            echo -e "${RED}✗ 删除: $file${NC}"
        else
            echo -e "${YELLOW}[DRY RUN] 将删除: $file${NC}"
        fi
    fi
}

# 移动文件
move_file() {
    local src=$1
    local dest_dir=$2
    if [ -f "$src" ]; then
        if [ "$DRY_RUN" = false ]; then
            if [ "$CREATE_BACKUP" = true ]; then
                cp "$src" "$BACKUP_DIR/"
            fi
            mv "$src" "$dest_dir/"
            echo -e "${GREEN}→ 移动: $src → $dest_dir/${NC}"
        else
            echo -e "${YELLOW}[DRY RUN] 将移动: $src → $dest_dir/${NC}"
        fi
    fi
}

# 开始清理
echo -e "${GREEN}开始清理...${NC}"
echo ""

# 1. 创建目录
create_dirs

# 2. 删除空的测试文件（2字节）
echo -e "${YELLOW}=== 清理空测试文件 ===${NC}"
delete_file "test_fix.json"
delete_file "test_fix_error.json"
delete_file "test_all_fixes.json"
delete_file "test_parser.json"
delete_file "test_structured.json"
delete_file "final_test_output.json"
echo ""

# 3. 移动测试JSON到归档目录
echo -e "${YELLOW}=== 归档测试JSON文件 ===${NC}"
for file in test_*.json; do
    if [ -f "$file" ]; then
        move_file "$file" "docs/test_data/archived"
    fi
done
echo ""

# 4. 删除中间版本chunks
echo -e "${YELLOW}=== 删除中间版本chunks ===${NC}"
delete_file "chunks_cleaned.json"
delete_file "chunks_standard.json"
echo ""

# 5. 移动分析文件
echo -e "${YELLOW}=== 归档分析文件 ===${NC}"
move_file "chunk_structure_analysis.json" "docs/analysis"
move_file "metadata_inheritance_example.json" "docs/analysis"
move_file "final_chunks_analysis.json" "docs/analysis"
echo ""

# 6. 归档旧脚本
echo -e "${YELLOW}=== 归档旧版本脚本 ===${NC}"
move_file "old_script_converter.py" "docs/archived_scripts"
echo ""

# 7. 移动测试日志
echo -e "${YELLOW}=== 归档测试日志 ===${NC}"
if [ -f "test_sample_chunker.log" ]; then
    move_file "test_sample_chunker.log" "docs/test_data/archived"
fi
echo ""

# 统计信息
if [ "$DRY_RUN" = false ]; then
    echo -e "${GREEN}=== 清理完成！ ===${NC}"
    echo ""
    echo "清理后的目录结构:"
    echo "  docs/"
    echo "    ├── analysis/           (分析文件)"
    echo "    ├── archived_scripts/   (旧脚本)"
    echo "    └── test_data/"
    echo "        └── archived/       (测试JSON)"
    echo ""
    
    if [ "$CREATE_BACKUP" = true ]; then
        echo -e "${GREEN}备份已保存至: $BACKUP_DIR/${NC}"
        echo "如需恢复，请从备份目录复制文件"
    fi
    
    echo ""
    echo -e "${YELLOW}建议后续操作:${NC}"
    echo "  1. 检查docs/目录中的文件"
    echo "  2. 运行 'git status' 查看变更"
    echo "  3. 如一切正常，执行 'git add .' 和 'git commit'"
    echo "  4. 可选：删除备份目录 'rm -rf $BACKUP_DIR'"
else
    echo -e "${YELLOW}=== DRY RUN完成 ===${NC}"
    echo ""
    echo "以上是将要执行的操作。"
    echo "如需实际执行，请运行："
    echo "  bash cleanup_old_files.sh"
    echo ""
    echo "如不需要备份，可添加 --no-backup 参数："
    echo "  bash cleanup_old_files.sh --no-backup"
fi

echo ""
echo -e "${GREEN}完成！${NC}"
