import time

bg = time.time()

# 导入必要的库和模块
import os
import filelock  # 用于文件锁，防止多进程同时访问同一文件
import copy
import random
import re
import warnings
import httpcore
from tqdm import tqdm  # 进度条显示
import yaml
import json
import asyncio  # 异步IO处理
import tenacity  # 重试机制
import torch
from openai import OpenAI, AsyncOpenAI, APIConnectionError
import whisper_timestamped  # 语音识别模型，带时间戳
from utils import *  # 导入自定义工具函数

# from lang import *
import pprint

# 忽略未来版本警告
warnings.filterwarnings("ignore", category=FutureWarning)
load_package = time.time()
print(f"[TIME]load package: use {load_package - bg:.2f}s")

# 设置全局常量和路径
ROOTPATH = os.path.dirname(os.path.abspath(__file__))
MODELSPATH = os.path.join(ROOTPATH, "models")
if not os.path.exists(MODELSPATH):
    os.makedirs(MODELSPATH)
WHISPER_MODEL = "medium.en"  # Whisper模型类型
LANGUAGE = "en"  # 源语言
CROSS_TIP = 5  # 每处理N个批次后提醒一次
MAX_PROMPT_TOKEN = 2500  # 最大prompt令牌数量
TIMEOUT = 600  # API超时设置(秒)
SEMAPHORE = 8  # 最大并发处理数量

# 定义需要重试的异常类型
RETRY_EXCEPTIONS = (
    json.decoder.JSONDecodeError,
    asyncio.TimeoutError,
    ConnectionError,
    httpcore.RemoteProtocolError,
    APIConnectionError,
)

# 创建API速率限制器，限制每分钟请求次数
API_RATE_LIMITER = RateLimiter(requests_per_minute=6)

# 从配置文件加载API密钥和基础URL
with open(os.path.join(ROOTPATH, "dsKey.yaml"), "r") as file:
    cfgs = yaml.safe_load(file)

# pprint.pprint(dsKey)

# 初始化异步OpenAI客户端
CLIENT = AsyncOpenAI(
    api_key=cfgs["api_key"],
    base_url=cfgs["base_url"],
)

# 创建缓存目录
if not os.path.exists(".cache"):
    os.makedirs(".cache")
if not os.path.exists(".cache/audio"):
    os.makedirs(".cache/audio")

# 初始化文件转换器
file_converter = FileConverter(ROOTPATH)
# bert = Bert()


def video2subtitles(
    model, filepath: str, name: str
) -> Subtitles:  # 修正拼写错误：vedio -> video
    """
    使用Whisper模型将视频/音频转换为字幕

    参数:
        model: 加载的Whisper模型
        filepath: 音频文件路径
        name: 输出字幕文件名(不含扩展名)

    返回:
        Subtitles对象，包含识别的字幕数据
    """
    print(f"[INFO]Transcribing audio {filepath}")

    result = whisper_timestamped.transcribe(
        model,
        filepath,
        language=LANGUAGE,
        detect_disfluencies=True,  # 检测语音中的停顿和填充词
        vad=True,  # 使用语音活动检测
    )
    return result2subtitles(result, name=name)


@tenacity.retry(
    stop=tenacity.stop_after_attempt(3),  # 最多重试3次
    wait=tenacity.wait_exponential(multiplier=1, min=2, max=10),  # 指数退避策略
    retry=tenacity.retry_if_exception_type(RETRY_EXCEPTIONS),  # 指定需要重试的异常类型
    reraise=True,  # 重试失败后抛出原始异常
    before_sleep=lambda retry_state: print(
        f"Retry attempt {retry_state.attempt_number} after error: {retry_state.outcome.exception()}"
    ),
)
async def get_completion(_messages):
    """
    异步调用OpenAI API获取翻译结果

    参数:
        _messages: 发送给API的消息列表

    返回:
        元组(原始完成对象, 文本完成内容, 解析后的JSON)
    """
    await API_RATE_LIMITER.acquire()  # 获取API使用权限
    _completion = await CLIENT.chat.completions.create(
        model=cfgs["model"], messages=_messages, timeout=TIMEOUT
    )
    _translated_completion = re.sub("\n", "", _completion.choices[0].message.content)
    print(f'[INFO]Translated:   """\n{_translated_completion}\n"""\n')
    # print(translated_completion)
    _translated_json = json.loads(_translated_completion)
    return _completion, _translated_completion, _translated_json


