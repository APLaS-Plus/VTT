<<<<<<< HEAD
"""
日志：
2025-03-02：
完成功能：
1. 视频转音频
2. 翻译输出字幕
3. 音频转文字（初步）
计划：
1. 优化音频转文字，正确切片保持句子完整性✅
2. 输出句子可能仍然不是正确的，初步使用大模型分析处理整合，再次翻译❌

2025-03-03：
完成功能：
1. 引用whisper_timestamped模块，优化音频转文字
2. 使用滑动窗口，保持上下文连贯（效果并不好）
计划：
1. 解决滑动窗口效果不好的问题，考虑字幕合并❌

2024-03-05：
完成功能：
1. 初步修复了翻译不准的问题，使用了思维链模型，放弃之前的滑动窗口，考虑了让大模型完全接受一长串上下文
计划：
1. 继续补充提示词内容保证模型输出的准确性✅
2. 可以用之后开始计划新建B站账号开始上传视频

2024-03-06:
完成功能：
1. 通过更换api运营商，阿里云换成了深度求索，速度至少快了30%，并且价格不变，甚至晚上还有优惠
2. 添加中途提示机制，进一步减少大模型道中输出错误格式的可能
3. 更换大模型输出格式为json，保证输出格式能够被格式化读取
计划：
1. 添加文件处理池结构✅
2. 优化代码格式，使其尽量保持高效
3. 添加翻译后文本检测特殊标记并合并字幕的功能，完善项目结构✅
4. 添加发现翻译后文本是空字符串后重启翻译的功能，防止出现缺译的情况

2024-03-07:
完成功能：
1. 初步写好异步处理多文件的功能，但是仍然有漏洞
2. 添加文件处理池
计划：
1. 优化异步处理结构
"""

import time

bg = time.time()

import os
from tqdm import tqdm
import copy
import yaml
import json
import asyncio
import tenacity
import torch
from openai import OpenAI, AsyncOpenAI
import whisper_timestamped
from utils import *
# from lang import *
import pprint

load_package = time.time()
print(f"[TIME]load package: use {load_package - bg:.2f}s")

ROOTPATH = os.path.dirname(os.path.abspath(__file__))
MODELSPATH = os.path.join(ROOTPATH, "models")
if not os.path.exists(MODELSPATH):
    os.makedirs(MODELSPATH)
WHISPER_MODEL = "medium.en"
LANGUAGE = "en"
MAX_CONTENT = 20
CROSS_TIP = 5
MAX_PROMPT_TOKEN = 2500
TIMEOUT = 600

RETRY_EXCEPTIONS = (json.decoder.JSONDecodeError)

with open(os.path.join(ROOTPATH,'dsKey.yaml'), 'r') as file:
    cfgs = yaml.safe_load(file)

# pprint.pprint(dsKey)

CLIENT = AsyncOpenAI(
    api_key=cfgs['api_key'],
    base_url=cfgs['base_url'],
)

if not os.path.exists(".cache"):
    os.makedirs(".cache")
if not os.path.exists(".cache/audio"):
    os.makedirs(".cache/audio")

file_coverter = FileCoverter(ROOTPATH)
# bert = Bert()

@tenacity.retry(stop=tenacity.stop_after_attempt(3), retry=tenacity.retry_if_exception_type(RETRY_EXCEPTIONS))
async def get_completion(_messages):
    try:
        _completion = await CLIENT.chat.completions.create(
                model=cfgs["model"],
                messages=_messages,
                timeout=TIMEOUT
            )
        return _completion
    except json.decoder.JSONDecodeError as e:
        pprint.pprint(e)
        raise
            
        
def vedio2subtitles(model, filepath: str, name:str)->Subtitles:
    print(f"[INFO]Transcribing audio {filepath}")

    result = whisper_timestamped.transcribe(
        model, filepath, language=LANGUAGE, detect_disfluencies=True, vad=True,
    )
    return result2subtitles(result, name=name)

