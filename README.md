# lyco-sub · 字幕生成工作台

转录 → 翻译 → 烧录。**本地推理优先，人类和 AI 都能用。**

架构参考 [rembg-ui](https://github.com/lilyco-42/rembg-ui)：FastAPI 只做后端，前端单文件 HTML，
CLI 与 HTTP 共用同一套 `core.pipeline`，不存在两套逻辑。

```
┌──────────────── FastAPI（仅提供服务）────────────────┐
│  /api/capabilities  /api/jobs  /api/probe  ...      │
└────────────────────────┬────────────────────────────┘
                         │ http://127.0.0.1:8043
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   桌面浏览器        手机浏览器          CLI / AI Agent
   （自动打开）      （同一 WiFi）      （lycosub ... --json）
```

---

## 为什么不是直接用 VideoCaptioner

调研阶段实测过它（见 [实测报告](#)），结论是**能用的部分自己实现更划算**：

| 问题 | 影响 |
|---|---|
| GPL-3.0 | 直接 import 会传染，闭源分发/商业授权不合法 |
| 私有接口 + 第三方签名中转 | 剪映引擎的签名走 `asrtools-update.bkfeng.top`，是个人中转服务 |
| 免费翻译通道已死 | 必应 auth 404、谷歌 429，实际只能上 LLM |
| 默认 CRF 28 | 153MB 源片烧完只剩 3MB |

所以这里**只借鉴它的协议知识，不链接它的代码**，引擎层按 MIT 自己写。

---

## 快速开始

```bash
uv venv .venv --python 3.11
uv pip install --python .venv/Scripts/python.exe -e .

# 装一个本地 ASR 引擎（二选一）
uv pip install --python .venv/Scripts/python.exe funasr modelscope torch torchaudio
uv pip install --python .venv/Scripts/python.exe faster-whisper
```

需要 **ffmpeg / ffprobe 在 PATH 中**。

```bash
.venv/Scripts/python.exe cli.py engines     # 先看哪些引擎可用
.venv/Scripts/python.exe cli.py serve       # 打开 Web 界面
```

---

## 引擎

| 引擎 | 类型 | 依赖 | 实测 |
|---|---|---|---|
| `funasr` | 本地 | funasr + torch | RTF 0.052，64s 音频 3.8s，**带标点**，默认 |
| `whisper` | 本地 | faster-whisper | CPU 上 large-v3 需 39s，中文专名易错、可能输出繁体 |
| `jianying` | 云端 | 无 | 中文专名最准、9s 出稿，但**私有接口，默认关闭** |

### 关于 jianying 引擎的风险（务必读完）

1. 走的是**剪映 PC 端私有接口**，不是公开 API，没有 SLA，字节随时可能改协议。
2. 请求签名依赖**第三方中转服务**（默认 `asrtools-update.bkfeng.top`），
   你的音频元数据会经过它。可用 `LYCOSUB_JY_SIGN_URL` 换成自建签名器。
3. 因此**默认不启用**，必须显式：

```bash
set LYCOSUB_ENABLE_JIANYING=1     # Windows
export LYCOSUB_ENABLE_JIANYING=1  # Linux/macOS
```

离线引擎才是默认路径。

---

## CLI（AI / 脚本优先）

```bash
lycosub engines                          # 引擎状态
lycosub probe demo.mp4 --json            # 探测媒体
lycosub transcribe demo.mp4 --engine funasr --json
lycosub translate a.srt --to en --json
lycosub run demo.mp4 --engine funasr --to en --burn hard --quality ultra --json
lycosub serve --lan                      # 手机同 WiFi 访问
```

**给 agent 的契约：**

- 进度和日志一律走 **stderr**，**stdout 只放结果**；
- `--json` 时 stdout 是一个稳定结构的 JSON 对象；
- 退出码：`0` 成功 / `1` 运行失败 / `2` 用法错误 / `3` 引擎不可用 / `4` 输入不存在；
- 所有命令支持 `--dry-run`，先看会做什么再执行。

---

## HTTP API

```bash
# 一次拿到全部能力，AI 用这个决定调什么
curl http://127.0.0.1:8043/api/capabilities

# 提交任务（本地路径，免上传）
curl -X POST http://127.0.0.1:8043/api/jobs/by-path \
  -H "Content-Type: application/json" \
  -d '{"path":"D:/v/demo.mp4","asr_engine":"funasr","burn_mode":"hard"}'

# 轮询
curl http://127.0.0.1:8043/api/jobs/<job_id>
```

任务在服务端**串行执行**——模型加载要吃几百 MB 到 GB 内存，并发只会互相拖慢并 OOM。
这是实测取舍，不是偷懒。

---

## 烧录的代价（实测数据）

| 项 | 实测 |
|---|---|
| 硬字幕 = 整片重编码 | 153.4MB 源片，`medium` 档压到 3.0MB |
| `ultra`(CRF 18) | 字幕带以外 PSNR 25.4dB（纯转码基线 55.3dB） |
| libass 偏色 | 全画面平均偏差 1.18/255，p99=8 |

**要绝对保真 → 用软字幕**（`--burn soft`，画面零重编码）。
**要直接能发 → 用硬字幕**，但请用 `--quality ultra`。

---

## 配置

全部可用环境变量覆盖：

| 变量 | 默认 | 说明 |
|---|---|---|
| `LYCOSUB_LLM_API_KEY` | 空 | LLM 翻译用，也读 `OPENAI_API_KEY` |
| `LYCOSUB_LLM_API_BASE` | api.openai.com/v1 | 任意 OpenAI 兼容端点 |
| `LYCOSUB_LLM_MODEL` | gpt-4o-mini | |
| `LYCOSUB_ASR_ENGINE` | funasr | |
| `LYCOSUB_ENABLE_JIANYING` | 未设 | 设为 1 才启用剪映引擎 |
| `LYCOSUB_HOST` / `LYCOSUB_PORT` | 127.0.0.1 / 8043 | |
| `LYCOSUB_HOME` | ~/.lyco-sub | 任务与上传目录 |

---

## 翻译

**免费通道已经全部失效**（实测：必应 auth 端点 404、谷歌 429），
所以只保留 LLM 一条可靠路径，接口留成可插拔。

```bash
set LYCOSUB_LLM_API_KEY=sk-...
lycosub translate a.srt --to en
```

翻译按批请求、强制返回 JSON 数组；**行数对不上时会补齐或截断，绝不静默错位**。

---

## 测试

```bash
.venv/Scripts/python.exe -m unittest discover -s tests -v
```

12 个用例，覆盖 SRT 解析/回写、质量度量、引擎注册、Windows 滤镜转义、
以及**"剪映引擎必须默认关闭"这条安全约束**。

---

## 目录

```
lyco-sub/
├── cli.py              # 命令行入口
├── server.py           # FastAPI 入口
├── core/
│   ├── asr/            # 引擎：funasr / whisper / jianying
│   ├── translate/      # 翻译器（LLM）
│   ├── render/         # 软/硬字幕合成
│   ├── pipeline.py     # 端到端管线（CLI 和 HTTP 共用）
│   ├── jobs.py         # 串行任务队列
│   ├── subtitles.py    # SRT 读写 + 质量度量
│   └── media.py        # ffmpeg/ffprobe 封装
├── frontend/index.html # 单文件 UI
└── tests/
```
