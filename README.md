# omarchy-dynamic-weather-wallpaper

**针对个人用户的环境不停生成新的动态壁纸的桌面插件**——持续感知你所在城市的天气、气温、时段与节气，基于你的基准照片用 AI 生成氛围壁纸并自动切换（懒加载缓存，同标签组合只生成一次）。

主流程：读温度 + 时间 + 天气 → 基准图 + AI 生成 → 系统自动切换。国内/国外双通道自动探测。

为 Omarchy (Arch + Hyprland) 而生，同时兼容 **macOS**（当前主力支持）与 **Windows**（基础支持）。仅依赖 Python 3 标准库，无任何 pip 依赖。

## 主流程

```
初始化: wget google.com 思路的网络探测 ──通──> 国外通道 (open-meteo 免key天气)
                        └──不通──> 国内通道 (itboy 免key天气, 失败自动回落 open-meteo)
              ┌────────────────────────────────────────────────┐
每轮循环:    读天气 → 天气tag化 + 温度范围化 + 时段分桶 + 节气 → 组合文件名
              │      westlake_rain_1216_20-25_springbegin.jpg
              ├─ 缓存已有(懒加载) ──> 直接使用
              └─ 缓存没有 ──> 基准图 + prompt 调 OpenAI 兼容生图接口(images/edits)
                                     └──> 保存到壁纸库 → 自动切换系统壁纸
```

## 快速开始 (macOS)

方式一：**DMG 安装（标准分发）**：

```bash
./build-mac.sh dmg          # 构建 dist/WeatherDynamic-<版本>.dmg
open dist/                  # 双击 DMG -> 将 WeatherDynamic 拖入 Applications
# 或直接下载 GitHub Release 页面的 DMG
```

方式二：App + 开机自启（LaunchAgent，登录自启 + 崩溃自动拉起）：

```bash
./build-mac.sh install      # 构建 dist/WeatherDynamic.app -> 拷贝到 /Applications -> 安装 LaunchAgent
open http://127.0.0.1:8765  # 设置后台
./build-mac.sh uninstall    # 停止自启动并删除应用(配置与壁纸保留)
```

方式二：源码直接运行：

```bash
./run.sh init          # 探测国内/国外通道，生成默认配置
./run.sh serve         # 启动设置后台 + 自动循环
open http://127.0.0.1:8765
```

在设置后台上传一张**基准图**（如 `westlake.jpg`），填好生图 API 后点「立即刷新一轮」即可看到效果。源码方式的自启动：`./install.sh mac` / 卸载 `./install.sh remove`。

## 设置后台 (http://127.0.0.1:8765)

界面默认英文，可一键切换中文（右上角 EN / 中文）。按功能分四个 Tab：

| Tab | 内容 |
|---|---|
| Status | 运行状态 + 常用操作（立即刷新 / 强制重新生图 / 探测通道 / 测试天气）+ 日志 |
| Base & AI | 上传/管理基准图（点击生效、右键删除）+ **自动生成基准图弹窗**（描述场景→文生图并生效）+ 生图配置（Base URL / Key / 模型 / Prompt） |
| Advanced | 分步引导：① 网络通道+代理 ② 天气源+城市（选 QWeather/OpenWeatherMap 才显示 Key 输入框，附获取步骤）③ 目标显示器（多显示器勾选）④ 刷新与命名规则 ⑤ 显示语言 |
| Gallery | **两层壁纸库**：上层按基准图分组切换，下层展示基于该基准图生成的壁纸，点击立即应用 |

**多显示器**：Advanced → 目标显示器，可勾选壁纸应用到哪几台（macOS 按显示名列出各桌面/空间，附当前壁纸名便于辨认；默认全部）。

城市选择：先选国家（中国 41 城 / 美国 20 城 / 其他自定义），再选城市；支持 **IP 自动定位**（走 ip-api，强制直连不经代理）。中国城市会自动带上 itboy 城市码，国外城市走 open-meteo geocoding。

城市选择：先选国家（中国 41 城 / 美国 20 城 / 其他自定义），再选城市；支持 **IP 自动定位**（走 ip-api，强制直连不经代理）。中国城市会自动带上 itboy 城市码，国外城市走 open-meteo geocoding。

## 文件命名规则（懒加载缓存键）

```
{基准图}_{天气}_{时段}_{温度}_{节气}.jpg
westlake_rain_1216_20-25_springbegin.jpg
```

| 标签 | 说明 | 示例 |
|---|---|---|
| 天气 tag | sunny / cloudy / overcast / rain / heavyrain / snow / thundershower / fog / haze / drizzle / partlycloudy / wind | `rain` |
| 时段 | 默认 4 小时一桶，起止小时拼 4 位（可配 `time_bucket_hours`） | `1216` |
| 温度 | `band` 模式：当前温度按 5℃ 区间量化；`minmax` 模式：当日最低-最高 | `20-25` / `12-23` |
| 节气 | 二十四节气英文标签，内置寿星公式计算 | `springbegin`(立春) / `colddew`(寒露) |

同样的标签组合只生成一次，命中缓存零成本切换——天气/时段/温度/节气任一变化才会触发新的 AI 生图。

## 天气源