async def translate_subtitle(subtitles: Subtitles) -> TokenCounter | Subtitles:
    """
    翻译字幕内容

    参数:
        subtitles: 需要翻译的Subtitles对象

    返回:
        元组(token计数器, 已翻译的字幕对象)
    """
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
    with tqdm(total=epochs, leave=True, position=0) as pbar:
        i = epochs
        while i > 0:
            trans_bg = time.time()

            # 定期添加提示词，防止AI忘记翻译规则
            if i % CROSS_TIP == CROSS_TIP - 1:
                messages.append({"role": "user", "content": contents.tip})
                messages.append({"role": "assistant", "content": "好的"})

            # 准备待翻译内容
            contents.suit_the_length_of_content()
            content = contents.build_contents()

            print(f'[INFO]To translate: """\n{content}"""\n')
            # print(prompt)
            messages.append({"role": "user", "content": content})

            # 添加随机延迟，避免API调用过于频繁
            await asyncio.sleep(random.uniform(0.5, 1.25))
            completion, translated_completion, translated_json = await get_completion(
                messages
            )

            # 更新已翻译字幕
            lated_item = 0
            for k, v in translated_json.items():
                k = int(k)
                lated_item = max(lated_item, k)
                translated_subtitles.subtitles[k].text = v
            contents.idx = lated_item + 1

            # 添加AI回复到消息历史
            messages.append({"role": "assistant", "content": translated_completion})
            trans_ed = time.time()

            # 计算token使用情况
            prompt_tokens = completion.usage.prompt_tokens
            completion_tokens = completion.usage.completion_tokens
            token_counter.add(pro=prompt_tokens, com=completion_tokens)

            # 当prompt令牌数过多时，清空历史对话减轻负担
            if prompt_tokens > MAX_PROMPT_TOKEN:
                messages.clear()
                messages = copy.deepcopy(systemprompt)

            print(
                f"[INFO]Token use: prompt tokens {prompt_tokens}, completion tokens {completion_tokens}, total {prompt_tokens + completion_tokens}"
            )
            print(f"[TIME]Trans use: {trans_ed - trans_bg:.2f}s")

            # 更新进度条
            i -= contents.to_translate_queue.maxlen
            pbar.write(f"Translating {translated_subtitles.name}")
            pbar.update(contents.to_translate_queue.maxlen)

    return token_counter, translated_subtitles


async def check_translated(_translated_subtitles: Subtitles) -> Subtitles:
    """
    检查并修复已翻译字幕中的问题，确保每个字幕都已被翻译成中文

    参数:
        _translated_subtitles: 待检查的字幕对象

    返回:
        修复后的字幕对象
    """
    base_messages = [
        {
            "role": "user",
            "content": """
你是一个翻译助手，你会将我接下来说的每一句英文翻译成简体中文，并且不包含任何的注释和说明，也不要展示你的思考过程。你将接收到的语句有可能是破碎的，你只需翻译他可以代表的意思即可。你的回复字数不应该超过50字。在你准备好后，请回答： 我准备好了
        """,
        },
        {"role": "assistant", "content": "我准备好了"},
    ]

    # 检测文本是否包含中文字符
    def is_chinese(text):
        for char in text:
            if "\u4e00" <= char <= "\u9fff":
                return True
        return False

    # 简单的聊天请求封装
    async def simple_chat(messages):
        await API_RATE_LIMITER.acquire()
        asyncio.sleep(random.uniform(0.5, 1.25))
        _completion = await CLIENT.chat.completions.create(
            model=cfgs["model"], messages=messages, timeout=TIMEOUT
        )
        return re.sub("\n", "", _completion.choices[0].message.content)

    # 合并相邻的已翻译字幕
    _translated_subtitles.merge_subtitles()
    for i in _translated_subtitles.subtitles:
        if i.text == "":
            print(f"[WARN]Subtitle {i.index} is empty, should be deleted")
            _translated_subtitles.subtitles.remove(i)

    # 重新设置索引并检查是否需要重新翻译
    for i in range(len(_translated_subtitles.subtitles)):
        _translated_subtitles.subtitles[i].index = i
        # 当翻译后文本全是英文时，重新翻译
        if not is_chinese(_translated_subtitles.subtitles[i].text):
            messages = copy.deepcopy(base_messages)
            messages.append(
                {"role": "user", "content": _translated_subtitles.subtitles[i].text}
            )
            print(
                f'[INFO]Subtitle {i} is to be translated, content is "{_translated_subtitles.subtitles[i].text}"'
            )
            _translated_subtitles.subtitles[i].text = await simple_chat(messages)

            print(
                f"[INFO]Subtitle {i} is translated to {_translated_subtitles.subtitles[i].text}"
            )

    return _translated_subtitles


