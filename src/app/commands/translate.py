"""
Minecraft mod translation functionality.
"""

import os
import json
import re
import shutil
import argparse
import time
from zipfile import ZipFile, ZIP_DEFLATED, BadZipFile
from typing import Dict, List, Any

# Import retry logic utilities
from ..utils.retry_logic import (
    create_retry_decorator, 
    global_rate_limiter,
    TranslationRateLimiter
)

# Constants
JAR = ".jar"
JSON = ".json"
LANG = ".lang"
MCFUNCTION = ".mcfunction"
DISABLE_LOGS = False

# Logging functions
title = ""


def log_title(new_title: str) -> None:
    """
    Change console title message.
    """
    global title
    if DISABLE_LOGS:
        return
    title = new_title
    clear_console()
    print(f"\n{title}\n")


def log_subtitle(new_message: str) -> None:
    """
    Change console subtitle message.
    """
    global title
    if DISABLE_LOGS:
        return
    title = f"{title}\n{new_message}"
    clear_console()
    print(f"\n{title}\n")


def log_message(message: str) -> None:
    """
    Change console message.
    """
    global title
    if DISABLE_LOGS:
        return
    clear_console()
    print(f"\n{title}\n{message}")


def clear_console() -> None:
    """
    Clear all console messages.
    """
    if DISABLE_LOGS:
        return
    command = ""
    if os.name == "nt":
        command = "cls"
    else:
        command = "clear"
    os.system(command)


# Utility function to handle JSON with comments
def remove_comments_from_json(json_str: str) -> str:
    """
    Remove comments from JSON string. Handles both // and /* */ comment styles.
    """
    # First, remove // style comments (up to end of line)
    result = re.sub(r"//.*$", "", json_str, flags=re.MULTILINE)

    # Then, remove /* */ style comments (can span multiple lines)
    result = re.sub(r"/\*.*?\*/", "", result, flags=re.DOTALL)

    return result


