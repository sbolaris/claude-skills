#!/usr/bin/env bash
#
# Install this repo's Claude Code config into ~/.claude on a new machine.
#
#   ./install.sh          # symlink everything (default)
#   ./install.sh --copy   # copy instead of symlink
#   ./install.sh --dry-run
#
# Symlinks are the default so that editing a skill during a session edits the
# repo directly — no copy-back step, and `git status` shows what you changed.
#
# Runtime state in ~/.claude (projects/, sessions/, history.jsonl, .credentials.json)
# is never touched. Anything replaced is backed up to ~/.claude/backups/<timestamp>/.

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP_DIR="$CLAUDE_DIR/backups/install-$STAMP"

MODE="symlink"
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --copy)    MODE="copy" ;;
    --dry-run) DRY_RUN=1 ;;
    -h|--help) sed -n '2,14p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

# Symlinked: Claude Code reads these and never rewrites them.
# skills/ is handled separately — see install_skills, which links each skill
# individually so the gitignored skills-local/ can be layered into the same
# directory.
LINK_ITEMS=(agents commands pipeline CLAUDE.md)

# Always copied: Claude Code REWRITES settings.json when you change model/theme
# via /config. Through a symlink that would silently edit the repo, and some
# writers replace the file rather than writing through, breaking the link.
COPY_ITEMS=(settings.json)

say() { printf '%s\n' "$*"; }
run() { if [ "$DRY_RUN" -eq 1 ]; then say "  [dry-run] $*"; else "$@"; fi; }

say "repo:   $REPO_DIR"
say "target: $CLAUDE_DIR"
say "mode:   $MODE"
[ "$DRY_RUN" -eq 1 ] && say "(dry run — nothing will change)"
say ""

run mkdir -p "$CLAUDE_DIR"

backup() {
  local target="$1"
  [ -e "$target" ] || [ -L "$target" ] || return 0
  run mkdir -p "$BACKUP_DIR"
  run mv "$target" "$BACKUP_DIR/"
  say "  backed up existing $(basename "$target") → ${BACKUP_DIR/#$HOME/\~}"
}

install_item() {
  local name="$1" how="$2"
  local src="$REPO_DIR/$name" dest="$CLAUDE_DIR/$name"

  if [ ! -e "$src" ]; then
    say "skip $name (not in repo)"
    return 0
  fi

  # Already correctly linked — leave it alone.
  if [ "$how" = symlink ] && [ -L "$dest" ] && [ "$(readlink "$dest")" = "$src" ]; then
    say "ok   $name (already linked)"
    return 0
  fi

  backup "$dest"
  if [ "$how" = symlink ]; then
    run ln -sfn "$src" "$dest"
    say "link $name"
  else
    run cp -R "$src" "$dest"
    say "copy $name"
  fi
}

# skills/ and skills-local/ are merged into one ~/.claude/skills directory by
# linking each skill individually. Claude Code only registers a skill that is a
# directory containing SKILL.md with YAML frontmatter, so a flat .md file left
# over from an older layout is inert — those get backed up along with everything
# else and replaced by the real thing.
install_skills() {
  local target="$CLAUDE_DIR/skills"

  # Replace whatever is there once, unless we already manage it.
  if [ ! -f "$target/.managed-by-claude-skills" ]; then
    backup "$target"
    run mkdir -p "$target"
    run touch "$target/.managed-by-claude-skills"
  fi

  local count=0 local_count=0
  for dir in "$REPO_DIR"/skills/*/; do
    [ -f "$dir/SKILL.md" ] || continue
    local name; name="$(basename "$dir")"
    if [ "$MODE" = symlink ]; then
      run ln -sfn "${dir%/}" "$target/$name"
    else
      run rm -rf "$target/$name"
      run cp -R "${dir%/}" "$target/$name"
    fi
    count=$((count + 1))
  done

  # Private overlay: gitignored, never published, installed the same way.
  if [ -d "$REPO_DIR/skills-local" ]; then
    for dir in "$REPO_DIR"/skills-local/*/; do
      [ -f "$dir/SKILL.md" ] || continue
      local name; name="$(basename "$dir")"
      if [ "$MODE" = symlink ]; then
        run ln -sfn "${dir%/}" "$target/$name"
      else
        run rm -rf "$target/$name"
        run cp -R "${dir%/}" "$target/$name"
      fi
      local_count=$((local_count + 1))
    done
  fi

  say "$([ "$MODE" = symlink ] && echo link || echo copy) skills ($count public$([ "$local_count" -gt 0 ] && echo ", $local_count from skills-local"))"
}

for item in "${LINK_ITEMS[@]}"; do install_item "$item" "$MODE"; done
install_skills
for item in "${COPY_ITEMS[@]}"; do install_item "$item" copy; done

say ""
say "Done. Not installed (intentionally, per machine):"
say "  settings.local.json  — machine-specific permission allow-rules; let each machine build its own"
say "  memory/              — project state, not committed to this repo"
say ""
say "skills-local/ is gitignored: put skills naming an employer's products, internal"
say "repos, or reverse-engineered vendor formats there. They install exactly like the"
say "public ones and are never committed."
say ""
say "settings.json was COPIED, not linked. If you change model/theme via /config,"
say "diff it back into the repo:"
say "  diff $CLAUDE_DIR/settings.json $REPO_DIR/settings.json"
say ""
say "Verify with:  claude  then  /agents  and  /help"
