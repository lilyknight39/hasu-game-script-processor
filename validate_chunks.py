#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Chunk质量验证工具
================

用于验证生成的chunks质量，包括：
- 大小分布统计
- 场景完整性检查
- 对话连贯性验证
- 元数据完整性检查
"""

import json
import sys
from collections import defaultdict
from typing import List, Dict


def load_chunks(json_file: str) -> List[Dict]:
    """加载chunks JSON文件"""
    with open(json_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def analyze_chunk_sizes(chunks: List[Dict]):
    """分析chunk大小分布"""
    print("\n" + "=" * 60)
    print("Chunk大小分布分析")
    print("=" * 60)
    
    sizes = [c['metadata']['token_count'] for c in chunks]
    
    # 基本统计
    total = len(sizes)
    total_tokens = sum(sizes)
    avg = total_tokens / total if total > 0 else 0
    
    print(f"总chunks数: {total}")
    print(f"总tokens数: {total_tokens}")
    print(f"平均大小: {avg:.1f} tokens")
    print(f"最小大小: {min(sizes)} tokens")
    print(f"最大大小: {max(sizes)} tokens")
    
    # 尺寸区间分布
    bins = {
        '0-100': 0,
        '100-500': 0,
        '500-1000': 0,
        '1000-2000': 0,
        '2000-3000': 0,
        '3000+': 0
    }
    
    for size in sizes:
        if size < 100:
            bins['0-100'] += 1
        elif size < 500:
            bins['100-500'] += 1
        elif size < 1000:
            bins['500-1000'] += 1
        elif size < 2000:
            bins['1000-2000'] += 1
        elif size < 3000:
            bins['2000-3000'] += 1
        else:
            bins['3000+'] += 1
    
    print("\n大小区间分布:")
    for bin_name, count in bins.items():
        percentage = (count / total) * 100 if total > 0 else 0
        print(f"  {bin_name:12} tokens: {count:5} chunks ({percentage:5.1f}%)")
    
    # 问题chunks（太小或太大）
    too_small = [c for c in chunks if c['metadata']['token_count'] < 100]
    too_large = [c for c in chunks if c['metadata']['token_count'] > 3000]
    
    print(f"\n问题chunks:")
    print(f"  过小(<100 tokens): {len(too_small)}")
    print(f"  过大(>3000 tokens): {len(too_large)}")
    
    if too_small:
        print(f"\n  过小chunks示例（前5个）:")
        for c in too_small[:5]:
            print(f"    - {c['chunk_id']}: {c['metadata']['token_count']} tokens")
    
    if too_large:
        print(f"\n  过大chunks示例（前5个）:")
        for c in too_large[:5]:
            print(f"    - {c['chunk_id']}: {c['metadata']['token_count']} tokens")


def analyze_metadata_coverage(chunks: List[Dict]):
    """分析元数据覆盖情况"""
    print("\n" + "=" * 60)
    print("元数据覆盖分析")
    print("=" * 60)
    
    total = len(chunks)
    
    # 统计各字段覆盖率
    has_characters = sum(1 for c in chunks if c['metadata']['characters'])
    has_location = sum(1 for c in chunks if c['metadata']['location'])
    has_bgm = sum(1 for c in chunks if c['metadata']['bgm'])
    has_dialogues = sum(1 for c in chunks if c['metadata']['dialogue_count'] > 0)
    
    print(f"包含角色信息: {has_characters}/{total} ({has_characters/total*100:.1f}%)")
    print(f"包含场景位置: {has_location}/{total} ({has_location/total*100:.1f}%)")
    print(f"包含BGM信息: {has_bgm}/{total} ({has_bgm/total*100:.1f}%)")
    print(f"包含对话内容: {has_dialogues}/{total} ({has_dialogues/total*100:.1f}%)")
    
    # 统计角色出现频率
    character_freq = defaultdict(int)
    for c in chunks:
        for char in c['metadata']['characters']:
            character_freq[char] += 1
    
    print(f"\n角色出现频率Top 10:")
    sorted_chars = sorted(character_freq.items(), key=lambda x: x[1], reverse=True)[:10]
    for char, freq in sorted_chars:
        print(f"  {char:10}: {freq:5} chunks")


def analyze_dialogue_distribution(chunks: List[Dict]):
    """分析对话分布"""
    print("\n" + "=" * 60)
    print("对话分布分析")
    print("=" * 60)
    
    dialogue_counts = [c['metadata']['dialogue_count'] for c in chunks]
    
    total = len(dialogue_counts)
    total_dialogues = sum(dialogue_counts)
    avg_dialogues = total_dialogues / total if total > 0 else 0
    
    print(f"总对话数: {total_dialogues}")
    print(f"平均每chunk对话数: {avg_dialogues:.1f}")
    print(f"最多对话数: {max(dialogue_counts)}")
    
    # 对话数区间
    bins = {
        '0': 0,
        '1-5': 0,
        '6-10': 0,
        '11-20': 0,
        '20+': 0
    }
    
    for count in dialogue_counts:
        if count == 0:
            bins['0'] += 1
        elif count <= 5:
            bins['1-5'] += 1
        elif count <= 10:
            bins['6-10'] += 1
        elif count <= 20:
            bins['11-20'] += 1
        else:
            bins['20+'] += 1
    
    print("\n对话数区间分布:")
    for bin_name, count in bins.items():
        percentage = (count / total) * 100 if total > 0 else 0
        print(f"  {bin_name:6} 对话: {count:5} chunks ({percentage:5.1f}%)")


def sample_chunk_content(chunks: List[Dict], sample_count: int = 3):
    """抽样显示chunk内容"""
    print("\n" + "=" * 60)
    print(f"随机抽样chunk内容（{sample_count}个）")
    print("=" * 60)
    
    import random
    samples = random.sample(chunks, min(sample_count, len(chunks)))
    
    for i, chunk in enumerate(samples, 1):
        print(f"\n样本 {i}: {chunk['chunk_id']}")
        print(f"  Token数: {chunk['metadata']['token_count']}")
        print(f"  角色: {', '.join(chunk['metadata']['characters']) if chunk['metadata']['characters'] else '无'}")
        print(f"  场景: {chunk['metadata']['location'] or '未知'}")
        print(f"  对话数: {chunk['metadata']['dialogue_count']}")
        print(f"  内容预览:")
        content = chunk['content']
        preview = content[:200] + "..." if len(content) > 200 else content
        for line in preview.split('\n')[:5]:
            if line.strip():
                print(f"    {line}")


def check_scene_integrity(chunks: List[Dict]):
    """检查场景完整性"""
    print("\n" + "=" * 60)
    print("场景完整性检查")
    print("=" * 60)
    
    # 按源文件分组
    file_groups = defaultdict(list)
    for chunk in chunks:
        file_groups[chunk['metadata']['source_file']].append(chunk)
    
    print(f"总文件数: {len(file_groups)}")
    
    # 检查每个文件的场景连续性
    incomplete_scenes = 0
    for filename, file_chunks in file_groups.items():
        scene_ids = set(c['metadata']['scene_id'] for c in file_chunks)
        
        # 检查是否有sub-chunks（表示场景被分割）
        has_splits = any('_sub_' in c['chunk_id'] for c in file_chunks)
        
        if has_splits:
            incomplete_scenes += 1
    
    print(f"被分割的场景文件数: {incomplete_scenes}")
    print(f"完整保留场景的文件数: {len(file_groups) - incomplete_scenes}")


def main():
    if len(sys.argv) < 2:
        print("用法: python validate_chunks.py <chunks_json_file>")
        sys.exit(1)
    
    json_file = sys.argv[1]
    
    print(f"加载chunks文件: {json_file}")
    chunks = load_chunks(json_file)
    print(f"成功加载 {len(chunks)} 个chunks\n")
    
    # 运行各项分析
    analyze_chunk_sizes(chunks)
    analyze_metadata_coverage(chunks)
    analyze_dialogue_distribution(chunks)
    check_scene_integrity(chunks)
    sample_chunk_content(chunks)
    
    print("\n" + "=" * 60)
    print("验证完成")
    print("=" * 60)


if __name__ == '__main__':
    main()
