#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REAL_HOME="${REAL_HOME:-$HOME}"
SKILL_TARGET="${REAL_HOME}/.agents/skills/gemini-subagent"
BIN_DIR="${REAL_HOME}/.local/bin"
BIN_LINK="${BIN_DIR}/gemini-subagent"
LINK_MODE=false

if [[ "${1:-}" == "--link" ]]; then
  LINK_MODE=true
fi

mkdir -p "${REAL_HOME}/.agents/skills" "${BIN_DIR}"

if [[ "$LINK_MODE" == "true" ]]; then
  ln -sfn "${SCRIPT_DIR}" "${SKILL_TARGET}"
  echo "[OK] Linked skill: ${SKILL_TARGET} -> ${SCRIPT_DIR}"
else
  if [[ "${SCRIPT_DIR}" != "${SKILL_TARGET}" ]]; then
    mkdir -p "${SKILL_TARGET}/scripts" "${SKILL_TARGET}/agents"
    cp -f "${SCRIPT_DIR}/SKILL.md" "${SKILL_TARGET}/SKILL.md"
    cp -f "${SCRIPT_DIR}/agents/openai.yaml" "${SKILL_TARGET}/agents/openai.yaml"
    cp -f "${SCRIPT_DIR}/scripts/gemini_subagent.py" "${SKILL_TARGET}/scripts/gemini_subagent.py"
    cp -f "${SCRIPT_DIR}/scripts/gemini_collab_mcp.py" "${SKILL_TARGET}/scripts/gemini_collab_mcp.py"
    chmod 755 "${SKILL_TARGET}/scripts/gemini_subagent.py" "${SKILL_TARGET}/scripts/gemini_collab_mcp.py"
    echo "[OK] Installed skill files to ${SKILL_TARGET}"
  else
    chmod 755 "${SKILL_TARGET}/scripts/gemini_subagent.py" "${SKILL_TARGET}/scripts/gemini_collab_mcp.py"
    echo "[OK] Skill already at ${SKILL_TARGET}"
  fi
fi

ln -sfn "${SKILL_TARGET}/scripts/gemini_subagent.py" "${BIN_LINK}"
echo "[OK] Linked CLI: ${BIN_LINK}"

AGENT_SKILL_DIRS=(
  "${REAL_HOME}/.gemini/config/skills"
  "${REAL_HOME}/Library/Application Support/Antigravity Google/home/.gemini/config/skills"
  "${REAL_HOME}/.claude/skills"
  "${REAL_HOME}/.codex/skills"
  "${REAL_HOME}/.workbuddy/skills"
)

for dir in "${AGENT_SKILL_DIRS[@]}"; do
  if [[ -d "$dir" ]]; then
    ln -sfn "${SKILL_TARGET}" "${dir}/gemini-subagent"
    echo "[OK] Registered skill in ${dir}/gemini-subagent"
  fi
done

echo ""
echo "Next steps:"
echo "  1. Run: ${BIN_LINK} doctor"
echo "  2. Optional: Mount ${SKILL_TARGET}/scripts/gemini_collab_mcp.py in Gemini.app Custom Local MCP (open 'googlegemini://?target=customize')"
