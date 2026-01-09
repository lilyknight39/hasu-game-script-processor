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
import re
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
                 similarity_threshold: float = 0.84,  # 根据最新报告略微收紧合并
                 min_merge_size: int = 150,
                 max_merged_size: int = 2000,  # 提高到2000以容纳合并内容
                 keep_voice_refs: bool = True,
                 keep_emotions: bool = True):  # 默认保留语音/情绪标签，删除改为可选
        """
        初始化优化器
        
        Args:
            xinference_url: XInference API地址
            model_uid: 模型UID
            similarity_threshold: 相似度阈值（超过此值考虑合并）
                                默认0.82适配细粒度模式（更多小chunks）
                                如使用默认chunker模式，建议提高到0.85-0.88
            min_merge_size: 最小合并大小 (默认300，用于合并细碎片段)
            max_merged_size: 合并后的最大大小限制
                           默认2000适配BGE-M3 (8k window)
                           如使用默认chunker模式，可提高到2500
            keep_voice_refs: 集成清洗时是否保留 voice_refs
            keep_emotions: 集成清洗时是否保留 emotions
        """
        self.xinference_url = xinference_url
        self.model_uid = model_uid
        self.similarity_threshold = similarity_threshold
        self.min_merge_size = min_merge_size
        self.max_merged_size = max_merged_size
        self.keep_voice_refs = keep_voice_refs
        self.keep_emotions = keep_emotions
        
        # 构建API endpoint
        self.embed_url = f"{xinference_url}/v1/embeddings"
        
        logger.info(f"初始化EmbeddingOptimizer:")
        logger.info(f"  API: {self.embed_url}")
        logger.info(f"  Model: {model_uid}")
        logger.info(f"  相似度阈值: {similarity_threshold}")
        logger.info(f"  最大合并大小: {max_merged_size}")
    
    def _estimate_tokens(self, text: str) -> int:
        """粗略估算token数，兼容中日英文本。"""
        japanese_chars = len(re.findall(r'[\u3040-\u30FF\u4E00-\u9FFF]', text))
        english_words = len(re.findall(r'[a-zA-Z]+', text))
        numbers = len(re.findall(r'\d+', text))
        return japanese_chars + english_words + numbers

    def _collect_emotion_action_summary(self, chunk: Dict) -> str:
        """
        从元数据/对话中提取情绪与动作摘要，用于丰富嵌入文本。
        优先使用标准格式的 dialogues；优化格式可能无情绪信息，则跳过。
        """
        emotions = set()
        actions = set()
        # 标准格式
        meta = chunk.get('metadata') or chunk.get('meta') or {}
        if meta:
            if 'dialogues' in meta:
                for dlg in meta['dialogues']:
                    if dlg.get('emotion_before'):
                        emotions.add(dlg['emotion_before'])
                    if dlg.get('emotion_after'):
                        emotions.add(dlg['emotion_after'])
                    if dlg.get('action_desc'):
                        actions.add(dlg['action_desc'])
                    elif dlg.get('action'):
                        actions.add(dlg['action'])
                    if dlg.get('state_changes'):
                        for chg in dlg['state_changes']:
                            if chg.get('type') == 'emotion' and chg.get('value'):
                                emotions.add(chg['value'])
                            if chg.get('type') == 'action' and chg.get('value'):
                                actions.add(chg['value'])
            # 场景级元数据的情绪/动作/状态变化
            for v in meta.get('emotions', {}).values():
                if v:
                    emotions.add(v)
            for v in meta.get('actions', {}).values():
                if v:
                    actions.add(v)
            for chg in meta.get('state_changes', []) or []:
                if chg.get('type') == 'emotion' and chg.get('value'):
                    emotions.add(chg['value'])
                if chg.get('type') == 'action' and chg.get('value'):
                    actions.add(chg['value'])
        return f"Emotions: {', '.join(sorted(emotions))}\nActions: {', '.join(sorted(actions))}" if emotions or actions else ""

    def _collect_voice_refs(self, chunk: Dict) -> str:
        """
        收集语音引用（对话级 + 场景级），用于嵌入时保留声线/角色线索。
        """
        meta = chunk.get('metadata') or chunk.get('meta') or {}
        voices = []
        for dlg in meta.get('dialogues', []) or []:
            if dlg.get('voice_ref'):
                voices.append(dlg['voice_ref'])
        voices.extend(meta.get('voice_refs', []) or meta.get('voices', []) or [])
        # 去重保持顺序
        seen = set()
        uniq = []
        for v in voices:
            if v and v not in seen:
                seen.add(v)
                uniq.append(v)
        return ', '.join(uniq)

    def _build_embedding_text(self, chunk: Dict) -> str:
        """构造和优化阶段一致的 embedding 输入文本 (meta + content)。"""
        scene_id = self._get_field(chunk, 'scene_id', '')
        location = self._get_field(chunk, 'location', '')
        time_period = self._get_field(chunk, 'time_period', '')
        weather = self._get_field(chunk, 'weather', '')
        scene_type = self._get_field(chunk, 'scene_type', '')
        bgm = self._get_field(chunk, 'bgm', '')
        chars = self._get_field(chunk, 'characters', [])
        if isinstance(chars, list):
            chars_str = ', '.join(chars)
        else:
            chars_str = str(chars)
        emotion_action_text = self._collect_emotion_action_summary(chunk)
        voice_text = self._collect_voice_refs(chunk)
        meta_lines = [
            f"Scene: {scene_id}",
            f"Location: {location}",
            f"Time: {time_period}",
            f"Weather: {weather}",
            f"SceneType: {scene_type}",
            f"BGM: {bgm}",
            f"Chars: {chars_str}",
        ]
        if emotion_action_text:
            meta_lines.append(emotion_action_text)
        if voice_text:
            meta_lines.append(f"VoiceRefs: {voice_text}")
        meta_text = "\n".join(meta_lines)
        return f"{meta_text}\n\n{chunk['content']}"

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
                'location': 'loc',
                'time_period': 'time',
                'weather': 'weather',
                'scene_type': 'scene_type',
                'characters': 'chars',
                'bgm': 'bgm',
                'voice_refs': 'voice_refs',
                'actions': 'actions',
                'state_changes': 'state_changes',
            }
            value = chunk['meta'].get(field_map.get(field, field), default)
            
            if field == 'source_file':
                # 尝试从scene字段或chunk_id推导源文件名
                scene_val = chunk['meta'].get('scene') or chunk.get('id', '')
                if scene_val and '_scene_' in scene_val:
                    return scene_val.split('_scene_', 1)[0] + '.txt'
            
            return value
        return default
    
    def _get_chunk_id(self, chunk: Dict) -> str:
        """获取chunk_id"""
        return chunk.get('id') or chunk.get('chunk_id', '')
    
    def _merge_unique_list(self, first, second) -> List:
        """合并列表并去重，保持顺序"""
        merged = []
        seen = set()
        for item in (first or []) + (second or []):
            if item in (None, ''):
                continue
            if item not in seen:
                seen.add(item)
                merged.append(item)
        return merged

    def _choose_field(self, primary, secondary):
        """
        返回合并后的单值字段:
        - 若其中一个为空，取非空
        - 若两者非空且不同，使用“value1 | value2”串联（去重保持顺序）
        """
        empty = (None, '', [])
        if primary in empty and secondary in empty:
            return None
        if primary in empty:
            return secondary
        if secondary in empty:
            return primary
        if primary == secondary:
            return primary
        # 去重串联
        merged = []
        for v in (primary, secondary):
            if v not in merged:
                merged.append(v)
        return " | ".join(merged)
    
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
        merged_tokens = self._estimate_tokens(merged_content)
        
        # 合并元数据 - 使用chunk1的格式
        if 'metadata' in chunk1:
            # 标准格式
            merged_metadata = chunk1['metadata'].copy()
            merged_metadata['chunk_id'] = f"{self._get_chunk_id(chunk1)}_merged"
            merged_metadata['token_count'] = merged_tokens
            
            # CRITICAL FIX: Merge dialogues
            dialogues1 = merged_metadata.get('dialogues', [])
            dialogues2 = chunk2.get('metadata', {}).get('dialogues', [])
            merged_metadata['dialogues'] = dialogues1 + dialogues2
            merged_metadata['dialogue_count'] = len(merged_metadata['dialogues']) or (
                self._get_field(chunk1, 'dialogue_count', 0) + self._get_field(chunk2, 'dialogue_count', 0)
            )
            
            # 合并角色/语音引用/情绪等上下文信息
            merged_metadata['characters'] = self._merge_unique_list(
                merged_metadata.get('characters', []),
                chunk2.get('metadata', {}).get('characters', [])
            )
            merged_metadata['voice_refs'] = self._merge_unique_list(
                merged_metadata.get('voice_refs', []),
                chunk2.get('metadata', {}).get('voice_refs', [])
            )
            merged_metadata['emotions'] = {
                **chunk1.get('metadata', {}).get('emotions', {}),
                **chunk2.get('metadata', {}).get('emotions', {})
            }
            merged_metadata['location'] = self._choose_field(
                merged_metadata.get('location'),
                chunk2.get('metadata', {}).get('location')
            )
            merged_metadata['time_period'] = self._choose_field(
                merged_metadata.get('time_period'),
                chunk2.get('metadata', {}).get('time_period')
            )
            merged_metadata['scene_type'] = self._choose_field(
                merged_metadata.get('scene_type'),
                chunk2.get('metadata', {}).get('scene_type')
            )
            merged_metadata['weather'] = self._choose_field(
                merged_metadata.get('weather'),
                chunk2.get('metadata', {}).get('weather')
            )
            merged_metadata['bgm'] = self._choose_field(
                merged_metadata.get('bgm'),
                chunk2.get('metadata', {}).get('bgm')
            )
            
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
            merged_meta['tokens'] = merged_tokens
            
            # CRITICAL FIX: Merge dialogues (dlgs)
            dlgs1 = merged_meta.get('dlgs', [])
            dlgs2 = chunk2.get('meta', {}).get('dlgs', [])
            merged_meta['dlgs'] = dlgs1 + dlgs2
            merged_meta['dlg_cnt'] = len(merged_meta['dlgs']) or (
                self._get_field(chunk1, 'dialogue_count', 0) + self._get_field(chunk2, 'dialogue_count', 0)
            )
            
            merged_meta['chars'] = self._merge_unique_list(
                merged_meta.get('chars', []),
                chunk2.get('meta', {}).get('chars', [])
            )
            merged_meta['loc'] = self._choose_field(
                merged_meta.get('loc'),
                chunk2.get('meta', {}).get('loc')
            )
            merged_meta['time'] = self._choose_field(
                merged_meta.get('time'),
                chunk2.get('meta', {}).get('time')
            )
            merged_meta['bgm'] = self._choose_field(
                merged_meta.get('bgm'),
                chunk2.get('meta', {}).get('bgm')
            )
            
            return {
                'id': f"{self._get_chunk_id(chunk1)}_merged",
                'content': merged_content,
                'meta': merged_meta,
                'merged_from': [self._get_chunk_id(chunk1), self._get_chunk_id(chunk2)]
            }

    def clean_chunk_data(self, chunk: Dict) -> Dict:
        """
        清理chunk数据 (集成自optimizer.py)
        1. 移除null/空字段
        2. 处理action/action_desc冗余
        3. 移除冗余元数据
        """
        import copy
        c = copy.deepcopy(chunk)
        
        if 'metadata' in c and 'dialogues' in c['metadata']:
            cleaned_dialogues = []
            for dlg in c['metadata']['dialogues']:
                # 若 action_desc 为空，尝试从 state_changes 中补上最后一次动作描述
                if (not dlg.get('action_desc')) and dlg.get('state_changes'):
                    for chg in reversed(dlg['state_changes']):
                        if chg.get('type') == 'action' and chg.get('value'):
                            dlg = dict(dlg)  # 不改原引用
                            dlg['action_desc'] = chg['value']
                            break
                # 移除null和空字符串字段
                cleaned_dlg = {k: v for k, v in dlg.items() if v not in (None, '', [])}
                
                # 处理action和action_desc的逻辑
                has_action_desc = 'action_desc' in cleaned_dlg and cleaned_dlg['action_desc'].strip()
                has_action = 'action' in cleaned_dlg and cleaned_dlg['action'].strip()
                
                if has_action_desc:
                    cleaned_dlg.pop('action', None)
                elif has_action:
                    cleaned_dlg.pop('action_desc', None)
                else:
                    cleaned_dlg.pop('action', None)
                    cleaned_dlg.pop('action_desc', None)
                
                cleaned_dialogues.append(cleaned_dlg)
            c['metadata']['dialogues'] = cleaned_dialogues
            
            # 只在显式不保留时移除顶层字段
            if not self.keep_voice_refs:
                c['metadata'].pop('voice_refs', None)
            if not self.keep_emotions:
                c['metadata'].pop('emotions', None)
            
            # 清理空的辅助字段，保持角色列表为非空字符串
            c['metadata']['characters'] = [ch for ch in c['metadata'].get('characters', []) if ch]
            for key in ['location', 'time_period', 'scene_type', 'weather', 'bgm']:
                if c['metadata'].get(key) in ('', None, []):
                    c['metadata'].pop(key, None)
        elif 'meta' in c and 'dlgs' in c['meta']:
            cleaned_dlgs = []
            for dlg in c['meta']['dlgs']:
                # 优化格式：若 act_desc 为空，尝试从 chg 中补最后一次动作
                if (not dlg.get('act_desc')) and dlg.get('chg'):
                    for chg in reversed(dlg['chg']):
                        if chg.get('type') == 'action' and chg.get('value'):
                            dlg = dict(dlg)
                            dlg['act_desc'] = chg['value']
                            break
                cleaned_dlg = {k: v for k, v in dlg.items() if v not in (None, '', [])}
                
                # 处理动作字段冗余
                has_act_desc = 'act_desc' in cleaned_dlg and cleaned_dlg['act_desc'].strip()
                has_act = 'act' in cleaned_dlg and cleaned_dlg['act']
                if has_act_desc:
                    cleaned_dlg.pop('act', None)
                elif not has_act:
                    cleaned_dlg.pop('act', None)
                    cleaned_dlg.pop('act_desc', None)
                
                cleaned_dlgs.append(cleaned_dlg)
            c['meta']['dlgs'] = cleaned_dlgs
            c['meta']['chars'] = [ch for ch in c['meta'].get('chars', []) if ch]
            for key in ['loc', 'time', 'bgm']:
                if c['meta'].get(key) in ('', None, []):
                    c['meta'].pop(key, None)
            
        # 移除结构冗余
        c.pop('parent_chunk_id', None)
        c.pop('overlap_prev', None)
        
        return c
    
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
        
        # 1. 获取所有chunks的embeddings (带元数据增强)
        logger.info("计算embeddings (带元数据注入)...")
        
        # 构建用于embedding的文本（注入上下文）
        embedding_texts = []
        for chunk in chunks:
            full_text = self._build_embedding_text(chunk)
            text_tokens = self._estimate_tokens(full_text)
            if text_tokens > self.max_merged_size * 1.5:
                logger.debug(f"chunk {self._get_chunk_id(chunk)} 嵌入文本较长，估计 {text_tokens} tokens")
            embedding_texts.append(full_text)
            
        embeddings = self.get_embeddings_batch(embedding_texts)
        
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
        
        # 按源文件分组，避免跨文件低相似度干扰
        file_groups: Dict[str, List[Dict]] = {}
        for chunk in chunks:
            source = self._get_field(chunk, 'source_file', 'unknown')
            if not source or source == 'unknown':
                cid = self._get_chunk_id(chunk)
                source = cid.rsplit('_scene_', 1)[0] + '.txt' if '_scene_' in cid else 'unknown'
            file_groups.setdefault(source, []).append(chunk)
        
        overall_similarities = []
        high_count = 0
        low_count = 0
        file_breakdown = {}
        low_pairs_all = []
        
        for source, file_chunks in file_groups.items():
            file_chunks.sort(key=lambda c: self._get_chunk_id(c))
            embedding_texts = [self._build_embedding_text(c) for c in file_chunks]
            file_embeddings = self.get_embeddings_batch(embedding_texts)
            
            file_similarities = []
            file_low_pairs = []
            
            for i in range(len(file_embeddings) - 1):
                sim = self.cosine_similarity(file_embeddings[i], file_embeddings[i + 1])
                overall_similarities.append(sim)
                file_similarities.append(sim)
                
                pair_record = {
                    'source_file': source,
                    'left_chunk': self._get_chunk_id(file_chunks[i]),
                    'right_chunk': self._get_chunk_id(file_chunks[i + 1]),
                    'similarity': sim
                }
                low_pairs_all.append(pair_record)
                
                if sim >= self.similarity_threshold:
                    high_count += 1
                if sim < 0.5:
                    low_count += 1
                    file_low_pairs.append(pair_record)
            
            file_breakdown[source] = {
                'chunk_count': len(file_chunks),
                'avg_similarity': float(np.mean(file_similarities)) if file_similarities else 0.0,
                'min_similarity': float(np.min(file_similarities)) if file_similarities else 0.0,
                'max_similarity': float(np.max(file_similarities)) if file_similarities else 0.0,
                'std_similarity': float(np.std(file_similarities)) if file_similarities else 0.0,
                'high_similarity_pairs': sum(1 for s in file_similarities if s >= self.similarity_threshold),
                'low_similarity_pairs': sum(1 for s in file_similarities if s < 0.5),
                'lowest_pairs': sorted(file_low_pairs, key=lambda p: p['similarity'])[:5]
            }
        
        # 统计汇总
        report = {
            'total_chunks': len(chunks),
            'avg_similarity': float(np.mean(overall_similarities)) if overall_similarities else 0.0,
            'min_similarity': float(np.min(overall_similarities)) if overall_similarities else 0.0,
            'max_similarity': float(np.max(overall_similarities)) if overall_similarities else 0.0,
            'std_similarity': float(np.std(overall_similarities)) if overall_similarities else 0.0,
            'high_similarity_pairs': high_count,
            'low_similarity_pairs': low_count,
            'file_breakdown': file_breakdown,
            'top_low_similarity_pairs': sorted(low_pairs_all, key=lambda p: p['similarity'])[:10]
        }
        
        logger.info("语义连贯性分析:")
        logger.info(f"  平均相似度: {report['avg_similarity']:.3f}")
        logger.info(f"  高相似度对数 (>={self.similarity_threshold}): {report['high_similarity_pairs']}")
        logger.info(f"  低相似度对数 (<0.5): {report['low_similarity_pairs']}")
        logger.info("  按文件统计已写入报告")
        
        return report


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='基于Embedding的Chunk优化工具')
    parser.add_argument('input_file', help='输入JSON文件（原始chunks）')
    parser.add_argument('-o', '--output', help='输出JSON文件（优化后）', required=True)
    parser.add_argument('--api-url', default='http://192.168.123.113:9997', help='XInference API地址')
    parser.add_argument('--model-uid', default='bge-m3', help='模型UID')
    parser.add_argument('--similarity-threshold', type=float, default=0.84, 
                       help='相似度阈值 (默认0.84，略收紧合并，默认chunker模式可用0.85-0.88)')
    parser.add_argument('--min-merge-size', type=int, default=150, help='最小合并大小')
    parser.add_argument('--max-merged-size', type=int, default=1800, 
                       help='合并后最大大小 (默认1800适配细粒度模式，默认chunker模式可用2000-2500)')
    parser.add_argument('--analyze-only', action='store_true', help='仅分析，不优化')
    parser.add_argument('--no-clean', action='store_true', help='跳过集成数据清理 (保留原始合并数据)')
    parser.add_argument('--keep-voice-refs', action='store_true', default=True, help='清理时保留 voice_refs 字段（默认保留）')
    parser.add_argument('--drop-voice-refs', action='store_true', help='显式删除 voice_refs 字段')
    parser.add_argument('--keep-emotions', action='store_true', default=True, help='清理时保留 emotions 字段（默认保留）')
    parser.add_argument('--drop-emotions', action='store_true', help='显式删除 emotions 字段')
    parser.add_argument('--analyze', action='store_true', help='优化后生成语义连贯性报告（默认不生成）')
    
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
        max_merged_size=args.max_merged_size,
        keep_voice_refs=bool(args.keep_voice_refs and not args.drop_voice_refs),
        keep_emotions=bool(args.keep_emotions and not args.drop_emotions)
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
        report_file = args.output.replace('.json', '_analysis.json')
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"分析报告已保存: {report_file}")
        return

    # 优化
    optimized_chunks = optimizer.optimize_chunks(chunks)
    
    # 集成数据清理 (替代 step 3)
    if not args.no_clean:
        logger.info("执行集成数据清理 (移除冗余数据)...")
        optimized_chunks = [optimizer.clean_chunk_data(c) for c in optimized_chunks]
    
    # 保存优化后的chunks
    with open(args.output, 'w', encoding='utf-8') as f:
        json.dump(optimized_chunks, f, ensure_ascii=False, indent=2)
    
    logger.info(f"优化结果已保存: {args.output}")
    
    # 可选分析
    if args.analyze:
        report = optimizer.analyze_semantic_coherence(optimized_chunks)
        report_file = args.output.replace('.json', '_analysis.json')
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        logger.info(f"分析报告已保存: {report_file}")


if __name__ == '__main__':
    main()
