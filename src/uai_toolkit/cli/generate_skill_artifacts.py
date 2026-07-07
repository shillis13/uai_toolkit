#!/usr/bin/env python3
"""Generate SKILL.md files and system prompt text from ai_profiles/skills/*.yml definitions.

Usage:
    python3 generate_skill_artifacts.py                    # Generate all
    python3 generate_skill_artifacts.py ai_comms           # Generate one by name
    python3 generate_skill_artifacts.py --list             # List available skills
    python3 generate_skill_artifacts.py --dry-run          # Show what would be generated
    python3 generate_skill_artifacts.py --format skill_md  # Only SKILL.md (default: all)
    python3 generate_skill_artifacts.py --format prompt    # Only system prompt text

Output:
    ai_profiles/skills/generated/{name}.SKILL.md       — Claude Code skill format
    ai_profiles/skills/generated/{name}.prompt.md      — System prompt injection text (Codex/Gemini)
"""

import argparse
import sys
import yaml
from pathlib import Path
from typing import Optional

# Resolve AI_ROOT
AI_ROOT = Path(__file__).resolve().parent.parent.parent.parent  # scripts/cli -> ai_general -> ai_root
AI_GENERAL = AI_ROOT / "ai_general"
SKILLS_DIR = AI_GENERAL / "ai_profiles" / "skills"
OUTPUT_DIR = SKILLS_DIR / "generated"


def load_skill(path: Path) -> dict:
    """Load and parse a skill YAML definition."""
    with open(path) as f:
        return yaml.safe_load(f)


def list_skills() -> list[Path]:
    """Find all .yml skill definitions (exclude generated/ and subdirs)."""
    return sorted(SKILLS_DIR.glob("*.yml"))


def _render_section_content(lines: list[str], section: dict, depth: int = 3):
    """Recursively render a workflow section's content into markdown lines."""
    skip = {"name", "description"}

    for key, value in section.items():
        if key in skip:
            continue

        heading = "#" * depth
        nice_key = key.replace("_", " ").title()

        if isinstance(value, list):
            # List of strings → bullet points
            if value and isinstance(value[0], str):
                lines.append(f"**{nice_key}:**")
                for item in value:
                    lines.append(f"- {item}")
                lines.append("")
            # List of dicts → structured items
            elif value and isinstance(value[0], dict):
                lines.append(f"{heading} {nice_key}")
                lines.append("")
                for item in value:
                    # Handle rule/why pairs
                    if "rule" in item:
                        lines.append(f"**{item['rule']}**")
                        if "why" in item:
                            lines.append(f"  Why: {item['why']}")
                        if "use_instead" in item:
                            lines.append(f"  Use instead: {item['use_instead']}")
                        lines.append("")
                    # Handle name/steps patterns
                    elif "name" in item and "steps" in item:
                        p_name = item.get("name", key)
                        p_desc = item.get("description", "")
                        lines.append(f"{heading}# {p_name}")
                        lines.append("")
                        if p_desc:
                            lines.append(p_desc)
                            lines.append("")
                        for step in item.get("steps", []):
                            step_text = step.lstrip("0123456789. ")
                            lines.append(f"- [ ] **{step_text}**")
                        lines.append("")
                        # Notes under steps
                        for note in item.get("notes", []):
                            lines.append(f"  - {note}")
                        if item.get("notes"):
                            lines.append("")
                    # Generic dict items
                    else:
                        for k, v in item.items():
                            lines.append(f"- **{k}:** {v}")
                        lines.append("")

        elif isinstance(value, dict):
            # Check if it's a named section with its own content
            if "name" in value or "description" in value or "steps" in value:
                sub_name = value.get("name", nice_key)
                sub_desc = value.get("description", "")
                if isinstance(sub_desc, str):
                    sub_desc = sub_desc.strip()
                lines.append(f"{heading} {sub_name}")
                lines.append("")
                if sub_desc:
                    lines.append(sub_desc)
                    lines.append("")
                # When
                for list_key in ["when", "how", "steps", "notes", "constraints"]:
                    items = value.get(list_key, [])
                    if items:
                        if list_key == "steps":
                            for step in items:
                                step_text = step.lstrip("0123456789. ")
                                lines.append(f"- [ ] **{step_text}**")
                        else:
                            lines.append(f"**{list_key.title()}:**")
                            for item in items:
                                lines.append(f"- {item}")
                        lines.append("")
                # Recurse for nested patterns/subsections
                patterns = value.get("patterns", {})
                if isinstance(patterns, dict):
                    for pk, pv in patterns.items():
                        if isinstance(pv, dict):
                            p_name = pv.get("name", pk)
                            p_desc = pv.get("description", "")
                            steps = pv.get("steps", [])
                            lines.append(f"{heading}# Pattern: {p_name}")
                            lines.append("")
                            if p_desc:
                                lines.append(p_desc)
                                lines.append("")
                            for step in steps:
                                step_text = step.lstrip("0123456789. ")
                                lines.append(f"- [ ] **{step_text}**")
                            lines.append("")
            else:
                # Generic dict section — recurse
                lines.append(f"{heading} {nice_key}")
                lines.append("")
                _render_section_content(lines, value, depth + 1)

        elif isinstance(value, str):
            lines.append(f"**{nice_key}:** {value}")
            lines.append("")


