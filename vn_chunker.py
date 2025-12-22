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
    DIALOGUE_END = r'^\\[ノベルテキスト削除\\]★##+$'
    
    # 角色相关（增强版：提取注释）
    # 角色相关（增强版：提取注释）
    CHARACTER_DISPLAY = r'^\[キャラ表示\s+(\w+)\s+'
    CHARACTER_MESSAGE = r'^\[メッセージ表示\s+(\w+)\s+(vo_adv_\d+_\d+_m\d+_\d+@\w+)\s+(.+?)\]$'
    CHARACTER_EMOTION = r'^\[キャラ表情変更\s+(\w+)\s+(\w+)\](?:#(.+))?$'  # 捕获注释
    CHARACTER_MOTION = r'^\[キャラモーション再生\s+(\w+)\s+([\w_]+)\s*.*?\](?:#(.+))?$'  # 捕获动作注释
    
    # 背景和环境（增强版：提取注释）
    BACKGROUND_PATTERN = r'^\[背景表示\s+([\w_]+)\s*([^\]]*?)\](?:#(.+))?$'
    BGM_PATTERN = r'^\[BGM再生\s+(\w+)\s+'
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
    
    def extract_dialogues(self, scene_lines: List[str]) -> List[List[Dict]]:
        """
        提取对话组
        
        Args:
            scene_lines: 场景行列表
            
        Returns:
            对话组列表
        """
        dialogue_groups = []
        current_group = []
        
    def extract_dialogues(self, scene_lines: List[str]) -> List[List[Dict]]:
        """
        提取对话组（支持两种格式）
        
        Args:
            scene_lines: 场景行列表
            
        Returns:
            对话组列表
        """
        dialogue_groups = []
        current_group = []
        
        for line in scene_lines:
            # 匹配带语音的对话 - [ノベルテキスト追加] (102系列)
            match = self.dialogue_re.match(line)
            if match:
                dialogue_text = match.group(1)
                character = match.group(2)
                current_group.append({
                    'text': dialogue_text,
                    'character': character,
                    'has_voice': True,
                    'raw_line': line
                })
                continue
            
            # 匹配不带语音的对话（纯叙述） - [ノベルテキスト追加]
            match = self.dialogue_no_voice_re.match(line)
            if match:
                dialogue_text = match.group(1)
                current_group.append({
                    'text': dialogue_text,
                    'character': 'narrator',
                    'has_voice': False,
                    'raw_line': line
                })
                continue
            
            # 匹配角色消息 - [メッセージ表示] (103+系列)
            match = self.character_message_re.match(line)
            if match:
                character = match.group(1)
                dialogue_text = match.group(3)
                current_group.append({
                    'text': dialogue_text,
                    'character': character,
                    'has_voice': True,
                    'raw_line': line
                })
                # 103+系列没有明确的对话组结束标记
                # 连续5句同格式视为一组，或遇到其他命令时结束
                if len(current_group) >= 5:
                    dialogue_groups.append(current_group)
                    current_group = []
                continue
            
            # 匹配对话结束标记 - [ノベルテキスト削除] (102系列)
            if self.dialogue_end_re.match(line):
                if current_group:
                    dialogue_groups.append(current_group)
                    current_group = []
                continue
            
            # 遇到其他命令（非对话）时，结束当前对话组
            if line.strip().startswith('[') and current_group:
                # 但不是对话相关命令
                if not any(cmd in line for cmd in ['ノベルテキスト', 'メッセージ表示', '待機']):
                    dialogue_groups.append(current_group)
                    current_group = []
        
        # 处理最后一组对话
        if current_group:
            dialogue_groups.append(current_group)
        
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
        按序提取对话及其关联的表情、动作、语音
        
        扫描场景行,当遇到对话命令时:
        1. 向前查找最近的表情/动作命令(作为对话前状态)
        2. 向后查找紧跟的表情变化(作为对话后状态)
        3. 提取voice_ref
        
        Args:
            scene_lines: 场景行列表
            
        Returns:
            按时间顺序的对话列表
        """
        dialogues = []
        
        # 编译动作正则
        motion_re = re.compile(r'^\[キャラモーション再生\s+(\w+)\s+([\w_]+)\s+.*?\](?:#(.+))?$')
        
        for i, line in enumerate(scene_lines):
            dialogue_line = None
            character = None
            text = None
            voice_ref = None
            
            # 1. 检测对话 (メッセージ表示格式)
            match = self.character_message_re.match(line)
            if match:
                character = match.group(1)
                voice_ref = match.group(2)  # 已经包含 "vo_adv_..." 格式
                text = match.group(3)
            
            # 2. 检测对话 (ノベルテキスト追加格式)
            if not match:
                match = self.dialogue_re.match(line)
                if match:
                    text = match.group(1)
                    character = match.group(2)
                    # 从原始行提取完整voice_ref
                    voice_match = re.search(r'vo_adv_\d+_\d+_m\d+_\d+@\w+', line)
                    if voice_match:
                        voice_ref = voice_match.group(0)
            
            # 3. 检测无语音对话
            if not match:
                match = self.dialogue_no_voice_re.match(line)
                if match:
                    text = match.group(1)
                    character = 'narrator'
                    voice_ref = None
            
            # 如果找到对话,清理文本并提取上下文
            if character and text:
                # 清理text中嵌入的命令(motion/emotion等)
                # 移除 [キャラモーション再生 xxx] 格式
                text = re.sub(r'\[キャラモーション再生[^\]]+\](?:#[^\]]+)?', '', text)
                # 移除 [キャラ表情変更 xxx] 格式
                text = re.sub(r'\[キャラ表情変更[^\]]+\](?:#[^\]]+)?', '', text)
                # 移除其他可能的命令
                text = re.sub(r'\[(?:BGM|SE|背景)[^\]]+\]', '', text)
                
                # 转换格式标记为实际字符
                text = text.replace('[r]', '\n')  # 换行
                text = text.replace('[Space]', ' ')  # 空格
                
                # 清理多余空格
                text = text.strip()
                
                emotion_before = None
                emotion_after = None
                action = None
                action_desc = ''
                
                # 向前扫描:查找最近的表情和动作(最多回溯10行)
                for j in range(max(0, i - 10), i):
                    prev_line = scene_lines[j]
                    
                    # 查找表情(优先使用注释)
                    emotion_match = self.character_emotion_re.match(prev_line)
                    if emotion_match and emotion_match.group(1) == character:
                        emotion_id = emotion_match.group(2)
                        emotion_comment = emotion_match.group(3) if len(emotion_match.groups()) >= 3 and emotion_match.group(3) else None
                        emotion_before = emotion_comment if emotion_comment else emotion_id
                    
                    # 查找动作(优先使用注释,其次映射表,最后为空)
                    motion_match = self.character_motion_re.match(prev_line)
                    if motion_match and motion_match.group(1) == character:
                        action = motion_match.group(2)  # mot_00_xxxxx
                        motion_comment = motion_match.group(3) if len(motion_match.groups()) >= 3 and motion_match.group(3) else None
                        
                        if motion_comment:
                            # 优先使用注释
                            action_desc = motion_comment
                        elif action in self.motion_mappings:
                            # 使用映射表
                            action_desc = self.motion_mappings[action]
                        else:
                            # 无映射时为空
                            action_desc = ''
                
                # 向后扫描:查找对话后的表情变化(最多前瞻5行)
                for j in range(i + 1, min(len(scene_lines), i + 6)):
                    next_line = scene_lines[j]
                    
                    # 如果遇到新的对话,停止搜索
                    if (self.character_message_re.match(next_line) or 
                        self.dialogue_re.match(next_line)):
                        break
                    
                    # 查找表情变化(优先使用注释)
                    emotion_match = self.character_emotion_re.match(next_line)
                    if emotion_match and emotion_match.group(1) == character:
                        emotion_id = emotion_match.group(2)
                        emotion_comment = emotion_match.group(3) if len(emotion_match.groups()) >= 3 and emotion_match.group(3) else None
                        emotion_after = emotion_comment if emotion_comment else emotion_id
                        break  # 找到第一个就停止
                
                # 创建对话对象
                dialogue = DialogueLine(
                    character=character,
                    text=text,
                    voice_ref=voice_ref,
                    emotion_before=emotion_before,
                    emotion_after=emotion_after,
                    action=action,
                    action_desc=action_desc
                )
                
                dialogues.append(dialogue)
        
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
            # 提取角色
            match = self.character_display_re.match(line)
            if match:
                metadata['characters'].add(match.group(1))
            
            match = self.character_message_re.match(line)
            if match:
                metadata['characters'].add(match.group(1))
            
            # 提取角色表情（优先使用注释中的人类可读名称）
            match = self.character_emotion_re.match(line)
            if match:
                character = match.group(1)
                emotion_id = match.group(2)
                emotion_comment = match.group(3) if len(match.groups()) >= 3 and match.group(3) else None
                
                # 优先使用注释,否则使用ID
                emotion = emotion_comment if emotion_comment else emotion_id
                metadata['emotions'][character] = emotion
            
            # 提取BGM
            match = self.bgm_re.match(line)
            if match and not metadata['bgm']:
                metadata['bgm'] = match.group(1)
            
            # 提取语音引用
            if 'vo_adv_' in line:
                voice_matches = re.findall(r'vo_adv_\d+_\d+_m\d+_\d+@\w+', line)
                metadata['voice_refs'].extend(voice_matches)
            
            # 提取天气（从SE，中等优先级）
            if '[SE再生' in line and not metadata['weather']:
                if 'rain' in line or '雨' in line:
                    metadata['weather'] = 'rain'
                elif 'thunder' in line or '雷' in line:
                    metadata['weather'] = 'storm'
                elif 'wind' in line or '風' in line:
                    metadata['weather'] = 'windy'
            
            # 提取背景（含注释解析 + 映射表fallback）
            match = self.background_re.match(line)
            if match:
                bg_id = match.group(1)
                bg_comment = match.group(3) if len(match.groups()) >= 3 and match.group(3) else None
                
                # Location: ID作为初始值（低优先级）
                if metadata['_location_source'] == 0:
                    metadata['location'] = bg_id
                    metadata['_location_source'] = 1
                
                # 尝试从注释解析（高优先级）
                if bg_comment:
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
                        if extracted_time == '朝' or extracted_time == 'morning':
                            metadata['time_period'] = 'morning'
                            metadata['_time_source'] = 3
                        elif extracted_time == '昼':
                            metadata['time_period'] = 'afternoon'
                            metadata['_time_source'] = 3
                        elif extracted_time == '午後' or extracted_time == 'afternoon':
                            metadata['time_period'] = 'afternoon'
                            metadata['_time_source'] = 3
                        elif extracted_time == '夕' or extracted_time == 'evening':
                            metadata['time_period'] = 'evening'
                            metadata['_time_source'] = 3
                        elif extracted_time == '夜' or extracted_time == 'night':
                            metadata['time_period'] = 'night'
                            metadata['_time_source'] = 3
                    
                    # 更新location
                    if location_parts and metadata['_location_source'] < 2:
                        metadata['location'] = '_'.join(location_parts)
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
                        elif '屋外' in bg_comment or '正門' in bg_comment or '校庭' in bg_comment:
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
                        metadata['emotions'][d.character] = d.emotion_after
                    elif d.emotion_before and d.character not in metadata['emotions']:
                        metadata['emotions'][d.character] = d.emotion_before
            
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
        
        # 转换set为list
        metadata['characters'] = list(metadata['characters'])
        
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

        
        for group in dialogue_groups:
            # 计算这组对话的token数
            group_text = '\n'.join([d['text'] for d in group])
            group_tokens = self.count_tokens(group_text)
            
            # 如果加上这组对话会超过最大限制，先保存当前chunk
            if current_tokens + group_tokens > self.max_chunk_size and current_chunk_lines:
                chunk_id = f"{scene_id}_sub_{sub_chunk_idx}"
                chunk = self.create_chunk(chunk_id, scene_id, source_file, current_chunk_lines, scene_id)
                chunks.append(chunk)
                
                # 重置，保留overlap
                overlap_groups = dialogue_groups[max(0, len(chunks) - self.overlap_lines):len(chunks)]
                current_chunk_lines = [d['raw_line'] for g in overlap_groups for d in g]
                current_tokens = self.count_tokens('\n'.join([d['text'] for g in overlap_groups for d in g]))
                sub_chunk_idx += 1
            
            # 添加当前对话组
            current_chunk_lines.extend([d['raw_line'] for d in group])
            current_tokens += group_tokens
        
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
        
        # 检测场景边界
        scenes = self.detect_scene_boundaries(lines)
        
        # 生成chunks
        chunks = self.create_chunks(scenes, lines, Path(file_path).name)
        
        return chunks
    
    def process_directory(self, directory: str, output_file: str, optimize: bool = False):
        """
        批量处理目录下所有txt文件
        
        Args:
            directory: 输入目录
            output_file: 输出JSON文件路径
            optimize: 是否使用优化格式输出
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
        self.export_to_json(all_chunks, output_file, optimize=optimize)
    
    def export_to_json(self, chunks: List[Chunk], output_file: str, optimize: bool = False):
        """
        导出chunks到JSON文件（Dify兼容格式）
        
        Args:
            chunks: chunk列表
            output_file: 输出文件路径
            optimize: 是否使用优化格式(压缩,适合embedding workflow)
        """
        if optimize:
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
                       help='使用优化格式导出(压缩,移除冗余字段,适合embedding workflow)')
    
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
    chunker.process_directory(args.input_dir, args.output, optimize=args.optimized)


if __name__ == '__main__':
    main()
