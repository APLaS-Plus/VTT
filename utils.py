import os
import platform
import subprocess
from tqdm import tqdm
import subprocess
from collections import deque

class Subtitle:
    def __init__(self, index='0', time="", text=""):
        self.index = index
        self.time = time
        self.text = text
        self.translated_text = ""

    def get_text(self):
        return f"{self.index}\n{self.time}\n{self.text}\n\n"
    
    def get_translated_text(self):
        return f"{self.index}\n{self.time}\n{self.translated_text}\n\n"

class File_coverter:
    def __init__(self, rootpath):
        self.rootpath = rootpath
        self.ffmpeg_path = ''
        self.check_ffmpeg()
        print(f"[INFO]Built File_coverter with ffmpeg_path: {self.ffmpeg_path}")
    
    def check_ffmpeg(self):
        print("[INFO]Checking ffmpeg")
        if platform.system() == "Linux":
            self.ffmpeg_path = "ffmpeg"
            try:
                # 运行 ffmpeg -version 命令
                result = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
                if result.returncode == 0:
                    print("[INFO]ffmpeg exists")
                else:
                    subprocess.CalledProcessError(result.returncode, result.args)
            except FileNotFoundError:
                print("[WARN]Without ffmpeg, installing ffmpeg")
                subprocess.run(["sudo", "apt", "update"], check=True)
                subprocess.run(["sudo", "apt", "install", "ffmpeg", "-y"], check=True)
        elif platform.system() == "Windows":
            self.ffmpeg_path = os.path.join(self.rootpath, "ffmpeg", "bin", "ffmpeg.exe")
            if not os.path.exists("ffmpeg"):
                print("[WARN]Without ffmpeg, downloading ffmpeg")
                if not os.path.exists("ffmpeg.zip"):
                    import requests

                    response = requests.get(
                        "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip",
                        stream=True,
                    )
                    total_size = int(response.headers.get("content-length", 0))
                    with open("ffmpeg.zip", "wb") as f, tqdm(
                        desc="下载进度",
                        total=total_size,
                        unit="iB",
                        unit_scale=True,
                        unit_divisor=1024,
                    ) as bar:
                        for data in response.iter_content(chunk_size=1024):
                            size = f.write(data)
                            bar.update(size)
                import zipfile
                from pathlib import Path

                with zipfile.ZipFile("ffmpeg.zip", "r") as zip_ref:
                    # 获取压缩包内所有文件的公共根目录
                    root_dir = None
                    for name in zip_ref.namelist():
                        if name.endswith("/"):
                            parts = Path(name).parts
                            if root_dir is None:
                                root_dir = parts[0]
                            elif parts[0] != root_dir:
                                root_dir = None
                                break

                    # 解压并重定向路径
                    for file in zip_ref.namelist():
                        if root_dir:
                            # 去除根目录
                            dest_path = os.path.join(
                                self.rootpath, "ffmpeg", os.path.relpath(file, root_dir)
                            )
                        else:
                            # 无统一根目录时直接解压
                            dest_path = os.path.join(self.rootpath, "ffmpeg", file)

                        # 创建父目录并解压文件
                        parent_dir = os.path.dirname(dest_path)
                        if not os.path.exists(parent_dir):
                            os.makedirs(parent_dir, exist_ok=True)

                        if not file.endswith("/"):  # 跳过目录
                            with zip_ref.open(file) as src, open(dest_path, "wb") as dst:
                                dst.write(src.read())
                os.remove("ffmpeg.zip")
        else:
            print("[ERROR]Unsupported platform")
            raise OSError

