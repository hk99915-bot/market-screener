#!/bin/sh
# 저장소 훅(.githooks/) 설치 — 세션 시작 시 1회: sh scripts/install_hooks.sh
#  - pre-push: scripts/prepush_check.py (board·check_functions·rules_terms·이메일·개인 금액·CI 게이트·pytest 서브셋)
#  - pre-commit: scripts/secret_guard.py (11/6 — 토큰·계좌번호 모양·개인 금액 커밋 차단, 우회 SECRET_GUARD_SKIP=1 은 기록됨)
# core.hooksPath 는 이 체크아웃(과 그 worktree 들)의 로컬 git 설정이다. Actions 러너의 checkout 에는 적용되지 않는다.
set -e
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
chmod +x .githooks/* 2>/dev/null || true
git config core.hooksPath .githooks
echo "hooks 설치: core.hooksPath=$(git config --get core.hooksPath) ($(ls .githooks | tr '\n' ' '))"
