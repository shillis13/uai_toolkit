import { describe, it, expect } from 'vitest';
import { parseSessionMentions } from '@uai/renderer-ui/components/prompt-mentions';

// name (lowercased) → session tracking_ids. Sessions map to [self]; teams/projects to members.
const names = new Map<string, string[]>([
  ['ember', ['id_ember']],
  ['anvil', ['id_anvil']],
  ['broken-clock', ['id_bc']],
  ['uai-core', ['id_ember', 'id_anvil']],   // a team → members
  ['society', ['id_bc', 'id_ember']],       // a project → member sessions
  ['uai core team', ['id_ember', 'id_anvil']], // a spaced display name (quoted form)
]);

describe('parseSessionMentions', () => {
  it('matches a known @name to its session', () => {
    expect(parseSessionMentions('@Ember do X', names)).toEqual(['id_ember']);
  });
  it('is case-insensitive', () => {
    expect(parseSessionMentions('hey @ANVIL', names)).toEqual(['id_anvil']);
  });
  it('expands a @team to its member sessions', () => {
    expect(parseSessionMentions('@uai-core sync up', names)).toEqual(['id_ember', 'id_anvil']);
  });
  it('expands a @project to its member sessions', () => {
    expect(parseSessionMentions('@society standup', names)).toEqual(['id_bc', 'id_ember']);
  });
  it('unions + de-duplicates across session/team/project mentions', () => {
    // anvil + uai-core(ember,anvil) → ember, anvil (deduped)
    expect(parseSessionMentions('@anvil and @uai-core', names)).toEqual(['id_anvil', 'id_ember']);
  });
  it('matches hyphenated names', () => {
    expect(parseSessionMentions('@broken-clock ping', names)).toEqual(['id_bc']);
  });
  it('ignores unknown names', () => {
    expect(parseSessionMentions('@nobody hi', names)).toEqual([]);
  });
  it('does NOT treat @/path as a recipient (file)', () => {
    expect(parseSessionMentions('read @/tmp/ember.txt', names)).toEqual([]);
  });
  it('does NOT treat @~/path as a recipient (file)', () => {
    expect(parseSessionMentions('see @~/ember/notes', names)).toEqual([]);
  });
  it('requires @ at start or after whitespace (not mid-word like an email)', () => {
    expect(parseSessionMentions('mail me at bob@ember.com', names)).toEqual([]);
  });
  it('handles a mix of file + session + team mentions', () => {
    expect(parseSessionMentions('@ember review @/tmp/x.ts and @uai-core too', names))
      .toEqual(['id_ember', 'id_anvil']);
  });
  it('resolves a @"quoted name with spaces"', () => {
    expect(parseSessionMentions('hey @"UAI Core Team" sync', names)).toEqual(['id_ember', 'id_anvil']);
  });
  it('quoted + bare mentions together', () => {
    expect(parseSessionMentions('@"UAI Core Team" and @broken-clock', names))
      .toEqual(['id_ember', 'id_anvil', 'id_bc']);
  });
  it('a bare @word does not swallow following text as a spaced name', () => {
    // @uai-core resolves; "team" after a space is not part of the mention
    expect(parseSessionMentions('@uai-core team meeting', names)).toEqual(['id_ember', 'id_anvil']);
  });
});
