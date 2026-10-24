# lyco-sub 平台矩阵与超前规划

这张表把「代码能跑」「能构建」「已验证」分开。不要把它当成已交付的承诺。

## 当前状态

| 平台 | 运行方式 | 交付格式 | 状态 | 验证程度 |
|---|---|---|---|---|
| Windows x64 | 源码 venv | — | ✅ 完整可用 | **已实测**：转录/翻译/烧录/HTTP/CLI |
| Windows x64 | Nuitka | `lycosub-windows.zip` | 🔧 脚本就绪 | 未跑完整构建（冷构建约 60–90min） |
| Linux x64 | 源码 venv | — | ⚠️ 理论可用 | **未实测**（无 Linux 环境） |
| Linux x64 | Nuitka | `lycosub-linux.tar.gz` | 🔧 脚本就绪 | 未跑 |
| macOS arm64/x64 | Nuitka | `.app.zip` | 🔧 脚本就绪 | 未跑 |
| Android | PWA（浏览器） | 可安装 Web App | 📋 规划中 | 未开始 |
| Android | 原生 | APK/AAB | 📋 规划中 | 未开始 |
| iOS | PWA | Safari 网页 | 📋 规划中 | 未开始 |

## 关键技术决策：为什么桌面包不带 torch

实测数据（Ryzen 7 8845HS，无 GPU）：

| 方案 | 依赖体积 | import 耗时 | 模型加载 | 可打包性 |
|---|---|---|---|---|
| funasr + torch | 1,084MB | **13s** | 5s（无punc）/ 31s（有punc） | ❌ 冷构建 179min+ |
| **sherpa-onnx** | **27MB** | **0.1s** | <1s | ✅ 纯 ONNX Runtime |

**结论：桌面包默认走 sherpa-onnx，不装 torch。**
需要 funasr 高级功能（标点、多模型）的用户用源码版。

模型不进安装包（paraformer int8 = 227MB），首次使用时下载到
`~/.lycosub/models/`。这样安装包能控制在 100MB 以内，
也避免 GitHub Release 单资产 2GiB 上限（rembg-ui 踩过 422 失败）。

## Android 三条路线（按投入从低到高）

### 路线 A：PWA（推荐先做）
- 现有前端已是单文件 HTML，加 manifest + Service Worker 即可安装；
- 推理走后端 HTTP（手机连同一 WiFi 或公网）；
- 成本：1 天；限制：必须联网到桌面端。

### 路线 B：sherpa-onnx Android AAR
- sherpa-onnx 官方提供 Android AAR，支持 onnx 模型端侧推理；
- 用 Kotlin/Java 壳 + 现有 Python 逻辑重写核心（字幕读写、ffmpeg 调用）；
- 成本：2–3 周；限制：烧录需要 ffmpeg-kit（Android 上有现成库）。

### 路线 C：Termux / Chaquopy 跑 Python
- 直接复用 Python 代码，但打包复杂、体验差；
- **不推荐**，只在内部测试用。

## CI 策略

`.github/workflows/build.yml`：
- `tests` job 先跑单测，不过就不出产物；
- `build-windows` 算出版本 tag，Linux/macOS **复用同一个 tag**
  （rembg-ui 踩过：靠 tag push 触发二次 workflow 不会生效，因为
  GITHUB_TOKEN push 的 tag 不触发新 run）；
- 三个平台都**只装轻量依赖**，不装 torch。

## 暂不宣称的目标

- **Windows ARM64 / Linux aarch64**：sherpa-onnx 有 wheel 但未验证，
  等真实设备再排期。
- **原生 iOS**：需要 Swift + ONNX Runtime Mobile 壳，不能由 Python 交叉编译。
- **HarmonyOS**：无成熟 Python/ONNX 链路。

## 签名与分发

当前 CI 产出**未签名**产物，适合内部测试。
正式分发需要：
- Windows：Authenticode 证书；
- macOS：Developer ID + 公证（否则用户要右键打开）；
- Android：keystore（`LYCOSUB_ANDROID_KEYSTORE_BASE64` secret）。