| 源 | 通道 | Key | 说明 |
|---|---|---|---|
| itboy | 国内 | 免 key | 中国气象局数据（个人维护，走 http），失败自动回落 open-meteo |
| open-meteo | 国外 | 免 key | 含 geocoding，国内多数网络也可直连 |
| 和风天气 QWeather | 国内 | 免费申请 | 数据更稳，见下方获取步骤 |
| OpenWeatherMap | 国外 | 免费申请 | 见下方获取步骤 |

默认 `auto`：国内通道用 itboy、国外通道用 open-meteo，都无需 Key。需要 Key 的源获取方式：

- **和风天气**：打开 [console.qweather.com](https://console.qweather.com) → 注册登录 → 控制台「项目管理」创建项目并生成凭据 → 复制 Key 填入设置页；新版账号会同时分配专属 **API Host**（形如 `abcxxx.re.qweatherapi.com`），一并填入「和风天气 API Host」输入框。免费订阅每日 1000 次。
- **OpenWeatherMap**：打开 [home.openweathermap.org](https://home.openweathermap.org) → 注册 → 「API keys」页直接复制 Key（约 10 分钟生效）。免费档 60 次/分钟。

生图接口为 OpenAI 兼容 `images/edits`（有基准图时）与 `images/generations`（无基准图时），`base_url` 可指向任意兼容服务（官方、中转站、自建网关均可）。未配置 API Key 时自动降级：直接以基准图本身作为壁纸，主流程依旧跑通。

## 平台支持

| 平台 | 壁纸切换方式 | 状态 |
|---|---|---|
| macOS | `osascript` 按显示器/桌面设置（System Events → Finder 回落） | ✅ 主力支持 |
| Omarchy / Linux | `swww` → `hyprpaper(hyprctl)` → `gsettings` → `feh` 自动探测 | ✅（Linux 侧标准工具链） |
| Windows | PowerShell `SystemParametersInfo` | ⚠️ 基础支持，未实测 |

Linux/Omarchy 安装：`./install.sh linux`（systemd 用户服务，无 systemd 时提示 Hyprland `exec-once` 写法）。

## 分发签名说明

`build-mac.sh` 自动探测钥匙串中的 **Developer ID Application** 证书：

- **有证书**：`codesign --options runtime --timestamp` 正式签名，配合公证（`xcrun notarytool submit`）后其他人可直接双击运行。
  证书申请：Xcode → Settings → Accounts → 登录 Apple Developer（付费账号）→ Manage Certificates → ➕ → **Developer ID Application**；
  公证凭据：`xcrun notarytool store-credentials <profile> --apple-id <id> --team-id <team>`。
- **无证书**：ad-hoc 签名，本机可直接运行；其他人首次打开需 **右键 → 打开**（或系统设置中允许）。

## 常用命令

```bash
./run.sh init                          # 初始化+探测
./run.sh serve                         # 设置后台+循环(推荐)
./run.sh daemon                        # 仅循环(无后台页面)
./run.sh once                          # 只跑一轮(不切壁纸)
./run.sh once --apply                  # 只跑一轮并切换壁纸
./run.sh status                        # 状态(JSON)
./run.sh set-wallpaper <file>          # 手动设一张
python3 -m unittest discover -s tests  # 单元测试
```

## 目录与配置

| 路径 | 用途 |
|---|---|
| `~/Library/Application Support/omarchy-dynamic-wallpaper/` (mac) | 配置与基准图 |
| `~/.config/omarchy-dynamic-wallpaper/` (linux) | 同上 |
| `~/.cache/omarchy-dynamic-wallpaper/wallpapers/` | 两层壁纸库：`{基准图前缀}/生成图.jpg`（懒加载缓存，旧扁平结构自动迁移） |
| `~/.cache/omarchy-dynamic-wallpaper/state.json` | 运行状态（含区域探测缓存） |

配置见 `config.example.json`；Prompt 模板默认英文（可改中文），多语言占位符：`{weather_name}` `{weather_en}` `{weather_cn}` `{weather}` `{temp}` `{temp_min}` `{temp_max}` `{hours}` `{solarterm_name}` `{solarterm_en}` `{solarterm_cn}` `{solarterm}` `{city}`（`*_name` 跟随界面语言输出）。

两个内置默认 Prompt（升级时旧默认自动迁移，自定义内容不受影响）：

- **壁纸生图**：在原模板基础上增加了天空规则——"If the scene includes sky, render the appropriate sun, moon or stars in a suitable position consistent with the weather and time of day."
- **基准图自动生成**（弹窗默认描述）："A small island in the middle of a lake, with a wooden house on the island. Deep forest and high mountains in the background, and the sun visible in the sky. Standard wallpaper-grade quality."（一座湖中小岛，岛上有木质房屋，背景深林高山，天空可见太阳，壁纸级质量）

> API Key 只保存在本机配置文件中，设置后台仅绑定 127.0.0.1，请勿随意端口转发。

## 注意

- 首次在 macOS 上切换壁纸时，系统可能弹窗要求给终端/Python 授予「自动化-系统事件」权限，允许一次即可。
- itboy 接口为个人维护的免费服务，波动时程序会自动回落 open-meteo；也可在后台把天气接口固定为 `open-meteo`。
- 节气采用寿星通式（21 世纪 C 值），2000–2099 年个别年份可能有 ±1 天偏差，对命名场景无影响。
