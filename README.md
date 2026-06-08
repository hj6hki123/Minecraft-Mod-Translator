
---

<div align="center">
   <table style="border: none;">
      <tr>
         <td align="center" style="padding: 20px; border-radius: 15px; border: none;">
            <h3>🌐 Minecraft Mod Translator</h3>
            <p><em>Easy online tool for Minecraft mod translation</em></p>
            <p>⏳ Don't waste your time • 🌍 90 languages • 🪙 50 free coins</p>
            <a href="https://mc-translator.net">
               <img src="https://img.shields.io/badge/_Get_Started-Click_Here-blue?style=for-the-badge&logo=rocket" alt="Get Started">
            </a>
         </td>
      </tr>
   </table>
</div>

---

<div align="center">
  <img src="docs/logo/logo.png" alt="Minecraft Mod Translator Logo" width="200">
</div>

# ⛏️ Minecraft Mod Translator

A powerful tool for translating Minecraft mods into multiple languages, automating the localization process for mod developers and translators.

> After searching extensively for an automatic translator for Minecraft mods without success, I developed this solution to address this need. While there is room for improvement, it effectively serves its purpose of making mods accessible across language barriers.

## 🚀 Features

- **Automated Translation**: Quickly translate mod files to multiple languages
- **AI-Powered Translation**: Optional OpenAI and DeepSeek integration for higher quality translations  
- **Batched AI Requests**: OpenAI and DeepSeek translate entries in batches with glossary support, timeout handling, and validation
- **Comprehensive File Support**: Compatible with JSON, LANG, and MCFUNCTION file formats
- **Multiple Translation Services**: Support for Google Translate (free), OpenAI, and DeepSeek (API key required)
- **Batch Processing**: Translate single files or entire mod folders at once
- **Smart Text Detection**: Automatically identifies translatable content while preserving game logic

## 🛠️ Installation

### Option 1: Pre-built Executables (Easiest)

