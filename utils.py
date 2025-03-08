import os
import time
import platform
import asyncio
import subprocess
from tqdm import tqdm
import subprocess
import copy
from collections import deque
import transformers

chat_tokenizer_dir = os.path.dirname(__file__)
tokenizer = transformers.AutoTokenizer.from_pretrained(
    chat_tokenizer_dir, trust_remote_code=True
)

class Subtitle:
    def __init__(self, index="0", _time="", text="", begin="", end=""):
        self.index = index
        self.time = _time
        self.begin = ""
        self.end = ""
        self.text = text

    def get_text(self):
        return f"{self.index}\n{self.time}\n{self.text}\n\n"

    def copy(self):
        return copy.deepcopy(self)


class Subtitles:
    def __init__(self, name: str = "", subtitles: list[Subtitle] = []):
        self.name = name
        self.subtitles = copy.deepcopy(subtitles)

    def copy(self):
        subtitles = [subtitle.copy() for subtitle in self.subtitles]
        return Subtitles(name=self.name, subtitles=subtitles)
    
    def subtitles2srt(self):
        if os.path.exists(self.name + ".srt"):
            os.remove(self.name + ".srt")
        with open(self.name + ".srt", "w", encoding="utf-8") as f:
            for subtitle in self.subtitles:
                f.write(subtitle.get_text())

    def merge_subtitles(self):
        merged_subtitles = []
        i = 0
        while i < len(self.subtitles):
            current_subtitle = self.subtitles[i]
            if current_subtitle.text != "[translated]":
                j = i + 1
                while (
                    j < len(self.subtitles) and self.subtitles[j].text == "[translated]"
                ):
                    j += 1
                if j > i + 1:
                    current_subtitle.time = (
                        f"{current_subtitle.begin} --> {self.subtitles[j-1].end}"
                    )
                merged_subtitles.append(current_subtitle)
                i = j
            else:
                i += 1
        self.subtitles = merged_subtitles


class FileCoverter:
    def __init__(self, rootpath):
        self.rootpath = rootpath
        self.ffmpeg_path = ""
        self.check_ffmpeg()
        print(f"[INFO]Built File_coverter with ffmpeg_path: {self.ffmpeg_path}")

    def check_ffmpeg(self):
        print("[INFO]Checking ffmpeg")
        if platform.system() == "Linux":
            self.ffmpeg_path = "ffmpeg"
            try:
                # 运行 ffmpeg -version 命令
                result = subprocess.run(
                    ["ffmpeg", "-version"], capture_output=True, text=True
                )
                if result.returncode == 0:
                    print("[INFO]ffmpeg exists")
                else:
                    subprocess.CalledProcessError(result.returncode, result.args)
            except FileNotFoundError:
                print("[WARN]Without ffmpeg, installing ffmpeg")
                subprocess.run(["sudo", "apt", "update"], check=True)
                subprocess.run(["sudo", "apt", "install", "ffmpeg", "-y"], check=True)
        elif platform.system() == "Windows":
            self.ffmpeg_path = os.path.join(
                self.rootpath, "ffmpeg", "bin", "ffmpeg.exe"
            )
            os.environ["PATH"] += os.pathsep + os.path.join(self.rootpath, "ffmpeg", "bin")
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
                            with zip_ref.open(file) as src, open(
                                dest_path, "wb"
                            ) as dst:
                                dst.write(src.read())
                os.remove("ffmpeg.zip")
        else:
            print("[ERROR]Unsupported platform")
            raise OSError


