#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
将final_chunks.json转换为Dify可导入的CSV格式
关键特性：元数据显性化 - 将metadata拼接到content头部
"""

import json
import csv
from pathlib import Path

def convert_chunks_to_dify_csv(input_file='final_chunks.json', output_file='dify_import.csv'):
    """
    转换chunks为Dify CSV格式
    
    元数据显性化策略：
    1. 环境上下文（场景、时间、地点）
    2. 角色登场信息
    3. 关键metadata（BGM、天气等）
    4. 剧本正文（包含表情和动作标注）
    """
    print(f'加载 {input_file}...')
    
    try:
        with open(input_file, 'r', encoding='utf-8') as f:
            raw_data = json.load(f)
            # 兼容单个对象或列表
            chunks = raw_data if isinstance(raw_data, list) else [raw_data]
        
        print(f'处理 {len(chunks)} 个chunks...')
        
        with open(output_file, 'w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            # Dify标准列名
            writer.writerow(['text', 'keywords', 'scene_id'])
            
            for idx, chunk in enumerate(chunks, 1):
                # 提取核心数据
                chunk_id = chunk.get('chunk_id', f'chunk_{idx}')
                raw_content = chunk.get('content', '')
                meta = chunk.get('metadata', {})
                
                # ============ 构建环境上下文头部 ============
                header_lines = []
                header_lines.append(f"【シーンID】{chunk_id}")
                
                # 时间信息
                if meta.get('time_period'):
                    time_map = {
                        'morning': '朝', 'noon': '昼', 'afternoon': '午後',
                        'evening': '夕方', 'night': '夜', 'midnight': '深夜'
                    }
                    time_ja = time_map.get(meta['time_period'], meta['time_period'])
                    header_lines.append(f"【時間】{time_ja}")
                
                # 地点信息
                if meta.get('location'):
                    header_lines.append(f"【場所】{meta['location']}")
                
                # 天气信息
                if meta.get('weather'):
                    weather_map = {
                        'rain': '雨', 'snow': '雪', 'sunny': '晴れ',
                        'cloudy': '曇り', 'storm': '嵐', 'windy': '強風'
                    }
                    weather_ja = weather_map.get(meta['weather'], meta['weather'])
                    header_lines.append(f"【天気】{weather_ja}")
                
                # 登场角色
                if meta.get('characters'):
                    chars_str = '、'.join(meta['characters'])
                    header_lines.append(f"【登場キャラ】{chars_str}")
                
                # BGM信息（可选，增强氛围感知）
                if meta.get('bgm'):
                    header_lines.append(f"【BGM】{meta['bgm']}")
                
                # 场景类型（可选）
                if meta.get('scene_type'):
                    scene_type_map = {
                        'indoor': '屋内', 'outdoor': '屋外',
                        'classroom': '教室', 'stage': 'ステージ'
                    }
                    scene_type_ja = scene_type_map.get(meta['scene_type'], meta['scene_type'])
                    header_lines.append(f"【シーン種類】{scene_type_ja}")
                
                # 对话数量统计
                if meta.get('dialogue_count'):
                    header_lines.append(f"【台詞数】{meta['dialogue_count']}")
                
                # ============ 拼接最终文本 ============
                header_text = "\n".join(header_lines)
                # 使用markdown标准分隔符,对embedding更友好
                final_text = f"{header_text}\n\n---\n\n{raw_content}"
                
                # ============ 构建关键词 ============
                keywords = []
                
                # 场景ID（最重要）
                keywords.append(chunk_id)
                
                # 源文件名
                if meta.get('source_file'):
                    source = meta['source_file'].replace('.txt', '')
                    keywords.append(source)
                
                # 角色名
                if meta.get('characters'):
                    keywords.extend(meta['characters'])
                
                # 地点
                if meta.get('location'):
                    keywords.append(meta['location'])
                
                # 时间段
                if meta.get('time_period'):
                    keywords.append(meta['time_period'])
                
                # 场景编号（从scene_id提取）
                scene_id = meta.get('scene_id', '')
                if scene_id:
                    keywords.append(scene_id)
                
                # 去重并转为字符串
                keywords_str = ','.join([str(k) for k in dict.fromkeys(keywords) if k])
                
                # 写入CSV
                writer.writerow([final_text, keywords_str, chunk_id])
                
                if idx % 100 == 0:
                    print(f'  已处理 {idx}/{len(chunks)} chunks...')
        
        # ============ 输出统计 ============
        output_size = Path(output_file).stat().st_size
        print(f'\n✓ 转换成功！')
        print(f'  输出文件: {output_file}')
        print(f'  文件大小: {output_size / 1024:.1f} KB')
        print(f'  总chunks数: {len(chunks)}')
        print(f'\n提示：')
        print(f'  1. CSV包含完整的环境上下文（时间、地点、角色）')
        print(f'  2. content已包含表情和动作标注，LLM可完美理解角色情绪')
        print(f'  3. keywords包含场景ID、角色名、地点等，便于检索')
        print(f'  4. 可直接导入Dify Knowledge Base')
        
    except FileNotFoundError:
        print(f'错误: 找不到文件 {input_file}')
        print(f'请确保已运行: python3 embedding_optimizer.py chunks_standard.json -o final_chunks.json')
    except Exception as e:
        print(f'转换错误: {e}')
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='转换chunks为Dify CSV格式')
    parser.add_argument('input', nargs='?', default='final_chunks.json', 
                       help='输入JSON文件 (默认: final_chunks.json)')
    parser.add_argument('-o', '--output', default='dify_import.csv',
                       help='输出CSV文件 (默认: dify_import.csv)')
    
    args = parser.parse_args()
    
    convert_chunks_to_dify_csv(args.input, args.output)