def parse_json_with_comments(file_path: str) -> Dict[str, Any]:
    """
    Parse a JSON file that may contain comments.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Remove comments
        clean_content = remove_comments_from_json(content)

        # Parse the cleaned JSON
        return json.loads(clean_content)
    except Exception as e:
        print(f"Error parsing JSON file {file_path}: {str(e)}")
        return {}


# Translator class
class Translator:
    """
    A class for translating text data from a source language to a target language.
    Supports Google Translate and OpenAI-compatible AI translation providers.
    """

    def __init__(
        self,
        source_language: str,
        target_language: str,
        capitalize: bool = True,
        use_openai: bool = False,
        ai_provider: str = "openai",
        model: str = None,
        batch_size: int = 50,
        request_timeout: float = 90,
        glossary_path: str = "glossary.json",
        use_batch: bool = True,
    ):
        self.source_language = source_language
        self.target_language = target_language
        self.capitalize = capitalize
        self.use_openai = use_openai
        self.ai_provider = ai_provider
        self.requested_model = model
        self.batch_size = max(1, int(batch_size or 50))
        self.request_timeout = float(request_timeout or 90)
        self.glossary_path = glossary_path or "glossary.json"
        self.use_batch = use_batch
        self.glossary = self._load_glossary(self.glossary_path) if self.use_openai else {}
        
        # Initialize retry decorators for both services
        self.google_retry = create_retry_decorator('google', max_retries=3)
        self.openai_retry = create_retry_decorator('openai', max_retries=3)
        self.ai_batch_retry = create_retry_decorator('ai_batch', max_retries=3)
        
        if self.use_openai:
            self._setup_ai_provider()

    def _load_glossary(self, glossary_path: str) -> Dict[str, str]:
        """Load an optional glossary JSON object for AI translation."""
        if not glossary_path:
            return {}

        normalized_path = os.path.abspath(glossary_path)
        if not os.path.exists(normalized_path):
            log_message(f"Glossary not found at {normalized_path}; continuing without glossary")
            return {}

        try:
            with open(normalized_path, "r", encoding="utf-8") as glossary_file:
                glossary_data = json.load(glossary_file)
            if not isinstance(glossary_data, dict):
                log_message(f"Glossary at {normalized_path} is not a JSON object; ignoring it")
                return {}

            cleaned_glossary = {
                str(key): str(value)
                for key, value in glossary_data.items()
                if str(key).strip() and str(value).strip()
            }
            log_message(f"Loaded glossary with {len(cleaned_glossary)} terms from {normalized_path}")
            return cleaned_glossary
        except Exception as e:
            log_message(f"Failed to load glossary at {normalized_path}: {e}; continuing without glossary")
            return {}

    def _setup_ai_provider(self):
        """Setup OpenAI-compatible client for AI translation."""
        try:
            from openai import OpenAI
            
            # Load environment variables from .env file
            try:
                from dotenv import load_dotenv
                # Try to load from current working directory and project root
                load_dotenv()  # Load from current directory
                load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '..', '..', '..', '.env'))  # Load from project root
                log_message("📄 Loaded .env configuration")
            except ImportError:
                log_message("⚠️ python-dotenv not found. Using system environment variables.")
            
            provider = self.ai_provider.lower()
            if provider == "deepseek":
                self.api_key = os.getenv("DEEPSEEK_API_KEY")
                if not self.api_key:
                    raise ValueError(
                        "DEEPSEEK_API_KEY environment variable not set.\n"
                        "Please:\n"
                        "1. Set DEEPSEEK_API_KEY environment variable, or\n"
                        "2. Create a .env file with: DEEPSEEK_API_KEY=your_key_here"
                    )
                self.openai_client = OpenAI(
                    api_key=self.api_key,
                    base_url=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
                )
                self.model = self.requested_model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash")
                self.deepseek_thinking = os.getenv("DEEPSEEK_THINKING", "disabled").lower()
                self.deepseek_reasoning_effort = os.getenv("DEEPSEEK_REASONING_EFFORT", "medium")
                log_message(f"🤖 DeepSeek initialized with model: {self.model}")
                return

            self.api_key = os.getenv("OPENAI_API_KEY")
            if not self.api_key:
                raise ValueError(
                    "OPENAI_API_KEY environment variable not set.\n"
                    "Please:\n"
                    "1. Set OPENAI_API_KEY environment variable, or\n"
                    "2. Create a .env file with: OPENAI_API_KEY=your_key_here"
                )
            
            self.openai_client = OpenAI(api_key=self.api_key)
            self.model = self.requested_model or os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
            log_message(f"🤖 OpenAI initialized with model: {self.model}")
            
        except ImportError:
            raise ImportError("OpenAI package not found. Install with: pip install openai python-dotenv")

    def _translate_with_openai(self, text: str) -> str:
        """Translate text using OpenAI-compatible chat completions with retry logic."""
        if not text.strip():
            return text
        
        # Apply the retry decorator to the actual translation call
        @self.openai_retry
        def _do_openai_translation(text: str) -> str:
            # Apply preventive delay to avoid rate limits
            global_rate_limiter.apply_service_delay('openai')
            
            system_prompt = f"""You are a professional translator specializing in Minecraft and video game localization.
            Translate from {self.source_language} to {self.target_language}.
            
            Guidelines:
            - Preserve formatting like %s, %d, %1$s, {{}} placeholders and Minecraft § formatting codes
            - Translate only the text value, never translate localization keys
            - Maintain Minecraft-appropriate terminology and tone
            - Use natural, idiomatic expressions
            - Keep technical terms consistent
            - You may leave short technical abbreviations such as HP, XP and OP untranslated
            
            Respond with ONLY the translated text, no explanations."""
            
            request = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Translate: {text}"}
                ],
                "temperature": 0.3,
                "max_tokens": 500,
                "timeout": self.request_timeout,
            }

            if self.ai_provider.lower() == "deepseek":
                if getattr(self, "deepseek_thinking", "disabled") == "enabled":
                    request["reasoning_effort"] = getattr(self, "deepseek_reasoning_effort", "medium")
                    request["extra_body"] = {"thinking": {"type": "enabled"}}
                else:
                    request["extra_body"] = {"thinking": {"type": "disabled"}}

            completion = self.openai_client.chat.completions.create(**request)
            
            translated_text = completion.choices[0].message.content.strip()
            
            if self.capitalize and translated_text:
                translated_text = translated_text[0].upper() + translated_text[1:]
                
            return translated_text
        
        try:
            return _do_openai_translation(text)
        except Exception as e:
            log_message(f"{self.ai_provider} translation failed after all retries for '{text}': {e}")
            return text  # Return original on error

    def translate_data(self, data: Dict[str, str]) -> Dict[str, str]:
        """
        Translate data from source to target language.
        """
        translation_service = self.ai_provider if self.use_openai else "Google Translate"
        log_message(f"Translating {len(data)} entries from {self.source_language} to {self.target_language} using {translation_service}...")

        if self.use_openai:
            return self._translate_data_openai(data)
        else:
            return self._translate_data_google(data)

    def _translate_data_openai(self, data: Dict[str, str]) -> Dict[str, str]:
        """Translate data using an OpenAI-compatible provider with rate limiting protection."""
        if self.use_batch:
            return self._translate_data_openai_batch(data)
        return self._translate_data_openai_single(data)

    def _translate_data_openai_single(self, data: Dict[str, str]) -> Dict[str, str]:
        """Translate data one entry at a time. Kept for fallback/debugging with --no-batch."""
        translated_data = {}
        total_items = len(data)
        
        for index, (key, text) in enumerate(data.items(), 1):
            if not text or not isinstance(text, str):
                translated_data[key] = text
                continue

            try:
                translated_text = self._translate_with_openai(text)
                log_message(f'🤖 [{index}/{total_items}] "{text}" → "{translated_text}"')
                translated_data[key] = translated_text
                
                # Add a small delay between requests to avoid overwhelming the API
                # Skip delay for the last item
                if index < total_items:
                    time.sleep(0.1)  # 100ms delay between requests
                    
            except Exception as e:
                log_message(f'Error translating "{text}": {str(e)}')
                translated_data[key] = text

        log_message(f"Successfully translated {len(data)} entries using {self.ai_provider}")
        return translated_data

    def _translate_data_openai_batch(self, data: Dict[str, str]) -> Dict[str, str]:
        """Translate data using JSON batches with validation and split fallback."""
        translated_data = {}
        items = list(data.items())
        translatable_items = [
            (index, key, text)
            for index, (key, text) in enumerate(items, 1)
            if text and isinstance(text, str)
        ]
        total_entries = len(items)
        total_translatable = len(translatable_items)

        if not translatable_items:
            return dict(items)

        total_batches = (total_translatable + self.batch_size - 1) // self.batch_size
        log_message(
            f"Batch AI translation enabled: {total_translatable}/{total_entries} translatable entries, "
            f"batch size {self.batch_size}, timeout {self.request_timeout:g}s"
        )

        translated_lookup = {}
        for batch_number, offset in enumerate(range(0, total_translatable, self.batch_size), 1):
            batch = translatable_items[offset:offset + self.batch_size]
            rows = [
                {"key": key, "source": text, "entry_index": entry_index}
                for entry_index, key, text in batch
            ]
            translated_lookup.update(
                self._translate_batch_with_split_fallback(rows, batch_number, total_batches)
            )

        for key, text in items:
            translated_data[key] = translated_lookup.get(key, text)

        failed_count = sum(
            1
            for key, text in items
            if key in translated_lookup and translated_lookup[key] == text and text and isinstance(text, str)
        )
        log_message(
            f"Successfully processed {len(data)} entries using {self.ai_provider}; "
            f"{failed_count} entries kept as source text"
        )
        return translated_data

    def _translate_batch_with_split_fallback(
        self,
        rows: List[Dict[str, Any]],
        batch_number: int,
        total_batches: int,
    ) -> Dict[str, str]:
        """Translate a batch, then split recursively if the whole batch keeps failing."""
        if not rows:
            return {}

        try:
            return self._translate_batch_with_openai(rows, batch_number, total_batches)
        except Exception as e:
            first_index = rows[0]["entry_index"]
            last_index = rows[-1]["entry_index"]
            log_message(
                f"Batch {batch_number}/{total_batches} entries {first_index}-{last_index} failed: {e}"
            )

            if len(rows) == 1:
                row = rows[0]
                log_message(f'FAILED {row["key"]} = {row["source"]}')
                return {row["key"]: row["source"]}

            midpoint = len(rows) // 2
            left = self._translate_batch_with_split_fallback(
                rows[:midpoint], batch_number, total_batches
            )
            right = self._translate_batch_with_split_fallback(
                rows[midpoint:], batch_number, total_batches
            )
            left.update(right)
            return left

    def _translate_batch_with_openai(
        self,
        rows: List[Dict[str, Any]],
        batch_number: int,
        total_batches: int,
    ) -> Dict[str, str]:
        """Translate one JSON batch through an OpenAI-compatible provider."""
        first_index = rows[0]["entry_index"]
        last_index = rows[-1]["entry_index"]

        @self.ai_batch_retry
        def _do_batch_translation() -> Dict[str, str]:
            global_rate_limiter.apply_service_delay('openai')

            log_message(
                f"Translating batch {batch_number}/{total_batches} entries {first_index}-{last_index}..."
            )
            started_at = time.monotonic()
            request_rows = [
                {"key": row["key"], "source": row["source"]}
                for row in rows
            ]
            user_payload = json.dumps(request_rows, ensure_ascii=False)
            source_chars = sum(len(row["source"]) for row in rows)
            max_tokens = min(12000, max(1000, source_chars * 3 + 800))

            request = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self._build_batch_system_prompt()},
                    {"role": "user", "content": user_payload},
                ],
                "temperature": 0.2,
                "max_tokens": max_tokens,
                "timeout": self.request_timeout,
            }

            if self.ai_provider.lower() == "deepseek":
                if getattr(self, "deepseek_thinking", "disabled") == "enabled":
                    request["reasoning_effort"] = getattr(self, "deepseek_reasoning_effort", "medium")
                    request["extra_body"] = {"thinking": {"type": "enabled"}}
                else:
                    request["extra_body"] = {"thinking": {"type": "disabled"}}

            completion = self.openai_client.chat.completions.create(**request)
            raw_response = completion.choices[0].message.content.strip()
            parsed_response = self._parse_json_array_response(raw_response)
            translated_lookup = self._validate_batch_response(rows, parsed_response)
            elapsed = time.monotonic() - started_at
            log_message(
                f"Translated batch {batch_number}/{total_batches} in {elapsed:.1f}s"
            )
            return translated_lookup

        return _do_batch_translation()

    def _build_batch_system_prompt(self) -> str:
        """Build the strict JSON batch translation prompt."""
        glossary_text = json.dumps(self.glossary, ensure_ascii=False, indent=2) if self.glossary else "{}"
        return f"""You are a professional Minecraft mod localization translator.