class ContentWindow:
    def __init__(self, preque_maxlen=4, sufque_maxlen=4, transque_maxlen=2):
        self.preque = deque(maxlen=preque_maxlen)
        self.current = None
        self.sufque = deque(maxlen=sufque_maxlen)
        self.translated_que = deque(maxlen=transque_maxlen - 1)

    def update_window(self, sentences: list, index: int):
        """动态更新上下文窗口"""
        # 前序窗口:当前句的前preque_maxlen句
        self.preque.clear()
        for i in range(max(0, index-self.preque.maxlen), index):
            self.preque.append(sentences[i])
        
        # 当前句
        self.current = sentences[index]
        
        # 后续窗口:当前句的后sufque_maxlen句
        self.sufque.clear()
        for i in range(index+1, min(len(sentences), index+self.sufque.maxlen+1)):
            self.sufque.append(sentences[i])

        # 翻译窗口:当前句的前preque_maxlen句
        self.translated_que.clear()
        for i in range(max(0, index-self.translated_que.maxlen), index):
            self.translated_que.append(sentences[i].translated_text)

    def build_translation_prompt(self) -> str:
        """构建包含上下文的翻译提示"""
        preback = [f"{s.text}" for s in self.preque]
        # print(preback)
        sufback = [f"{s.text}" for s in self.sufque]
        # print(sufback)
        preque_list = list(self.preque)  # 转换为列表
        matched_preque = preque_list[-len(self.translated_que):]  # 正确切片
        transback = [f"{orig}<->{pre.text}" for orig, pre in zip(self.translated_que, matched_preque)]
        # print(transback)
        prompt = f"""
[系统角色] 
您是一个专业级字幕翻译引擎，具备跨句连贯性检测能力。当前处于严格的双重验证翻译模式。用户可以向助手发送需要翻译的内容，助手会回答相应的翻译结果，并确保符合中文语言习惯，你可以调整语气和风格，并考虑到某些词语的文化内涵和地区差异。同时作为翻译家，需将原文翻译成具有信达雅标准的译文。"信" 即忠实于原文的内容与意图；"达" 意味着译文应通顺易懂，表达清晰；"雅" 则追求译文的文化审美和语言的优美。目标是创作出既忠于原作精神，又符合目标语言文化和读者审美的翻译。

[输入结构]
[源语言] 英语(EN-US)
[目标语言] 简体中文(ZH-CN)

[上下文信息]
前序对话原文缓存池(长度限制:{self.preque.maxlen}条，先后顺序为最远->最近):
{preback}

当前待译句(焦点区域):
{self.current.text}

后续对话原文缓存池(前瞻窗口:{self.sufque.maxlen}条，先后顺序为最近->最远): :
{sufback}

已翻译缓存池(格式:原文<->译文;长度限制:{self.translated_que.maxlen}条，先后顺序为最远->最近):
{transback}

[输出规范]
✅ 必须条件:返回内容必须满足以下之一:
   - 完整的目标语言译文
   - 精确的[translated]标记(表示已翻译或无需翻译，仅当已翻译缓存池内容已足够表示完整语义)

❌ 禁止行为:
   - 对未能表示完整语义的内容使用标记:[translated]
   - 添加任何注释

[特别说明]
1. [translated]标记仅用于表示已翻译缓存池已经存在了足够完整语义，当前待译句不需要翻译的情况，不得用于其他情况。
2. 务必分析准确已翻译缓存池中的内容和当前待译句的关系，确保翻译的连贯性和准确性。
3. 不论如何，谢谢你的帮助，你是我见过的最好的ai之一，许多其他ai不能完成的任务你都能很好的完成，希望你能够给出和你以往的表现一样好的结果，谢谢你。

[验证示例]
▶ 案例1:
迭代1:
当前句:"Could apples, berries and cacao"
后文缓存池:['improve our memory as we get older?']
→ ❌错误输出:"苹果、浆果和可可豆[translated][说明]由于当前句为不完整句子，且后续内容将构成完整语义，此处暂时标记为[translated]，待后续内容出现后再进行完整翻译。"
→ ✅正确输出:"苹果、浆果和可可豆，能否改善我们随着年龄增长而衰退的记忆力？"

迭代2:
当前句:"improve our memory as we get older?"
前文缓存池:['Could apples, berries and cacao']
→ ❌错误输出:"随着年龄增长，我们的记忆力会变好吗？[translated][说明]由于当前句为不完整句子，且前文内容构成完整语义，此处暂时标记为[translated]，待前文内容出现后再进行完整翻译。"
→ ✅正确输出:"[translated]"

处理逻辑:
1. 检测到疑问句拆分特征，但不满足合并条件(缓存池无记录)
2. 第二次翻译时检测到前文疑问词，但缓存池已有翻译记录，不独立处理，返回特殊标记

▶ 案例2:
迭代1:
当前句:"Don't forget to subscribe to our channel"
后文缓存池:['like this video and try the quiz on our website.']
→ ✅正确输出:"别忘了订阅我们的频道，给这个视频点赞，并尝试我们网站上的小测验。"

迭代2:
当前句:"like this video and try the quiz on our website."
前文缓存池:['Don't forget to subscribe to our channel']
→ ❌错误输出:"给这个视频点赞，并尝试我们网站上的小测验。"
→ ✅正确输出:"[translated]"

迭代1处理流程:
1. 检测到当前句为祈使句"Don't forget..." 
2. 后续句以"and"开头且首字母小写
3. 符合并列结构合并条件
4. 合并翻译："别忘了订阅我们的频道，给这个视频点赞，并尝试我们网站上的小测验。"

迭代2处理流程:
1. 当前句"like this..."出现在合并记录的第二个位置
2. 检查到已翻译缓存池存在包含该句的可以包含完整语义的翻译
3. 触发[translated]标记
4. 输出验证：
   - ❌ 错误条件：未关联合并记录 → 重复翻译
   - ✅ 正确条件：检测到合并记录 → [translated]
"""
        return prompt

def read_subtitle(file):
    subtitles = []
    with open(file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        i = 0
        while i < len(lines):
            subtitle = Subtitle()
            subtitle.index = int(lines[i].strip())
            subtitle.time = lines[i + 1].strip()
            subtitle.text = lines[i + 2].strip()
            subtitles.append(subtitle)
            i += 4
    return subtitles

def result2subtitles(result):
    subtitles = []
    def secend2time(secend):
        intsecend = int(secend)
        h = intsecend // 3600
        m = (intsecend % 3600) // 60
        s = intsecend % 60
        ms = int((secend - intsecend) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"
    for i, segment in enumerate(result["segments"]):
        subtitles.append(Subtitle(str(i + 1), f"{secend2time(float(segment['start']))} --> {secend2time(float(segment['end']))}", segment["text"][1:]))
    return subtitles

def subtitles2srt(subtitles, filename):
    with open(filename + '_zh_CN' + 'srt', "w", encoding="utf-8") as f:
        for subtitle in subtitles:
            f.write(subtitle.get_translated_text())
    with open(filename + '.srt', "w", encoding="utf-8") as f:
        for subtitle in subtitles:
            f.write(subtitle.get_text())

def vedio2audio(video_path, audio_path,_file_coverter:File_coverter):
    video_path = os.path.join(_file_coverter.rootpath, video_path)
    audio_path = os.path.join(".cache", "audio", os.path.basename(audio_path))
    if os.path.exists(audio_path):
        return audio_path
    command = [
        _file_coverter.ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        video_path,  # 输入视频文件
        "-vn",  # 禁用视频流
        "-acodec",
        "flac",  # 指定音频编码器
        "-compression_level", "0",  # 无损压缩
        audio_path,  # 输出音频文件
    ]
    # 执行命令
    print(f"[INFO]Cmd: {' '.join(command)}")
    subprocess.run(command, cwd=_file_coverter.rootpath, check=True)
    print(f"[INFO]Video {video_path} converted to audio {audio_path}")
    return audio_path