async def translate_one_video(
    subtitles: Subtitles,
) -> None:
    """
    处理单个视频的字幕翻译过程

    参数:
        subtitles: 待翻译的字幕对象

    包含文件锁处理，确保多进程下安全处理同一个视频
    """
    transed_path = subtitles.name + "_zh_CN.srt"
    lock_path = transed_path + ".lock"
    try:
        # 使用文件锁防止多个进程同时处理同一个视频
        with filelock.FileLock(lock_path, timeout=len(subtitles.subtitles) / 10 * 300):
            if not os.path.exists(transed_path):
                # 如果翻译结果不存在，进行翻译
                trans_bg = time.time()
                tc, transed_srt = await translate_subtitle(subtitles)
                trans_ed = time.time()
                print(f"[TIME]Trans use {trans_ed-trans_bg:.2f}s")
                print(
                    f"[INFO]Token use total: pro total {tc.prompt_tokens}, com total {tc.completion_tokens}; token price is {tc.cal_price(cfgs['prompt_tokens_price'], cfgs['completion_tokens'])} RMB"
                )
            else:
                # 如果翻译结果已存在，直接读取
                print(f"[WARN]Translated srt is exsit in {transed_path}")
                transed_srt = read_subtitle(transed_path)

            # 检查和修复翻译结果
            transed_srt = await check_translated(transed_srt)
            # 保存为SRT文件
            transed_srt.subtitles2srt()
            print(f"[INFO]File \"{transed_srt.name + '.srt'}\" saved")
    finally:
        # 确保删除锁文件
        if os.path.exists(lock_path):
            try:
                os.remove(lock_path)
            except:
                pass


async def main(convert_srt_list):
    """
    主异步处理函数，使用信号量控制并发处理的视频数量

    参数:
        convert_srt_list: 待处理的字幕列表
    """
    # 使用信号量限制最大并发数
    semaphore = asyncio.Semaphore(SEMAPHORE)  # 同时最多处理SEMAPHORE个视频

    async def limited_translate(subtitle):
        """使用信号量限制并发的翻译函数"""
        async with semaphore:
            return await translate_one_video(subtitle)

    # 并发执行所有翻译任务
    await asyncio.gather(*[limited_translate(i) for i in convert_srt_list])


if __name__ == "__main__":
    # 程序主入口

    # 获取需要处理的视频文件列表
    convert_list = [
        i for i in os.listdir("example") if i.endswith(".mp4")
    ]
    convert_srt_list = []

    # 加载Whisper模型
    ws_model = whisper_timestamped.load_model(WHISPER_MODEL, download_root=MODELSPATH)

    # 处理每个视频文件
    for file in tqdm(
        convert_list, desc="Video to subtitles"
    ):
        mp4_path = os.path.join("example", file)
        if not os.path.exists(mp4_path):
            print(f"[ERROR]File {mp4_path} not found")
            FileExistsError

        # 如果是MP4文件，先转为音频文件
        if mp4_path.endswith(".mp4"):
            print(f"[INFO]Converting video {mp4_path} to audio")
            audio_path = mp4_path.replace(".mp4", ".flac")
            mp3_path = video2audio(
                mp4_path, audio_path, file_converter
            )
        
        if not os.path.exists(mp4_path.replace(".mp4", ".srt")):
            print(f"[INFO]Model {WHISPER_MODEL} loaded")
            load_model = time.time()
            print(f"[TIME]Load model: use {load_model - load_package:.2f}s")
            video_srt = video2subtitles(
                ws_model, mp3_path, name=mp4_path.replace(".mp4", "")
            )
            convert_srt_list.append(
                video_srt
            )
            video_srt.subtitles2srt()  # 修正拼写错误：vedio_srt -> video_srt
        else:
            # 如果字幕文件存在，直接读取
            video_srt = read_subtitle(
                mp4_path.replace(".mp4", ".srt")
            )
            convert_srt_list.append(
                video_srt
            )

    # 释放模型内存
    del ws_model
    torch.cuda.empty_cache()

    # 异步处理所有字幕翻译任务
    asyncio.run(
        main(convert_srt_list)
    )

    # 计算总耗时
    ed = time.time()
    print(f"[TIME]Total use: {ed - bg:.2f}s")
