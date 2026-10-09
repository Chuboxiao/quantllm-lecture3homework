#!/bin/bash
set -euo pipefail
task_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$task_root"
repo_name="quantllm-lecture3homework"

if ! command -v gh >/dev/null 2>&1; then
  if ! command -v brew >/dev/null 2>&1; then
    echo "请先从 https://cli.github.com/ 安装 GitHub CLI，再运行此脚本。"
    exit 1
  fi
  brew install gh
fi
if ! gh auth status >/dev/null 2>&1; then
  gh auth login --hostname github.com --git-protocol https --web
fi
gh auth setup-git
owner="$(gh api user --jq .login)"
target="$owner/$repo_name"

if git remote get-url origin >/dev/null 2>&1; then
  existing="$(git remote get-url origin)"
  if [[ "$existing" != "https://github.com/$target.git" && "$existing" != "git@github.com:$target.git" ]]; then
    echo "origin 已指向另一个仓库：$existing。请检查后再上传。"
    exit 1
  fi
  git push --set-upstream origin main
else
  if gh repo view "$target" >/dev/null 2>&1; then
    echo "同名仓库已存在：https://github.com/$target。请更换本脚本 repo_name 或自行设置远程仓库。"
    exit 1
  fi
  gh repo create "$target" --public --source . --remote origin --push --description "第三讲实践课：上证50高频数据、完整订单簿、模拟撮合与网页展示"
fi
echo
echo "上传完成。请将这个仓库链接提交到课程 Issue #6："
echo "https://github.com/$target"
echo "提交位置：https://github.com/aslan9/pku_quantllm/issues/6"
