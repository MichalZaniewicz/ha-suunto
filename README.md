# Suunto for Home Assistant (unofficial)

<p align="center">
  <img src="https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto/main/docs/readme/hero.svg" alt="Your nights and workouts, inside Home Assistant" width="100%">
</p>

<p align="center">
  <a href="https://github.com/MichalZaniewicz/ha-suunto/releases"><img alt="Release" src="https://img.shields.io/github/v/release/MichalZaniewicz/ha-suunto?style=for-the-badge&label=release&labelColor=0f3149&color=3fd0e0"></a>
  <a href="https://hacs.xyz"><img alt="HACS" src="https://img.shields.io/badge/HACS-custom-ffb52e?style=for-the-badge&labelColor=0f3149"></a>
  <a href="https://github.com/MichalZaniewicz/ha-suunto/actions/workflows/validate.yml"><img alt="Validate" src="https://img.shields.io/github/actions/workflow/status/MichalZaniewicz/ha-suunto/validate.yml?branch=main&style=for-the-badge&label=validate&labelColor=0f3149&color=7fe3a6"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/github/license/MichalZaniewicz/ha-suunto?style=for-the-badge&labelColor=0f3149&color=93aabf"></a>
</p>

Your **Suunto** watch data in Home Assistant, from the Suunto app (Sports Tracker). Sleep, HRV, recovery, training load and every workout become sensors, long-term statistics and a calendar, with notifications and an optional daily AI insight. Sign in with your Suunto email and password: no Docker, no partner keys.

