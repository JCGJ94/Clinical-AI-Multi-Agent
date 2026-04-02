# Skill Registry — Clinical-AI-Multi-Agent

Generated: 2026-03-30

## User Skills

| Skill | Trigger |
|-------|---------|
| branch-pr | When creating a pull request, opening a PR, or preparing changes for review |
| issue-creation | When creating a GitHub issue, reporting a bug, or requesting a feature |
| judgment-day | When user says "judgment day", "judgment-day", "review adversarial", "dual review", "doble review", "juzgar", "que lo juzguen" |
| skill-creator | When user asks to create a new skill, add agent instructions, or document patterns for AI |
| go-testing | When writing Go tests, using teatest, or adding test coverage |

## Project Skills

_None detected._

## Project Conventions

_No CLAUDE.md, AGENTS.md, or .cursorrules found at project root._

## Compact Rules

### branch-pr
- Always create a branch per change (never commit to main directly)
- Branch naming: `feat/`, `fix/`, `chore/`, `docs/` prefix
- PR must reference an issue
- PR title follows conventional commits format

### issue-creation
- Issues must be created before any implementation work
- Use labels: `bug`, `feature`, `chore`, `docs`
- Include acceptance criteria in issue body

### judgment-day
- Two independent blind judge sub-agents review simultaneously
- Both must pass before changes are accepted
- Escalate after 2 failed iterations

### skill-creator
- Follow Agent Skills spec format with SKILL.md frontmatter
- Include triggers, compact rules, and examples
