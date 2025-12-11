import re
import os
import glob

# 角色ID到日文显示名的映射表 (主要用于102期脚本)
ROLE_MAP = {
    'kaho': '花帆',
    'sayaka': 'さやか',
    'kozue': '梢',
    'tsuzuri': '綴理',
    'megumi': '慈',
    'rurino': '瑠璃乃',
    'ginko': '吟子',
    'kosuzu': '小鈴',
    'hime': '姫芽',
    'sachi': '沙知',
    'unison': '全員',
    # 如果有未知ID，脚本会自动首字母大写使用
}

def clean_text(text):
    """
    文本清洗函数：强力去除 [Space], [r], 注音符号等
    """
    if not text:
        return ""
    
    # 1. 【核心修正】强制替换 [Space] 和 [r]，不再仅依赖正则
    # 这能保证 102 期脚本中 "藤島[Space]慈" 变成 "藤島 慈"
    text = text.replace('[Space]', ' ').replace('[r]', ' ')
    # 兼容小写的情况
    text = text.replace('[space]', ' ').replace('[R]', ' ')
    
    # 2. 去除注音符号，例如 【頂】{いただき} -> 頂
    # 移除 {} 及其内部的内容
    text = re.sub(r'\{.*?\}', '', text)
    
    # 3. 移除可能残留的开头结尾空格
    return text.strip()

def parse_game_script(file_content):
    """
    解析混合格式的游戏脚本 (102期 Novel模式 & 103期 ADV模式)
    """
    extracted_lines = []
    
    # --- 正则表达式定义 ---

    # 模式A (103期): [メッセージ表示 角色名 ID @变量名 文本]
    msg_adv_pattern = re.compile(r'\[メッセージ表示\s+(?P<role>\S+)\s+\S+\s+(?P<text>.+?)\]')

    # 模式B (102期 对话): [ノベルテキスト追加 『文本』 vo_adv_... @role_id]
    # 优化：兼容有『』和没有『』的情况
    msg_novel_pattern = re.compile(r'\[ノベルテキスト追加\s+(?:『(?P<text>.+?)』|(?P<text_raw>.+?))\s+vo_adv_\S+@(?P<role_id>\w+)\]')

    # 模式C (通用 旁白): [ノベルテキスト追加 文本] (且不包含 vo_adv)
    novel_plain_pattern = re.compile(r'\[ノベルテキスト追加\s+(?P<text>.+?)\]')
    
    # 忽略模式: 包含“削除”或“★”的行
    ignore_pattern = re.compile(r'削除|★')
    
    # 表情/情绪
    emotion_pattern = re.compile(r'\[キャラ表情変更\s+(?P<role>\S+)\s+[^\]]+\]\s*#(?P<emotion>.*)')
    
    # 动作 (兼容 102期的 "即時再生" 和 103期的 "再生")
    motion_pattern = re.compile(r'\[キャラモーション(再生|即時再生)\s+(?P<role>\S+)\s+[^\]]+\]\s*#(?P<action>.*)')

    # 【修正】source 标签处理
    # 匹配 格式，且不再导致语法错误
    source_tag_pattern = re.compile(r'</?source>')

    lines = file_content.split('\n')
    
    for line in lines:
        line = line.strip()
        if not line:
            continue
            
        # 预处理：去除 source 标签
        line = source_tag_pattern.sub('', line)
        
        # 0. 检查是否是需要忽略的行
        if ignore_pattern.search(line):
            continue

        # 1. 尝试匹配 103期 ADV对话
        match_adv = msg_adv_pattern.search(line)
        if match_adv:
            role = match_adv.group('role')
            # 这里的 clean_text 会处理掉 [r] 和 [Space]
            text = clean_text(match_adv.group('text'))
            extracted_lines.append(f"**{role}**: 「{text}」")
            continue

        # 2. 尝试匹配 102期 Novel对话 (带语音ID的行)
        match_novel_msg = msg_novel_pattern.search(line)
        if match_novel_msg:
            role_id = match_novel_msg.group('role_id')
            # 优先使用 『』 内的文本，如果没有则使用原始文本
            raw_text = match_novel_msg.group('text') or match_novel_msg.group('text_raw')
            text = clean_text(raw_text)
            
            # 将英文ID转换为日文名
            role_name = ROLE_MAP.get(role_id, role_id.capitalize())
            
            extracted_lines.append(f"**{role_name}**: 「{text}」")
            continue

        # 3. 尝试匹配 纯旁白 (Novel Text)
        match_novel_plain = novel_plain_pattern.search(line)
        if match_novel_plain:
            if 'vo_adv_' not in line:
                text = clean_text(match_novel_plain.group('text'))
                if text:
                    extracted_lines.append(f"> *{text}*")
            continue
            
        # 4. 表情处理
        match_emotion = emotion_pattern.search(line)
        if match_emotion:
            role = match_emotion.group('role')
            emotion = clean_text(match_emotion.group('emotion'))
            # 过滤掉无意义的数字（102期脚本中会有 "0" 这种参数）
            if emotion and not emotion.replace('.', '', 1).isdigit():
                extracted_lines.append(f"({role}の表情: {emotion})")
            continue

        # 5. 动作处理
        match_motion = motion_pattern.search(line)
        if match_motion:
            role = match_motion.group('role')
            action = clean_text(match_motion.group('action'))
            if action and "汎用" not in action and "待機" not in action:
                 extracted_lines.append(f"({role}の動作: {action})")
            continue

    return extracted_lines

def convert_files_to_markdown(input_files, output_file="merged_script.md"):
    """
    读取文件并转换为Markdown
    """
    if not input_files:
        print("エラー: .txtファイルが見つかりませんでした。")
        return

    with open(output_file, 'w', encoding='utf-8') as outfile:
        outfile.write("# Game Script Extraction (Cleaned V3)\n\n")
        
        count = 0
        for file_path in input_files:
            filename = os.path.basename(file_path)
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                
                print(f"処理中 (Processing): {filename}...")
                
                parsed_lines = parse_game_script(content)
                
                if parsed_lines:
                    outfile.write(f"## File: {filename}\n\n")
                    outfile.write("\n\n".join(parsed_lines))
                    outfile.write("\n\n---\n\n")
                    count += 1
                else:
                    print(f"  -> 警告: {filename} から有効なテキストが抽出できませんでした。")
                
            except Exception as e:
                print(f"読み込みエラー {filename}: {e}")

    print(f"\n完了！ 合計 {count} ファイルを処理しました。")
    print(f"出力先: {output_file}")

if __name__ == "__main__":
    # 按文件名排序处理
    current_files = sorted(glob.glob("*.txt"))
    convert_files_to_markdown(current_files, "dify_knowledge_base.md")