# Opt-in cron for `orchestrator hypothesize`

**Default: OFF.** Do not wire this up until you have manually run ≥5 full cycles
with no surprises (see prerequisites below).

## Prerequisites

Before enabling a scheduled cycle, confirm:

1. At least 5 manual `uv run orchestrator hypothesize` cycles have completed
   cleanly — no AST validator rejects, no sandbox kills, no runaway spend.
2. `HYPOTHESIS_DAILY_USD_CAP` is set to a value you are willing to lose every
   single day. The budget guard aborts mid-cycle on overshoot, but a stuck
   cron will try again tomorrow.
3. `XAI_API_KEY` is present in the environment the cron user inherits
   (systemd `EnvironmentFile=` or crontab `source .env`).
4. Generated proposed strategies have been reviewed at least once by hand —
   cron output goes straight to `wiki/30-Strategies/proposed/` without a
   gate, so anything produced there is still blocked from live trading by
   the usual promotion workflow, but you should skim the files.

## Example crontab entry (commented out by default)

```cron
# algo-betting: daily hypothesis cycle at 07:15 UTC
# 15 7 * * * cd /home/you/algo-betting && /usr/bin/env -S bash -c 'source .env && uv run orchestrator hypothesize >> var/research_orchestrator/cron.log 2>&1'
```

Uncomment the second line only after the prerequisites above are satisfied.

## Example systemd timer (preferred on a server)

`/etc/systemd/system/orchestrator-hypothesize.service`:

```ini
[Unit]
Description=algo-betting hypothesis cycle

[Service]
Type=oneshot
WorkingDirectory=/home/you/algo-betting
EnvironmentFile=/home/you/algo-betting/.env
ExecStart=/home/you/.local/bin/uv run orchestrator hypothesize
StandardOutput=append:/home/you/algo-betting/var/research_orchestrator/cron.log
StandardError=inherit
```

`/etc/systemd/system/orchestrator-hypothesize.timer`:

```ini
[Unit]
Description=Run hypothesis cycle daily

[Timer]
OnCalendar=*-*-* 07:15:00 UTC
Persistent=false

[Install]
WantedBy=timers.target
```

Enable with `systemctl --user enable --now orchestrator-hypothesize.timer`.
Disable with `systemctl --user disable --now orchestrator-hypothesize.timer`.

## Where logs go

- stdout/stderr: `var/research_orchestrator/cron.log` (append-only; rotate
  manually or via `logrotate`)
- per-cycle daily summary: `wiki/70-Daily/YYYY-MM-DD.md`
- per-spec proposed strategies: `wiki/30-Strategies/proposed/*.md`
- spend accounting: `var/research_orchestrator/spend.db` (SQLite)

## Checking spend

```
uv run orchestrator spend-today
```

Prints `Spend today: $X.XX / $Y.YY cap`. Run this before assuming cron is
healthy — a silent budget-cap abort shows up as `$0.00 spent` with a cycle
that produced zero outcomes in the daily log.

## Disabling

Comment the crontab line, or `systemctl disable --now
orchestrator-hypothesize.timer`. No state cleanup is required — the
orchestrator is stateless between cycles apart from the SQLite spend DB and
the wiki files, both of which are safe to leave in place.
