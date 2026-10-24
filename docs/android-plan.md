# Android / 移动端规划

## 已实现：PWA（阶段 1，零额外成本）

手机浏览器打开 → 「添加到主屏幕」→ 当 App 用。

已落地的东西：
- `/manifest.webmanifest`：standalone 显示、主题色、快捷方式
- `/sw.js`：外壳 cache-first，**API 请求永不缓存**（避免拿到过期任务状态）
- `/icon.svg`：内联生成，不依赖 PIL（少一个打包依赖）
- `index.html` 注册 SW + apple-touch-icon

⚠️ **Service Worker 只在 https 或 localhost 生效。** 手机通过局域网
`http://192.168.x.x:8043` 访问时注册会被浏览器拒绝，这是浏览器安全限制，
不是 bug。局域网下页面照常能用，只是不能离线。

**推理仍在桌面端**，手机是遥控器 + 预览。适合「手机拍完直接传桌面处理」。

## 为什么 Android 不能直接复用桌面包

| 桌面假设 | Android 现实 |
|---|---|
| `subprocess` 调 ffmpeg | 需要 ffmpeg-kit 或 MediaCodec |
| 文件系统任意读写 | 分区存储，只能访问授权目录 |
| 模型放 `~/.lycosub` | 沙箱目录，卸载即删 |
| Nuitka 打包 Python | 需要 Chaquopy 或重写 |

## 阶段 2：端侧推理（2–3 周）

sherpa-onnx 提供 Android AAR，是唯一现实的端侧路径：

```gradle
implementation("com.k2-fsa.sherpa.onnx:sherpa-onnx:1.10.0")
```

需要重写（Python → Kotlin）：
- `core/subtitles.py`：SRT 读写 + 度量（纯逻辑，最易移植）
- `core/media.py`：ffmpeg → ffmpeg-kit-android
- `core/render/burn.py`：ffmpeg 滤镜 → ffmpeg-kit 的 `subtitles` 滤镜
- `core/asr/sherpa_engine.py`：直接调 AAR

**不用重写**：`core/translate/llm.py`（纯 HTTP）、`core/pipeline.py`（编排）。

⚠️ 注意 `sherpa_engine.py` 里的分片逻辑（`LYCOSUB_CHUNK_SEC`，默认 20s）
必须一起移植 —— 实测长音频一次性喂给 sense-voice 会丢内容（64s 音频只出 72 字，
按 20s 切片后出 141 字）。

## 阶段 3：模型分发

- sense-voice int8 = 228MB，**不能塞进 APK**（Play 上限 200MB）；
- 用 Play Asset Delivery，或首次启动下载 + 断点续传（后端已实现）；
- 国内下载速度实测 0.44–0.81 MB/s，228MB 要 5–8 分钟，必须给进度提示。

## 风险

| 风险 | 缓解 |
|---|---|
| ffmpeg-kit 已归档（2025） | 改用 Media3 Transformer，或自带 ffmpeg 二进制 |
| 端侧推理发热/耗电 | 限制并发，长视频分片 |
| 模型下载失败 | 镜像源 + 断点续传（已实现） |
| SVG 图标在旧 Android WebView 不显示 | 加 PNG 兜底（需要 Pillow，权衡后再决定） |