> [!TIP]
> ⭐ **Enjoying this integration?** Every star is real motivation for me to keep
> developing it :)
>
> ☕ Want to say thanks another way? You can [buy me a coffee](https://buymeacoffee.com/zanula).

<!-- The badge lives OUTSIDE the alert on purpose: Home Assistant rewrites a
GitHub alert into <ha-alert> and drops every child whose textContent is empty,
which silently removes any <img> placed inside it. -->

[![Star this repo](https://img.shields.io/github/stars/MichalZaniewicz/ha-suunto?style=for-the-badge&logo=github&label=STAR%20THIS%20REPO&labelColor=555555&color=ffc107)](https://github.com/MichalZaniewicz/ha-suunto) [![Buy me a coffee](https://img.shields.io/badge/BUY%20ME%20A%20COFFEE-FFDD00?style=for-the-badge&logo=buymeacoffee&logoColor=black)](https://buymeacoffee.com/zanula)

<p align="center">
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=MichalZaniewicz&repository=ha-suunto&category=integration"><img alt="Open your Home Assistant instance and open this repository inside the Home Assistant Community Store." src="https://my.home-assistant.io/badges/hacs_repository.svg"></a>
</p>

<p align="center">
  <b><a href="https://github.com/MichalZaniewicz/ha-suunto/wiki">Documentation (wiki)</a></b> · <a href="https://github.com/MichalZaniewicz/ha-suunto/wiki/Installation">Installation</a> · <a href="https://github.com/MichalZaniewicz/ha-suunto/wiki/Configuration">Configuration</a> · <a href="https://github.com/MichalZaniewicz/ha-suunto/wiki/Sensors">Sensors</a> · <a href="https://github.com/MichalZaniewicz/ha-suunto/wiki/Blueprints">Blueprints</a> · <a href="https://github.com/MichalZaniewicz/ha-suunto/wiki/AI-Insight">AI Insight</a> · <a href="https://github.com/MichalZaniewicz/ha-suunto-cards">Cards</a>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto/main/docs/readme/trailer.webp" alt="Suunto for Home Assistant - the 45-second trailer" width="100%">
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto/main/docs/readme/stats.svg" alt="104 sensors, 8 blueprints, 66 cards, 8 languages, 0 partner keys" width="100%">
</p>

## What it does

<p align="center">
  <img src="https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto/main/docs/readme/features.svg" alt="Sleep and readiness, training load, every workout, 8 ready-made notifications, daily AI insight, hourly curves that fill in later" width="100%">
</p>

<details>
<summary><b>Every feature, in detail</b></summary>

- 😴 **Sleep, every night.** Duration, deep/light/REM, average and lowest heart rate, HRV, SpO2, quality, bedtime and wake-up time, naps kept apart so they never inflate the night, plus sleep regularity and your weekend social jetlag.
- 🔋 **Readiness and recovery.** A 0-100 readiness score from sleep, HRV and resting heart rate against your own baseline, recovery balance and stress, a recovery countdown after each workout, and an alert when HRV drops while resting heart rate rises.
- 📈 **Training load.** Fitness, fatigue and form (CTL / ATL / TSB), the acute:chronic workload ratio, a suggestion for today (rest / easy / moderate / hard) and a 7-day form forecast.
- 🚴 **Every workout.** Distance, duration, pace, speed, heart rate and time in zones 0-5 with their bpm ranges, TSS, Peak Training Effect, EPOC, your feeling, laps, the GPS route with per-point speed, weather, route achievements, best efforts from 1K to the marathon, and a workouts calendar.
- 🏆 **Totals and records.** This month and this year, lifetime totals per sport, monthly, yearly and all-time records, VO2max and fitness age.
- 🔔 **Notifications.** 8 ready-made blueprints: good morning (fires once you're actually up), new workout, long workout finished, low readiness, unusual recovery, a weekly digest, gear service and the AI insight report. One click to import each.
- 🤖 **A daily AI insight.** The AI model you already use in Home Assistant reads your night, recovery and training each morning and writes a short verdict with advice for the day. Optional, with no API key of ours and no extra Suunto requests.
- 📊 **Curves that fill in later.** Hourly heart rate, steps, energy, recovery balance and stress as long-term statistics, plus daily sleep, readiness and load trends. A watch that syncs late backfills the gaps.
- 🧭 **A daily brief.** One plain sentence about your sleep, HRV, readiness and form, in 8 languages.
- 🚲 **Commutes and gear.** Fuel and CO2 saved by riding instead of driving, and distance on each bike, chain or pair of shoes with a service reminder.
- 🌍 **8 languages.** English, Polish, German, Portuguese, French, Spanish, Italian and Dutch, following your Home Assistant language.
- 🔐 **One login.** Your password is used once, exchanged for a session token and not stored. Suunto emails you about a new login only at setup, or if the session ever expires.

</details>

<p align="center">
  <a href="https://github.com/user-attachments/assets/1dc9d95c-bf14-449e-8f4c-783758cafbe3"><img src="https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto/main/docs/readme/video-header.svg" alt="Don't want to read? Watch the 3-minute tour" width="100%"></a>
</p>

<p align="center">🔊 <b>The video starts muted</b> - click the speaker icon in the player to hear the voice-over.</p>



https://github.com/user-attachments/assets/0e43480c-e3f6-4b18-b22a-8393331db2d5



## Daily AI insight

<p align="center">
  <img src="https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto/main/docs/readme/ai-insight.webp" alt="Daily AI insight: every morning, your day read by AI" width="100%">
</p>

When you wake up, the AI model you already use in Home Assistant (Gemini, OpenAI, Claude, or a local Ollama) reads last night, your recovery and your training load, and writes a short verdict for sleep, recovery, training and activity with advice for the day. It runs through Home Assistant's AI Task: no API key here and no extra Suunto requests. Read it on the dashboard, get it as a notification with a blueprint, or press *Generate* any time. **[Setting it up](https://github.com/MichalZaniewicz/ha-suunto/wiki/AI-Insight)**

## A dashboard in minutes

<p align="center">
  <a href="https://github.com/MichalZaniewicz/ha-suunto-cards"><img src="https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto/main/docs/readme/cards-wall.webp" alt="66 cards, one training dashboard" width="100%"></a>
</p>

**[Suunto Cards](https://github.com/MichalZaniewicz/ha-suunto-cards)** is a companion repo with 66 cards made for this integration: last workout, HR zones, a 24-hour sleep clock, training load, a form forecast, a FIFA-style player card, achievements and more. Add it in HACS as a *Dashboard*.

<details>
<summary><b>See all 66 cards</b></summary>

![Suunto Cards preview](https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto-cards/master/docs/screenshots/cards-overview-dark.png)

</details>

## Get started

<p align="center">
  <img src="https://raw.githubusercontent.com/MichalZaniewicz/ha-suunto/main/docs/readme/steps.svg" alt="Get started: download in HACS, restart, add the integration, log in" width="100%">
</p>

<p align="center">
  <a href="https://my.home-assistant.io/redirect/hacs_repository/?owner=MichalZaniewicz&repository=ha-suunto&category=integration"><img alt="Open this repository in HACS" src="https://my.home-assistant.io/badges/hacs_repository.svg" height="32"></a>
  &nbsp;
  <a href="https://my.home-assistant.io/redirect/config_flow_start/?domain=suunto_app"><img alt="Add the Suunto App integration to Home Assistant" src="https://my.home-assistant.io/badges/config_flow_start.svg" height="32"></a>
</p>

1. **Download** *Suunto App (unofficial)* in HACS - the first button opens it (or add this repository in HACS as an *Integration*).
2. **Restart** Home Assistant.
3. **Add the integration** - the second button, or Settings → Devices & services → **Add integration** → **Suunto App (unofficial)**.
4. **Log in** with the email and password of your Suunto app account. (Two-factor authentication on the account may block the login.)

Then pick the [blueprints](https://github.com/MichalZaniewicz/ha-suunto/wiki/Blueprints) you want and add [the cards](https://github.com/MichalZaniewicz/ha-suunto-cards). Every option and every entity is in the **[wiki](https://github.com/MichalZaniewicz/ha-suunto/wiki)**.

> [!NOTE]
> Unofficial integration, not affiliated with or endorsed by Suunto. It signs in with your own Suunto account and may stop working after a Suunto app update; use it at your own risk. Your password is used once, exchanged for a session token and not stored - [why](https://github.com/MichalZaniewicz/ha-suunto/wiki/Privacy-&-Disclaimer#credentials).

## Documentation

Everything else is in the **[wiki](https://github.com/MichalZaniewicz/ha-suunto/wiki)**:

- **Getting started:** [Installation](https://github.com/MichalZaniewicz/ha-suunto/wiki/Installation) · [Configuration](https://github.com/MichalZaniewicz/ha-suunto/wiki/Configuration) - refresh intervals, fuel figures for the commute savings, gear, the AI insight.
- **Features:** [AI Insight](https://github.com/MichalZaniewicz/ha-suunto/wiki/AI-Insight) · [Blueprints](https://github.com/MichalZaniewicz/ha-suunto/wiki/Blueprints) (all 8, with import buttons) · [Automations & Templates](https://github.com/MichalZaniewicz/ha-suunto/wiki/Automations-&-Templates) · [Dashboard Examples](https://github.com/MichalZaniewicz/ha-suunto/wiki/Dashboard-Examples).
- **Reference:** [Sensors](https://github.com/MichalZaniewicz/ha-suunto/wiki/Sensors) · [Derived Metrics](https://github.com/MichalZaniewicz/ha-suunto/wiki/Derived-Metrics) · [Long-term Statistics](https://github.com/MichalZaniewicz/ha-suunto/wiki/Long-term-Statistics) · [Workouts Calendar & Recent](https://github.com/MichalZaniewicz/ha-suunto/wiki/Workouts-Calendar-&-Recent) · [Activity Types](https://github.com/MichalZaniewicz/ha-suunto/wiki/Activity-Types) · [Data & Units](https://github.com/MichalZaniewicz/ha-suunto/wiki/Data-&-Units).
- **Background:** [Architecture](https://github.com/MichalZaniewicz/ha-suunto/wiki/Architecture) · [Privacy & Disclaimer](https://github.com/MichalZaniewicz/ha-suunto/wiki/Privacy-&-Disclaimer) · [Troubleshooting & FAQ](https://github.com/MichalZaniewicz/ha-suunto/wiki/Troubleshooting-&-FAQ) · [Changelog](CHANGELOG.md).

## Related projects

- **[Suunto Cards](https://github.com/MichalZaniewicz/ha-suunto-cards)**: 66 Lovelace cards for this integration.

## Acknowledgments

- [`tajchert/suuntool`](https://github.com/tajchert/suuntool): the login pipeline is ported from this project.

## License

MIT - see [LICENSE](LICENSE).