async def translate_subtitle(subtitles:Subtitles):
    contents = Contents(maxquelen=MAX_CONTENT)
    systemprompt = [
        {
            "role": "user",
            "content": contents.system_prompt
        },
        {
            "role": "assistant",
            "content": "好的"
        }
    ]
    translated_subtitles = copy.deepcopy(subtitles)
    translated_subtitles.name += "_zh_CN"
    messages = copy.deepcopy(systemprompt)
    token_counter = TokenCounter()
    
    epochs = len(translated_subtitles.subtitles)//MAX_CONTENT
    epochs += 1 if len(translated_subtitles.subtitles)%MAX_CONTENT > 0 else 0
    # print(epochs)
    
    for i in tqdm(range(1, epochs + 1), desc=f"Translating {translated_subtitles.name}"):
        trans_bg = time.time()

        if i%CROSS_TIP == CROSS_TIP - 1:
            messages.append({
                "role": "user",
                "content": contents.tip
                })
            messages.append({
                "role": "assistant",
                "content": "好的"
                })

        contents.upgrade_queue(translated_subtitles)
        content = contents.build_contents()
        
        print(f"[INFO]To translate: \"\"\"\n{content}\"\"\"\n")
        # print(prompt)
        messages.append({
            "role": "user",
            "content": content
            })
        
        completion = await get_completion(messages)

        # pprint.pprint(completion)
        
        translated_completion = completion.choices[0].message.content
        print(f"[INFO]Translated:   \"\"\"\n{translated_completion}\n\"\"\"\n")
        # print(translated_completion)
        
        translated_json = json.loads(translated_completion)
        # pprint.pprint(translated_json)
        for k, v in translated_json.items():
            translated_subtitles.subtitles[int(k)].text = v
            # print(k,v)
        
        messages.append({
            "role": "assistant",
            "content": translated_completion
            })
        trans_ed = time.time()

        prompt_tokens = completion.usage.prompt_tokens
        completion_tokens = completion.usage.completion_tokens
        token_counter.add(pro=prompt_tokens, com=completion_tokens)

        if prompt_tokens > MAX_PROMPT_TOKEN:
            messages.clear()
            messages = copy.deepcopy(systemprompt)
        
        print(f"[INFO]Token use: prompt tokens {prompt_tokens}, completion tokens {completion_tokens}, total {prompt_tokens + completion_tokens}")
        print(f"[TIME]Trans use: {trans_ed - trans_bg:.2f}s")
    
    return token_counter, translated_subtitles

async def translate_one_vedio(subtitles:Subtitles):
    transed_path = subtitles.name + '_zh_CN.srt'
    if not os.path.exists(transed_path):
        trans_bg = time.time()
        tc, transed_srt = await translate_subtitle(subtitles)
        trans_ed = time.time()

        print(f"[TIME]Trans use {trans_ed-trans_bg:.2f}s")
    
        print(f"[INFO]Token use total: pro total {tc.prompt_tokens}, com total {tc.completion_tokens}; token price is {tc.cal_price(cfgs['prompt_tokens_price'], cfgs['completion_tokens'])} RMB")
    else:
        print(f'[WARN]Translated srt is exsit in {transed_path}')
        transed_srt = read_subtitle(transed_path)

    transed_srt.merge_subtitles()
    transed_srt.subtitles2srt()
    print(f"[INFO]File \"{transed_srt.name + '.srt'}\" saved")

async def main(cover_srt_list):
    await asyncio.gather(*[translate_one_vedio(i) for i in cover_srt_list])

if __name__ == "__main__":
    
    covert_list = [
        i for i in os.listdir("example") if i.endswith(".mp4")
        ]
    covert_srt_list = []
    
    ws_model = whisper_timestamped.load_model(WHISPER_MODEL, download_root=MODELSPATH)
    for file in tqdm(covert_list, desc="Vedio to subtitles"):
        mp4_path = os.path.join("example", file)
        if not os.path.exists(mp4_path):
            print(f"[ERROR]File {mp4_path} not found")
            FileExistsError
        if mp4_path.endswith(".mp4"):
            print(f"[INFO]Converting video {mp4_path} to audio")
            audio_path = mp4_path.replace(".mp4", ".flac")
            mp3_path = vedio2audio(mp4_path, audio_path, file_coverter)
    
        if not os.path.exists(mp4_path.replace(".mp4",".srt")):
            print(f"[INFO]Model {WHISPER_MODEL} loaded")
            load_model = time.time()
            print(f"[TIME]Load model: use {load_model - load_package:.2f}s")
            vedio_srt = vedio2subtitles(ws_model, mp3_path, name=mp4_path.replace(".mp4", ""))
            covert_srt_list.append(vedio_srt)
            vedio_srt.subtitles2srt()
            # print(id(vedio_srt.subtitles))
        else:
            vedio_srt = read_subtitle(mp4_path.replace(".mp4",".srt"))
            covert_srt_list.append(vedio_srt)
            # print(id(vedio_srt.subtitles))

    del ws_model
    torch.cuda.empty_cache()

    
    asyncio.run(main(covert_srt_list))
    
    ed = time.time()
    print(f"[TIME]Total use: {ed - bg:.2f}s")