Download ready-to-use executable files from the [Releases Page](https://github.com/zvictorium/minecraft-mod-translator/releases):

- **App Version**: Download `Minecraft Mod Translator.exe` (Interactive application)
- **CLI Version**: Download `mod-translator.exe` (Command-line interface)

Simply download and run - no Python installation required!

### Option 2: From Source (For Developers)

```bash
# Clone or download the project
git clone https://github.com/zvictorium/minecraft-mod-translator.git
cd minecraft-mod-translator

# Setup the environment (Windows)
setup.bat
# Or for Linux/Mac
./setup.sh

# For AI translation support, install additional dependencies:
pip install openai python-dotenv
# Or install everything with:
pip install -e .[ai]

# Run the application (Windows)
start.bat
# Or for Linux/Mac
./start.sh
```

## 🎯 Usage

### Interactive Mode (Recommended)

```bash
mod-translator app
```

### Command Line Interface

```bash
# Basic usage with Google Translate (free)
mod-translator --path path/to/mods --source en_US --target es_ES --output path/to/output

# AI-powered translation with OpenAI (requires API key)
mod-translator --path path/to/mods --source en_US --target es_ES --output path/to/output --ai
mod-translator --path path/to/mods --source en_US --target es_ES --output path/to/output --provider openai --model gpt-4o-mini

# AI-powered translation with DeepSeek (OpenAI-compatible API)
mod-translator --path path/to/mods --source en_US --target zh_TW --output path/to/output --provider deepseek --model deepseek-v4-flash
mod-translator --path path/to/mods --source en_US --target zh_TW --output path/to/output --provider deepseek --model deepseek-v4-pro
mod-translator --path path/to/mods --source en_US --target zh_TW --output path/to/output --provider deepseek --model deepseek-v4-flash --batch-size 50 --request-timeout 90 --glossary glossary.json

# Parameters:
# --path (-p): Path to mod or mods folder (default: ./mods)
# --source (-s): Source language code (e.g., en_US)
# --target (-t): Target language code (e.g., es_ES)
# --output (-o): Output folder path (if same as mods path, will replace original mods)
# --ai: Backward-compatible shortcut for OpenAI translation (requires OPENAI_API_KEY)
# --provider: Select google, openai, or deepseek
# --model: AI model name, such as gpt-4o-mini, deepseek-v4-flash, deepseek-v4-pro, or a custom model string
# --batch-size: AI translation batch size, default 50. Google Translate ignores this option.
# --request-timeout: Timeout in seconds for each AI request, default 90.
# --glossary: Path to glossary JSON for AI translation, default glossary.json.
# --no-batch: Disable AI batch translation and use one request per entry for debugging.
```

### 🤖 AI Translation Setup

The translator supports Google Translate by default, plus OpenAI-compatible AI providers through the `openai` Python package.

#### OpenAI

1. **Get an OpenAI API key**: Visit [OpenAI API](https://platform.openai.com/api-keys)
2. **Set up environment**: Create a `.env` file in the project root:
   ```
   OPENAI_API_KEY=your_api_key_here
   OPENAI_MODEL=gpt-3.5-turbo
   ```
3. **Install dependencies**: 
   ```bash
   pip install openai python-dotenv
   ```
4. **Use `--ai` or `--provider openai`** when running translations

> **Note**: OpenAI translation provides better context awareness and gaming-specific terminology but requires an API key with usage costs.

#### DeepSeek

DeepSeek uses an OpenAI-compatible API. Configure it with:

```env
DEEPSEEK_API_KEY=your_api_key_here
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

Examples:

```bash
mod-translator --path ./mods --source en_US --target zh_TW --output ./translated --provider deepseek --model deepseek-v4-flash
mod-translator --path ./mods --source en_US --target zh_TW --output ./translated --provider deepseek --model deepseek-v4-pro
```

Optional DeepSeek reasoning settings:

```env
DEEPSEEK_THINKING=disabled
DEEPSEEK_REASONING_EFFORT=medium
```

Use `--model` to override `DEEPSEEK_MODEL` for a single run.

#### Batched AI translation and glossary

OpenAI and DeepSeek translation uses batch mode by default. The tool sends multiple localization values in one JSON request, validates that the response keeps every original key, and checks that Minecraft formatting codes and placeholders are preserved. If a batch fails, it retries, splits the batch into smaller pieces, and only falls back to the original source text for entries that still fail as single items.

Create `glossary.json` in the project root, or pass a custom path with `--glossary`:

```json
{
  "Crystallite": "晶質石",
  "Nether Diamond": "地獄鑽石",
  "Ender Titanium": "終界鈦",
  "Charm": "護符",
  "Staff": "法杖",
  "Ore Vision": "礦物視覺",
  "HP": "HP",
  "XP": "XP",
  "OP": "OP"
}
```

Useful controls:

```bash
# Smaller batches can be more stable on weaker or stricter models
mod-translator --path ./mods --source en_US --target zh_TW --output ./translated --provider deepseek --batch-size 20

# Avoid hanging forever on a slow request
mod-translator --path ./mods --source en_US --target zh_TW --output ./translated --provider deepseek --request-timeout 60

# Return to the original one-entry request flow for debugging
mod-translator --path ./mods --source en_US --target zh_TW --output ./translated --provider deepseek --no-batch
```

## 📸 Screenshots

### Main Application
![Main Application](docs/screenshots/main-app.png)

### Confirmation
![Confirmation](docs/screenshots/confirmation.png)

### Translation Process
![Translation Process](docs/screenshots/translation-process.png)

### Results View
![Results View](docs/screenshots/results-view.png)

## 📄 License

This project is licensed under the [**Creative Commons Attribution-NonCommercial 4.0 International License (CC BY-NC 4.0)**](LICENSE).

## 🙋 Support

- **🐙 Repository**: [https://github.com/zvictorium/minecraft-mod-translator](https://github.com/zvictorium/minecraft-mod-translator)
- **📋 Issues**: [Report bugs or request features](https://github.com/zvictorium/minecraft-mod-translator/issues)
- **📦 Releases**: [Download latest version](https://github.com/zvictorium/minecraft-mod-translator/releases)

---

**Made with ❤️ for Minecraft modders and the community**

[!["Buy Me A Coffee"](https://www.buymeacoffee.com/assets/img/custom_images/orange_img.png)](https://www.buymeacoffee.com/victorium)
