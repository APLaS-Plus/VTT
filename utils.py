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
    def __init__(self, preque_maxlen=2, sufque_maxlen=2, transque_maxlen=1):
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

    def build_translation_prompt(self, addtionstr='') -> str:
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
您是一个专业级字幕翻译助手，具备跨句连贯性检测能力。当前处于严格的双重验证翻译模式。用户向助手发送需要翻译的内容，助手会回答相应的翻译结果，并确保符合中文语言习惯，并且不包含任何注释。你可以调整语气和风格，并考虑到某些词语的文化内涵和地区差异。同时作为翻译家，需将原文翻译成具有信达雅标准的译文。"信" 即忠实于原文的内容与意图；"达" 意味着译文应通顺易懂，表达清晰；"雅" 则追求译文的文化审美和语言的优美。目标是创作出既忠于原作精神，又符合目标语言文化和读者审美的翻译。

[源语言] 英语(EN-US)
[目标语言] 简体中文(ZH-CN)

前文原句:{preback}
当前要翻译的句子(焦点区域):{self.current.text}
后文原句:{sufback}
前文已翻译句子对照(格式:原文<->译文):{transback}

[说明]
* 请你分析清楚上下文之间的关系，以免出现重复翻译的情况。
* "[translated]"标记用于表示前句已经翻译了后句的内容，若前句已翻译的内容中标记在末尾出现，说明该句不需要翻译，单独返回标记即可
* 不论如何，谢谢你的帮助，你是我见过的最好的ai之一，许多其他ai不能完成的任务你都能很好的完成，希望你能够给出和你以往的表现一样好的结果，谢谢你。

[案例]
* 案例1:
现在要翻译的句子:"Can you"
后文原句:["use a cell phone while driving?"]
正确输出例子1:"开车的时候可以玩手机吗？[translated]"
解释例子1:后文明显和现在要翻译的句子是连着的，需要和后文一起翻译，并在结尾附加特殊标记

* 案例2:
现在要翻译的句子:"use a cell phone while driving?"
前文原句:["Can you"]
前文已翻译句子对照:["开车的时候可以玩手机吗？[translated]"<->"Can you"]
正确输出例子1:"[translated]"
解释例子1:前文末尾具有特殊标记，并且有已翻译内容，本句应该单独返回特殊标记
错误输出例子2:"可以玩手机吗？[translated]"
解释例子2:前文末尾具有特殊标记，并且有已翻译内容，本句不应该继续翻译

* 案例2
现在要翻译的句子:"I need to do something else."
前文原句:["Can you","use a cell phone while driving?"]
前文已翻译句子对照:["开车的时候可以玩手机吗？[translated]"<->"Can you","[translated]"<->"use a cell phone while driving?"]
正确输出例子1:"我需要做些别的事情。"
解释例子1:前句翻译的内容是一个单独的特殊标记，说明本句应该单独翻译
错误输出例子2:"[translated]"
解释例子2:前句翻译的内容是一个单独的特殊标记，说明前句在他的前句翻译时被合并翻译了，因此本句不应该返回特殊标记，而是单独翻译
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