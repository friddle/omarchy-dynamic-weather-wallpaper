# WeatherDynamic

English | [简体中文](README_zh.md)

**AI wallpapers that change with the weather.** Starting from one base photo of your own scene, it generates an atmospheric wallpaper matching the current weather, temperature, time of day and solar term, then switches your desktop wallpaper automatically. Each condition is generated once and cached — switching later costs nothing.

## Download

Get the latest version from [GitHub Releases](https://github.com/friddle/omarchy-dynamic-weather-wallpaper/releases):

| Platform | File | Notes |
|---|---|---|
| macOS | `WeatherDynamic-x.y.z.dmg` | Standard DMG, ships with a built-in base image |
| Windows | `WeatherDynamic.exe` | Single file, just run it |

## Usage

### macOS

1. Open the DMG and drag WeatherDynamic into **Applications**.
2. Launch the app — the settings window pops up right away, and the background service starts with it.
3. On the **Base & AI** tab, fill in your image-generation API (Base URL / Key / model) — or just click around with the built-in base image first.
4. Click **Refresh Now**. A wallpaper is generated and applied; from then on the app keeps swapping wallpapers as the weather changes.

- The first wallpaper switch may prompt for a macOS "System Events" automation permission — allow it once.
- The app is unsigned: on a new machine, open it via **right-click → Open** the first time.

### Windows

1. Double-click `WeatherDynamic.exe` — the settings window pops up right away.
2. If SmartScreen warns, choose **More info → Run anyway**.
3. To autostart: `Win+R` → `shell:startup` → drop a shortcut to the exe in that folder.

## Settings window

| Tab | What's there |
|---|---|
| Status | Run status, refresh / regenerate actions, logs |
| Base & AI | Manage base images; image-generation API config; generate a new base image from a text description |
| Advanced | Network channel, weather source, city (with IP auto-location), target displays, language |
| Gallery | Wallpaper library grouped by base image — click any wallpaper to apply it instantly |

Multi-monitor setups can pick which displays get the wallpaper (Advanced → target displays).

## Weather sources

Default mode `auto` needs no API key: it uses itboy (China Meteorological Administration data) on Chinese networks and open-meteo elsewhere, with automatic detection and fallback. QWeather and OpenWeatherMap are also supported with free API keys — the settings page includes step-by-step instructions for obtaining them.

The image API is OpenAI-compatible; `base_url` can point to the official API, a relay, or your own gateway. Without a key the app degrades gracefully: your base photo itself becomes the wallpaper.

## Linux / running from source

```bash
git clone https://github.com/friddle/omarchy-dynamic-weather-wallpaper.git
cd omarchy-dynamic-weather-wallpaper
./run.sh init
./run.sh gui        # background service + settings window
./install.sh linux  # autostart (systemd user service)
```

Python 3 standard library only, no pip dependencies. Wallpaper switching auto-detects swww / hyprpaper / gsettings / feh.

> API keys are stored only in the local config file.
