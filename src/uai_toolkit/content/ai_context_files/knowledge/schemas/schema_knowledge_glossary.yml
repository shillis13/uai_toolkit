# Knowledge Glossary Schema

**Version:** 1.0.0
**Maintainer:** Librarian CLI agent
**Load:** AUTO (include in every session's initial context)

## Purpose

Solves the bootstrap problem: Claude needs to know what's IN files to know WHEN to load them. This glossary provides term recognition and pointer resolution without loading full documents.

## Usage

When Claude encounters a term from this glossary in conversation:
1. Use definition for immediate context
2. Load primary_ref if details needed
3. Check also_in for related context

## Regeneration

Librarian rebuilds on: new file additions, weekly maintenance, or on-demand when gaps discovered.

## Metadata Fields

| Field | Description |
|-------|-------------|
| title | AI Root Knowledge Glossary |
| version | Schema version |
| generated | ISO timestamp when regenerated |
| generator | librarian |
| term_count | Total terms indexed |
| file_count | Files scanned |

## Term Entry Structure

```yaml
term_name:
  term: "Display Name"
  aliases: [alt1, alt2]      # Alternative phrasings to match
  domain: architecture       # Category
  definition: |
    1-2 sentences explaining the term
  primary_ref: "REF:path/to/file.yml"
  also_in:
    - "REF:path/to/other.yml"
  related_terms: [other_term, concept]
```

## Domain Categories

| Domain | Description | Examples |
|--------|-------------|----------|
| architecture | System design patterns, structural concepts | federated memory, drain-and-fill |
| protocol | Communication patterns, coordination rules | task coordination, pulse system |
| tool | MCP servers, utilities, integrations | Desktop Commander, mem0 |
| concept | Mental models, principles, named patterns | context conservation, bootstrap problem |
| workflow | Multi-step procedures, operational sequences | overnight automation, peer review |
| entity | Named systems, agents, platforms | Chatty, librarian, Claude Desktop |

## Extraction Rules

### What to Index
- Named patterns with specific meaning in our system
- Acronyms and abbreviations we use
- Tool names and their purposes
- Protocol names and versions
- Architectural concepts unique to our system
- Named agents/roles (librarian, custodian, etc.)

### What to Skip
- Generic programming terms (API, JSON, YAML)
- Standard tool names without our-specific usage
- One-off mentions without recurring significance
- Terms already well-defined in Claude's training

### Definition Guidelines
- 1-2 sentences maximum
- Answer "what is X?" without requiring file load
- Include key distinguishing characteristics
- Reference relationships to other terms where helpful

## Output Files

| File | Load Priority | Est. Tokens | Format |
|------|---------------|-------------|--------|
| glossary_knowledge_index.yml | AUTO | ~2000-4000 | Full schema with all terms |
| glossary_knowledge_index.condensed.yml | AUTO | ~800-1200 | Minimal format for token conservation |

## Manifest Enhancements

### Per-File Additions

| Field | Format | Purpose |
|-------|--------|---------|
| triggers | List of 3-5 phrases | Phrases that should prompt loading this file |
| abstract | 1-2 sentence summary | What question does this file answer? |
| answers | List of questions | Questions this file directly answers |
