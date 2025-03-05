"""
日志：
2025-03-02：
完成功能：
1. 视频转音频
2. 翻译输出字幕
3. 音频转文字（初步）
计划：
1. 优化音频转文字，正确切片保持句子完整性
2. 输出句子可能仍然不是正确的，初步使用大模型分析处理整合，再次翻译

2025-03-03：
完成功能：
1. 引用whisper_timestamped模块，优化音频转文字
2. 使用滑动窗口，保持上下文连贯（效果并不好）
计划：
1. 解决滑动窗口效果不好的问题，考虑字幕合并
"""

import time

bg = time.time()

import os
import subprocess
from tqdm import tqdm
import yaml
import platform
from openai import OpenAI
import whisper_timestamped
from utils import *
from lang import *
import pprint

load_package = time.time()
print(f"[TIME]load package: use {load_package - bg:.2f}s")

ROOTPATH = os.path.dirname(os.path.abspath(__file__))
MODELSPATH = os.path.join(ROOTPATH, "models")
if not os.path.exists(MODELSPATH):
    os.makedirs(MODELSPATH)
WHISPER_MODEL = "large-v3"
LANGUAGE = "en"

with open(os.path.join(ROOTPATH,'dsKey.yaml'), 'r') as file:
    dsKey = yaml.safe_load(file)

# pprint.pprint(dsKey)

CLIENT = OpenAI(
    api_key=dsKey['api_key'],
    base_url=dsKey['base_url'],
)

if not os.path.exists(".cache"):
    os.makedirs(".cache")
if not os.path.exists(".cache/audio"):
    os.makedirs(".cache/audio")

file_coverter = File_coverter(ROOTPATH)
# bert = Bert()

load_model = time.time()
print(f"[INFO]Load model: use {load_model - load_package:.2f}s")

def translate_subtitle(subtitles):
    window = ContentWindow()

    for i in range(len(subtitles)):
        print(f"[INFO]To translate: \"{subtitles[i].text}\"")

        pre_score, suf_score, additionstr = 0, 0, '[用户通过实时计算的关联度评分给出的建议]\n'
        # if i > 0:
        #     pre_score = bert.integrated_scoring(subtitles[i - 1].text, subtitles[i].text)
        # if i < len(subtitles) - 1:
        #     suf_score = bert.integrated_scoring(subtitles[i].text, subtitles[i + 1].text)
        # print(f"[INFO]Score of crosstext: pre {pre_score:.2f}, suf {suf_score:.2f}")

        # if pre_score > 0.8:
        #     additionstr += "* 前句与待翻译句子相关度大于0.8，建议直接返回[translated]。\n"
        # else:
        #     additionstr += "* 前句与待翻译句子相关度小于0.8，建议单独翻译。\n"
        # if suf_score > 0.8:
        #     additionstr += "* 待翻译句子与后句相关度大于0.8，建议与后文一起翻译。\n"
        # else:
        #     additionstr += "* 待翻译句子与后句相关度小于0.8，建议单独翻译。\n"
        
        window.update_window(subtitles, i)
        prompt = window.build_translation_prompt(addtionstr=additionstr)
        # print(prompt)
        messages = [{
            "role": "user",
            "content": prompt
            }]
        
        completion = (
            CLIENT.chat.completions.create(
                model="deepseek-v3",
                messages=messages,
                temperature=1.3,
            )
            .choices[0]
            .message.content
        )
        subtitles[i].translated_text = completion

        print(f"[INFO]Translated: \"{completion}\"")
        print(f"[INFO]Translated {i+1}/{len(subtitles)} subtitles\n")

    return subtitles


def vedio2subtitles(model, filepath: str):
    print(f"[INFO]Transcribing audio {filepath}")

    result = whisper_timestamped.transcribe(
        model, filepath, language=LANGUAGE, detect_disfluencies=True, vad=True,
    )
    return result2subtitles(result)

if __name__ == "__main__":

    # model = whisper_timestamped.load_model(WHISPER_MODEL, download_root=MODELSPATH)
    # print(f"[INFO]Model {WHISPER_MODEL} loaded")

    # mp4_path = os.path.join("example", "MIT Introduction to Deep Learning (2024) _ 6.S191.mp4")
    # if not os.path.exists(mp4_path):
    #     print(f"[ERROR]File {mp4_path} not found")
    #     FileExistsError
    # if mp4_path.endswith(".mp4"):
    #     print(f"[INFO]Converting video {mp4_path} to audio")
    #     audio_path = mp4_path.replace(".mp4", ".flac")
    #     mp3_path = vedio2audio(mp4_path, audio_path,file_coverter)

    # output = vedio2subtitles(model, mp3_path)
    
    # output = translate_subtitle(output)

    # subtitles2srt(output, mp4_path.replace(".mp4", "").split("/")[-1])

    test = read_subtitle("Can diet improve memory_ BBC News Review.srt")
    # for i in test:
    #     print(i.get_text())
    test = translate_subtitle(test)
    subtitles2srt(test, "Can diet improve memory_ BBC News Review")
