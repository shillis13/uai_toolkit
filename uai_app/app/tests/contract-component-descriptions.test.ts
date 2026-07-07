/**
 * Contract Test: Component Descriptions
 *
 * Quality Gate 1D.3 — validates that every registered component's
 * describe() output conforms to the ComponentDescription schema.
 *
 * This prevents the "placeholder div catastrophe" by verifying that
 * components are actually registered, not just defined.
 */

import { describe, it, expect, beforeAll } from 'vitest';
import { ComponentRegistry } from '@uai/shared/component-registry';
import { registerInitialComponents } from '@uai/shared/component-descriptions';
import type { ComponentDescription } from '../../architecture/contracts';

beforeAll(() => {
  registerInitialComponents();
});

describe('ComponentRegistry contract tests', () => {
  it('has at least 5 registered components', () => {
    const ids = ComponentRegistry.list();
    expect(ids.length).toBeGreaterThanOrEqual(5);
  });

  it('includes all expected architectural components', () => {
    const expected = ['session_navigator', 'workspace', 'session_pane', 'context_panel', 'bottom_panel'];
    for (const id of expected) {
      expect(ComponentRegistry.has(id)).toBe(true);
    }
  });

  it('every component returns a valid describe() output', () => {
    const ids = ComponentRegistry.list();
    for (const id of ids) {
      const desc = ComponentRegistry.describe(id);
      expect(desc).toBeDefined();
      validateComponentDescription(desc!, id);
    }
  });

  it('describeAll() returns descriptions for all registered components', () => {
    const all = ComponentRegistry.describeAll();
    const ids = ComponentRegistry.list();
    expect(Object.keys(all).length).toBe(ids.length);
    for (const id of ids) {
      expect(all[id]).toBeDefined();
    }
  });
});

/**
 * Validate a ComponentDescription against the contract schema.
 * This is the structural validation that prevents registration of
 * incomplete or malformed component descriptions.
 */
function validateComponentDescription(desc: ComponentDescription, expectedId: string): void {
  // Required fields
  expect(desc.schema_version).toBeTypeOf('number');
  expect(desc.schema_version).toBeGreaterThanOrEqual(1);

  expect(desc.id).toBe(expectedId);
  expect(desc.id).toBeTypeOf('string');
  expect(desc.id.length).toBeGreaterThan(0);

  expect(desc.path).toBeTypeOf('string');
  expect(desc.path).toContain('app');

  expect(desc.name).toBeTypeOf('string');
  expect(desc.name.length).toBeGreaterThan(0);

  expect(desc.description).toBeTypeOf('string');
  expect(desc.description.length).toBeGreaterThan(0);

  // Parent: null for root-level, string for children
  expect(desc.parent === null || typeof desc.parent === 'string').toBe(true);

  // Children array
  expect(Array.isArray(desc.children)).toBe(true);

  // State: Record<string, StateDescriptor>
  expect(typeof desc.state).toBe('object');
  for (const [key, stateDesc] of Object.entries(desc.state)) {
    expect(key.length).toBeGreaterThan(0);
    expect(stateDesc.description).toBeTypeOf('string');
    expect(typeof stateDesc.readable).toBe('boolean');
    expect(typeof stateDesc.writable).toBe('boolean');
    expect(['local', 'command']).toContain(stateDesc.write_mechanism);
  }

  // Commands
  expect(typeof desc.commands).toBe('object');
  for (const [key, cmdDesc] of Object.entries(desc.commands)) {
    expect(key.length).toBeGreaterThan(0);
    expect(cmdDesc.description).toBeTypeOf('string');
    expect(typeof cmdDesc.safety).toBe('string');
    expect(typeof cmdDesc.idempotent).toBe('boolean');
    expect(typeof cmdDesc.async).toBe('boolean');
    expect(['immediate', 'fast', 'slow']).toContain(cmdDesc.latency);
  }

  // Actions
  expect(typeof desc.actions).toBe('object');

  // Events
  expect(typeof desc.events).toBe('object');

  // Context
  expect(Array.isArray(desc.context)).toBe(true);
  for (const ctx of desc.context) {
    expect(ctx.key).toBeTypeOf('string');
    expect(ctx.type).toBeTypeOf('string');
    expect(typeof ctx.required).toBe('boolean');
  }
}