=======
"""
日志：
2025-03-02：
完成功能：
1. 视频转音频
2. 翻译输出字幕
3. 音频转文字（初步）
计划：
1. 优化音频转文字，正确切片保持句子完整性✅
2. 输出句子可能仍然不是正确的，初步使用大模型分析处理整合，再次翻译❌

2025-03-03：
完成功能：
1. 引用whisper_timestamped模块，优化音频转文字
2. 使用滑动窗口，保持上下文连贯（效果并不好）
计划：
1. 解决滑动窗口效果不好的问题，考虑字幕合并❌

2024-03-05：
完成功能：
1. 初步修复了翻译不准的问题，使用了思维链模型，放弃之前的滑动窗口，考虑了让大模型完全接受一长串上下文
计划：
1. 继续补充提示词内容保证模型输出的准确性✅
2. 可以用之后开始计划新建B站账号开始上传视频

2024-03-06:
完成功能：
1. 通过更换api运营商，阿里云换成了深度求索，速度至少快了30%，并且价格不变，甚至晚上还有优惠
2. 添加中途提示机制，进一步减少大模型道中输出错误格式的可能
3. 更换大模型输出格式为json，保证输出格式能够被格式化读取
计划：
1. 添加文件处理池结构
2. 优化代码格式，使其尽量保持高效
3. 添加翻译后文本检测特殊标记并合并字幕的功能，完善项目结构
4. 添加发现翻译后文本是空字符串后重启翻译的功能，防止出现缺译的情况
"""

import time

bg = time.time()

import os
from tqdm import tqdm
import yaml
import json
import tenacity
from openai import OpenAI
import whisper_timestamped
from utils import *
# from lang import *
import pprint

load_package = time.time()
print(f"[TIME]load package: use {load_package - bg:.2f}s")

ROOTPATH = os.path.dirname(os.path.abspath(__file__))
MODELSPATH = os.path.join(ROOTPATH, "models")
if not os.path.exists(MODELSPATH):
    os.makedirs(MODELSPATH)
WHISPER_MODEL = "medium.en"
LANGUAGE = "en"
MAX_CONTENT = 20
CROSS_TIP = 5
MAX_PROMPT_TOKEN = 2500
TIMEOUT = 600

RETRY_EXCEPTIONS = (json.decoder.JSONDecodeError)

with open(os.path.join(ROOTPATH,'dsKey.yaml'), 'r') as file:
    cfgs = yaml.safe_load(file)

# pprint.pprint(dsKey)

CLIENT = OpenAI(
    api_key=cfgs['api_key'],
    base_url=cfgs['base_url'],
)

if not os.path.exists(".cache"):
    os.makedirs(".cache")
if not os.path.exists(".cache/audio"):
    os.makedirs(".cache/audio")

file_coverter = FileCoverter(ROOTPATH)
# bert = Bert()

ws_model = whisper_timestamped.load_model(WHISPER_MODEL, download_root=MODELSPATH)
print(f"[INFO]Model {WHISPER_MODEL} loaded")

load_model = time.time()
print(f"[TIME]Load model: use {load_model - load_package:.2f}s")

@tenacity.retry(stop=tenacity.stop_after_attempt(3), retry=tenacity.retry_if_exception_type(RETRY_EXCEPTIONS))
def get_completion(_messages):
    try:
        _completion = CLIENT.chat.completions.create(
                model=cfgs["model"],
                messages=_messages,
                timeout=TIMEOUT
            )
        return _completion
    except json.decoder.JSONDecodeError as e:
        print(e.response.text)
        

