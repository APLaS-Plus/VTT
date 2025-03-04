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
    def __init__(self, preque_maxlen=4, sufque_maxlen=4):
        self.preque = deque(maxlen=preque_maxlen)
        self.current = None
        self.sufque = deque(maxlen=sufque_maxlen)

    def update_window(self, sentences: list, index: int):
        """动态更新上下文窗口"""
        # 前序窗口：当前句的前preque_maxlen句
        self.preque.clear()
        for i in range(max(0, index-self.preque.maxlen), index):
            self.preque.append(sentences[i])
        
        # 当前句
        self.current = sentences[index]
        
        # 后续窗口：当前句的后sufque_maxlen句
        self.sufque.clear()
        for i in range(index+1, min(len(sentences), index+self.sufque.maxlen+1)):
            self.sufque.append(sentences[i])

    def build_translation_prompt(self) -> str:
        """构建包含上下文的翻译提示"""
        preback = [f"{s.text}\n" for s in self.preque]
        sufback = [f"{s.text}\n" for s in self.sufque]
        prompt = f"\
        你是一个专业字幕翻译引擎，请根据以下上下文进行精准翻译：\n\
        [源语言] 英语\n\
        [目标语言] 简体中文\n\n\
        ----- 前序对话 -----\n\
        {preback}\n\
        ----- 当前待译句 -----\n\
        {self.current.text}\n\
        ----- 后续对话 -----\n\
        {sufback}\n\n\
        翻译要求：\n\
        1. 保持上下文连贯\n\
        2. 注意遇到的专业术语\n\
        3. 请勿添加任何注释或备注，你只需将发给你的待译句翻译成简体中文\n\
        4. 保持口语化，不要过于正式\n\
        "
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