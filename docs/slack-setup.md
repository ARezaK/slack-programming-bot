# Slack App Setup Guide

## 1. Create a Slack App

1. Go to https://api.slack.com/apps
2. Click "Create New App" → "From scratch"
3. Name: "Coding Agent" (or whatever you prefer)
4. Select your workspace
5. Click "Create App"

## 2. Enable Socket Mode

1. Go to **Settings** → **Socket Mode** in the left sidebar
2. Toggle "Enable Socket Mode" → ON
3. When prompted, create an app-level token:
   - Token Name: "socket-mode"
   - Scope: `connections:write`
   - Click "Generate"
4. Copy the `xapp-...` token → this is your `SLACK_APP_TOKEN`

## 3. Set Bot Scopes

1. Go to **Features** → **OAuth & Permissions**
2. Under "Bot Token Scopes", add:
   - `app_mentions:read` — to receive @mentions
   - `chat:write` — to reply in threads
   - `channels:history` — to read thread replies
   - `groups:history` — for private channels (optional)

## 4. Enable Events

1. Go to **Features** → **Event Subscriptions**
2. Toggle "Enable Events" → ON
3. Under "Subscribe to bot events", add:
   - `app_mention` — triggers when someone @mentions the bot
   - `message.channels` — to catch thread replies
4. Click "Save Changes"

## 5. Install to Workspace

1. Go to **Settings** → **Install App**
2. Click "Install to Workspace"
3. Authorize the app
4. Copy the "Bot User OAuth Token" (`xoxb-...`) → this is your `SLACK_BOT_TOKEN`

## 6. Configure .env

```bash
cp .env.example .env
# Edit .env with your tokens:
# SLACK_BOT_TOKEN=xoxb-...
# SLACK_APP_TOKEN=xapp-...
# ANTHROPIC_API_KEY=sk-ant-...
```

## 7. Run the Bot

```bash
# First, scan your repos
uv run bot-cli scan-repos

# Start the bot
uv run bot-cli run
```

## 8. Test It

In any channel where the bot is added, type:
```
@Coding Agent fix the login tests in PMSS
```

To add the bot to a channel: go to the channel, click the channel name at top → "Integrations" → "Add apps" → select your bot.
