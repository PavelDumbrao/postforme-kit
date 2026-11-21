# Официальный MCP-сервер Post for Me (по желанию)

Скрипт `scripts/pfm.py` закрывает всё нужное для публикации. MCP добавляет агенту «живой» доступ к API Post for Me: можно спрашивать статистику, списки постов, переносить запланированное обычными словами.

Как он устроен: у сервера два инструмента — поиск по документации и запуск кода на официальном SDK в песочнице. Песочница **не видит ваш диск**, поэтому ролик с компьютера через MCP не загрузить — для этого остаётся `scripts/pfm.py` (или публичная ссылка на файл).

Ключ тот же, что в `.env`. Важно: MCP даёт агенту полный доступ ко всем подключённым соцсетям.

## Вариант A. Облачный (ничего не ставить)
Адрес: `https://post-for-me.stlmcp.com`, ключ передаётся заголовком `x-post-for-me-api-key`.

**Claude Code** (в терминале):
```bash
claude mcp add post_for_me --transport http https://post-for-me.stlmcp.com --header "x-post-for-me-api-key: pfm_live_ваш-ключ"
```

**Cursor** — Settings → Tools & MCP → New MCP Server, в `mcp.json`:
```json
{
  "mcpServers": {
    "post_for_me": {
      "url": "https://post-for-me.stlmcp.com",
      "headers": { "x-post-for-me-api-key": "pfm_live_ваш-ключ" }
    }
  }
}
```

**VS Code** — Command Palette → «MCP: Open User Configuration»:
```json
{
  "servers": {
    "post_for_me": {
      "type": "http",
      "url": "https://post-for-me.stlmcp.com",
      "headers": { "x-post-for-me-api-key": "pfm_live_ваш-ключ" }
    }
  }
}
```

## Вариант B. Локально через npx (нужен Node.js 20+)
**Claude Desktop / Cursor / любой клиент с JSON-конфигом:**
```json
{
  "mcpServers": {
    "post_for_me": {
      "command": "npx",
      "args": ["-y", "post-for-me-mcp@latest"],
      "env": { "POST_FOR_ME_API_KEY": "pfm_live_ваш-ключ" }
    }
  }
}
```

**Codex** (`~/.codex/config.toml`):
```toml
[mcp_servers.post_for_me]
command = "npx"
args = ["-y", "post-for-me-mcp@latest"]
env = { POST_FOR_ME_API_KEY = "pfm_live_ваш-ключ" }
```

## Проверка
Спросите агента: «Через MCP Post for Me покажи мои подключённые соцсети». Должен вернуться тот же список, что у `python3 scripts/pfm.py accounts`.

## Что спрашивать через MCP
- «Покажи запланированные посты на эту неделю».
- «Перенеси пост sp_... на завтра 12:00 по Москве».
- «Сколько просмотров и лайков у моих последних 5 Reels?»
- «Почему не опубликовался пост sp_...? Покажи ошибку».

Источник: README пакета [post-for-me-mcp](https://www.npmjs.com/package/post-for-me-mcp) и страница https://www.postforme.dev/resources/let-ai-post-for-you.