def generate_skill_md(skill: dict) -> str:
    """Generate Claude Code SKILL.md content from a skill definition."""
    meta = skill.get("metadata", {})
    name = meta.get("name", "unnamed")
    description = meta.get("description", "").strip()
    trigger = skill.get("trigger", {})
    trigger_desc = trigger.get("description", "").strip()
    workflow = skill.get("workflow", {})
    tools = skill.get("tools", {})

    lines = []

    # Frontmatter
    lines.append("---")
    lines.append(f'name: {name}')
    lines.append(f'description: "{trigger_desc}"')
    lines.append("---")
    lines.append("")

    # Title
    title = meta.get("name", "Unnamed Skill").replace("-", " ").title()
    lines.append(f"# {title}")
    lines.append("")
    lines.append(description)
    lines.append("")

    # Decision tree (if present)
    decision_tree = workflow.get("decision_tree", [])
    if decision_tree:
        lines.append("## Decision Tree")
        lines.append("")
        for item in decision_tree:
            q = item.get("question", "")
            y = item.get("yes", "")
            n = item.get("no", "")
            lines.append(f"**{q}**")
            if y:
                lines.append(f"- Yes → {y}")
            if n:
                lines.append(f"- No → {n}")
            lines.append("")

    # Available tools
    if tools:
        lines.append("## Available Tools")
        lines.append("")
        for tool_group_key, tool_group in tools.items():
            group_desc = tool_group.get("description", "")
            mcp = tool_group.get("mcp_server", "")
            lines.append(f"### {group_desc}")
            if mcp:
                lines.append(f"MCP Server: `{mcp}`")
            lines.append("")
            for op in tool_group.get("operations", []):
                if isinstance(op, dict):
                    for op_name, op_desc in op.items():
                        lines.append(f"- `{mcp}:{op_name}` — {op_desc}")
                elif isinstance(op, str):
                    # "name: description" format
                    if ":" in op:
                        op_name, op_desc = op.split(":", 1)
                        lines.append(f"- `{mcp}:{op_name.strip()}` — {op_desc.strip()}")
                    else:
                        lines.append(f"- `{mcp}:{op}`")
            lines.append("")

    # Generic workflow section renderer
    skip_keys = {"overview", "decision_tree", "guidelines", "anti_patterns"}
    for section_key, section in workflow.items():
        if section_key in skip_keys:
            continue
        if not isinstance(section, dict):
            continue

        section_name = section.get("name", section_key.replace("_", " ").title())
        section_desc = section.get("description", "")
        if isinstance(section_desc, str):
            section_desc = section_desc.strip()

        lines.append(f"## {section_name}")
        lines.append("")
        if section_desc:
            lines.append(section_desc)
            lines.append("")

        # Render known sub-structures
        _render_section_content(lines, section)
        lines.append("")

    # Guidelines
    guidelines = workflow.get("guidelines", [])
    if guidelines:
        lines.append("## Guidelines")
        lines.append("")
        for g in guidelines:
            lines.append(f"- {g}")
        lines.append("")

    # Anti-patterns
    anti = workflow.get("anti_patterns", [])
    if anti:
        lines.append("## Anti-Patterns")
        lines.append("")
        for a in anti:
            lines.append(f"- {a}")
        lines.append("")

    return "\n".join(lines)


