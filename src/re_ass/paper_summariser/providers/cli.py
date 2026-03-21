"""CLI-based LLM providers for the Science Paper Summariser.

Providers invoke AI CLI tools (claude, codex, gemini, copilot) via subprocess
in non-interactive mode. All CLI providers share a common base pattern: combine
system and user prompts into a single text prompt and capture stdout.

CLI providers never support direct PDF input — text extraction via marker-pdf
is always performed before the prompt is constructed.
"""

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .base import Provider


class CLIProvider(Provider):
    """Base class for CLI-based providers.

    Subclasses configure the invocation by setting class attributes:
        cli_command          — Executable name (e.g. "claude").
        prompt_flag          — Flag for the prompt argument (e.g. "-p"), or "" for positional.
        extra_flags          — Additional flags inserted before the prompt.
        model_flag           — Flag for model override (e.g. "--model"), or "" to disable.
        default_context_size — Context window size for the provider family.
        default_timeout      — Subprocess timeout in seconds.
    """

    cli_command = ""
    prompt_flag = ""
    extra_flags = []
    model_flag = "--model"
    default_context_size = 200_000
    default_timeout = 600
    env_blocklist = ()

    def setup(self):
        """Verify the CLI tool is available on PATH and apply default model."""
        if not shutil.which(self.cli_command):
            raise ValueError(f"'{self.cli_command}' CLI not found on PATH")
        if not self.model and hasattr(self, "default_model"):
            self.model = self.default_model

    def supports_direct_pdf(self):
        return False

    def _build_command(self, prompt):
        """Build the subprocess command list."""
        cmd = [self.cli_command, *self.extra_flags]
        if self.model and self.model_flag:
            cmd.extend([self.model_flag, self.model])
        if self.prompt_flag:
            cmd.extend([self.prompt_flag, prompt])
        else:
            cmd.append(prompt)
        return cmd

    def _run_command(self, cmd, input_text=None):
        """Run the CLI command and normalise timeout errors."""
        env = os.environ.copy()
        for key in self.env_blocklist:
            env.pop(key, None)

        timeout_seconds = int(self.config.get("timeout", self.default_timeout))
        try:
            return subprocess.run(
                cmd,
                input=input_text,
                capture_output=True,
                env=env,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                f"{self.cli_command} timed out after {timeout_seconds}s"
            ) from exc

    @staticmethod
    def _get_error_output(result):
        """Extract a concise error message from a completed subprocess."""
        error_output = result.stderr.strip() or result.stdout.strip()
        return error_output[:500] if error_output else "(no output)"

    def process_document(self, content, is_pdf, system_prompt, user_prompt, max_tokens=12288):
        """Process document by invoking the CLI tool with the combined prompt."""
        combined_prompt = f"{system_prompt}\n\n{user_prompt}"
        cmd = self._build_command(combined_prompt)

        logging.info(
            f"Invoking {self.cli_command} CLI "
            f"(prompt: {len(combined_prompt)} chars, timeout: {int(self.config.get('timeout', self.default_timeout))}s)"
        )

        result = self._run_command(cmd)

        if result.returncode != 0:
            error_snippet = self._get_error_output(result)
            raise RuntimeError(
                f"{self.cli_command} exited with code {result.returncode}: {error_snippet}"
            )

        output = result.stdout
        if not output or not output.strip():
            raise ValueError(f"{self.cli_command} returned empty output")

        logging.info(f"{self.cli_command} CLI returned {len(output)} chars")
        return output

    def get_max_context_size(self):
        return self.default_context_size


class ClaudeCLI(CLIProvider):
    """Claude Code CLI provider (claude --output-format text -p <prompt>)."""

    cli_command = "claude"
    prompt_flag = "-p"
    extra_flags = ["--output-format", "text"]
    model_flag = "--model"
    default_model = "claude-sonnet-4-6"
    default_context_size = 200_000
    env_blocklist = ("ANTHROPIC_API_KEY",)


class CodexCLI(CLIProvider):
    """OpenAI Codex CLI provider (codex exec <prompt>).

    Model override uses codex's -c config syntax rather than a --model flag.
    """

    cli_command = "codex"
    prompt_flag = ""  # Prompt is positional after the exec subcommand
    extra_flags = ["exec"]
    model_flag = ""  # Handled by _build_command override
    default_context_size = 200_000
    default_timeout = 1800
    env_blocklist = ("OPENAI_API_KEY",)

    def _build_command(self, prompt):
        """Build command with codex-specific model config syntax."""
        cmd = [self.cli_command, *self.extra_flags]
        if self.model:
            cmd.extend(["-c", f'model="{self.model}"'])
        cmd.extend(["-"])
        return cmd

    def process_document(self, content, is_pdf, system_prompt, user_prompt, max_tokens=12288):
        """Run Codex using stdin for the prompt and a temp file for the final reply.

        Codex writes session banners and warnings to stdout in exec mode. Using
        `-o` keeps the captured summary clean and avoids leaking prompt text via
        timeout exceptions because the prompt is no longer a positional argument.
        """
        combined_prompt = f"{system_prompt}\n\n{user_prompt}"
        cmd = self._build_command(combined_prompt)

        output_path = None
        try:
            with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as tmp:
                output_path = Path(tmp.name)

            cmd.extend(["-o", str(output_path)])

            logging.info(
                f"Invoking {self.cli_command} CLI "
                f"(prompt: {len(combined_prompt)} chars, timeout: {int(self.config.get('timeout', self.default_timeout))}s)"
            )

            result = self._run_command(cmd, input_text=combined_prompt)

            if result.returncode != 0:
                error_snippet = self._get_error_output(result)
                raise RuntimeError(
                    f"{self.cli_command} exited with code {result.returncode}: {error_snippet}"
                )

            output = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
            if not output or not output.strip():
                raise ValueError(f"{self.cli_command} returned empty output")

            logging.info(f"{self.cli_command} CLI returned {len(output)} chars")
            return output
        finally:
            if output_path and output_path.exists():
                output_path.unlink()


class GeminiCLI(CLIProvider):
    """Google Gemini CLI provider (gemini -o text -p <prompt>)."""

    cli_command = "gemini"
    prompt_flag = "-p"
    extra_flags = ["-o", "text"]
    model_flag = "-m"
    default_context_size = 1_000_000
    env_blocklist = ("GOOGLE_API_KEY",)


class CopilotCLI(CLIProvider):
    """GitHub Copilot CLI provider.

    Requires --allow-all-tools for non-interactive mode and --silent
    to suppress stats/progress output that would pollute the summary.
    """

    cli_command = "copilot"
    prompt_flag = "-p"
    extra_flags = ["--allow-all-tools", "--output-format", "text", "--silent"]
    model_flag = "--model"
    default_context_size = 128_000
