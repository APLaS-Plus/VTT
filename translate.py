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
1. 优化异步处理结构✅

2024-03-08：
完成功能：
1. 优化异步拷贝，添加文件锁，深拷贝等机制，保障文件处理的安全性
2. 更改批次翻译的逻辑，添加token计算器，修改为按照token数量判断翻译批次
3. 优化异步访问机制，防止api卡住不给用
计划：
1. 异步处理中仍然有未知bug，有时候会莫名其妙保存文本为原文本，待明日再处理
2. 设置重译机制（重提）
"""

import time

bg = time.time()

import os
import filelock
import copy
import random
import warnings
import httpcore
from tqdm import tqdm
import yaml
import json
import asyncio
import tenacity
import torch
from openai import OpenAI, AsyncOpenAI, APIConnectionError
import whisper_timestamped
from utils import *

# from lang import *
import pprint

warnings.filterwarnings("ignore", category=FutureWarning)
load_package = time.time()
print(f"[TIME]load package: use {load_package - bg:.2f}s")

ROOTPATH = os.path.dirname(os.path.abspath(__file__))
MODELSPATH = os.path.join(ROOTPATH, "models")
if not os.path.exists(MODELSPATH):
    os.makedirs(MODELSPATH)
WHISPER_MODEL = "medium.en"
LANGUAGE = "en"
CROSS_TIP = 5
MAX_PROMPT_TOKEN = 2500
TIMEOUT = 600
SEMAPHORE = 8

RETRY_EXCEPTIONS = (
    json.decoder.JSONDecodeError,
    asyncio.TimeoutError,
    ConnectionError,
    httpcore.RemoteProtocolError,
    APIConnectionError,
)

API_RATE_LIMITER = RateLimiter(requests_per_minute=6)

with open(os.path.join(ROOTPATH, "dsKey.yaml"), "r") as file:
    cfgs = yaml.safe_load(file)

# pprint.pprint(dsKey)

CLIENT = AsyncOpenAI(
    api_key=cfgs["api_key"],
    base_url=cfgs["base_url"],
)

if not os.path.exists(".cache"):
    os.makedirs(".cache")
if not os.path.exists(".cache/audio"):
    os.makedirs(".cache/audio")

file_coverter = FileCoverter(ROOTPATH)
# bert = Bert()


@tenacity.retry(
    stop=tenacity.stop_after_attempt(3),
    wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),
    retry=tenacity.retry_if_exception_type(RETRY_EXCEPTIONS),
    reraise=True,
    before_sleep=lambda retry_state: print(
        f"Retry attempt {retry_state.attempt_number} after error: {retry_state.outcome.exception()}"
    ),
)
async def get_completion(_messages):
    await API_RATE_LIMITER.acquire()
    return await CLIENT.chat.completions.create(
        model=cfgs["model"], messages=_messages, timeout=TIMEOUT
    )


def vedio2subtitles(model, filepath: str, name: str) -> Subtitles:
    print(f"[INFO]Transcribing audio {filepath}")

    result = whisper_timestamped.transcribe(
        model,
        filepath,
        language=LANGUAGE,
        detect_disfluencies=True,
        vad=True,
    )
    return result2subtitles(result, name=name)


async def translate_subtitle(subtitles: Subtitles) -> TokenCounter | Subtitles:
    translated_subtitles = subtitles.copy()
    translated_subtitles.name += "_zh_CN"
    contents = Contents(subtitle_obj=translated_subtitles)
    systemprompt = [
        {"role": "user", "content": contents.system_prompt},
        {"role": "assistant", "content": "好的"},
    ]
    messages = copy.deepcopy(systemprompt)
    token_counter = TokenCounter()

    epochs = len(translated_subtitles.subtitles)
    with tqdm(total=epochs) as pbar:
        i = epochs
        while i > 0:
            trans_bg = time.time()

            if i % CROSS_TIP == CROSS_TIP - 1:
                messages.append({"role": "user", "content": contents.tip})
                messages.append({"role": "assistant", "content": "好的"})

            contents.suit_the_length_of_content()
            content = contents.build_contents()

            print(f'[INFO]To translate: """\n{content}"""\n')
            # print(prompt)
            messages.append({"role": "user", "content": content})

            await asyncio.sleep(random.uniform(0.5, 1.25))
            completion = await get_completion(messages)

            # pprint.pprint(completion)

            translated_completion = completion.choices[0].message.content
            print(f'[INFO]Translated:   """\n{translated_completion}\n"""\n')
            # print(translated_completion)

            translated_json = json.loads(translated_completion)
            # pprint.pprint(translated_json)
            for k, v in translated_json.items():
                translated_subtitles.subtitles[int(k)].text = v
                # print(k,v)

            messages.append({"role": "assistant", "content": translated_completion})
            trans_ed = time.time()

            prompt_tokens = completion.usage.prompt_tokens
            completion_tokens = completion.usage.completion_tokens
            token_counter.add(pro=prompt_tokens, com=completion_tokens)

            if prompt_tokens > MAX_PROMPT_TOKEN:
                messages.clear()
                messages = copy.deepcopy(systemprompt)

            print(
                f"[INFO]Token use: prompt tokens {prompt_tokens}, completion tokens {completion_tokens}, total {prompt_tokens + completion_tokens}"
            )
            print(f"[TIME]Trans use: {trans_ed - trans_bg:.2f}s")

            i -= contents.to_translate_queue.maxlen
            pbar.write(f"Translating {translated_subtitles.name}")
            pbar.update(contents.to_translate_queue.maxlen)

    return token_counter, translated_subtitles


async def translate_one_vedio(subtitles: Subtitles) -> None:
    transed_path = subtitles.name + "_zh_CN.srt"
    lock_path = transed_path + ".lock"
    try:
        with filelock.FileLock(lock_path, timeout=len(subtitles.subtitles) / 10 * 300):
            if not os.path.exists(transed_path):
                trans_bg = time.time()
                tc, transed_srt = await translate_subtitle(subtitles)
                trans_ed = time.time()
                print(f"[TIME]Trans use {trans_ed-trans_bg:.2f}s")
                print(
                    f"[INFO]Token use total: pro total {tc.prompt_tokens}, com total {tc.completion_tokens}; token price is {tc.cal_price(cfgs['prompt_tokens_price'], cfgs['completion_tokens'])} RMB"
                )
            else:
                print(f"[WARN]Translated srt is exsit in {transed_path}")
                transed_srt = read_subtitle(transed_path)

            transed_srt.merge_subtitles()
            transed_srt.subtitles2srt()
            print(f"[INFO]File \"{transed_srt.name + '.srt'}\" saved")
    finally:
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
            except:
                pass


async def main(cover_srt_list):
    # 使用信号量限制最大并发数
    semaphore = asyncio.Semaphore(SEMAPHORE)  # 同时最多处理3个视频

    async def limited_translate(subtitle):
        async with semaphore:
            return await translate_one_vedio(subtitle)

    await asyncio.gather(*[limited_translate(i) for i in cover_srt_list])


if __name__ == "__main__":

    covert_list = [i for i in os.listdir("example") if i.endswith(".mp4")]
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

        if not os.path.exists(mp4_path.replace(".mp4", ".srt")):
            print(f"[INFO]Model {WHISPER_MODEL} loaded")
            load_model = time.time()
            print(f"[TIME]Load model: use {load_model - load_package:.2f}s")
            vedio_srt = vedio2subtitles(
                ws_model, mp3_path, name=mp4_path.replace(".mp4", "")
            )
            covert_srt_list.append(vedio_srt)
            vedio_srt.subtitles2srt()
            # print(id(vedio_srt.subtitles))
        else:
            vedio_srt = read_subtitle(mp4_path.replace(".mp4", ".srt"))
            covert_srt_list.append(vedio_srt)
            # print(id(vedio_srt.subtitles))

    del ws_model
    torch.cuda.empty_cache()

    asyncio.run(main(covert_srt_list))

    ed = time.time()
    print(f"[TIME]Total use: {ed - bg:.2f}s")
