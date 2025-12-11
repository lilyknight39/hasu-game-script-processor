#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
基于Embedding的场景边界优化工具
================================

使用BGE-M3模型计算语义相似度，优化chunk边界：
1. 合并语义相近的小chunks
2. 优化不合理的场景分割
3. 保留语义边界完整性
"""

import json
import requests
import numpy as np
from typing import List, Dict, Tuple
import logging
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class EmbeddingOptimizer:
    """基于Embedding的Chunk优化器"""
    
    def __init__(self, 
                 xinference_url: str = "http://192.168.123.113:9997",
                 model_uid: str = "bge-m3",
                 similarity_threshold: float = 0.82,  # 降低以适应细粒度模式
                 min_merge_size: int = 100,
                 max_merged_size: int = 1800):  # 降低以避免超大chunks
        """
        初始化优化器
        
        Args:
            xinference_url: XInference API地址
            model_uid: 模型UID
            similarity_threshold: 相似度阈值（超过此值考虑合并）
                                默认0.82适配细粒度模式（更多小chunks）
                                如使用默认chunker模式，建议提高到0.85-0.88
            min_merge_size: 最小合并大小
            max_merged_size: 合并后的最大大小限制
                           默认1800适配细粒度模式
                           如使用默认chunker模式，可提高到2000-2500
        """
        self.xinference_url = xinference_url
        self.model_uid = model_uid
        self.similarity_threshold = similarity_threshold
        self.min_merge_size = min_merge_size
        self.max_merged_size = max_merged_size
        
        # 构建API endpoint
        self.embed_url = f"{xinference_url}/v1/embeddings"
        
        logger.info(f"初始化EmbeddingOptimizer:")
        logger.info(f"  API: {self.embed_url}")
        logger.info(f"  Model: {model_uid}")
        logger.info(f"  相似度阈值: {similarity_threshold}")
        logger.info(f"  最大合并大小: {max_merged_size}")
    
    def get_embedding(self, text: str) -> np.ndarray:
        """
        获取文本的embedding向量
        
        Args:
            text: 输入文本
            
        Returns:
            embedding向量
        """
        try:
            response = requests.post(
                self.embed_url,
                json={
                    "model": self.model_uid,
                    "input": text
                },
                timeout=30
            )
            response.raise_for_status()
            data = response.json()
            
            # 提取embedding
            embedding = data['data'][0]['embedding']
            return np.array(embedding)
            
        except Exception as e:
            logger.error(f"获取embedding失败: {e}")
            raise
    
    def get_embeddings_batch(self, texts: List[str], batch_size: int = 10) -> List[np.ndarray]:
        """
        批量获取embeddings
        
        Args:
            texts: 文本列表
            batch_size: 批次大小
            
        Returns:
            embedding列表
        """
        embeddings = []
        
        for i in tqdm(range(0, len(texts), batch_size), desc="获取embeddings"):
            batch = texts[i:i + batch_size]
            
            try:
                response = requests.post(
                    self.embed_url,
                    json={
                        "model": self.model_uid,
                        "input": batch
                    },
                    timeout=60
                )
                response.raise_for_status()
                data = response.json()
                
                # 提取所有embeddings
                batch_embeddings = [np.array(item['embedding']) for item in data['data']]
                embeddings.extend(batch_embeddings)
                
            except Exception as e:
                logger.error(f"批次 {i//batch_size} 获取embedding失败: {e}")
                # 失败则逐个获取
                for text in batch:
                    try:
                        emb = self.get_embedding(text)
                        embeddings.append(emb)
                    except:
                        # 如果单个也失败，使用零向量
                        embeddings.append(np.zeros(1024))  # bge-m3默认维度
        
        return embeddings
    
    def cosine_similarity(self, vec1: np.ndarray, vec2: np.ndarray) -> float:
        """
        计算余弦相似度
        
        Args:
            vec1: 向量1
            vec2: 向量2
            
        Returns:
            相似度分数 (0-1)
        """
        dot_product = np.dot(vec1, vec2)
        norm1 = np.linalg.norm(vec1)
        norm2 = np.linalg.norm(vec2)
        
        if norm1 == 0 or norm2 == 0:
            return 0.0
        
        return dot_product / (norm1 * norm2)
    
    def _get_field(self, chunk: Dict, field: str, default=None):
        """
        获取chunk字段(兼容标准和优化格式)
        
        标准格式: chunk['metadata']['token_count']
        优化格式: chunk['meta']['tokens']
        """
        if 'metadata' in chunk:
            # 标准格式
            return chunk['metadata'].get(field, default)
        elif 'meta' in chunk:
            # 优化格式 - 字段映射
            field_map = {
                'token_count': 'tokens',
                'dialogue_count': 'dlg_cnt',
                'scene_id': 'scene',
                'source_file': 'scene',  # 从scene推导
            }
            return chunk['meta'].get(field_map.get(field, field), default)
        return default
    
    def _get_chunk_id(self, chunk: Dict) -> str:
        """获取chunk_id"""
        return chunk.get('id') or chunk.get('chunk_id', '')
    
    def should_merge(self, chunk1: Dict, chunk2: Dict, similarity: float) -> bool:
        """
        判断是否应该合并两个chunks
        
        Args:
            chunk1: 第一个chunk
            chunk2: 第二个chunk
            similarity: 相似度分数
            
        Returns:
            是否应该合并
        """
        # 使用兼容方法
        size1 = self._get_field(chunk1, 'token_count', 0)
        size2 = self._get_field(chunk2, 'token_count', 0)
        
        # 条件1: 至少有一个是小chunk
        has_small_chunk = (size1 < self.min_merge_size) or (size2 < self.min_merge_size)
        
        # 条件2: 相似度超过阈值
        high_similarity = similarity >= self.similarity_threshold
        
        # 条件3: 合并后不超过最大限制
        merged_size = size1 + size2
        within_limit = merged_size <= self.max_merged_size
        
        # 条件4: 来自同一源文件
        source1 = self._get_field(chunk1, 'source_file', '')
        source2 = self._get_field(chunk2, 'source_file', '')
        same_source = (source1 == source2) if source1 and source2 else True
        
        # 条件5: 场景相关性检查
        try:
            chunk_id1 = self._get_chunk_id(chunk1)
            chunk_id2 = self._get_chunk_id(chunk2)
            scene1 = self._get_field(chunk1, 'scene_id', '')
            scene2 = self._get_field(chunk2, 'scene_id', '')
            
            if '_sub_' in chunk_id1:
                scene1 = chunk_id1.rsplit('_sub_', 1)[0]
            if '_sub_' in chunk_id2:
                scene2 = chunk_id2.rsplit('_sub_', 1)[0]
            
            if scene1 == scene2:
                scene_related = True
            else:
                try:
                    num1 = int(scene1.split('_')[-1])
                    num2 = int(scene2.split('_')[-1])
                    scene_related = abs(num1 - num2) <= 3
                except:
                    scene_related = True
        except:
            scene_related = True
        
        should_merge_decision = (has_small_chunk and high_similarity and 
                                 within_limit and same_source and scene_related)
        
        if should_merge_decision:
            logger.debug(f"合并: {self._get_chunk_id(chunk1)} + {self._get_chunk_id(chunk2)}")
        
        return should_merge_decision
    
    def merge_chunks(self, chunk1: Dict, chunk2: Dict) -> Dict:
        """
        合并两个chunks
        
        Args:
            chunk1: 第一个chunk
            chunk2: 第二个chunk
            
        Returns:
            合并后的chunk
        """
        # 合并内容
        merged_content = chunk1['content'] + '\n---\n' + chunk2['content']
        
        # 合并元数据 - 使用chunk1的格式
        if 'metadata' in chunk1:
            # 标准格式
            merged_metadata = chunk1['metadata'].copy()
            merged_metadata['chunk_id'] = f"{self._get_chunk_id(chunk1)}_merged"
            merged_metadata['token_count'] = self._get_field(chunk1, 'token_count', 0) + self._get_field(chunk2, 'token_count', 0)
            merged_metadata['dialogue_count'] = self._get_field(chunk1, 'dialogue_count', 0) + self._get_field(chunk2, 'dialogue_count', 0)
            
            return {
                'chunk_id': merged_metadata['chunk_id'],
                'content': merged_content,
                'metadata': merged_metadata,
                'parent_chunk_id': chunk1.get('parent_chunk_id'),
                'overlap_prev': chunk1.get('overlap_prev', ''),
                'merged_from': [self._get_chunk_id(chunk1), self._get_chunk_id(chunk2)]
            }
        else:
            # 优化格式
            merged_meta = chunk1['meta'].copy()
            merged_meta['tokens'] = self._get_field(chunk1, 'token_count', 0) + self._get_field(chunk2, 'token_count', 0)
            merged_meta['dlg_cnt'] = self._get_field(chunk1, 'dialogue_count', 0) + self._get_field(chunk2, 'dialogue_count', 0)
            
            return {
                'id': f"{self._get_chunk_id(chunk1)}_merged",
                'content': merged_content,
                'meta': merged_meta,
                'merged_from': [self._get_chunk_id(chunk1), self._get_chunk_id(chunk2)]
            }
    
    def optimize_chunks(self, chunks: List[Dict], use_cache: bool = True) -> List[Dict]:
        """
        优化chunks列表
        
        Args:
            chunks: 原始chunks列表
            use_cache: 是否使用缓存的embeddings
            
        Returns:
            优化后的chunks列表
        """
        logger.info(f"开始优化 {len(chunks)} 个chunks")
        
        # 1. 获取所有chunks的embeddings
        logger.info("计算embeddings...")
        texts = [chunk['content'] for chunk in chunks]
        embeddings = self.get_embeddings_batch(texts)
        
        # 2. 按源文件分组
        file_groups = {}
        for idx, chunk in enumerate(chunks):
            source = self._get_field(chunk, 'source_file', 'unknown')
            # 如果source为空,从chunk_id推导
            if not source or source == 'unknown':
                chunk_id = self._get_chunk_id(chunk)
                source = chunk_id.rsplit('_scene_', 1)[0] + '.txt' if '_scene_' in chunk_id else 'unknown'
            
            if source not in file_groups:
                file_groups[source] = []
            file_groups[source].append((idx, chunk, embeddings[idx]))
        
        logger.info(f"共 {len(file_groups)} 个源文件")
        
        # 3. 对每个文件的chunks进行优化
        optimized_chunks = []
        total_merged = 0
        
        for source_file, file_chunks in tqdm(file_groups.items(), desc="优化文件"):
            # 排序chunks（按chunk_id）
            file_chunks.sort(key=lambda x: self._get_chunk_id(x[1]))
            
            i = 0
            while i < len(file_chunks):
                current_idx, current_chunk, current_emb = file_chunks[i]
                
                # 检查是否可以与下一个chunk合并
                merged = False
                if i + 1 < len(file_chunks):
                    next_idx, next_chunk, next_emb = file_chunks[i + 1]
                    
                    # 计算相似度
                    similarity = self.cosine_similarity(current_emb, next_emb)
                    
                    # 判断是否合并
                    if self.should_merge(current_chunk, next_chunk, similarity):
                        # 合并
                        merged_chunk = self.merge_chunks(current_chunk, next_chunk)
                        optimized_chunks.append(merged_chunk)
                        total_merged += 1
                        i += 2  # 跳过下一个（已合并）
                        merged = True
                
                if not merged:
                    # 不合并，保留原chunk
                    optimized_chunks.append(current_chunk)
                    i += 1
        
        logger.info(f"优化完成:")
        logger.info(f"  原始chunks: {len(chunks)}")
        logger.info(f"  优化后: {len(optimized_chunks)}")
        logger.info(f"  合并次数: {total_merged}")
        logger.info(f"  减少: {len(chunks) - len(optimized_chunks)} chunks")
        
        return optimized_chunks
    
    def analyze_semantic_coherence(self, chunks: List[Dict]) -> Dict:
        """
        分析chunks的语义连贯性
        
        Args:
            chunks: chunks列表
            
        Returns:
            分析报告
        """
        logger.info("分析语义连贯性...")
        
        # 获取embeddings
        texts = [chunk['content'] for chunk in chunks]
        embeddings = self.get_embeddings_batch(texts)
        
        # 计算相邻chunks的相似度
        similarities = []
        for i in range(len(embeddings) - 1):
            sim = self.cosine_similarity(embeddings[i], embeddings[i + 1])
            similarities.append(sim)
        
        # 统计
        report = {
            'total_chunks': len(chunks),
            'avg_similarity': np.mean(similarities) if similarities else 0,
            'min_similarity': np.min(similarities) if similarities else 0,
            'max_similarity': np.max(similarities) if similarities else 0,
            'std_similarity': np.std(similarities) if similarities else 0,
            'high_similarity_pairs': sum(1 for s in similarities if s >= self.similarity_threshold),
            'low_similarity_pairs': sum(1 for s in similarities if s < 0.5)
        }
        
        logger.info("语义连贯性分析:")
        logger.info(f"  平均相似度: {report['avg_similarity']:.3f}")
        logger.info(f"  高相似度对数 (>={self.similarity_threshold}): {report['high_similarity_pairs']}")
        logger.info(f"  低相似度对数 (<0.5): {report['low_similarity_pairs']}")
        
        return report


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='基于Embedding的Chunk优化工具')
    parser.add_argument('input_file', help='输入JSON文件（原始chunks）')
    parser.add_argument('-o', '--output', help='输出JSON文件（优化后）', required=True)
    parser.add_argument('--api-url', default='http://192.168.123.113:9997', help='XInference API地址')
    parser.add_argument('--model-uid', default='bge-m3', help='模型UID')
    parser.add_argument('--similarity-threshold', type=float, default=0.82, 
                       help='相似度阈值 (默认0.82适配细粒度模式，默认chunker模式建议0.85-0.88)')
    parser.add_argument('--min-merge-size', type=int, default=100, help='最小合并大小')
    parser.add_argument('--max-merged-size', type=int, default=1800, 
                       help='合并后最大大小 (默认1800适配细粒度模式，默认chunker模式可用2000-2500)')
    parser.add_argument('--analyze-only', action='store_true', help='仅分析，不优化')
    
    args = parser.parse_args()
    
    # 加载chunks
    logger.info(f"加载chunks: {args.input_file}")
    with open(args.input_file, 'r', encoding='utf-8') as f:
        chunks = json.load(f)
    
    # 创建优化器
    optimizer = EmbeddingOptimizer(
        xinference_url=args.api_url,
        model_uid=args.model_uid,
        similarity_threshold=args.similarity_threshold,
        min_merge_size=args.min_merge_size,
        max_merged_size=args.max_merged_size
    )
    
    # 测试API连接
    try:
        logger.info("测试API连接...")
        test_emb = optimizer.get_embedding("测试文本")
        logger.info(f"API连接成功！Embedding维度: {len(test_emb)}")
    except Exception as e:
        logger.error(f"API连接失败: {e}")
        logger.error("请检查XInference服务是否正常运行")
        return
    
    if args.analyze_only:
        # 仅分析
        report = optimizer.analyze_semantic_coherence(chunks)
        
        # 保存分析报告
        report_file = args.output.replace('.json', '_analysis.json')
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"分析报告已保存: {report_file}")
    else:
        # 优化
        optimized_chunks = optimizer.optimize_chunks(chunks)
        
        # 保存优化后的chunks
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(optimized_chunks, f, ensure_ascii=False, indent=2)
        
        logger.info(f"优化结果已保存: {args.output}")
        
        # 同时进行分析
        report = optimizer.analyze_semantic_coherence(optimized_chunks)
        report_file = args.output.replace('.json', '_analysis.json')
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"分析报告已保存: {report_file}")


if __name__ == '__main__':
    main()
