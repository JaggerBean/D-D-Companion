# D&D Companion — Discord voice copilot

Local Windows app for a Discord D&D table. Bot joins voice channel, receives every Discord member's own PCM stream. Each member's audio goes through local `faster-whisper` separately. Transcript labels come from Discord user identity, not unreliable speaker diarization on mixed desktop recording.

```text
Discord member audio streams (identity already known)
                     |
       local bot receives PCM per member
                     |
   local faster-whisper large-v3-turbo on RTX 4090
                     |
speaker-labelled transcript + local WAV archives + SQLite session
                     |
rolling scene context + campaign notes
                     |
F5/F6/F7/F8 copies compact prompt to clipboard
                     |
your normal ChatGPT conversation: Ctrl+V, Enter
```

No OpenAI API, paid transcription API, browser automation, ChatGPT login automation, or automatic ChatGPT submission. Audio, transcript, vocabulary, notes, character files, WAV archives stay on computer running bot. Only clipboard text you choose to paste into ChatGPT leaves it.

## One Discord-account step cannot be automated

Bot must be created and invited under a Discord account that can add bots to your D&D server. No program can safely create a bot or retrieve its token without that account's Developer Portal authorization.

1. At [Discord Developer Portal](https://discord.com/developers/applications), create application. Open **Bot**. Create and copy token.
2. In **OAuth2 > URL Generator**, select `bot` and `applications.commands`. Give only **View Channels**, **Connect**, **Speak**. Open generated URL. Add bot to D&D server. Discord documents `bot` installs bot; `applications.commands` enables slash commands. [Discord OAuth2 docs](https://discord.com/developers/docs/topics/oauth2)
3. Run `setup.bat`. Open `config/discord.env`. Replace placeholder:

   ```ini
   DISCORD_BOT_TOKEN=your-token-here
   ```

   Never share or commit this file.
4. Put test-server ID in first-run wizard. `/join` appears immediately. Blank works but global commands can take time to appear.

## Install and session flow

1. On Windows RTX 4090 machine, install 64-bit Python 3.12+ and current NVIDIA driver.
2. Double-click `setup.bat`. Creates `.venv`, installs voice/local transcription dependencies, copies private token-file template, checks CUDA, opens app.
3. Complete wizard. First transcription downloads selected Whisper model. `large-v3-turbo`: live latency. `large-v3`: slower, accuracy-first.
4. Create session. Click **Start Discord Bot**.
5. In Discord server, join session voice channel. Run `/join`. Bot joins current channel, receives distinct participant streams. `/leave` disconnects. `/whoami` reports Discord ID for mapping.
6. Press F8 for an in-character response prompt. Prompt copies locally. App can focus open ChatGPT window. Paste/send manually.

Later: double-click `run.bat`.

## Hotkeys

| Key | Action |
|---|---|
| F8 | Copy roleplay prompt |
| F7 | Copy tactical prompt |
| F6 | Copy knowledge-check prompt |
| F5 | Copy questions-to-ask prompt |
| F9 | Mark last 30 seconds as important notes |
| Ctrl+F9 | Insert new-scene marker |
| Ctrl+F8 | Copy roleplay prompt and focus ChatGPT |
| F10 | Show control panel |

Bindings: `config.yaml`. `controller_user_ids` can limit `/join` and `/leave` to specified Discord IDs. Empty: server managers control them.

## Speaker names and vocabulary

Run `/whoami` once per person. Add IDs to `config/speakers.yaml`:

```yaml
speakers:
  "123456789012345678": "Vaelor"
  "234567890123456789": "DM"
```

Add fictional names, locations, NPCs, spells, items one per line to `config/vocabulary.txt`. Whisper uses local initial prompt for proper names. Never invents/re-writes dialogue.

Put character reference in `character/character_summary.md` or `.txt`. Set `character.include_summary_in_prompt: true` only when needed.

## Local session storage

Each session autosaves under `sessions/YYYY-MM-DD_HHMMSS_name/`:

```text
audio/              original Discord PCM/WAV archive per speaker
transcript.jsonl    machine-readable live transcript
transcript.txt      readable transcript
notes.md            marked/manual campaign facts
metadata.json       session metadata
```

`sessions/sessions.db` stores session/transcript records. JSONL writes immediately. Correct misheard lines with **Correct Transcript**.

## Troubleshooting

**`/join` missing:** enter server ID in `discord.application_guild_id`, restart bot. Confirm OAuth scopes include `bot` and `applications.commands`.

**Bot cannot join:** role needs View Channel, Connect, Speak. Token must be in `config/discord.env`, not example file.

**Bot joins, no transcript:** confirm player consent, inspect `logs/app.log`, update `discord-ext-voice-recv` if Discord changes voice transport. Extension is third-party and describes API as not fully feature-complete. [Project docs](https://github.com/imayhaveborkedit/discord-ext-voice-recv)

**CUDA unavailable:** update NVIDIA drivers. Install CUDA/cuDNN runtime needed by installed CTranslate2. `setup.bat` prints CUDA device count. App falls back to CPU.

**Whisper slow:** change to `distil-large-v3`, `medium`, `small` in `config.yaml`. RTX 4090: keep `device: cuda`, `compute_type: float16`.

**Hotkey conflict:** use e.g. `ctrl+alt+f8` in `config.yaml`.

## Real-world verification

Tests cover persistence, prompt/context trimming, notes, config, corrections. Windows/Discord checks remain: bot invite/token, voice permissions, current Discord voice transport, CUDA model loading, per-person labels, hotkey conflicts.
