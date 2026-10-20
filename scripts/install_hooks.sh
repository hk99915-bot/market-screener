#!/bin/sh
# 저장소 훅(.githooks/) 설치 — 세션 시작 시 1회: sh scripts/install_hooks.sh
# core.hooksPath 는 이 체크아웃(과 그 worktree 들)의 로컬 git 설정이다. Actions 러너의 checkout 에는 적용되지 않는다.
set -e
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
chmod +x .githooks/* 2>/dev/null || true
git config core.hooksPath .githooks
echo "hooks 설치: core.hooksPath=$(git config --get core.hooksPath) ($(ls .githooks | tr '\n' ' '))"