def translate_subtitle(subtitles:list[Subtitle]):
    contents = Contents(maxquelen=MAX_CONTENT)
    systemprompt = [
        {
            "role": "user",
            "content": contents.system_prompt
        },
        {
            "role": "assistant",
            "content": "好的"
        }
    ]
    
    messages = systemprompt.copy()
    token_counter = TokenCounter()
    
    epochs = len(subtitles)//MAX_CONTENT
    epochs += 1 if len(subtitles)%MAX_CONTENT > 0 else 0
    # print(epochs)
    
    for i in range(1, epochs + 1):
        trans_bg = time.time()

        if i%CROSS_TIP == CROSS_TIP - 1:
            messages.append({
                "role": "user",
                "content": contents.tip
                })
            messages.append({
                "role": "assistant",
                "content": "好的"
                })

        contents.upgrade_queue(subtitles)
        content = contents.build_contents()
        
        print(f"[INFO]To translate: \"\"\"\n{content}\"\"\"\n")
        # print(prompt)
        messages.append({
            "role": "user",
            "content": content
            })
        
        completion = get_completion(messages)

        # pprint.pprint(completion)
        
        translated_completion = completion.choices[0].message.content
        print(f"[INFO]Translated:   \"\"\"\n{translated_completion}\n\"\"\"\n")
        # print(translated_completion)
        
        translated_json = json.loads(translated_completion)
        # pprint.pprint(translated_json)
        for k, v in translated_json.items():
            subtitles[int(k)].translated_text = v
            # print(k,v)
        
        messages.append({
            "role": "assistant",
            "content": translated_completion
            })
        trans_ed = time.time()

        prompt_tokens = completion.usage.prompt_tokens
        completion_tokens = completion.usage.completion_tokens
        token_counter.add(pro=prompt_tokens, com=completion_tokens)

        if prompt_tokens > MAX_PROMPT_TOKEN:
            messages.clear()
            messages = systemprompt.copy()
        
        print(f"[INFO]Token use: prompt tokens {prompt_tokens}, completion tokens {completion_tokens}, total {prompt_tokens + completion_tokens}")
        print(f"[TIME]Trans use: {trans_ed - trans_bg:.2f}s")
    
    return token_counter, subtitles


def vedio2subtitles(model, filepath: str):
    print(f"[INFO]Transcribing audio {filepath}")

    result = whisper_timestamped.transcribe(
        model, filepath, language=LANGUAGE, detect_disfluencies=True, vad=True,
    )
    return result2subtitles(result)

if __name__ == "__main__":

    mp4_path = os.path.join("example", "MIT Introduction to Deep Learning (2024) _ 6.S191.mp4")
    if not os.path.exists(mp4_path):
        print(f"[ERROR]File {mp4_path} not found")
        FileExistsError
    if mp4_path.endswith(".mp4"):
        print(f"[INFO]Converting video {mp4_path} to audio")
        audio_path = mp4_path.replace(".mp4", ".flac")
        mp3_path = vedio2audio(mp4_path, audio_path, file_coverter)

    if not os.path.exists(mp4_path.split('\\')[-1].split('.')[0] + '.srt'):
        output = vedio2subtitles(ws_model, mp3_path)
    else:
        output = read_subtitle(mp4_path.split('\\')[-1].split('.')[0] + '.srt')
    
    subtitles2srt(output, mp4_path.replace(".mp4", "").split("/")[-1])
    
    # test = read_subtitle("Can diet improve memory_ BBC News Review.srt")
    trans_bg = time.time()
    tc, output = translate_subtitle(output)
    trans_ed = time.time()

    print(f"[TIME]Trans use {trans_ed-trans_bg:.2f}s")
    
    print(f"[INFO]Token use total: pro total {tc.prompt_tokens}, com total {tc.completion_tokens}; token price is {tc.cal_price(cfgs['prompt_tokens_price'], cfgs['completion_tokens'])} RMB")
    
    subtitles2srt(output, mp4_path.replace(".mp4", ""))
>>>>>>> 0d3fdf93c1d58e13219e33da3292767f35a1749a
