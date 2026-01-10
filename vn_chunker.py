#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Visual Novel Script Intelligent Chunker for Dify Knowledge Base
================================================================

智能分块预处理脚本，针对Visual Novel/Galgame剧本文档进行语义感知分块。

主要功能：
- 场景边界检测
- 对话完整性保持
- 元数据提取
- 智能重叠策略
"""

import re
import json
import os
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from dataclasses import dataclass, asdict
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class DialogueLine:
    """单条对话数据"""
    character: str                      # 角色名
    text: str                           # 对话文本
    voice_ref: Optional[str] = None     # 语音文件引用
    emotion_before: Optional[str] = None  # 对话前的表情
    emotion_after: Optional[str] = None   # 对话后的表情变化
    action: Optional[str] = None        # 动作ID (如 mot_01_30012)
    action_desc: str = ''               # 动作描述 (如 "頷く")
    state_changes: Optional[List[Dict]] = None  # 对话间的状态变化记录


@dataclass
class ChunkMetadata:
    """Chunk元数据"""
    chunk_id: str
    scene_id: str
    source_file: str
    characters: List[str]
    location: str
    bgm: str
    emotions: Dict[str, str]
    actions: Dict[str, str]
    state_changes: List[Dict]
    voice_refs: List[str]
    chunk_type: str
    token_count: int
    dialogue_count: int
    time_period: str = ''      # 时间段
    weather: str = ''          # 天气
    scene_type: str = ''       # 场景类型
    dialogues: List[Dict] = None  # 结构化对话序列
    
    def __post_init__(self):
        if self.dialogues is None:
            self.dialogues = []
        if self.actions is None:
            self.actions = {}
        if self.state_changes is None:
            self.state_changes = []


@dataclass
class Chunk:
    """分块数据结构"""
    chunk_id: str
    content: str
    metadata: ChunkMetadata
    parent_chunk_id: Optional[str] = None
    overlap_prev: str = ""
    
    def to_optimized_dict(self) -> Dict:
        """
        转换为优化的字典格式(用于embedding workflow)
        
        优化策略:
        - 移除冗余字段(voice_refs, emotions, parent_chunk_id, overlap_prev)  
        - 压缩dialogues格式(字段名缩短,移除null值)
        - 字段名缩短
        """
        # 优化dialogues格式
        optimized_dialogues = []
        for dlg in self.metadata.dialogues:
            compact_dlg = {
                'char': dlg['character'],
                'text': dlg['text']
            }
            # 只添加非空字段
            if dlg.get('voice_ref'):
                compact_dlg['voice'] = dlg['voice_ref']
            if dlg.get('emotion_before'):
                compact_dlg['e_bef'] = dlg['emotion_before']
            if dlg.get('emotion_after'):
                compact_dlg['e_aft'] = dlg['emotion_after']
            
            # 动作: 如果有act_desc则只保留act_desc,否则保留act
            if dlg.get('action_desc'):
                compact_dlg['act_desc'] = dlg['action_desc']
            elif dlg.get('action'):
                compact_dlg['act'] = dlg['action']
            if dlg.get('state_changes'):
                compact_dlg['chg'] = dlg['state_changes']
            
            optimized_dialogues.append(compact_dlg)
        
        return {
            'id': self.chunk_id,
            'content': self.content,
            'meta': {
                'scene': self.metadata.scene_id,
                'chars': self.metadata.characters,
                'loc': self.metadata.location,
                'bgm': self.metadata.bgm,
                'tokens': self.metadata.token_count,
                'dlg_cnt': self.metadata.dialogue_count,
                'time': self.metadata.time_period,
                'dlgs': optimized_dialogues
            }
        }

    def _build_dense_text(self, ctx: Dict, script: List[Dict]) -> str:
        """
        构建高密度文本表示：
        - 使用精简的上下文头部 loc/time/weather/type/bgm
        - 对话行使用短标注 (emo/act/chg)，旁白不加角色前缀
        """
        header_parts = []
        header_map = [('loc', 'loc'), ('time', 'time'),
                      ('weather', 'weather'), ('type', 'type'),
                      ('bgm', 'bgm')]
        for key, label in header_map:
            val = ctx.get(key)
            if val:
                header_parts.append(f"{label}:{val}")
        chars = ctx.get('chars', [])
        header = f"[{self.chunk_id}]"
        if header_parts:
            header = f"{header} " + " | ".join(header_parts)

        lines = []
        for row in script:
            speaker = row.get('c') or 'narrator'
            text = row.get('t', '')
            annotations = []
            emo = row.get('e')
            if emo:
                if isinstance(emo, list) and len(emo) >= 2:
                    before = emo[0]
                    after = emo[1] if len(emo) > 1 else None
                    if before and after and before != after:
                        annotations.append(f"emo:{before}->{after}")
                    else:
                        annotations.append(f"emo:{after or before}")
                else:
                    annotations.append(f"emo:{emo}")
            if row.get('a'):
                annotations.append(f"act:{row['a']}")
            if row.get('chg'):
                state_tags = [f"{c[0]}:{c[1]}" for c in row['chg'] if len(c) == 2 and all(c)]
                if state_tags:
                    annotations.append("chg:" + ";".join(state_tags))
            tail = f" [{' | '.join(annotations)}]" if annotations else ""
            if speaker.lower() == 'narrator':
                lines.append(f"{text}{tail}")
            else:
                lines.append(f"{speaker}: {text}{tail}")

        # 如果没有结构化对话，则回退到原始content
        if not lines and self.content:
            return self.content

        return header + "\n" + "\n".join(lines)

    def to_dense_dict(self) -> Dict:
        """
        生成高密度结构化格式:
        - ctx 使用短键名，去掉空字段
        - script 压缩对话行，短键名并去掉空值
        - stats 收录 token/对话统计
        - text 为带上下文头的紧凑文本，便于直接用于向量化
        """
        meta = self.metadata

        # 压缩对话行
        script = []
        for dlg in meta.dialogues:
            line = {
                'c': dlg.get('character', 'narrator'),
                't': dlg.get('text', '')
            }
            if dlg.get('voice_ref'):
                line['v'] = dlg['voice_ref']
            e_bef = dlg.get('emotion_before')
            e_aft = dlg.get('emotion_after')
            if e_bef or e_aft:
                if e_bef and e_aft and e_bef != e_aft:
                    line['e'] = [e_bef, e_aft]
                else:
                    line['e'] = e_aft or e_bef
            act = dlg.get('action_desc') or dlg.get('action')
            if act:
                line['a'] = act
            if dlg.get('state_changes'):
                compact_changes = []
                for change in dlg['state_changes']:
                    c_type = change.get('type')
                    c_val = change.get('value')
                    if c_type and c_val:
                        compact_changes.append([c_type, c_val])
                if compact_changes:
                    line['chg'] = compact_changes
            # 去掉空字段
            line = {k: v for k, v in line.items() if v not in (None, '', [], {})}
            if line.get('t'):
                script.append(line)

        # 压缩上下文
        ctx = {
            'loc': meta.location,
            'time': meta.time_period,
            'weather': meta.weather,
            'type': meta.scene_type,
            'bgm': meta.bgm,
            'chars': meta.characters
        }
        if meta.voice_refs:
            ctx['voices'] = meta.voice_refs
        if meta.state_changes:
            compact_state = []
            for change in meta.state_changes:
                char = change.get('character')
                c_type = change.get('type')
                c_val = change.get('value')
                if char and c_type and c_val:
                    compact_state.append([char, c_type, c_val])
            if compact_state:
                ctx['state'] = compact_state
        if meta.emotions:
            ctx['emo'] = meta.emotions
        if meta.actions:
            ctx['act'] = meta.actions
        ctx = {k: v for k, v in ctx.items() if v not in (None, '', [], {})}

        stats = {
            'tok': meta.token_count,
            'dlg': meta.dialogue_count
        }

        dense_text = self._build_dense_text(ctx, script)

        return {
            'id': self.chunk_id,
            'scene': meta.scene_id,
            'src': meta.source_file,
            'ctx': ctx,
            'stats': stats,
            'script': script,
            'text': dense_text
        }

    def _build_timeline_payload(self) -> Tuple[List[Dict], Dict[str, Dict[str, List[List]]]]:
        """
        根据结构化对话生成关键帧脚本与时间线:
        - script 行保留 c/t/v，新增 kf（本行发生的关键帧标签列表）
        - timeline 为每个角色的 emo/act 变化节点列表 [[state, line_idx], ...]
        """
        script = []
        narrator_buffer: List[str] = []
        timeline: Dict[str, Dict[str, List[List]]] = {}
        last_emo: Dict[str, Optional[str]] = {}
        last_act: Dict[str, Optional[str]] = {}

        for idx, dlg in enumerate(self.metadata.dialogues, 1):
            char = dlg.get('character', 'narrator') or 'narrator'
            text = dlg.get('text', '')
            voice_ref = dlg.get('voice_ref')
            kf_labels: List[str] = []

            def flush_narrator():
                nonlocal narrator_buffer
                if narrator_buffer:
                    merged_text = ' '.join(narrator_buffer).strip()
                    if merged_text:
                        script.append({'c': 'narrator', 't': merged_text, 'kf': ['nar:block']})
                    narrator_buffer = []

            def ensure_track(c: str):
                if c not in timeline:
                    timeline[c] = {'emo': [], 'act': []}

            # 情感关键帧：前置状态与后置状态若产生变化则记录
            emo_before = dlg.get('emotion_before')
            emo_after = dlg.get('emotion_after')
            if emo_before and emo_before != last_emo.get(char):
                ensure_track(char)
                last_emo[char] = emo_before
                timeline[char]['emo'].append([emo_before, idx])
                kf_labels.append(f"emo:{emo_before}")
            if emo_after and emo_after != last_emo.get(char):
                ensure_track(char)
                last_emo[char] = emo_after
                timeline[char]['emo'].append([emo_after, idx])
                kf_labels.append(f"emo→:{emo_after}")

            # 动作关键帧：优先动作描述
            action_val = dlg.get('action_desc') or dlg.get('action')
            if action_val and action_val != last_act.get(char):
                ensure_track(char)
                last_act[char] = action_val
                timeline[char]['act'].append([action_val, idx])
                kf_labels.append(f"act:{action_val}")

            if char == 'narrator':
                narrator_buffer.append(text)
                continue

            flush_narrator()

            row = {'c': char, 't': text}
            if voice_ref:
                row['v'] = voice_ref
            if kf_labels:
                row['kf'] = kf_labels
            script.append(row)

        # 处理尾部剩余旁白
        if narrator_buffer:
            merged_text = ' '.join(narrator_buffer).strip()
            if merged_text:
                script.append({'c': 'narrator', 't': merged_text, 'kf': ['nar:block']})

        # 清理空轨道
        cleaned_timeline = {
            c: {k: v for k, v in tracks.items() if v}
            for c, tracks in timeline.items()
            if any(tracks.values())
        }
        return script, cleaned_timeline

    def _render_timeline_text(self, ctx: Dict, script: List[Dict], timeline: Dict[str, Dict[str, List[List]]],
                               compact_tags: bool = False, drop_positions: bool = False) -> str:
        """
        渲染带关键帧行内提示与尾部时间线汇总的文本。
        """
        header_parts = []
        header_map = [('loc', 'loc'), ('time', 'time'), ('weather', 'weather'), ('type', 'type'), ('bgm', 'bgm')]
        for key, label in header_map:
            val = ctx.get(key)
            if val:
                header_parts.append(f"{label}:{val}")
        header = f"[{self.chunk_id}]"
        if header_parts:
            header = f"{header} " + " | ".join(header_parts)

        lines = [header]
        for row in script:
            speaker = row.get('c') or 'narrator'
            text = row.get('t', '')
            tag = ''
            if row.get('kf'):
                if compact_tags:
                    tag = " ^" + ";".join(row['kf'])
                else:
                    tag = " {" + ", ".join(row['kf']) + "}"
            if speaker.lower() == 'narrator':
                lines.append(f"{text}{tag}")
            else:
                lines.append(f"{speaker}: {text}{tag}")

        if timeline:
            lines.append("")  # 空行分隔
            for char, tracks in timeline.items():
                track_parts = []
                emo_track = tracks.get('emo', [])
                act_track = tracks.get('act', [])
                if emo_track:
                    if drop_positions:
                        states = [item if isinstance(item, str) else item[0] for item in emo_track]
                        emo_seq = " -> ".join(states)
                    else:
                        emo_seq = " -> ".join([f"{state}@{line}" for state, line in emo_track])
                    track_parts.append(f"emo {emo_seq}")
                if act_track:
                    if drop_positions:
                        states = [item if isinstance(item, str) else item[0] for item in act_track]
                        act_seq = " -> ".join(states)
                    else:
                        act_seq = " -> ".join([f"{state}@{line}" for state, line in act_track])
                    track_parts.append(f"act {act_seq}")
                if track_parts:
                    lines.append(f"{char} timeline: " + " | ".join(track_parts))

        return "\n".join(lines)

    def to_timeline_dict(self, compact_tags: bool = False, drop_positions: bool = False) -> Dict:
        """
        生成关键帧/时间线格式:
        - script 使用 kf 表示本行关键帧标签
        - timeline 汇总每个角色的 emo/act 变化节点
        - text 同时包含行内提示与尾部时间线摘要
        - compact_tags: 行内标签使用 ^tag 而非 {...}
        - drop_positions: 时间线不带行号，只保留状态序列（使用 -> 连接）
        """
        meta = self.metadata

        # 如果缺少结构化对话，回退到 dense
        if not meta.dialogues:
            dense = self.to_dense_dict()
            dense['timeline'] = {}
            return dense

        script, timeline = self._build_timeline_payload()

        if drop_positions:
            # 仅保留状态序列，去掉行号
            clean_timeline = {}
            for char, tracks in timeline.items():
                cleaned_tracks = {}
                for kind in ['emo', 'act']:
                    seq = tracks.get(kind, [])
                    states = []
                    last = None
                    for item in seq:
                        state = item if isinstance(item, str) else item[0]
                        if state and state != last:
                            states.append(state)
                            last = state
                    if states:
                        cleaned_tracks[kind] = states
                if cleaned_tracks:
                    clean_timeline[char] = cleaned_tracks
            timeline = clean_timeline

        ctx_items = [
            ('loc', meta.location),
            ('time', meta.time_period),
            ('weather', meta.weather),
            ('type', meta.scene_type),
            ('bgm', meta.bgm),
            ('chars', meta.characters),
            ('voices', meta.voice_refs if meta.voice_refs else None),
            ('emo', meta.emotions if meta.emotions else None),
            ('act', meta.actions if meta.actions else None),
        ]
        if meta.state_changes:
            state_emo: Dict[str, List[str]] = {}
            state_act: Dict[str, List[str]] = {}
            for change in meta.state_changes:
                char = change.get('character')
                c_type = change.get('type')
                c_val = change.get('value')
                if char and c_type and c_val:
                    if c_type == 'emotion':
                        state_emo.setdefault(char, []).append(c_val)
                    elif c_type == 'action':
                        state_act.setdefault(char, []).append(c_val)
            # 去除连续重复
            def dedup_seq(seq: List[str]) -> List[str]:
                deduped = []
                last = None
                for v in seq:
                    if v != last:
                        deduped.append(v)
                        last = v
                return deduped
            state_emo = {k: dedup_seq(v) for k, v in state_emo.items() if v}
            state_act = {k: dedup_seq(v) for k, v in state_act.items() if v}
            ctx_items.append(('state_emo', state_emo if state_emo else None))
            ctx_items.append(('state_act', state_act if state_act else None))
        ctx = {k: v for k, v in ctx_items if v not in (None, '', [], {})}
        stats = {
            'tok': meta.token_count,
            'dlg': len(script)
        }

        text = self._render_timeline_text(ctx, script, timeline, compact_tags=compact_tags, drop_positions=drop_positions)

        return {
            'id': self.chunk_id,
            'scene': meta.scene_id,
            'src': meta.source_file,
            'ctx': {k: v for k, v in ctx.items() if v not in (None, '', [], {})},
            'stats': stats,
            'script': script,
            'timeline': timeline,
            'text': text
        }


class VisualNovelChunker:
    """Visual Novel剧本智能分块器"""
    
    # 场景边界标记正则
    SCENE_BOUNDARY_PATTERNS = [
        r'^##+场面転換##+$',
        r'^##+場面転換##+$',
        r'^\[暗転_イン .* 完了待ち\]$',
    ]
    
    # 对话文本模式
    DIALOGUE_PATTERN = r'^\[ノベルテキスト追加\s+(.+?)\s+vo_adv_\d+_\d+_m\d+_\d+@(\w+)\]$'
    DIALOGUE_PATTERN_NO_VOICE = r'^\[ノベルテキスト追加\s+(.+?)\]$'
    DIALOGUE_END = r'^\[ノベルテキスト削除\]★#+$'
    
    # 角色相关（增强版：提取注释）
    # 角色/表情/动作允许日文与下划线，兼容“キャラモーション即時再生”
    CHARACTER_DISPLAY = r'^\s*#*\[キャラ表示\s+([^\s\]]+)\s+'
    CHARACTER_MESSAGE = r'^\s*#*\[メッセージ表示\s+([^\s\]]+)\s+(vo_adv_\d+_\d+_m\d+_\d+@\w+)\s+(.+?)\]$'
    CHARACTER_EMOTION = r'^\s*#*\[キャラ表情変更\s+([^\s\]]+)\s+([^\s\]]+)\](?:#(.+))?$'  # 捕获注释
    CHARACTER_MOTION = r'^\s*#*\[キャラモーション(?:即時)?再生\s+([^\s\]]+)\s+([^\s\]]+)\s*.*?\](?:#(.+))?$'  # 捕获动作注释
    
    # 背景和环境（增强版：提取注释）
    BACKGROUND_PATTERN = r'^\s*#*\[背景表示\s+([^\s\]]+)\s*([^\]]*?)\](?:#(.+))?$'
    BGM_PATTERN = r'^\s*#*\[BGM再生\s+([^\s\]]+)\s+'
    def __init__(self, 
                 overlap_lines: int = 3,
                 target_chunk_size: int = 2000,
                 min_chunk_size: int = 400,
                 max_chunk_size: int = 3000,
                 overlap_tokens: int = 200,
                 fine_grained_mode: bool = False):
        """
        初始化分块器
        
        Args:
            overlap_lines: 重叠的对话行数
            overlap_lines: 对话组之间的重叠行数
            target_chunk_size: 目标chunk大小(tokens)
            min_chunk_size: 最小chunk大小
            max_chunk_size: 最大chunk大小
            overlap_tokens: 重叠token数
            fine_grained_mode: 细粒度模式（产生更多小chunks，配合optimizer使用）
        """
        self.overlap_lines = overlap_lines
        self.fine_grained_mode = fine_grained_mode
        self.overlap_tokens = overlap_tokens
        
        # 细粒度模式下，强制调整默认参数以生成更小的块
        if fine_grained_mode:
            # 如果使用的是默认的大尺寸参数，则调整为细粒度参数
            if target_chunk_size == 2000:
                self.target_chunk_size = 600
            else:
                self.target_chunk_size = target_chunk_size
                
            if max_chunk_size == 3000:
                self.max_chunk_size = 800
            else:
                self.max_chunk_size = max_chunk_size
        else:
            self.target_chunk_size = target_chunk_size
            self.max_chunk_size = max_chunk_size
            
        self.min_chunk_size = min_chunk_size
        
        # 编译正则表达式
        self.scene_patterns = [re.compile(p, re.MULTILINE) for p in self.SCENE_BOUNDARY_PATTERNS]
        self.dialogue_re = re.compile(self.DIALOGUE_PATTERN)
        self.dialogue_no_voice_re = re.compile(self.DIALOGUE_PATTERN_NO_VOICE)
        self.dialogue_end_re = re.compile(self.DIALOGUE_END)
        self.character_display_re = re.compile(self.CHARACTER_DISPLAY)
        self.character_message_re = re.compile(self.CHARACTER_MESSAGE)
        self.character_emotion_re = re.compile(self.CHARACTER_EMOTION)
        self.character_motion_re = re.compile(self.CHARACTER_MOTION)  # 新增
        self.background_re = re.compile(self.BACKGROUND_PATTERN)
        self.bgm_re = re.compile(self.BGM_PATTERN)
        self.se_re = re.compile(r'^\s*#*\[SE再生\s+([^\s\]]+)\s*')
        
        # 加载motion映射表
        self.motion_mappings = {}
        try:
            mapping_file = Path(__file__).parent / 'motion_mappings.json'
            if mapping_file.exists():
                with open(mapping_file, 'r', encoding='utf-8') as f:
                    self.motion_mappings = json.load(f)
                logger.info(f"加载了 {len(self.motion_mappings)} 个motion映射")
        except Exception as e:
            logger.warning(f"无法加载motion映射表: {e}, 将只使用注释")

    def _normalize_text(self, text: str) -> str:
        if not text:
            return ''
        text = text.replace('　', ' ')
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def _normalize_location(self, text: str) -> str:
        text = self._normalize_text(text)
        if not text:
            return ''
        text = re.sub(r'[／/・]+', '_', text)
        text = re.sub(r'[_\\s]+', '_', text)
        return text

    def _normalize_label(self, text: str) -> str:
        return self._normalize_text(text)

    def _normalize_time_keyword(self, raw: str) -> str:
        if not raw:
            return ''
        raw = raw.lower()
        mapping = {
            '朝': 'morning',
            'morning': 'morning',
            '昼': 'afternoon',
            '午後': 'afternoon',
            'afternoon': 'afternoon',
            '夕': 'evening',
            '夕方': 'evening',
            'evening': 'evening',
            '夜': 'night',
            '夜中': 'night',
            '深夜': 'night',
            'night': 'night',
        }
        for key, val in mapping.items():
            if key in raw:
                return val
        return ''
    
    def parse_script(self, file_path: str) -> List[str]:
        """
        解析单个剧本文件
        
        Args:
            file_path: 剧本文件路径
            
        Returns:
            文件行列表
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            logger.info(f"成功读取文件: {file_path}, 共{len(lines)}行")
            return [line.rstrip('\n') for line in lines]
        except Exception as e:
            logger.error(f"读取文件失败 {file_path}: {e}")
            return []
    
    def detect_scene_boundaries(self, lines: List[str]) -> List[Tuple[int, int]]:
        """
        检测场景边界
        
        Args:
            lines: 文件行列表
            
        Returns:
            场景边界列表 [(start_line, end_line), ...]
        """
        boundaries = [0]  # 第一个场景从0开始
        
        for i, line in enumerate(lines):
            # 检查是否是场景转换标记
            for pattern in self.scene_patterns:
                if pattern.match(line):
                    boundaries.append(i)
                    break
        
        # 添加文件结束位置
        boundaries.append(len(lines))
        
        # 构建场景区间
        scenes = []
        for i in range(len(boundaries) - 1):
            start = boundaries[i]
            end = boundaries[i + 1]
            if end - start > 5:  # 过滤太短的"场景"
                scenes.append((start, end))
        
        logger.info(f"检测到 {len(scenes)} 个场景")
        return scenes
    
    def extract_dialogues(self, scene_lines: List[str]) -> List[Dict]:
        """
        提取对话组（支持两种格式）
        
        Args:
            scene_lines: 场景行列表
            
        Returns:
            对话组列表
        """
        dialogue_groups: List[Dict] = []
        current_group: List[Dict] = []
        group_start: Optional[int] = None
        group_end: Optional[int] = None
        
        for i, line in enumerate(scene_lines):
            # 匹配带语音的对话 - [ノベルテキスト追加] (102系列)
            match = self.dialogue_re.match(line)
            if match:
                dialogue_text = match.group(1)
                character = match.group(2)
                if group_start is None:
                    group_start = i
                group_end = i
                current_group.append({
                    'text': dialogue_text,
                    'character': character,
                    'has_voice': True,
                    'raw_line': line,
                    'line_idx': i
                })
                continue
            
            # 匹配不带语音的对话（纯叙述） - [ノベルテキスト追加]
            match = self.dialogue_no_voice_re.match(line)
            if match:
                dialogue_text = match.group(1)
                if group_start is None:
                    group_start = i
                group_end = i
                current_group.append({
                    'text': dialogue_text,
                    'character': 'narrator',
                    'has_voice': False,
                    'raw_line': line,
                    'line_idx': i
                })
                continue
            
            # 匹配角色消息 - [メッセージ表示] (103+系列)
            match = self.character_message_re.match(line)
            if match:
                character = match.group(1)
                dialogue_text = match.group(3)
                if group_start is None:
                    group_start = i
                group_end = i
                current_group.append({
                    'text': dialogue_text,
                    'character': character,
                    'has_voice': True,
                    'raw_line': line,
                    'line_idx': i
                })
                # 103+系列没有明确的对话组结束标记
                # 连续5句同格式视为一组，或遇到其他命令时结束
                if len(current_group) >= 5:
                    dialogue_groups.append({
                        'start': group_start,
                        'end': group_end,
                        'dialogues': current_group
                    })
                    current_group = []
                    group_start = None
                    group_end = None
                continue
            
            # 匹配对话结束标记 - [ノベルテキスト削除] (102系列)
            if self.dialogue_end_re.match(line):
                if current_group:
                    dialogue_groups.append({
                        'start': group_start,
                        'end': group_end,
                        'dialogues': current_group
                    })
                    current_group = []
                    group_start = None
                    group_end = None
                continue
            
            # 遇到其他命令（非对话）时，结束当前对话组
            if line.strip().startswith('[') and current_group:
                # 但不是对话相关命令
                if not any(cmd in line for cmd in ['ノベルテキスト', 'メッセージ表示', '待機']):
                    dialogue_groups.append({
                        'start': group_start,
                        'end': group_end,
                        'dialogues': current_group
                    })
                    current_group = []
                    group_start = None
                    group_end = None
        
        # 处理最后一组对话
        if current_group:
            dialogue_groups.append({
                'start': group_start,
                'end': group_end,
                'dialogues': current_group
            })
        
        return dialogue_groups
    
    # 背景ID映射表（用于注释不在同一行的情况）
    BACKGROUND_MAPPING = {
        'story_bg_image_050': ('背景_市内バス車内', 'morning'),
        'story_bg_image_034': ('寮_ラウンジ', 'night'),
        'story_bg_image_009': ('学校_校舎入口', 'afternoon'),
        'story_bg_image_012': ('学校_音楽堂ライブステージ遠景', 'afternoon'),
        'story_bg_image_007': ('学校_廊下(教室前)', 'afternoon'),
        'story_bg_image_006': ('蓮ノ空女学院（学校）物置', 'afternoon'),
        'story_bg_image_003': ('教室', 'morning'),
        'story_bg_image_058': ('学校_屋上', None),
        'story_bg_image_049': ('金沢駅前', 'afternoon'),
        'story_bg_image_000': ('黒い背景', None),
        'story_bg_image_177': ('バス車内', 'night'),
    }
    
    def extract_structured_dialogues(self, scene_lines: List[str]) -> List[DialogueLine]:
        """
        单遍状态机扫描: 维护每个角色的当前表情/动作状态
        - 遇到表情/动作命令 -> 更新角色状态
        - 遇到对话 -> 记录当前状态为 before；将上一句对话到当前行之间的同角色变化作为 after
        - 不依赖行数窗口，直到下一句对话或场景结束自动收尾
        """
        dialogues: List[DialogueLine] = []
        current_state: Dict[str, Dict[str, Optional[str]]] = {}
        last_dialogue_idx_by_char: Dict[str, int] = {}
        last_dialogue_line_by_char: Dict[str, int] = {}
        pending_changes: Dict[str, List[Dict]] = {}
        voice_to_char: Dict[str, str] = dict(getattr(self, '_voice_to_char', {}))

        # 预扫描：建立 voice_id -> 角色名映射（本场景内）
        for line in scene_lines:
            disp_match = self.character_display_re.match(line)
            if disp_match:
                disp_char = disp_match.group(1)
                em_tag = re.search(r'emotion_([A-Za-z0-9_]+)', line)
                if em_tag:
                    voice_to_char[em_tag.group(1)] = disp_char
            msg_match = self.character_message_re.match(line)
            if msg_match:
                voice_ref = msg_match.group(2)
                if voice_ref and '@' in voice_ref:
                    voice_id = voice_ref.split('@', 1)[1]
                    voice_to_char[voice_id] = msg_match.group(1)
        
        def ensure_state(char: str):
            if char not in current_state:
                current_state[char] = {
                    'emotion': None,
                    'action': None,
                    'action_desc': ''
                }
            if char not in pending_changes:
                pending_changes[char] = []
        
        for idx, line in enumerate(scene_lines):
            # 1) 表情事件
            em_match = self.character_emotion_re.match(line)
            if em_match:
                char = em_match.group(1)
                emotion_id = em_match.group(2)
                emotion_comment = em_match.group(3) if len(em_match.groups()) >= 3 and em_match.group(3) else None
                ensure_state(char)
                emotion_val = emotion_comment if emotion_comment else emotion_id
                current_state[char]['emotion'] = emotion_val
                pending_changes[char].append({'type': 'emotion', 'value': emotion_val, 'line': idx})
                continue
            
            # 2) 动作事件
            motion_match = self.character_motion_re.match(line)
            if motion_match:
                char = motion_match.group(1)
                action_id = motion_match.group(2)
                action_comment = motion_match.group(3) if len(motion_match.groups()) >= 3 and motion_match.group(3) else None
                ensure_state(char)
                current_state[char]['action'] = action_id
                if action_comment:
                    current_state[char]['action_desc'] = action_comment
                elif action_id in self.motion_mappings:
                    current_state[char]['action_desc'] = self.motion_mappings[action_id]
                else:
                    current_state[char]['action_desc'] = ''
                pending_changes[char].append({
                    'type': 'action',
                    'value': current_state[char]['action_desc'] or action_id,
                    'line': idx
                })
                continue
            
            # 3) 对话匹配
            dialogue_match = None
            character = None
            text = None
            voice_ref = None
            
            match_msg = self.character_message_re.match(line)
            if match_msg:
                dialogue_match = match_msg
                character = match_msg.group(1)
                voice_ref = match_msg.group(2)
                text = match_msg.group(3)
                # 记录 voice_id -> character 映射
                if voice_ref and '@' in voice_ref:
                    voice_id = voice_ref.split('@', 1)[1]
                    voice_to_char[voice_id] = character
            
            if not dialogue_match:
                match_dlg = self.dialogue_re.match(line)
                if match_dlg:
                    dialogue_match = match_dlg
                    text = match_dlg.group(1)
                    voice_id = match_dlg.group(2)
                    character = voice_to_char.get(voice_id, voice_id)
                    voice_match = re.search(r'vo_adv_\d+_\d+_m\d+_\d+@\w+', line)
                    if voice_match:
                        voice_ref = voice_match.group(0)
            
            if not dialogue_match:
                match_narr = self.dialogue_no_voice_re.match(line)
                if match_narr:
                    dialogue_match = match_narr
                    text = match_narr.group(1)
                    character = 'narrator'
                    voice_ref = None
            
            if not dialogue_match:
                continue  # 非对话、非表情/动作，跳过
            
            # 清理文本中的嵌入命令/格式符
            text = re.sub(r'\[キャラモーション(?:即時)?再生[^\]]+\](?:#[^\]]+)?', '', text)
            text = re.sub(r'\[キャラ表情変更[^\]]+\](?:#[^\]]+)?', '', text)
            text = re.sub(r'\[(?:BGM|SE|背景)[^\]]+\]', '', text)
            text = text.replace('[r]', '\n').replace('[Space]', ' ').strip()
            
            ensure_state(character)
            
            # 取当前状态作为 before
            before_emotion = current_state[character].get('emotion')
            before_action = current_state[character].get('action')
            before_action_desc = current_state[character].get('action_desc', '')
            
            # 如果存在该角色上一句对话，将当前状态写入其 after
            if character in last_dialogue_idx_by_char:
                last_dialogue = dialogues[last_dialogue_idx_by_char[character]]
                last_line = last_dialogue_line_by_char.get(character)
                if last_line is not None:
                    gap = idx - last_line - 1
                    if gap > 200:
                        logger.debug(
                            f"对话后非对话区段超过200行: 角色 {character}, 行索引 {last_line}->{idx}"
                        )
                last_dialogue.emotion_after = before_emotion
                if before_action_desc:
                    last_dialogue.action_desc = before_action_desc
                elif before_action:
                    last_dialogue.action = before_action
                # 记录该角色对话间的状态变化序列
                if pending_changes.get(character):
                    last_dialogue.state_changes = pending_changes[character].copy()
                pending_changes[character] = []
            
            # 创建当前对话
            dialogue = DialogueLine(
                character=character,
                text=text,
                voice_ref=voice_ref,
                emotion_before=before_emotion,
                emotion_after=None,
                action=before_action,
                action_desc=before_action_desc,
                state_changes=[]
            )
            dialogues.append(dialogue)
            last_dialogue_idx_by_char[character] = len(dialogues) - 1
            last_dialogue_line_by_char[character] = idx
            pending_changes[character] = []
        
        # 场景结束时，为每个角色补充最后一句对话的 after（用当前状态）
        for char, last_idx in last_dialogue_idx_by_char.items():
            last_dialogue = dialogues[last_idx]
            state = current_state.get(char, {})
            if state:
                last_dialogue.emotion_after = state.get('emotion', last_dialogue.emotion_after)
                if state.get('action_desc'):
                    last_dialogue.action_desc = state.get('action_desc')
                elif state.get('action'):
                    last_dialogue.action = state.get('action')
            if pending_changes.get(char):
                last_dialogue.state_changes = pending_changes[char].copy()
        
        return dialogues
    
    def extract_metadata(self, scene_lines: List[str]) -> Dict:
        """
        提取场景元数据（优先级处理版本）
        
        信息来源优先级：
        1. 高优先级：背景注释 #后的明确信息
        2. 中优先级：BGM/SE推断的信息
        3. 低优先级：从ID模式推断的信息
        
        高优先级信息不会被低优先级信息覆盖
        
        Args:
            scene_lines: 场景行列表
            
        Returns:
            元数据字典
        """
        metadata = {
            'characters': set(),
            'location': '',
            'bgm': '',
            'emotions': {},
            'actions': {},
            'state_changes': [],
            'voice_refs': [],
            'time_period': '',
            'weather': '',
            'scene_type': '',
            # 内部使用：记录信息来源优先级
            '_time_source': 0,        # 0=无 1=推断 2=BGM 3=注释
            '_scene_type_source': 0,  # 0=无 1=推断 2=注释
            '_location_source': 0     # 0=无 1=ID 2=注释
        }
        
        # 第一遍：收集基础信息
        for line in scene_lines:
            norm_line = line.lstrip('#').strip()
            # 提取角色
            match = self.character_display_re.match(line)
            if match:
                metadata['characters'].add(self._normalize_label(match.group(1)))
            
            match = self.character_message_re.match(line)
            if match:
                metadata['characters'].add(self._normalize_label(match.group(1)))
            
            # 提取角色表情（优先使用注释中的人类可读名称）
            match = self.character_emotion_re.match(line)
            if match:
                character = self._normalize_label(match.group(1))
                emotion_id = self._normalize_label(match.group(2))
                emotion_comment = match.group(3) if len(match.groups()) >= 3 and match.group(3) else None
                
                # 优先使用注释,否则使用ID
                emotion = self._normalize_label(emotion_comment) if emotion_comment else emotion_id
                metadata['emotions'][character] = emotion
                metadata['state_changes'].append({
                    'type': 'emotion',
                    'character': character,
                    'value': emotion
                })

            # 提取角色动作（用于元数据记录）
            match = self.character_motion_re.match(line)
            if match:
                character = self._normalize_label(match.group(1))
                action_id = self._normalize_label(match.group(2))
                action_comment = match.group(3) if len(match.groups()) >= 3 and match.group(3) else None
                if action_comment:
                    action_desc = self._normalize_label(action_comment)
                elif action_id in self.motion_mappings:
                    action_desc = self.motion_mappings[action_id]
                else:
                    action_desc = ''
                metadata['actions'][character] = action_desc or action_id
                metadata['state_changes'].append({
                    'type': 'action',
                    'character': character,
                    'value': action_desc or action_id
                })
            
            # 提取BGM
            match = self.bgm_re.match(line)
            if match and not metadata['bgm']:
                metadata['bgm'] = self._normalize_label(match.group(1))
            
            # 提取语音引用
            if 'vo_adv_' in line:
                voice_matches = re.findall(r'vo_adv_\d+_\d+_m\d+_\d+@\w+', line)
                metadata['voice_refs'].extend(voice_matches)
            
            # 提取天气（从SE，中等优先级）
            if self.se_re.match(line) and not metadata['weather']:
                lower_line = norm_line.lower()
                if 'rain' in lower_line or '雨' in norm_line:
                    metadata['weather'] = 'rain'
                elif 'thunder' in lower_line or '雷' in norm_line:
                    metadata['weather'] = 'storm'
                elif 'wind' in lower_line or '風' in norm_line:
                    metadata['weather'] = 'windy'
                elif 'snow' in lower_line or '雪' in norm_line:
                    metadata['weather'] = 'snow'
            
            # 提取背景（含注释解析 + 映射表fallback）
            match = self.background_re.match(line)
            if match:
                bg_id = self._normalize_label(match.group(1))
                bg_comment = match.group(3) if len(match.groups()) >= 3 and match.group(3) else None
                
                # Location: ID作为初始值（低优先级）
                if metadata['_location_source'] == 0:
                    metadata['location'] = bg_id
                    metadata['_location_source'] = 1
                
                # 尝试从注释解析（高优先级）
                if bg_comment:
                    bg_comment = self._normalize_text(bg_comment)
                    time_keywords = ['朝', '昼', '夕', '夜', '午前', '午後', 
                                   'morning', 'afternoon', 'evening', 'night']
                    
                    # 智能解析
                    extracted_time = None
                    clean_comment = bg_comment
                    
                    # 1. 提取括号内的时间
                    paren_match = re.search(r'[（(]([朝昼夕夜午前午後]+)[）)]', clean_comment)
                    if paren_match:
                        extracted_time = paren_match.group(1)
                        clean_comment = re.sub(r'[（(][朝昼夕夜午前午後]+[）)]', '', clean_comment)
                    
                    # 2. 统一分隔符
                    clean_comment = clean_comment.replace('　', ' ')
                    clean_comment = re.sub(r'[／/・,、]+', ' ', clean_comment)
                    
                    # 3. 分割
                    if '_' in clean_comment:
                        parts = [p.strip() for p in clean_comment.split('_') if p.strip()]
                    else:
                        parts = [p.strip() for p in clean_comment.split() if p.strip()]
                    
                    # 4. 末尾时间提取
                    if len(parts) == 1 and not extracted_time:
                        for kw in time_keywords:
                            if parts[0].endswith(kw):
                                extracted_time = kw
                                parts[0] = parts[0][:-len(kw)]
                                break
                    
                    # 5. 分离地点和时间
                    location_parts = []
                    for part in parts:
                        if part in time_keywords and not extracted_time:
                            extracted_time = part
                        elif part:
                            location_parts.append(part)
                    
                    # 设置时间
                    if extracted_time and metadata['_time_source'] < 3:
                        normalized_time = self._normalize_time_keyword(extracted_time)
                        if normalized_time:
                            metadata['time_period'] = normalized_time
                            metadata['_time_source'] = 3
                    
                    # 更新location
                    if location_parts and metadata['_location_source'] < 2:
                        metadata['location'] = self._normalize_location('_'.join(location_parts))
                        metadata['_location_source'] = 2
                    
                    # 从注释推断场景类型（高优先级）
                    comment_lower = bg_comment.lower()
                    if metadata['_scene_type_source'] < 2:
                        if '教室' in bg_comment or 'classroom' in comment_lower:
                            metadata['scene_type'] = 'classroom'
                            metadata['_scene_type_source'] = 2
                        elif '寮' in bg_comment or 'ラウンジ' in bg_comment or '部屋' in bg_comment:
                            metadata['scene_type'] = 'indoor'
                            metadata['_scene_type_source'] = 2
                        elif '廊下' in bg_comment or '階段' in bg_comment:
                            metadata['scene_type'] = 'corridor'
                            metadata['_scene_type_source'] = 2
                        elif 'ステージ' in bg_comment or 'stage' in comment_lower:
                            metadata['scene_type'] = 'stage'
                            metadata['_scene_type_source'] = 2
                        elif '屋外' in bg_comment or '正門' in bg_comment or '校庭' in bg_comment or '屋上' in bg_comment:
                            metadata['scene_type'] = 'outdoor'
                            metadata['_scene_type_source'] = 2
                
                # Fallback: 使用映射表（当注释在前一行或不存在时）
                elif bg_id in self.BACKGROUND_MAPPING:
                    mapped_loc, mapped_time = self.BACKGROUND_MAPPING[bg_id]
                    
                    # 更新location（映射表优先级高于ID）
                    if metadata['_location_source'] < 2:
                        metadata['location'] = mapped_loc
                        metadata['_location_source'] = 2
                    
                    # 更新time（如果映射表有时间信息）
                    if mapped_time and metadata['_time_source'] < 3:
                        metadata['time_period'] = mapped_time
                        metadata['_time_source'] = 3
        
        # 第二遍：应用中/低优先级推断（仅在高优先级信息不存在时）
        
        # 从BGM推断时间（中优先级，source=2）
        if metadata['_time_source'] < 2 and metadata['bgm']:
            bgm_lower = metadata['bgm'].lower()
            if 'morning' in bgm_lower or '朝' in bgm_lower:
                metadata['time_period'] = 'morning'
                metadata['_time_source'] = 2
            elif 'night' in bgm_lower or 'evening' in bgm_lower or '夜' in bgm_lower:
                metadata['time_period'] = 'night'
                metadata['_time_source'] = 2
            elif 'afternoon' in bgm_lower or '昼' in bgm_lower:
                metadata['time_period'] = 'afternoon'
                metadata['_time_source'] = 2
        
        # 从location ID推断场景类型（低优先级，source=1）
        if metadata['_scene_type_source'] < 1 and metadata['location']:
            loc_lower = metadata['location'].lower()
            if 'classroom' in loc_lower or '教室' in loc_lower:
                metadata['scene_type'] = 'classroom'
                metadata['_scene_type_source'] = 1
            elif 'outdoor' in loc_lower or '屋外' in loc_lower or 'gate' in loc_lower or '正門' in loc_lower:
                metadata['scene_type'] = 'outdoor'
                metadata['_scene_type_source'] = 1
            elif 'room' in loc_lower or '部室' in loc_lower or '寮' in loc_lower:
                metadata['scene_type'] = 'indoor'
                metadata['_scene_type_source'] = 1
            elif 'stage' in loc_lower or 'ステージ' in loc_lower:
                metadata['scene_type'] = 'stage'
                metadata['_scene_type_source'] = 1
        
        # 清理内部优先级字段
        del metadata['_time_source']
        del metadata['_scene_type_source']
        del metadata['_location_source']
        
        # 新增: 提取结构化对话序列
        structured_dialogues = self.extract_structured_dialogues(scene_lines)
        
        # 填充结构化对话字段
        metadata['dialogues'] = [asdict(d) for d in structured_dialogues]
        
        # 向后兼容: 从结构化对话更新汇总字段
        if structured_dialogues:
            # 更新角色列表(合并原有的和对话中的)
            dialogue_characters = set(d.character for d in structured_dialogues if d.character != 'narrator')
            metadata['characters'] = metadata['characters'].union(dialogue_characters)
            
            # 更新表情字典(优先使用对话后的表情,其次是对话前的)
            for d in structured_dialogues:
                if d.character != 'narrator':
                    if d.emotion_after:
                        metadata['emotions'][self._normalize_label(d.character)] = self._normalize_label(d.emotion_after)
                    elif d.emotion_before and d.character not in metadata['emotions']:
                        metadata['emotions'][self._normalize_label(d.character)] = self._normalize_label(d.emotion_before)
            
            # 更新voice_refs
            dialogue_voices = [d.voice_ref for d in structured_dialogues if d.voice_ref]
            # 去重同时保持顺序
            seen = set()
            unique_voices = []
            for v in dialogue_voices:
                if v not in seen:
                    seen.add(v)
                    unique_voices.append(v)
            metadata['voice_refs'] = unique_voices
        
        # 统一规范化字段
        metadata['location'] = self._normalize_location(metadata['location'])
        metadata['bgm'] = self._normalize_label(metadata['bgm'])
        metadata['time_period'] = self._normalize_label(metadata['time_period'])
        metadata['weather'] = self._normalize_label(metadata['weather'])
        metadata['scene_type'] = self._normalize_label(metadata['scene_type'])

        # 规范化情绪/动作字典
        metadata['emotions'] = {
            self._normalize_label(k): self._normalize_label(v)
            for k, v in metadata['emotions'].items()
            if self._normalize_label(k) and self._normalize_label(v)
        }
        metadata['actions'] = {
            self._normalize_label(k): self._normalize_label(v)
            for k, v in metadata['actions'].items()
            if self._normalize_label(k) and self._normalize_label(v)
        }

        # 规范化状态变化列表
        normalized_changes = []
        for item in metadata['state_changes']:
            character = self._normalize_label(item.get('character', ''))
            value = self._normalize_label(item.get('value', ''))
            if not character or not value:
                continue
            normalized_changes.append({
                'type': item.get('type', ''),
                'character': character,
                'value': value
            })
        metadata['state_changes'] = normalized_changes

        # 转换set为稳定的list（排序保证嵌入一致性）
        metadata['characters'] = sorted(self._normalize_label(c) for c in metadata['characters'] if self._normalize_label(c))
        
        return metadata
    
    def count_tokens(self, text: str) -> int:
        """
        简单的token计数（日文按字符计数，英文按空格分词）
        
        Args:
            text: 文本内容
            
        Returns:
            token数量估算
        """
        # 简化的token计数：日文每个字符约1 token，英文单词约1 token
        japanese_chars = len(re.findall(r'[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]', text))
        english_words = len(re.findall(r'[a-zA-Z]+', text))
        return japanese_chars + english_words
    
    def compile_scene_text(self, scene_lines: List[str]) -> str:
        """
        编译场景文本（基于结构化对话生成更丰富的文本）
        
        Args:
            scene_lines: 场景行列表
            
        Returns:
            编译后的文本
        """
        # 优先使用结构化对话
        structured_dialogues = self.extract_structured_dialogues(scene_lines)
        
        if structured_dialogues:
            content_lines = []
            for dlg in structured_dialogues:
                # 基础对话
                if dlg.character == 'narrator':
                    line = dlg.text
                else:
                    line = f"{dlg.character}: {dlg.text}"
                
                # 添加表情和动作信息
                annotations = []
                if dlg.emotion_before and dlg.emotion_after and dlg.emotion_before != dlg.emotion_after:
                    annotations.append(f"表情:{dlg.emotion_before}, →{dlg.emotion_after}")
                elif dlg.emotion_after:
                    annotations.append(f"表情:{dlg.emotion_after}")
                elif dlg.emotion_before:
                    annotations.append(f"表情:{dlg.emotion_before}")
                
                if dlg.action_desc:
                    annotations.append(f"动作:{dlg.action_desc}")
                
                if annotations:
                    line = f"{line} [{', '.join(annotations)}]"
                
                content_lines.append(line)
            
            return '\n'.join(content_lines)
        
        # Fallback: 使用旧方法
        return self._compile_scene_text_legacy(scene_lines)
    
    def _compile_scene_text_legacy(self, scene_lines: List[str]) -> str:
        """
        旧版编译场景文本逻辑(Fallback)
        
        Args:
            scene_lines: 场景行列表
            
        Returns:
            编译后的文本
        """
        content_lines = []
        
        for line in scene_lines:
            # 提取对话文本 - [ノベルテキスト追加]
            match = self.dialogue_re.match(line)
            if match:
                content_lines.append(f"{match.group(2)}: {match.group(1)}")
                continue
            
            match = self.dialogue_no_voice_re.match(line)
            if match:
                content_lines.append(match.group(1))
                continue
            
            # 提取角色消息 - [メッセージ表示]
            match = self.character_message_re.match(line)
            if match:
                content_lines.append(f"{match.group(1)}: {match.group(3)}")
                continue
        
        # Fallback: 如果完全没有对话内容，提取场景描述
        if not content_lines:
            # 提取元数据作为场景描述
            metadata = self.extract_metadata(scene_lines)
            scene_desc_parts = []
            
            # 场景位置
            if metadata['location']:
                scene_desc_parts.append(f"[场景: {metadata['location']}]")
            
            # 登场角色
            if metadata['characters']:
                chars = ', '.join(metadata['characters'][:5])  # 最多5个避免太长
                scene_desc_parts.append(f"[登场: {chars}]")
            
            # BGM信息（可能暗示场景氛围）
            if metadata['bgm']:
                scene_desc_parts.append(f"[音乐: {metadata['bgm']}]")
            
            # 提取场景注释（如 #通常立ち, #シリアス）
            # 但排除命令行（以[开头）
            for line in scene_lines:
                stripped = line.strip()
                # 只提取#开头的注释，不要[开头的命令
                if stripped.startswith('#') and not stripped.startswith('####'):
                    # 排除背景命令的注释部分（已经在metadata中处理）
                    if not stripped.startswith('#['):
                        desc = stripped.lstrip('#').strip()
                        # 过滤太长的（可能是分隔线）和空行
                        if desc and len(desc) < 50 and not desc.startswith('カメラ'):
                            scene_desc_parts.append(f"[{desc}]")
                            if len(scene_desc_parts) >= 8:  # 避免太多注释
                                break
            
            if scene_desc_parts:
                content_lines.extend(scene_desc_parts)
            else:
                # 如果实在没有任何描述，标记为视觉场景
                content_lines.append("[视觉场景]")
        
        return '\n'.join(content_lines)
    
    def count_all_dialogues(self, scene_lines: List[str]) -> int:
        """
        统计所有对话数量（包括[ノベルテキスト追加]和[メッセージ表示]）
        
        Args:
            scene_lines: 场景行列表
            
        Returns:
            总对话数
        """
        count = 0
        for line in scene_lines:
            if self.dialogue_re.match(line) or \
               self.dialogue_no_voice_re.match(line) or \
               self.character_message_re.match(line):
                count += 1
        return count
    
    def create_chunk(self, 
                     chunk_id: str,
                     scene_id: str,
                     source_file: str,
                     scene_lines: List[str],
                     parent_id: Optional[str] = None) -> Chunk:
        """
        创建单个chunk
        
        Args:
            chunk_id: chunk ID
            scene_id: 场景ID
            source_file: 源文件名
            scene_lines: 场景行列表
            parent_id: 父chunk ID
            
        Returns:
            Chunk对象
        """
        # 编译文本内容
        content = self.compile_scene_text(scene_lines)
        
        # 提取元数据
        meta_dict = self.extract_metadata(scene_lines)
        
        # 统计所有对话
        dialogue_count = self.count_all_dialogues(scene_lines)
        
        # 计算token数
        token_count = self.count_tokens(content)
        
        # 创建元数据对象
        metadata = ChunkMetadata(
            chunk_id=chunk_id,
            scene_id=scene_id,
            source_file=source_file,
            characters=meta_dict['characters'],
            location=meta_dict['location'],
            bgm=meta_dict['bgm'],
            emotions=meta_dict['emotions'],
            actions=meta_dict.get('actions', {}),
            state_changes=meta_dict.get('state_changes', []),
            voice_refs=meta_dict['voice_refs'],
            chunk_type='scene',
            token_count=token_count,
            dialogue_count=dialogue_count,
            time_period=meta_dict.get('time_period', ''),
            weather=meta_dict.get('weather', ''),
            scene_type=meta_dict.get('scene_type', ''),
            dialogues=meta_dict.get('dialogues', [])
        )
        

        
        return Chunk(
            chunk_id=chunk_id,
            content=content,
            metadata=metadata,
            parent_chunk_id=parent_id
        )
    
    def split_by_dialogues(self, scene_id: str, source_file: str, scene_lines: List[str]) -> List[Chunk]:
        """
        当场景过长时，按对话组分块
        
        Args:
            scene_id: 场景ID
            source_file: 源文件名
            scene_lines: 场景行列表
            
        Returns:
            chunk列表
        """
        dialogue_groups = self.extract_dialogues(scene_lines)
        chunks = []
        current_chunk_lines = []
        current_tokens = 0
        sub_chunk_idx = 0
        recent_groups: List[Dict] = []

        def select_overlap_groups(groups: List[Dict]) -> List[Dict]:
            """
            根据配置选择需要保留的重叠对话组。
            
            优先保证 overlap_lines 的行数；如果配置了 overlap_tokens，则继续向前累加直到达到该 token 数。
            """
            if not groups:
                return []
            
            selected: List[List[Dict]] = []
            accumulated_tokens = 0
            
            for g in reversed(groups):
                group_text = '\n'.join([d['text'] for d in g['dialogues']])
                group_tokens = self.count_tokens(group_text)
                
                need_more_lines = len(selected) < self.overlap_lines
                need_more_tokens = self.overlap_tokens and accumulated_tokens < self.overlap_tokens
                
                if need_more_lines or need_more_tokens:
                    selected.insert(0, g)  # 保持原顺序
                    accumulated_tokens += group_tokens
                else:
                    break
            
            return selected
        
        for idx, group in enumerate(dialogue_groups):
            # 计算这组对话的token数
            group_text = '\n'.join([d['text'] for d in group['dialogues']])
            group_tokens = self.count_tokens(group_text)
            prev_end = dialogue_groups[idx - 1]['end'] if idx > 0 else None
            group_start = 0 if prev_end is None else prev_end + 1
            next_start = dialogue_groups[idx + 1]['start'] if idx + 1 < len(dialogue_groups) else len(scene_lines)
            group_lines = scene_lines[group_start:next_start]
            
            # 如果加上这组对话会超过最大限制，先保存当前chunk
            if current_tokens + group_tokens > self.max_chunk_size and current_chunk_lines:
                chunk_id = f"{scene_id}_sub_{sub_chunk_idx}"
                chunk = self.create_chunk(chunk_id, scene_id, source_file, current_chunk_lines, scene_id)
                chunks.append(chunk)
                
                # 重置，保留overlap
                overlap_groups = select_overlap_groups(recent_groups)
                current_chunk_lines = [line for g in overlap_groups for line in g['lines']]
                current_tokens = self.count_tokens('\n'.join([d['text'] for g in overlap_groups for d in g['dialogues']]))
                recent_groups = overlap_groups.copy()
                sub_chunk_idx += 1
            
            # 添加当前对话组
            current_chunk_lines.extend(group_lines)
            current_tokens += group_tokens
            recent_groups.append({
                'dialogues': group['dialogues'],
                'lines': group_lines
            })
        
        # 处理最后一个chunk
        if current_chunk_lines:
            chunk_id = f"{scene_id}_sub_{sub_chunk_idx}"
            chunk = self.create_chunk(chunk_id, scene_id, source_file, current_chunk_lines, scene_id)
            chunks.append(chunk)
        
        return chunks
    
    def create_chunks(self, scenes: List[Tuple[int, int]], lines: List[str], source_file: str) -> List[Chunk]:
        """
        生成智能分块
        
        Args:
            scenes: 场景边界列表
            lines: 文件行列表
            source_file: 源文件名
            
        Returns:
            chunk列表
        """
        chunks = []
        base_filename = Path(source_file).stem

        
        for scene_idx, (start, end) in enumerate(scenes):
            scene_id = f"{base_filename}_scene_{scene_idx:03d}"
            scene_lines = lines[start:end]
            
            # 编译场景文本并计算token数
            scene_text = self.compile_scene_text(scene_lines)
            scene_tokens = self.count_tokens(scene_text)
            
            # 细粒度模式：更激进的分割阈值
            split_threshold = self.target_chunk_size if self.fine_grained_mode else self.max_chunk_size
            
            if scene_tokens <= split_threshold:
                # 场景大小合适，作为单个chunk
                chunk = self.create_chunk(scene_id, scene_id, source_file, scene_lines)
                chunks.append(chunk)
            else:
                # 场景过长，按对话组分块
                logger.info(f"场景 {scene_id} 过长 ({scene_tokens} tokens)，按对话组分块")
                sub_chunks = self.split_by_dialogues(scene_id, source_file, scene_lines)
                chunks.extend(sub_chunks)
        
        logger.info(f"文件 {source_file} 生成 {len(chunks)} 个chunks (细粒度模式: {self.fine_grained_mode})")
        return chunks
    
    def process_file(self, file_path: str) -> List[Chunk]:
        """
        处理单个文件
        
        Args:
            file_path: 文件路径
            
        Returns:
            chunk列表
        """
        logger.info(f"开始处理文件: {file_path}")
        
        # 解析文件
        lines = self.parse_script(file_path)
        if not lines:
            return []

        # 预构建全文件 voice_id -> 角色名 映射
        voice_to_char: Dict[str, str] = {}
        for line in lines:
            disp_match = self.character_display_re.match(line)
            if disp_match:
                disp_char = disp_match.group(1)
                em_tag = re.search(r'emotion_([A-Za-z0-9_]+)', line)
                if em_tag:
                    voice_to_char[em_tag.group(1)] = disp_char
            msg_match = self.character_message_re.match(line)
            if msg_match:
                voice_ref = msg_match.group(2)
                if voice_ref and '@' in voice_ref:
                    voice_id = voice_ref.split('@', 1)[1]
                    voice_to_char[voice_id] = msg_match.group(1)
        self._voice_to_char = voice_to_char
        
        # 检测场景边界
        scenes = self.detect_scene_boundaries(lines)
        
        # 生成chunks
        chunks = self.create_chunks(scenes, lines, Path(file_path).name)
        
        return chunks
    
    def process_directory(self, directory: str, output_file: str, export_format: str = "standard"):
        """
        批量处理目录下所有txt文件
        
        Args:
            directory: 输入目录
            output_file: 输出JSON文件路径
            export_format: 输出格式 (standard|optimized|dense|timeline)
        """
        txt_files = list(Path(directory).glob('*.txt'))
        
        # 按故事序号排序 (完整的文件名数字顺序)
        def get_story_number(path: Path) -> int:
            """提取文件名中的故事编号用于排序"""
            try:
                # 提取 story_main_ 后的完整数字部分
                name = path.stem  # story_main_10250101
                if 'story_main_' in name:
                    story_num = name.split('_')[2]  # "10250101" (完整数字)
                    return int(story_num)
                return 999999999  # 其他文件排在最后
            except:
                return 999999999
        
        txt_files.sort(key=get_story_number)
        
        logger.info(f"发现 {len(txt_files)} 个txt文件")
        if txt_files:
            first_story = get_story_number(txt_files[0])
            last_story = get_story_number(txt_files[-1])
            logger.info(f"故事顺序: {first_story}xxx -> {last_story}xxx")
        
        all_chunks = []
        
        for file_path in txt_files:
            chunks = self.process_file(str(file_path))
            all_chunks.extend(chunks)
        
        logger.info(f"总共生成 {len(all_chunks)} 个chunks")
        
        # 导出为JSON
        self.export_to_json(all_chunks, output_file, export_format=export_format)
    
    def export_to_json(self, chunks: List[Chunk], output_file: str, export_format: str = "standard"):
        """
        导出chunks到JSON文件（Dify兼容格式）
        
        Args:
            chunks: chunk列表
            output_file: 输出文件路径
            export_format: 输出格式 (standard|optimized|dense|timeline)
        """
        if export_format == "timeline":
            output_data = [chunk.to_timeline_dict() for chunk in chunks]
            logger.info("使用 timeline 关键帧格式导出 (行内关键帧 + 角色时间线)")
        elif export_format == "timeline_compact":
            output_data = [chunk.to_timeline_dict(compact_tags=True) for chunk in chunks]
            logger.info("使用 timeline_compact 关键帧格式导出 (无括号短标签)")
        elif export_format == "timeline_flow":
            output_data = [chunk.to_timeline_dict(compact_tags=True, drop_positions=True) for chunk in chunks]
            logger.info("使用 timeline_flow 关键帧格式导出 (短标签 + 去行号，使用箭头序列)")
        elif export_format == "dense":
            output_data = [chunk.to_dense_dict() for chunk in chunks]
            logger.info("使用 dense 高密度格式导出 (精简上下文键名, 单份文本表示)")
        elif export_format == "optimized":
            # 使用优化格式
            output_data = [chunk.to_optimized_dict() for chunk in chunks]
            logger.info(f"使用优化格式导出 (移除冗余字段,压缩dialogues)")
        else:
            # 使用标准格式
            output_data = []
            for chunk in chunks:
                chunk_dict = {
                    'chunk_id': chunk.chunk_id,
                    'content': chunk.content,
                    'metadata': asdict(chunk.metadata),
                    'parent_chunk_id': chunk.parent_chunk_id,
                    'overlap_prev': chunk.overlap_prev
                }
                output_data.append(chunk_dict)
            logger.info(f"使用标准格式导出")
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        
        # 输出文件大小
        file_size = Path(output_file).stat().st_size
        logger.info(f"成功导出到: {output_file}")
        logger.info(f"文件大小: {file_size / 1024:.1f} KB")
        
        # 输出统计信息
        self.print_statistics(chunks)
    
    def print_statistics(self, chunks: List[Chunk]):
        """打印统计信息"""
        total_tokens = sum(c.metadata.token_count for c in chunks)
        avg_tokens = total_tokens / len(chunks) if chunks else 0
        
        token_counts = [c.metadata.token_count for c in chunks]
        min_tokens = min(token_counts) if token_counts else 0
        max_tokens = max(token_counts) if token_counts else 0
        
        logger.info("=" * 50)
        logger.info("分块统计信息:")
        logger.info(f"  总chunks数: {len(chunks)}")
        logger.info(f"  总tokens数: {total_tokens}")
        logger.info(f"  平均tokens: {avg_tokens:.1f}")
        logger.info(f"  最小tokens: {min_tokens}")
        logger.info(f"  最大tokens: {max_tokens}")
        logger.info("=" * 50)


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='Visual Novel剧本智能分块工具')
    parser.add_argument('input_dir', help='输入目录（包含txt文件）')
    parser.add_argument('-o', '--output', default='chunks_output.json', help='输出JSON文件路径')
    parser.add_argument('--target-size', type=int, default=2000, help='目标chunk大小（tokens）')
    parser.add_argument('--min-size', type=int, default=400, help='最小chunk大小（tokens）')
    parser.add_argument('--max-size', type=int, default=3000, help='最大chunk大小（tokens）')
    parser.add_argument('--overlap', type=int, default=200, help='重叠token数')
    parser.add_argument('--fine-grained', action='store_true', 
                       help='细粒度模式（配合embedding optimizer使用，产生更多小chunks）')
    parser.add_argument('--optimized', action='store_true',
                       help='使用优化格式导出(压缩,移除冗余字段,适合embedding workflow) -- 已被 --format 取代，但保留兼容')
    parser.add_argument('--format', choices=['standard', 'optimized', 'dense', 'timeline', 'timeline_compact', 'timeline_flow'], default='standard',
                       help='输出格式：standard(默认) | optimized(压缩字段) | dense(高密度结构化) | timeline(关键帧时间线) | timeline_compact(关键帧短标签) | timeline_flow(箭头序列，无行号)')
    parser.add_argument('--dense', action='store_true',
                       help='快捷开关，等价于 --format dense')
    parser.add_argument('--timeline', action='store_true',
                       help='快捷开关，等价于 --format timeline')
    parser.add_argument('--timeline-compact', dest='timeline_compact', action='store_true',
                       help='快捷开关，等价于 --format timeline_compact')
    parser.add_argument('--timeline-flow', dest='timeline_flow', action='store_true',
                       help='快捷开关，等价于 --format timeline_flow')
    
    args = parser.parse_args()
    
    # 创建分块器
    chunker = VisualNovelChunker(
        target_chunk_size=args.target_size,
        min_chunk_size=args.min_size,
        max_chunk_size=args.max_size,
        overlap_tokens=args.overlap,
        fine_grained_mode=args.fine_grained
    )
    
    # 处理目录
    export_format = args.format
    if getattr(args, 'timeline_flow', False):
        export_format = 'timeline_flow'
    elif getattr(args, 'timeline_compact', False):
        export_format = 'timeline_compact'
    elif args.timeline:
        export_format = 'timeline'
    elif args.dense:
        export_format = 'dense'
    elif args.optimized:
        export_format = 'optimized'
    chunker.process_directory(args.input_dir, args.output, export_format=export_format)


if __name__ == '__main__':
    main()
