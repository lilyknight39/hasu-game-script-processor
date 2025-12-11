#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
优化Embedding输出格式
移除null字段,减少文件大小
"""

import json
import sys
from pathlib import Path

def optimize_for_embedding(input_file: str, output_file: str):
    """
    优化chunks格式用于embedding:
    1. 移除dialogues中的null/空字段
    2. 移除冗余的metadata字段
    3. 保留embedding必需的信息
    """
    print(f'加载 {input_file}...')
    with open(input_file, 'r', encoding='utf-8') as f:
        chunks = json.load(f)
    
    print(f'处理 {len(chunks)} 个chunks...')
    optimized_chunks = []
    
    for chunk in chunks:
        # 优化dialogues - 只保留非空字段
        if 'metadata' in chunk and 'dialogues' in chunk['metadata']:
            cleaned_dialogues = []
            for dlg in chunk['metadata']['dialogues']:
                # 移除null和空字符串字段
                cleaned_dlg = {k: v for k, v in dlg.items() if v not in (None, '', [])}
                cleaned_dialogues.append(cleaned_dlg)
            chunk['metadata']['dialogues'] = cleaned_dialogues
        
        # 移除冗余字段(可选)
        if 'metadata' in chunk:
            # 移除voice_refs(已在dialogues中)
            chunk['metadata'].pop('voice_refs', None)
            # 移除emotions(已在dialogues中)  
            chunk['metadata'].pop('emotions', None)
            # 移除parent_chunk_id和overlap_prev
        chunk.pop('parent_chunk_id', None)
        chunk.pop('overlap_prev', None)
        
        optimized_chunks.append(chunk)
    
    print(f'保存到 {output_file}...')
    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump(optimized_chunks, f, ensure_ascii=False, indent=2)
    
    # 统计
    original_size = Path(input_file).stat().st_size
    optimized_size = Path(output_file).stat().st_size
    reduction = (1 - optimized_size / original_size) * 100
    
    print(f'\n优化完成:')
    print(f'  原始大小: {original_size / 1024:.1f} KB')
    print(f'  优化后: {optimized_size / 1024:.1f} KB')
    print(f'  减少: {reduction:.1f}%')

if __name__ == '__main__':
    if len(sys.argv) < 3:
        print('用法: python3 optimize_for_dify.py <input.json> <output.json>')
        sys.exit(1)
    
    optimize_for_embedding(sys.argv[1], sys.argv[2])
