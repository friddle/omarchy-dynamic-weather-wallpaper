# WeatherDynamicWallpaper

[English](README.md) | 简体中文

**随天气变化的 AI 动态壁纸。** 以你自己场景的一张基准照片为底,结合当前天气、气温、时段与二十四节气生成氛围壁纸,并自动切换系统壁纸。相同条件只生成一次并缓存,之后切换零成本。

## 下载

到 [GitHub Releases](https://github.com/friddle/omarchy-dynamic-weather-wallpaper/releases) 下载最新版:

| 平台 | 文件 | 说明 |
|---|---|---|
| macOS | `WeatherDynamicWallpaper-x.y.z.dmg` | 标准 DMG,内置默认基准图 |
| Windows | `WeatherDynamicWallpaper.exe` | 单文件,双击即用 |

## 使用

### macOS

1. 打开 DMG,把 WeatherDynamicWallpaper 拖入 **应用程序**;
2. 启动应用——设置窗口随即弹出,后台服务同时启动;
3. 在 **Base & AI** 页填入生图 API(Base URL / Key / 模型),也可以先用内置基准图直接体验;
4. 点 **立即刷新一轮**,壁纸生成并应用;之后应用会随天气变化自动换壁纸。

- 首次切换壁纸时,macOS 可能请求「自动化-系统事件」权限,允许一次即可。
- 应用未签名,在新机器上首次打开需 **右键 → 打开**。

### Windows

1. 双击 `WeatherDynamicWallpaper.exe`——设置窗口随即弹出;
2. SmartScreen 拦截时选 **更多信息 → 仍要运行**;
3. 开机自启:`Win+R` → `shell:startup`,把应用快捷方式放入该文件夹。

## 设置窗口

| 页签 | 内容 |
|---|---|
| Status | 运行状态、立即刷新 / 强制重生成、日志 |
| Base & AI | 基准图管理、生图 API 配置、用文字描述直接生成基准图 |
| Advanced | 网络通道、天气源、城市(支持 IP 自动定位)、目标显示器、语言 |
| 挂件 | 把天气/温度信息挂件合成到壁纸上——样式、拖拽定位、字段行编辑、背景不透明度、字号缩放 |
| Gallery | 壁纸库,按基准图分组,点击任意壁纸立即应用 |

多显示器可在 Advanced → 目标显示器 中指定应用到哪几台。

## 天气源

默认 `auto` 模式免 Key:国内网络走 itboy(中国气象局数据),国外走 open-meteo,自动探测、失败自动回落。也支持和风天气、OpenWeatherMap(免费申请 Key,设置页内有获取步骤)。

生图接口为 OpenAI 兼容格式,`base_url` 可指向官方、中转站或自建网关;未配置 Key 时自动降级:直接以基准图作为壁纸。生图调用失败(接口不可达、Key 无效、额度用尽等)时同样降级,不会中断整轮流程。

## Omarchy(插件方式)

在 [Omarchy](https://omarchy.org/) 上,本仓库同时是一个标准 shell 插件——顶栏天气挂件(图标 + 气温,悬浮显示详情),一键打开控制页,右键启动/重启壁纸服务:

```bash
omarchy plugin add https://github.com/friddle/omarchy-dynamic-weather-wallpaper.git --enable
```

装好后右键挂件一次即可安装并启动服务(也可先自行运行 `./install.sh linux`)。"切主题不换壁纸"只需把仓库自带的 hook 拷进 theme-set 目录:

```bash
cp ~/.config/omarchy/plugins/io.github.friddle.weatherwall/keep-dynamic-wallpaper.hook \
   ~/.config/omarchy/hooks/theme-set.d/keep-dynamic-wallpaper
chmod +x ~/.config/omarchy/hooks/theme-set.d/keep-dynamic-wallpaper
```

### 依赖

- 顶栏挂件:`curl` 与 Omarchy shell(Quickshell)——Omarchy 自带。
- 壁纸服务:Python 3(仅标准库)+ systemd 用户会话。
- 全程无需 sudo/pkexec。

### 卸载

```bash
# 1. 移除插件(顶栏挂件及自带文件)
omarchy plugin remove io.github.friddle.weatherwall --yes

# 2. 停止并移除壁纸服务
systemctl --user disable --now weatherwall.service
rm -f ~/.config/systemd/user/weatherwall.service
systemctl --user daemon-reload

# 3. 移除主题 hook(如已安装)
rm -f ~/.config/omarchy/hooks/theme-set.d/keep-dynamic-wallpaper

# 4. 可选:删除配置与壁纸缓存
rm -rf ~/.config/omarchy-dynamic-wallpaper ~/.cache/omarchy-dynamic-wallpaper
```

## Linux / 源码运行

```bash
git clone https://github.com/friddle/omarchy-dynamic-weather-wallpaper.git
cd omarchy-dynamic-weather-wallpaper
./run.sh init
./run.sh gui        # 后台服务 + 设置窗口
./install.sh linux  # 开机自启(systemd 用户服务)；完成后自动打开
                    # http://127.0.0.1:8765 并输出配置页说明
```

仅依赖 Python 3 标准库,无需 pip 安装。壁纸切换自动探测 KDE Plasma / GNOME / omarchy / swww / hyprpaper / gsettings / feh。

> API Key 仅保存在本机配置文件中。
