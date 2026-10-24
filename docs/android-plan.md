# Android 兼容规划

## 为什么 Android 不能直接复用桌面包

| 桌面假设 | Android 现实 |
|---|---|
| `subprocess` 调 ffmpeg | 需要 ffmpeg-kit 或 MediaCodec |
| 文件系统任意读写 | 分区存储，只能访问授权目录 |
| 模型放 `~/.lycosub` | 沙箱目录，且卸载即删 |
| Nuitka 打包 Python | 需要 Chaquopy 或重写 |

## 阶段 1：PWA（1 天，建议先做）

现有 `frontend/index.html` 已是单文件，只需：

1. 加 `manifest.webmanifest`（name/icons/display:standalone）；
2. 加 Service Worker 缓存壳；
3. 后端加 `/api/pwa/manifest` 动态生成（按 LAN IP）。

**推理仍在桌面端**，手机只是遥控器 + 预览。适合「手机拍完直接传桌面处理」。

## 阶段 2：端侧推理（2–3 周）

sherpa-onnx 提供 Android AAR：

```gradle
implementation("com.k2-fsa.sherpa.onnx:sherpa-onnx:1.10.0")
```

需要重写的部分（Python → Kotlin）：
- `core/subtitles.py`：SRT 读写 + 度量（纯逻辑，易移植）
- `core/media.py`：ffmpeg → ffmpeg-kit-android
- `core/render/burn.py`：ffmpeg 滤镜 → ffmpeg-kit 的 `subtitles` 滤镜
- `core/asr/sherpa_engine.py`：直接调 AAR，模型放 assets 或首次下载

**不用重写**：`core/translate/llm.py`（纯 HTTP）、`core/pipeline.py`（编排逻辑）。

## 阶段 3：模型分发

- paraformer int8 = 227MB，**不能塞进 APK**（Play 上限 200MB，且用户流量成本高）；
- 用 Play Asset Delivery 或首次启动下载；
- 小模型选项：sense-voice int8 约 170MB，支持中英日韩粤。

## 风险

| 风险 | 缓解 |
|---|---|
| ffmpeg-kit 已停止维护（2025 归档） | 改用 Media3 Transformer，或自带 ffmpeg 二进制 |
| 端侧推理发热/耗电 | 限制并发，长视频分片 |
| 模型下载失败 | 提供镜像源 + 断点续传（已在 `sherpa_engine.py` 实现） |