Translate JSON array entries from {self.source_language} to {self.target_language}.

Rules:
- The input is a JSON array of objects: [{{"key":"...","source":"..."}}].
- Return ONLY a valid JSON array of objects: [{{"key":"...","target":"..."}}].
- Return every input key exactly once and do not change any key.
- Translate only the source value into Traditional Chinese when target is zh_TW.
- Use Minecraft terminology and natural in-game wording.
- Strictly apply this glossary when matching source terms:
{glossary_text}
- Preserve Minecraft formatting codes such as §9 and §r exactly.
- Preserve placeholders exactly, including %s, %d, %1$s, %2$d, {placeholder}, and line breaks.
- Do not translate short technical abbreviations such as HP, XP, or OP.
- Do not include explanations, markdown, comments, or surrounding text."""

    def _parse_json_array_response(self, raw_response: str) -> List[Dict[str, Any]]:
        """Parse a model response that must contain a JSON array."""
        cleaned_response = raw_response.strip()
        if cleaned_response.startswith("```"):
            cleaned_response = re.sub(r"^```(?:json)?\s*", "", cleaned_response, flags=re.IGNORECASE)
            cleaned_response = re.sub(r"\s*```$", "", cleaned_response)

        try:
            parsed_response = json.loads(cleaned_response)
        except json.JSONDecodeError as e:
            raise ValueError(f"JSON parse failed: {e}") from e

        if not isinstance(parsed_response, list):
            raise ValueError("model response is not a JSON array")
        return parsed_response

    def _validate_batch_response(
        self,
        rows: List[Dict[str, Any]],
        parsed_response: List[Dict[str, Any]],
    ) -> Dict[str, str]:
        """Validate key coverage and protected tokens before accepting a batch."""
        expected_keys = [row["key"] for row in rows]
        received_keys = []
        translated_lookup = {}

        for item in parsed_response:
            if not isinstance(item, dict):
                raise ValueError("batch response contains a non-object item")
            if "key" not in item or "target" not in item:
                raise ValueError("batch response item must contain key and target")

            key = item["key"]
            target = item["target"]
            if not isinstance(key, str) or not isinstance(target, str):
                raise ValueError("batch response key and target must be strings")
            received_keys.append(key)
            translated_lookup[key] = target

        if received_keys != expected_keys:
            missing_keys = [key for key in expected_keys if key not in translated_lookup]
            extra_keys = [key for key in received_keys if key not in expected_keys]
            raise ValueError(f"batch key mismatch; missing={missing_keys}, extra={extra_keys}")

        for row in rows:
            key = row["key"]
            source = row["source"]
            target = translated_lookup[key]
            missing_tokens = self._missing_protected_tokens(source, target)
            if missing_tokens:
                raise ValueError(f"{key} lost protected tokens: {missing_tokens}")
            if self.capitalize and target:
                translated_lookup[key] = target[0].upper() + target[1:]

        return translated_lookup

    def _missing_protected_tokens(self, source: str, target: str) -> List[str]:
        """Return protected placeholders/format tokens missing from translated text."""
        token_pattern = re.compile(
            r"(§[0-9a-fk-or]|%\d+\$[sd]|%[sd]|%%|\{[^{}\n]+\})",
            re.IGNORECASE,
        )
        source_tokens = token_pattern.findall(source)
        missing_tokens = []
        for token in source_tokens:
            if target.count(token) < source.count(token) and token not in missing_tokens:
                missing_tokens.append(token)
        if target.count("\n") < source.count("\n"):
            missing_tokens.append("\\n")
        if target.count("\\n") < source.count("\\n"):
            missing_tokens.append("\\\\n")
        return missing_tokens

    def _translate_data_google(self, data: Dict[str, str]) -> Dict[str, str]:
        """Translate data using Google Translate with rate limiting protection"""
        import time
        
        translated_data = {}
        total_items = len(data)
        
        for index, (key, text) in enumerate(data.items(), 1):
            if not text or not isinstance(text, str):
                # Skip empty or non-string values
                translated_data[key] = text
                continue

            try:
                translated_text = self._translate_with_google(text)
                log_message(f'🌐 [{index}/{total_items}] "{text}" → "{translated_text}"')
                translated_data[key] = translated_text
                
                # Add a small delay between requests to avoid overwhelming the API
                # Skip delay for the last item
                if index < total_items:
                    time.sleep(0.1)  # 100ms delay between requests
                    
            except Exception as e:
                log_message(f'Error translating "{text}": {str(e)}')
                translated_data[key] = text  # Keep original on error

        log_message(f"Successfully translated {len(data)} entries using Google Translate")
        return translated_data

    def translate(self, string: str) -> str:
        """
        Translate string from source to target language.
        """
        if not string or not isinstance(string, str):
            return string

        if self.use_openai:
            return self._translate_with_openai(string)
        else:
            return self._translate_with_google(string)

    def _translate_with_google(self, string: str) -> str:
        """Translate string using Google Translate with retry logic and rate limiting"""
        
        # Apply the retry decorator to the actual translation call
        @self.google_retry
        def _do_google_translation(text: str) -> str:
            # Apply preventive delay to avoid rate limits
            global_rate_limiter.apply_service_delay('google')
            
            try:
                from deep_translator import GoogleTranslator
            except ImportError:
                raise ImportError("deep_translator package is required for Google translation. Install with: pip install deep-translator")

            translator = GoogleTranslator(
                source=self.source_language, target=self.target_language
            )
            translated_string = translator.translate(text)
            if self.capitalize and translated_string:
                translated_string = translated_string.capitalize()
            return translated_string
        
        try:
            return _do_google_translation(string)
        except ImportError as e:
            print(f"Error: {e}")
            return string
        except Exception as e:
            log_message(f'Google translation failed after all retries for "{string}": {str(e)}')
            return string  # Return original string on error


# Settings class
class Settings:
    """
    The Settings class is responsible for managing configuration settings
    for this Minecraft translation tool.
    """

    def __init__(self, cli_args: argparse.Namespace = None):
        # Default values if no CLI arguments provided
        self.source_mc_lang = self._format_lang("en_US")
        self.target_mc_lang = self._format_lang("es_ES")
        self.mods_path = "./"
        self.temp_path = "temp"
        self.translation_path = "./translated"
        self.use_ai = False  # Default to Google Translate
        self.ai_provider = "google"
        self.ai_model = None
        self.batch_size = 50
        self.request_timeout = 90
        self.glossary_path = "glossary.json"
        self.no_batch = False

        # Override with CLI arguments if provided
        if cli_args:
            if hasattr(cli_args, "source") and cli_args.source:
                self.source_mc_lang = self._format_lang(cli_args.source)

            if hasattr(cli_args, "target") and cli_args.target:
                self.target_mc_lang = self._format_lang(cli_args.target)

            if hasattr(cli_args, "path") and cli_args.path:
                self.mods_path = cli_args.path

            if hasattr(cli_args, "output") and cli_args.output:
                self.translation_path = cli_args.output
                
            if hasattr(cli_args, "ai") and cli_args.ai:
                self.use_ai = True
                self.ai_provider = "openai"
                self.source_mc_lang = self._format_lang(cli_args.source)

            if hasattr(cli_args, "provider") and cli_args.provider:
                self.ai_provider = cli_args.provider.lower()
                self.use_ai = self.ai_provider in {"openai", "deepseek"}

            if hasattr(cli_args, "model") and cli_args.model:
                self.ai_model = cli_args.model

            if hasattr(cli_args, "batch_size") and cli_args.batch_size:
                self.batch_size = max(1, int(cli_args.batch_size))

            if hasattr(cli_args, "request_timeout") and cli_args.request_timeout:
                self.request_timeout = float(cli_args.request_timeout)

            if hasattr(cli_args, "glossary") and cli_args.glossary:
                self.glossary_path = cli_args.glossary

            if hasattr(cli_args, "no_batch") and cli_args.no_batch:
                self.no_batch = True

            if hasattr(cli_args, "target") and cli_args.target:
                self.target_mc_lang = self._format_lang(cli_args.target)

            if hasattr(cli_args, "path") and cli_args.path:
                self.mods_path = cli_args.path

            if hasattr(cli_args, "output") and cli_args.output:
                self.translation_path = cli_args.output

        # Set Google language codes
        self.source_google_lang = self._get_google_lang(self.source_mc_lang)
        self.target_google_lang = self._get_google_lang(self.target_mc_lang)

    def _get_google_lang(self, mc_lang: str) -> str:
        """
        Get Google language code from Minecraft language code.
        """
        google_lang = mc_lang.split("_")[0]
        return google_lang

    def _replace_appdata(self, path: str) -> str:
        """
        Replace %Appdata% for its respective path.
        """
        pattern = re.compile(r"%appdata%", re.IGNORECASE)
        appdata_path = os.getenv("APPDATA", "").replace("\\", "\\\\")
        new_path = re.sub(pattern, appdata_path, path)
        return new_path

    def _format_lang(self, mc_lang: str) -> str:
        """
        Format language code for Minecraft (e.g., us_US, es_ES...)
        """
        language, region = mc_lang.split("_")
        formatted_language_code = f"{language.lower()}_{region.upper()}"
        return formatted_language_code


# File Manager class
class FileManager:
    """
    A utility class for managing translation of Minecraft mod files.
    """

    def __init__(self, settings: Settings):
        self.temp_path = settings.temp_path
        self.translation_path = settings.translation_path
        self.mods_path = settings.mods_path

        self.source_mc_lang = settings.source_mc_lang
        self.target_mc_lang = settings.target_mc_lang

        # Choose translator based on settings
        if settings.use_ai:
            log_message(f"🤖 Using {settings.ai_provider} translator...")
            try:
                self.translator = Translator(
                    settings.source_mc_lang,
                    settings.target_mc_lang,
                    use_openai=True,
                    ai_provider=settings.ai_provider,
                    model=settings.ai_model,
                    batch_size=settings.batch_size,
                    request_timeout=settings.request_timeout,
                    glossary_path=settings.glossary_path,
                    use_batch=not settings.no_batch,
                )
            except (ImportError, ValueError) as e:
                log_message(f"❌ {settings.ai_provider} initialization failed: {e}")
                log_message("🔄 Falling back to Google Translate...")
                self.translator = Translator(
                    settings.source_google_lang, settings.target_google_lang
                )
        else:
            log_message("🌐 Using Google Translate...")
            self.translator = Translator(
                settings.source_google_lang, settings.target_google_lang
            )

    def create_needed_folders(self) -> None:
        """
        Create necessary folders if they do not exist.
        """
        os.makedirs(self.temp_path, exist_ok=True)
        os.makedirs(self.translation_path, exist_ok=True)

    def unpack_mods(self) -> None:
        """
        Unpack all mod.jar files.
        """
        mod_list = os.listdir(self.mods_path)
        for mod_name in mod_list:
            if mod_name.endswith(JAR):
                mod_file_path = os.path.join(self.mods_path, mod_name)
                unpacking_destination = os.path.join(self.temp_path, mod_name)
                try:
                    with ZipFile(mod_file_path, "r") as zip:
                        log_message(f"Unpacking {mod_name}...")
                        zip.extractall(unpacking_destination)
                except BadZipFile:
                    raise BadZipFile(f"{mod_file_path} is not a valid JAR/ZIP file")

    def get_lang_folders(self) -> List[str]:
        """
        Get all language folder paths and mcfunction root folders.
        """
        lang_folders = []
        found_files = []
        log_message(f"Searching for language files in {self.temp_path}...")

        # First, find all language files in the extracted mods
        for foldername, _, filenames in os.walk(self.temp_path):
            source_json_lower = f"{self.source_mc_lang.lower()}{JSON}"
            source_json_original = f"{self.source_mc_lang}{JSON}"
            source_lang_lower = f"{self.source_mc_lang.lower()}{LANG}"
            source_lang_original = f"{self.source_mc_lang}{LANG}"

            for filename in filenames:
                lower_filename = filename.lower()
                if (
                    lower_filename == source_json_lower.lower()
                    or lower_filename == source_json_original.lower()
                    or lower_filename == source_lang_lower.lower()
                    or lower_filename == source_lang_original.lower()
                ):
                    found_files.append((foldername, filename))

        # Now find the language folders (typically containing "lang" in the path)
        for folder, filename in found_files:
            if "lang" in folder.lower():
                if folder not in lang_folders:
                    lang_folders.append(folder)
                    mod_path_parts = folder.split(os.sep)
                    mod_name = (
                        mod_path_parts[1] if len(mod_path_parts) > 1 else "unknown"
                    )
                    log_message(f"Found language folder: {folder}")
                    log_message(f"Contains source file: {filename}")
            else:
                # If we didn't find a folder with "lang" in the name, use the parent directory
                parent_folder = os.path.dirname(folder)
                if parent_folder not in lang_folders:
                    lang_folders.append(parent_folder)
                    mod_path_parts = parent_folder.split(os.sep)
                    mod_name = (
                        mod_path_parts[1] if len(mod_path_parts) > 1 else "unknown"
                    )
                    log_message(
                        f"Found language file outside standard lang folder: {folder}"
                    )
                    log_message(f"Using parent folder: {parent_folder}")

        # Also search for .mcfunction files and add their root mod folders
        mcfunction_folders = self.get_mcfunction_folders()
        for folder in mcfunction_folders:
            if folder not in lang_folders:
                lang_folders.append(folder)

        if not lang_folders:
            log_message(
                f"Warning: No language folders found containing {self.source_mc_lang} files"
            )
            # List all directories to help with debugging
            log_message("Available directories:")
            for dirpath, dirnames, _ in os.walk(self.temp_path):
                if "lang" in dirpath.lower() or "assets" in dirpath.lower():
                    log_message(f"  - {dirpath}")
                    log_message(f"    Contents: {os.listdir(dirpath)}")

        return lang_folders

    def get_mcfunction_folders(self) -> List[str]:
        """
        Get all mod root folders that contain .mcfunction files.
        """
        mcfunction_folders = []
        log_message(f"Searching for .mcfunction files in {self.temp_path}...")

        # Find all .mcfunction files in the extracted mods
        for foldername, _, filenames in os.walk(self.temp_path):
            for filename in filenames:
                if filename.endswith(MCFUNCTION):
                    # Get the mod root folder (first level under temp_path)
                    path_parts = foldername.split(os.sep)
                    temp_parts = self.temp_path.split(os.sep)
                    
                    # Find the mod root - it's the directory immediately under temp_path
                    if len(path_parts) > len(temp_parts):
                        mod_root_parts = temp_parts + [path_parts[len(temp_parts)]]
                        mod_root = os.sep.join(mod_root_parts)
                        
                        if mod_root not in mcfunction_folders:
                            mcfunction_folders.append(mod_root)
                            mod_name = path_parts[len(temp_parts)] if len(path_parts) > len(temp_parts) else "unknown"
                            log_message(f"Found mod with .mcfunction files: {mod_name}")
                            break  # No need to continue checking this folder

        return mcfunction_folders

    def edit_lang_files(self, lang_folders: List[str]) -> None:
        """
        Translate the source language file to the target language.
        """
        for lang_folder in lang_folders:
            # Extract mod name from the path in a platform-independent way
            path_parts = lang_folder.split(os.sep)
            # The mod name is typically the 2nd element in the path (after temp directory)
            if len(path_parts) > 1:
                mod_name = path_parts[1]
                mod_name = mod_name.replace(JAR, "")
            else:
                mod_name = "unknown-mod"

            log_subtitle(f"Processing {mod_name}...")

            # Check if source language files exist before attempting translation
            source_json_path = os.path.join(
                lang_folder, f"{self.source_mc_lang.lower()}{JSON}"
            )
            source_lang_path = os.path.join(lang_folder, f"{self.source_mc_lang}{LANG}")

            # Target language file paths
            target_json_path = os.path.join(
                lang_folder, f"{self.target_mc_lang.lower()}{JSON}"
            )
            target_lang_path = os.path.join(lang_folder, f"{self.target_mc_lang}{LANG}")

            # Flag to track if we found and processed any files
            files_processed = False

            # Check and process JSON files
            if os.path.exists(source_json_path):
                log_subtitle(
                    f"Creating {self.target_mc_lang.lower()}{JSON} from {self.source_mc_lang.lower()}{JSON}..."
                )
                original_data = self._read_json_file(source_json_path)
                if original_data:
                    translated_data = self.translator.translate_data(original_data)
                    self._write_json_file(translated_data, target_json_path)
                    log_message(f"Successfully translated JSON file for {mod_name}")
                    files_processed = True
                else:
                    log_message(f"No data found in source JSON file for {mod_name}")

            # Check and process LANG files
            if os.path.exists(source_lang_path):
                log_subtitle(
                    f"Creating {self.target_mc_lang}{LANG} from {self.source_mc_lang}{LANG}..."
                )
                original_data = self._read_lang_file(source_lang_path)
                if original_data:
                    translated_data = self.translator.translate_data(original_data)
                    self._write_lang_file(translated_data, target_lang_path)
                    log_message(f"Successfully translated LANG file for {mod_name}")
                    files_processed = True
                else:
                    log_message(f"No data found in source LANG file for {mod_name}")

            # If no exact match found, try case-insensitive search
            if not files_processed:
                log_message(
                    f"Searching for alternative source files in {lang_folder}..."
                )
                for filename in os.listdir(lang_folder):
                    lower_filename = filename.lower()

                    # Try to find JSON files with case-insensitive matching
                    if lower_filename == f"{self.source_mc_lang.lower()}{JSON}".lower():
                        source_file_path = os.path.join(lang_folder, filename)
                        target_file_path = os.path.join(
                            lang_folder, f"{self.target_mc_lang.lower()}{JSON}"
                        )

                        log_subtitle(
                            f"Creating {self.target_mc_lang.lower()}{JSON} from {filename}..."
                        )
                        original_data = self._read_json_file(source_file_path)
                        if original_data:
                            translated_data = self.translator.translate_data(
                                original_data
                            )
                            self._write_json_file(translated_data, target_file_path)
                            log_message(
                                f"Successfully translated JSON file for {mod_name}"
                            )
                            files_processed = True
                        else:
                            log_message(
                                f"No data found in source JSON file for {mod_name}"
                            )

                    # Try to find LANG files with case-insensitive matching
                    elif lower_filename == f"{self.source_mc_lang}{LANG}".lower():
                        source_file_path = os.path.join(lang_folder, filename)
                        target_file_path = os.path.join(
                            lang_folder, f"{self.target_mc_lang}{LANG}"
                        )

                        log_subtitle(
                            f"Creating {self.target_mc_lang}{LANG} from {filename}..."
                        )
                        original_data = self._read_lang_file(source_file_path)
                        if original_data:
                            translated_data = self.translator.translate_data(
                                original_data
                            )
                            self._write_lang_file(translated_data, target_file_path)
                            log_message(
                                f"Successfully translated LANG file for {mod_name}"
                            )
                            files_processed = True
                        else:
                            log_message(
                                f"No data found in source LANG file for {mod_name}"
                            )

            if not files_processed:
                log_message(f"No translatable language files found for {mod_name}")

            # Check if this is a mod root folder and process .mcfunction files
            # A mod root folder is directly under temp_path
            temp_path_parts = self.temp_path.split(os.sep)
            lang_folder_parts = lang_folder.split(os.sep)
            
            # Check if this folder is a mod root (temp_path + one level)
            if len(lang_folder_parts) == len(temp_path_parts) + 1:
                log_subtitle(f"Checking for .mcfunction files in {mod_name}...")
                self.translate_mcfunction_files(lang_folder)
                files_processed = True

    # Removed _translate_mod function as it's no longer needed

    def _read_json_file(self, path: str) -> Dict[str, str]:
        """
        Read JSON file data.
        """
        try:
            # Use our custom JSON parser that can handle comments
            data = parse_json_with_comments(path)

            if data:
                log_message(f"Successfully loaded JSON with {len(data)} entries")
            else:
                log_message(f"Warning: No data found in JSON file: {path}")

            return data
        except Exception as e:
            log_message(f"Error reading JSON file {path}: {str(e)}")
            return {}

    def _read_lang_file(self, path: str) -> Dict[str, str]:
        """
        Read LANG file.
        """
        data = {}
        with open(path, "r") as file:
            lines = file.readlines()
        for line in lines:
            line = line.strip()
            if line:
                try:
                    key, value = line.split("=", 1)  # Split on first equals sign only
                    data[key] = value
                except ValueError:
                    # Skip lines that don't have key=value format
                    pass
        return data

    def _write_json_file(self, data: Dict[str, str], path: str) -> None:
        """
        Write JSON file.
        """
        try:
            log_message(f"Writing JSON file to {path}")
            os.makedirs(os.path.dirname(path), exist_ok=True)

            with open(path, "w", encoding="utf-8") as file:
                json.dump(data, file, indent=4, ensure_ascii=False)

            if os.path.exists(path):
                file_size = os.path.getsize(path)
                log_message(f"JSON file successfully written ({file_size} bytes)")
                # Verify file content
                with open(path, "r", encoding="utf-8") as check_file:
                    content = check_file.read()
                    if len(content) > 0:
                        log_message(f"Verified file content: {len(content)} bytes")
                    else:
                        log_message(f"WARNING: File exists but is empty")
            else:
                log_message(f"WARNING: Failed to create file {path}")
        except Exception as e:
            log_message(f"ERROR writing JSON file: {str(e)}")

    def _write_lang_file(self, data: Dict[str, str], path: str) -> None:
        """
        Write LANG file.
        """
        try:
            log_message(f"Writing LANG file to {path}")
            os.makedirs(os.path.dirname(path), exist_ok=True)

            text = ""
            for key, value in data.items():
                text += f"{key}={value}\n"

            with open(path, "w", encoding="utf-8") as file:
                file.write(text)

            if os.path.exists(path):
                file_size = os.path.getsize(path)
                log_message(f"LANG file successfully written ({file_size} bytes)")
            else:
                log_message(f"WARNING: Failed to create file {path}")
        except Exception as e:
            log_message(f"ERROR writing LANG file: {str(e)}")

    def _read_mcfunction_file(self, path: str) -> Dict[str, str]:
        """
        Read MCFUNCTION file and extract translatable text from data modify storage commands.
        Returns a dictionary where keys are unique identifiers and values are the translatable text.
        """
        data = {}
        try:
            with open(path, "r", encoding="utf-8") as file:
                lines = file.readlines()
            
            for line_num, line in enumerate(lines, 1):
                line = line.strip()
                # Look for data modify storage commands with quoted text
                if "data modify storage" in line and "set value" in line:
                    # Extract text between double quotes, handling escaped quotes
                    # This regex matches the content between quotes, handling escaped quotes
                    match = re.search(r'set value "([^"\\]*(?:\\.[^"\\]*)*)"', line)
                    if match:
                        text = match.group(1)
                        # Unescape the text for translation
                        text = text.replace('\\"', '"')
                        # Use file path and line number as unique key
                        key = f"{path}:{line_num}"
                        data[key] = text
                        
            log_message(f"Extracted {len(data)} translatable strings from {path}")
            return data
        except Exception as e:
            log_message(f"Error reading MCFUNCTION file {path}: {str(e)}")
            return {}

    def _write_mcfunction_file(self, original_path: str, translated_data: Dict[str, str]) -> None:
        """
        Write MCFUNCTION file with translated text, preserving the original structure.
        """
        try:
            log_message(f"Writing MCFUNCTION file to {original_path}")
            
            with open(original_path, "r", encoding="utf-8") as file:
                lines = file.readlines()
            
            # Process each line and replace translatable text
            for line_num, line in enumerate(lines):
                original_line = line.strip()
                if "data modify storage" in original_line and "set value" in original_line:
                    # Find the corresponding translated text
                    key = f"{original_path}:{line_num + 1}"
                    if key in translated_data:
                        # Replace the quoted text with translated version
                        translated_text = translated_data[key]
                        # Escape any quotes in the translated text
                        escaped_text = translated_text.replace('"', '\\"')
                        # Replace the original quoted text with translated text
                        # This regex handles escaped quotes properly
                        new_line = re.sub(r'(set value )"([^"\\]*(?:\\.[^"\\]*)*)"', f'\\1"{escaped_text}"', line)
                        lines[line_num] = new_line
            
            # Write the modified content back to the file
            with open(original_path, "w", encoding="utf-8") as file:
                file.writelines(lines)
                
            file_size = os.path.getsize(original_path)
            log_message(f"MCFUNCTION file successfully updated ({file_size} bytes)")
        except Exception as e:
            log_message(f"ERROR writing MCFUNCTION file: {str(e)}")

    def translate_mcfunction_files(self, mod_root_path: str) -> None:
        """
        Find and translate all .mcfunction files in a mod.
        """
        mcfunction_files = []
        
        # Find all .mcfunction files in the mod
        for foldername, _, filenames in os.walk(mod_root_path):
            for filename in filenames:
                if filename.endswith(MCFUNCTION):
                    file_path = os.path.join(foldername, filename)
                    mcfunction_files.append(file_path)
        
        if not mcfunction_files:
            return
            
        log_message(f"Found {len(mcfunction_files)} .mcfunction files to translate")
        
        # Process each mcfunction file
        for file_path in mcfunction_files:
            log_message(f"Processing {file_path}")
            
            # Read translatable text from the file
            original_data = self._read_mcfunction_file(file_path)
            
            if original_data:
                # Translate the extracted text
                translated_data = self.translator.translate_data(original_data)
                
                # Write back the translated content
                self._write_mcfunction_file(file_path, translated_data)
                
                log_message(f"Successfully translated {len(original_data)} strings in {file_path}")
            else:
                log_message(f"No translatable content found in {file_path}")

    def convert_translated_mods(self) -> None:
        """
        Convert all translated mod folders into JAR files.
        """
        mod_folder_list = os.listdir(self.temp_path)
        for mod_folder in mod_folder_list:
            log_message(f'Converting {mod_folder} into mod file...')
            unpacked_mod_path = os.path.join(self.temp_path, mod_folder)
            
            # Check if input and output paths are the same
            same_paths = os.path.abspath(self.mods_path) == os.path.abspath(self.translation_path)
            
            # If same paths, create JAR directly in mods_path to avoid file access issues
            if same_paths:
                translation_path = os.path.join(self.mods_path, mod_folder)
            else:
                translation_path = os.path.join(self.translation_path, mod_folder)
                
            self._convert_folder_to_jar(unpacked_mod_path, translation_path)

    def _convert_folder_to_jar(self, folder_path: str, jar_path: str) -> None:
        """
        Convert folder to JAR file.
        """
        try:
            log_message(f"Creating JAR file: {jar_path}")
            # Ensure the target directory exists
            os.makedirs(os.path.dirname(jar_path), exist_ok=True)

            # First, check if the target language files exist
            lang_files_found = []
            for root, _, files in os.walk(folder_path):
                for file in files:
                    if file.lower().endswith(".json") or file.lower().endswith(".lang"):
                        if self.target_mc_lang.lower() in file.lower():
                            relative_path = os.path.relpath(
                                os.path.join(root, file), folder_path
                            )
                            lang_files_found.append(relative_path)
                            log_message(f"Found target language file: {relative_path}")

            if not lang_files_found:
                log_message(
                    "WARNING: No target language files found in the folder to be packaged! Looking for source files..."
                )

                # If no target files are found, try to generate them from source files
                source_files_found = []
                for root, _, files in os.walk(folder_path):
                    for file in files:
                        if file.lower().endswith(".json") or file.lower().endswith(
                            ".lang"
                        ):
                            if self.source_mc_lang.lower() in file.lower():
                                source_path = os.path.join(root, file)
                                target_path = source_path.replace(
                                    self.source_mc_lang.lower(),
                                    self.target_mc_lang.lower(),
                                )
                                source_files_found.append(
                                    (source_path, target_path, file)
                                )
                                log_message(f"Found source language file: {file}")

                # Try to translate the source files
                for source_path, target_path, filename in source_files_found:
                    extension = os.path.splitext(filename)[1].lower()
                    if extension == JSON:
                        log_message(f"Translating source file: {filename}")
                        original_data = self._read_json_file(source_path)
                        if original_data:
                            translated_data = self.translator.translate_data(
                                original_data
                            )
                            self._write_json_file(translated_data, target_path)
                            relative_path = os.path.relpath(target_path, folder_path)
                            lang_files_found.append(relative_path)
                            log_message(
                                f"Created target language file: {os.path.basename(target_path)}"
                            )
                    elif extension == LANG:
                        log_message(f"Translating source file: {filename}")
                        original_data = self._read_lang_file(source_path)
                        if original_data:
                            translated_data = self.translator.translate_data(
                                original_data
                            )
                            self._write_lang_file(translated_data, target_path)
                            relative_path = os.path.relpath(target_path, folder_path)
                            lang_files_found.append(relative_path)
                            log_message(
                                f"Created target language file: {os.path.basename(target_path)}"
                            )

            # Create the JAR file
            file_count = 0
            with ZipFile(jar_path, "w", ZIP_DEFLATED) as jar:
                for root, _, files in os.walk(folder_path):
                    for file in files:
                        file_path = os.path.join(root, file)
                        relative_path = os.path.relpath(file_path, folder_path)
                        jar.write(file_path, relative_path)
                        file_count += 1

                        # Log when we find a target language file
                        if file.lower().endswith(".json") or file.lower().endswith(
                            ".lang"
                        ):
                            if self.target_mc_lang.lower() in file.lower():
                                log_message(
                                    f"Added target language file to JAR: {relative_path}"
                                )

            # Verify the JAR was created
            if os.path.exists(jar_path):
                jar_size = os.path.getsize(jar_path)
                log_message(
                    f"Successfully created JAR file with {file_count} files ({jar_size} bytes)"
                )
            else:
                log_message(f"ERROR: Failed to create JAR file {jar_path}")
        except Exception as e:
            log_message(f"ERROR creating JAR file: {str(e)}")

    def remove_original_mod_files(self) -> None:
        """
        Remove original JAR files from mods folder, but leave folders intact.
        When input and output paths are the same, we want to overwrite specific
        files but not delete the entire directory structure.
        """
        # Before removing files, check if translated files exist
        translated_jars = [
            f for f in os.listdir(self.translation_path) if f.endswith(JAR)
        ]

        if not translated_jars:
            log_message(
                "WARNING: No translated JAR files found. Skipping removal of original files."
            )
            return

        log_message(
            f"Found {len(translated_jars)} translated JAR files. Proceeding with removal of originals."
        )

        # Count how many files we'll actually remove
        files_to_remove = []
        for filename in os.listdir(self.mods_path):
            file_path = os.path.join(self.mods_path, filename)
            # Only remove JAR files, leave directories intact
            if os.path.isfile(file_path) and file_path.endswith(JAR):
                # Only add to removal list if we have a corresponding translated file
                if filename in translated_jars:
                    files_to_remove.append(file_path)

        log_message(
            f"Will remove {len(files_to_remove)} original JAR files that have translated versions"
        )

        # Now actually remove the files
        for file_path in files_to_remove:
            try:
                os.remove(file_path)
                log_message(f"Removed original JAR file: {file_path}")
            except Exception as e:
                log_message(f"Error removing original JAR file {file_path}: {e}")

        # Ensure we don't accidentally empty directories
        log_message(f"Original JAR files removed. Directories preserved.")

    def move_translated_mod_files(self) -> None:
        """
        Move files to output folder.
        """
        for filename in os.listdir(self.translation_path):
            source_path = os.path.join(self.translation_path, filename)
            destination_path = os.path.join(self.mods_path, filename)

            # Check if source and destination are the same
            if os.path.abspath(source_path) == os.path.abspath(destination_path):
                log_message(
                    f"Skipping {filename} as source and destination are the same"
                )
                continue

            log_message(
                f"Moving {filename} from {self.translation_path} to {self.mods_path}"
            )

            # Handle file or directory differently
            if os.path.isfile(source_path):
                shutil.copy2(source_path, destination_path)
                log_message(f"Copied file {filename}")
            elif os.path.isdir(source_path):
                # For directories, merge contents rather than replacing
                if os.path.exists(destination_path):
                    # Merge directory contents without deleting existing files
                    for root, dirs, files in os.walk(source_path):
                        # Get relative path from source
                        rel_path = os.path.relpath(root, source_path)
                        if rel_path == ".":
                            rel_path = ""

                        # Create target directory
                        target_dir = os.path.join(destination_path, rel_path)
                        os.makedirs(target_dir, exist_ok=True)

                        # Copy all files
                        for file in files:
                            src_file = os.path.join(root, file)
                            dst_file = os.path.join(target_dir, file)
                            shutil.copy2(src_file, dst_file)
                            log_message(f"Copied {os.path.join(rel_path, file)}")
                else:
                    # If destination doesn't exist, copy the whole directory
                    shutil.copytree(source_path, destination_path)
                    log_message(f"Copied directory {filename}")

            log_message(f"Successfully moved {filename}")

    def copy_translated_files_to_same_path(self) -> None:
        """
        When input and output paths are the same, we need to copy translated files
        from the temp directory back to the input path, overwriting the original files
        but preserving the directory structure.
        """
        log_message(f"Copying translated files to original directory: {self.mods_path}")

        # Make sure the mods_path exists for the copy operation
        os.makedirs(self.mods_path, exist_ok=True)

        jar_files_copied = 0

        # First, find all translated JAR files in translation_path
        for filename in os.listdir(self.translation_path):
            source_path = os.path.join(self.translation_path, filename)
            dest_path = os.path.join(self.mods_path, filename)

            if os.path.isfile(source_path) and source_path.endswith(JAR):
                # Copy JAR files, overwriting any existing ones
                log_message(f"Copying JAR file: {filename}")
                try:
                    shutil.copy2(source_path, dest_path)
                    jar_files_copied += 1
                    log_message(f"Copied {filename} to {self.mods_path}")
                except Exception as e:
                    log_message(f"Error copying JAR file {filename}: {e}")
            elif os.path.isdir(source_path):
                # For directories, we need to be careful not to delete anything
                # that wasn't part of the translation
                log_message(f"Processing directory: {filename}")

                # For each unpacked mod folder, copy content carefully
                for root, dirs, files in os.walk(source_path):
                    # Get the relative path from the translation path
                    rel_path = os.path.relpath(root, source_path)
                    if rel_path == ".":
                        rel_path = ""

                    # Create the corresponding directory in the original path
                    target_dir = os.path.join(dest_path, rel_path)
                    os.makedirs(target_dir, exist_ok=True)

                    # Copy all files in the directory
                    for file in files:
                        src_file = os.path.join(root, file)
                        dst_file = os.path.join(target_dir, file)
                        try:
                            shutil.copy2(src_file, dst_file)
                            log_message(f"Copied file: {os.path.join(rel_path, file)}")
                        except Exception as e:
                            log_message(
                                f"Error copying file {os.path.join(rel_path, file)}: {e}"
                            )

        if jar_files_copied > 0:
            log_message(
                f"Successfully copied {jar_files_copied} JAR files to {self.mods_path}"
            )
        else:
            log_message(f"WARNING: No JAR files were copied to {self.mods_path}")

        # Verify JAR files in the destination directory
        jar_files_in_dest = [f for f in os.listdir(self.mods_path) if f.endswith(JAR)]
        log_message(
            f"JAR files in destination directory after copying: {len(jar_files_in_dest)}"
        )
        for jar_file in jar_files_in_dest:
            jar_path = os.path.join(self.mods_path, jar_file)
            jar_size = os.path.getsize(jar_path)
            log_message(f"  - {jar_file} ({jar_size} bytes)")

        log_message(f"Successfully copied all translated files to {self.mods_path}")

    def remove_folder(self, folder_path: str) -> None:
        """
        Remove entire folder.
        """
        shutil.rmtree(folder_path)


def add_translate_arguments(parser: argparse.ArgumentParser) -> None:
    """
    Add arguments for the translate command.

    Args:
        parser: ArgumentParser object
    """
    parser.add_argument(
        "-p", "--path", help="Path to mod or mod folder", default="./mods"
    )
    parser.add_argument("-s", "--source", help="Source language code (e.g., en_US)")
    parser.add_argument("-t", "--target", help="Target language code (e.g., es_ES)")
    parser.add_argument("-o", "--output", help="Output folder path")
    parser.add_argument(
        "--ai", action="store_true", help="Use OpenAI translation instead of Google Translate"
    )
    parser.add_argument(
        "--provider",
        choices=["google", "openai", "deepseek"],
        help="Translation provider. Use deepseek for DeepSeek API.",
    )
    parser.add_argument(
        "--model",
        help="AI model name, e.g. deepseek-v4-pro, deepseek-v4-flash, or deepseek-v4-flash+",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=50,
        help="AI translation batch size (default: 50). Google Translate ignores this option.",
    )
    parser.add_argument(
        "--request-timeout",
        type=float,
        default=90,
        help="Timeout in seconds for each AI API request (default: 90).",
    )
    parser.add_argument(
        "--glossary",
        default="glossary.json",
        help="Path to a glossary JSON file for AI translation (default: glossary.json).",
    )
    parser.add_argument(
        "--no-batch",
        action="store_true",
        help="Disable AI batch translation and use the previous one-entry request flow.",
    )


def handle_translate_command(args: argparse.Namespace) -> None:
    """
    Handle the translate command.
    
    Args:
        args: ArgumentParser arguments
    """
    try:
        provider = getattr(args, "provider", None)
        ai_requested = (hasattr(args, "ai") and args.ai) or provider in {"openai", "deepseek"}

        # Check if AI translation is requested
        if ai_requested:
            provider = provider or "openai"
            log_message(f"🤖 AI translation mode enabled ({provider})")
            # Check if OpenAI dependencies are available
            try:
                import openai
                # Try to load .env file first
                try:
                    from dotenv import load_dotenv
                    load_dotenv()  # This loads the .env file from current directory
                    log_message("📄 Loaded .env file")
                except ImportError:
                    log_message("⚠️ python-dotenv not found, using system environment variables")
                
                # Now check for API key after loading .env
                env_key_name = "DEEPSEEK_API_KEY" if provider == "deepseek" else "OPENAI_API_KEY"
                api_key = os.getenv(env_key_name)
                if not api_key:
                    print(f"❌ Error: {env_key_name} environment variable not set.")
                    print(f"Please set your {provider} API key:")
                    print(f"1. Set {env_key_name} environment variable, or")
                    print(f"2. Create a .env file with: {env_key_name}=your_key_here")
                    print("3. Make sure the .env file is in the project root directory")
                    return
                else:
                    log_message(f"✅ {provider} API key found (length: {len(api_key)} characters)")
                    
            except ImportError:
                print("❌ Error: OpenAI package not found.")
                print("Please install it with: pip install openai python-dotenv")
                return
        else:
            # Check if deep_translator is installed for Google Translate
            try:
                from deep_translator import GoogleTranslator
            except ImportError:
                print("Error: deep_translator package is required for translation.")
                print("Please install it with: pip install deep_translator")
                return
        
        # Create settings with CLI arguments
        settings = Settings(cli_args=args)
        
        file_manager = FileManager(settings)
        
        file_manager.create_needed_folders()
        
        log_title('Unpacking mod files...')
        file_manager.unpack_mods()
        lang_folders = file_manager.get_lang_folders()
        log_title('Translating mods...')
        file_manager.edit_lang_files(lang_folders)
        
        # If input and output paths are the same, we need to handle this case specially
        same_paths = os.path.abspath(settings.mods_path) == os.path.abspath(settings.translation_path)
        
        if same_paths:
            log_title('Input and output paths are the same - removing original JAR files first...')
            # Step 1: Get list of all original JAR files to be replaced
            original_jars = [f for f in os.listdir(settings.mods_path) if f.endswith(JAR)]
            log_message(f"Found {len(original_jars)} original JAR files that will be replaced")
            
            # Step 2: Remove original JAR files BEFORE generating new ones (no backup)
            for jar_file in original_jars:
                jar_path = os.path.join(settings.mods_path, jar_file)
                try:
                    os.remove(jar_path)
                    log_message(f"Removed original JAR: {jar_path}")
                except Exception as e:
                    log_message(f"Error removing {jar_path}: {e}")
        
        # Now convert to mod files - the convert_translated_mods method now handles same paths
        log_title('Converting to mod files...')
        file_manager.convert_translated_mods()
        
        # If same paths, no need to copy files since they're already created in the right place
        if same_paths:
            log_title('Verifying translated JAR files...')
            jar_files = [f for f in os.listdir(settings.mods_path) if f.endswith(JAR)]
            log_message(f"Found {len(jar_files)} JAR files in output directory")
            
            # Verify the files exist and have size
            for jar_file in jar_files:
                jar_path = os.path.join(settings.mods_path, jar_file)
                size = os.path.getsize(jar_path)
                log_message(f"Verified JAR file: {jar_file} ({size} bytes)")
        else:
            # Different paths - output is already in the translation_path
            log_title('Translation completed to output directory...')
        
        # Clean up
        file_manager.remove_folder(settings.temp_path)
        log_title('All mods have been translated!\n')
    except Exception as e:
        print(f"Error translating mods: {e}")
        import traceback
        traceback.print_exc()
        raise