def generate_prompt_text(skill: dict) -> str:
    """Generate system prompt injection text for Codex/Gemini from a skill definition.

    This is a more compact version without SKILL.md frontmatter,
    designed to be injected into --append-system-prompt.
    """
    meta = skill.get("metadata", {})
    name = meta.get("name", "unnamed")
    description = meta.get("description", "").strip()
    workflow = skill.get("workflow", {})
    tools = skill.get("tools", {})

    lines = []

    title = name.replace("-", " ").title()
    lines.append(f"# Skill: {title}")
    lines.append("")
    lines.append(description)
    lines.append("")

    # Compact tool reference
    if tools:
        lines.append("## Tools")
        for tool_group_key, tool_group in tools.items():
            mcp = tool_group.get("mcp_server", "")
            ops = tool_group.get("operations", [])
            op_names = []
            for op in ops:
                if isinstance(op, dict):
                    op_names.extend(op.keys())
                elif isinstance(op, str) and ":" in op:
                    op_names.append(op.split(":")[0].strip())
                elif isinstance(op, str):
                    op_names.append(op)
            if op_names:
                lines.append(f"- {mcp}: {', '.join(op_names)}")
        lines.append("")

    # Compact workflow patterns
    for section_key in ["inner_comms", "inter_comms"]:
        section = workflow.get(section_key, {})
        if not section:
            continue
        patterns = section.get("patterns", {})
        if isinstance(patterns, dict):
            for pattern_key, pattern in patterns.items():
                if isinstance(pattern, dict):
                    p_name = pattern.get("name", pattern_key)
                    steps = pattern.get("steps", [])
                    lines.append(f"### {p_name}")
                    for step in steps:
                        lines.append(f"  {step}")
                    lines.append("")

    # Guidelines (compact)
    guidelines = workflow.get("guidelines", [])
    if guidelines:
        lines.append("## Rules")
        for g in guidelines:
            lines.append(f"- {g}")
        lines.append("")

    return "\n".join(lines)


def generate(skill_name: Optional[str] = None, formats: list[str] = ["skill_md", "prompt"],
             dry_run: bool = False) -> int:
    """Generate artifacts for one or all skills."""
    skills = list_skills()

    if not skills:
        print("No skill definitions found in", SKILLS_DIR)
        return 1

    if skill_name:
        skills = [s for s in skills if s.stem == skill_name]
        if not skills:
            print(f"Skill '{skill_name}' not found. Available:",
                  ", ".join(s.stem for s in list_skills()))
            return 1

    OUTPUT_DIR.mkdir(exist_ok=True)

    generated = 0
    for skill_path in skills:
        skill = load_skill(skill_path)
        name = skill.get("metadata", {}).get("name", skill_path.stem)

        if "skill_md" in formats:
            out_path = OUTPUT_DIR / f"{name}.SKILL.md"
            content = generate_skill_md(skill)
            if dry_run:
                print(f"Would write: {out_path} ({len(content)} chars)")
            else:
                out_path.write_text(content)
                print(f"Generated: {out_path}")
            generated += 1

        if "prompt" in formats:
            out_path = OUTPUT_DIR / f"{name}.prompt.md"
            content = generate_prompt_text(skill)
            if dry_run:
                print(f"Would write: {out_path} ({len(content)} chars)")
            else:
                out_path.write_text(content)
                print(f"Generated: {out_path}")
            generated += 1

    print(f"\n{generated} artifact(s) {'would be ' if dry_run else ''}generated.")
    return 0


def main():
    parser = argparse.ArgumentParser(description="Generate skill artifacts from YAML definitions")
    parser.add_argument("skill", nargs="?", help="Skill name to generate (default: all)")
    parser.add_argument("--list", action="store_true", help="List available skill definitions")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be generated")
    parser.add_argument("--format", choices=["skill_md", "prompt", "all"], default="all",
                        help="Output format (default: all)")
    args = parser.parse_args()

    if args.list:
        skills = list_skills()
        if not skills:
            print("No skill definitions found.")
        else:
            for s in skills:
                skill = load_skill(s)
                name = skill.get("metadata", {}).get("name", s.stem)
                desc = skill.get("metadata", {}).get("description", "")[:80]
                print(f"  {name:<25} {desc}")
        return

    formats = ["skill_md", "prompt"] if args.format == "all" else [args.format]
    sys.exit(generate(args.skill, formats, args.dry_run))


if __name__ == "__main__":
    main()