class Contents:

    def __init__(self, maxquelen=5, subtitle_obj=None):
        self.to_translate_queue = deque(maxlen=maxquelen)
        self.content = ''
        self.idx = 0
        self.subtitle_obj = subtitle_obj
        self.system_prompt = f"""
###角色任务###
英->中字幕翻译器，具备跨句语义检测能力

###语言规则###
源语言：英语(EN-US)
目标语言：简体中文(ZH-CN)

###核心规则###
1. 输出格式严格遵循json格式（不要包含任何额外字符）：
{{
    "句子1序号": <已翻译句子1>, 
    "句子2序号": <已翻译句子2>, 
    "句子3序号": <已翻译句子3>
}}
2. 当检测到连续短句时：
   - 前句翻译需包含完整语义
   - 后句标记[translated]
   （例：原句3"Could you"+4"help me?" → 译3"你可以帮我吗"+4"[translated]"）

3. 不完整句子暂不翻译：
   - 语义不完整时等待后续句子，后续句子出来再一起翻译
   - 确认完整语义后才输出翻译

###输入示例1###
2:I'am superman.
3:This is blue.
4:Could you
5:help me?
6.What is

###输出示例1###
{{
    "2": "我是超人", 
    "3": "这是蓝色的", 
    "4": "你可以帮我吗", 
    "5": "[translated]"
}}

###输入示例2###
7. the apple?
8. I don't know

###输出示例2###
{{
    "6": "什么是苹果？",
    "7": "[translated]",
    "8": "我不知道"
}}

###禁止事项###
❌ 添加解释性文字
❌ 改变输出格式
❌ 翻译不完整句子

确保：
1. 不使用Markdown代码块
2.不包含注释或标记
3.使用英文双引号
4.键名使用字符串类型数字

当你准备好后，请回复好的
"""

        ########################################################################################
        self.tip = """
###用户提示###
为了防止你回复格式发生错误，在此再次提示

###核心规则###
1. 输出格式严格遵循json格式（不要包含任何额外字符）：
{{
    "句子1序号": <已翻译句子1>, 
    "句子2序号": <已翻译句子2>, 
    "句子3序号": <已翻译句子3>
}}

2. 当检测到连续短句时：
   - 前句翻译需包含完整语义
   - 后句标记[translated]
   （例：原句3"Could you"+4"help me?" → 译3"你可以帮我吗"+4"[translated]"）

3. 不完整句子暂不翻译：
   - 语义不完整时等待后续句子，后续句子出来再一起翻译
   - 确认完整语义后才输出翻译

###禁止事项###
❌ 添加解释性文字
❌ 改变输出格式
❌ 翻译不完整句子

确保：
1. 不使用Markdown代码块
2.不包含注释或标记
3.使用英文双引号
4.键名使用字符串类型数字

你再次确认后，请回复好的
"""

    def upgrade_system_prompt(self, prompt: str) -> None:
        self.system_prompt = prompt

    def upgrade_queue(self) -> None:
        _quelen = self.to_translate_queue.maxlen
        self.to_translate_queue.clear()
        for i in range(self.idx, min(len(self.subtitle_obj.subtitles), self.idx + _quelen)):
            self.to_translate_queue.append(self.subtitle_obj.subtitles[i])

        self.content = copy.deepcopy("")
        tmp_que = list(self.to_translate_queue)
        for i in range(len(tmp_que)):
            self.content += f"{self.idx + i}:{tmp_que[i].text}\n"

    def build_contents(self) -> str:
        self.idx += self.to_translate_queue.maxlen
        return self.content

    def get_token(cal_str):
        res = len(tokenizer.encode(cal_str))
        return res

    def suit_the_length_of_content(self):
        self.upgrade_queue()
        # 二分搜索最适长度
        left = 0
        right = 30
        prompt_tokens = Contents.get_token(self.system_prompt)
        while left < right:
            mid = left + (right - left) // 2
            self.to_translate_queue = deque(maxlen=mid)
            self.upgrade_queue()
            if Contents.get_token(self.content) < prompt_tokens // 5 * 3:
                left = mid + 1
            else:
                right = mid - 1


class TokenCounter:
    def __init__(self):
        self.prompt_tokens = 0
        self.completion_tokens = 0

    def add(self, pro, com):
        if pro < 0 or com < 0:
            raise ValueError("Token counts cannot be negative.")
        self.prompt_tokens += pro
        self.completion_tokens += com

    def cal_price(self, pre_pro, pre_com) -> float:
        return pre_pro * self.prompt_tokens + pre_com * self.completion_tokens


class RateLimiter:
    def __init__(self, requests_per_minute=60):
        self.rate = requests_per_minute
        self.available_tokens = requests_per_minute
        self.last_check = time.time()
        self.lock = asyncio.Lock()

    async def acquire(self):
        """等待直到可以执行下一个请求"""
        async with self.lock:
            now = time.time()
            time_passed = now - self.last_check
            self.last_check = now

            # 基于经过时间添加令牌
            self.available_tokens += time_passed * (self.rate / 60.0)

            # 令牌数量上限
            if self.available_tokens > self.rate:
                self.available_tokens = self.rate

            # 如果没有令牌可用，需要等待
            if self.available_tokens < 1:
                wait_time = (1 - self.available_tokens) / (self.rate / 60.0)
                await asyncio.sleep(wait_time)
                self.available_tokens = 0
            else:
                self.available_tokens -= 1


def read_subtitle(file: str) -> Subtitles:
    subtitles = Subtitles(name=os.path.splitext(file)[0])
    with open(file, "r", encoding="utf-8") as f:
        lines = f.readlines()
        i = 0
        while i < len(lines):
            subtitle = Subtitle()
            subtitle.index = int(lines[i].strip())
            subtitle.time = lines[i + 1].strip()
            subtitle.text = lines[i + 2].strip()
            subtitle.begin = subtitle.time.split(" --> ")[0]
            subtitle.end = subtitle.time.split(" --> ")[1]
            subtitles.subtitles.append(subtitle)
            i += 4
    return subtitles


def result2subtitles(result, name) -> Subtitles:
    subtitles = Subtitles(name=name)

    def secend2time(secend):
        intsecend = int(secend)
        h = intsecend // 3600
        m = (intsecend % 3600) // 60
        s = intsecend % 60
        ms = int((secend - intsecend) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    for i, segment in enumerate(result["segments"]):
        begin = secend2time(float(segment["start"]))
        end = secend2time(float(segment["end"]))
        subtitles.subtitles.append(
            Subtitle(
                index=str(i + 1),
                _time=f"{begin} --> {end}",
                text=segment["text"][1:],
                begin=begin,
                end=end,
            )
        )
    return subtitles


def vedio2audio(video_path, audio_path, _file_coverter: FileCoverter) -> str:
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
        "-compression_level",
        "0",  # 无损压缩
        audio_path,  # 输出音频文件
    ]
    # 执行命令
    print(f"[INFO]Cmd: {' '.join(command)}")
    subprocess.run(command, cwd=_file_coverter.rootpath, check=True)
    print(f"[INFO]Video {video_path} converted to audio {audio_path}")
    return audio_path
