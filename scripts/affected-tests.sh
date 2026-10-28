#!/bin/sh
# 本机只跑这次改动影响到的测试，全量交给 CI。比的是工作区（含未提交的改动）和基点之间改过的文件：
#
#   后端：改过或新增的 backend/tests/test_*.py，加上直接导入了改过模块（backend/src/eidolon/*.py）的测试文件；
#         被 15 个以上测试导入的枢纽模块（config、store 这类）只加名字里带它的测试。另跑 ruff 和 pyright（全项目，很快）。
#   前端：vitest related 按导入关系找出改过的 frontend/src 文件相关的测试；另跑 typecheck。
#
#   sh scripts/affected-tests.sh [基点]          基点默认是和 origin/main 的分叉点
#   sh scripts/affected-tests.sh --list [基点]   只列出要跑的测试，不跑
#
# 间接受影响的测试会漏掉，由 CI 的全量兜底。
# 退出码：0 都通过（或没有要跑的）；非 0 有一项失败。
set -u

cd "$(dirname "$0")/.." || exit 1
list_only=0
if [ "${1:-}" = "--list" ]; then
  list_only=1
  shift
fi
base=${1:-$(git merge-base origin/main HEAD)}
hub=15
hubs=$(mktemp)
trap 'rm -f "$hubs"' EXIT

changed=$( (git diff --name-only "$base" --; git ls-files --others --exclude-standard) | sort -u)

importers_of() {
  grep -rlE "^(from eidolon\.$1 import|import eidolon\.$1|from eidolon import (.*[ ,])?$1([ ,]|\$))" \
    backend/tests --include='test_*.py'
}

backend_tests=$(
  {
    printf '%s\n' "$changed" | grep -E '^backend/tests/(.*/)?test_[^/]*\.py$'
    printf '%s\n' "$changed" | grep -E '^backend/src/eidolon/[^/]+\.py$' | while read -r file; do
      module=$(basename "$file" .py)
      importers=$(importers_of "$module")
      if [ "$(printf '%s\n' "$importers" | grep -c .)" -gt "$hub" ]; then
        printf '%s\n' "$module" >> "$hubs"
        find backend/tests -name "test_*${module}*.py"
      else
        printf '%s\n' "$importers"
      fi
    done
  } | sort -u | while read -r test; do [ -f "$test" ] && printf '%s\n' "$test"; done
)
frontend_sources=$(printf '%s\n' "$changed" | grep -E '^frontend/src/.*\.(ts|tsx)$' | while read -r file; do
  [ -f "$file" ] && printf '%s\n' "${file#frontend/}"
done)
backend_changed=$(printf '%s\n' "$changed" | grep -E '^backend/' | head -n 1)
frontend_changed=$(printf '%s\n' "$changed" | grep -E '^frontend/' | head -n 1)
stand3d_changed=$(printf '%s\n' "$changed" | grep -E '^(scripts/stand3d/|scripts/check-stand3d\.py$|\.github/workflows/ci\.yml$)' | head -n 1)

if [ "$list_only" = 1 ]; then
  printf '基点 %s\n后端测试：\n%s\n枢纽模块（只按名字找测试）：%s\n前端改过的源文件（vitest related）：\n%s\n' \
    "$base" "${backend_tests:-（无）}" "$(sort -u "$hubs" | tr '\n' ' ')" "${frontend_sources:-（无）}"
  exit 0
fi

failed=0
run() {
  printf '\n▶ %s\n' "$*"
  "$@" || failed=1
}

if [ -n "$backend_changed" ]; then
  (cd backend && run uv run ruff check && run uv run pyright && exit "$failed") || failed=1
  if [ -n "$backend_tests" ]; then
    # shellcheck disable=SC2046 # 测试文件名不带空格，按行拆成参数
    (cd backend && run uv run pytest -q -p no:cacheprovider $(printf '%s\n' "$backend_tests" | sed 's#^backend/##') && exit "$failed") || failed=1
  fi
fi
if [ -n "$frontend_changed" ]; then
  (cd frontend && run npm run --silent typecheck && exit "$failed") || failed=1
  if [ -n "$frontend_sources" ]; then
    # shellcheck disable=SC2086 # 源文件名不带空格，按行拆成参数
    (cd frontend && run npx vitest related --run --passWithNoTests $frontend_sources && exit "$failed") || failed=1
  fi
fi
if [ -n "$stand3d_changed" ]; then
  run uv run --no-project --python 3.11 python scripts/check-stand3d.py
  (cd backend && run uv run ruff check --config pyproject.toml ../scripts/stand3d ../scripts/check-stand3d.py && exit "$failed") || failed=1
fi

if [ "$failed" = 0 ]; then
  printf '\n受影响的检查都通过了；全量看 CI。\n'
else
  printf '\n有检查失败，见上面的输出。\n'
fi
exit "$failed"
