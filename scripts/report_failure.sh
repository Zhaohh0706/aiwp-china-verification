#!/usr/bin/env bash
# 月度榜单失败时开一个 issue；同一天再失败就追加评论，免得刷屏。
set -euo pipefail
DAY=$(date -u +%F)
LABEL=leaderboard-failure
TITLE="[leaderboard] 月度榜单在 $DAY 失败"

gh label create "$LABEL" --color B60205 --description "月度榜单流水线失败（自动创建）" || true

BODY=$(cat <<TXT
运行：${RUN_URL}

取数被配额挡住是正常的，那一步设了 continue-on-error，不会让工作流失败。
走到这里说明是出榜、测试或提交出了问题。先看 \`make leaderboard\` 的输出，
再看 \`data/\` 下的 parquet 是否完整。
TXT
)

NUM=$(gh issue list --state open --label "$LABEL" --limit 50 --json number,title \
      | jq -r --arg t "$TITLE" 'map(select(.title == $t)) | first | .number // empty')
if [ -n "$NUM" ]; then
  gh issue comment "$NUM" --body "$BODY"
else
  gh issue create --title "$TITLE" --label "$LABEL" --body "$BODY"
fi
