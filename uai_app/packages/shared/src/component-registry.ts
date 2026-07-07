/**
 * ComponentRegistry — central registry for all architectural components.
 *
 * Every architectural component registers with this registry and provides
 * a describe() method returning ComponentDescription. This enables:
 * - Embedded AI discovery of available components and their capabilities
 * - Auto-generated help and documentation
 * - Contract testing (every component's description validates against schema)
 * - Component tree visualization
 */

import type { ComponentDescription } from '../../../architecture/contracts';

// ─── Describable Component Interface ──────────────────────────────────────

export interface DescribableComponent {
  describe(): ComponentDescription;
}

// ─── ComponentRegistry ────────────────────────────────────────────────────

class ComponentRegistryImpl {
  private components = new Map<string, DescribableComponent>();

  /**
   * Register a component with its description provider.
   */
  register(id: string, component: DescribableComponent): void {
    this.components.set(id, component);
  }

  /**
   * Unregister a component.
   */
  unregister(id: string): void {
    this.components.delete(id);
  }

  /**
   * Get a registered component by ID.
   */
  get(id: string): DescribableComponent | undefined {
    return this.components.get(id);
  }

  /**
   * Get the description for a specific component.
   */
  describe(id: string): ComponentDescription | undefined {
    return this.components.get(id)?.describe();
  }

  /**
   * Get descriptions for all registered components.
   * Returns a map of component ID → ComponentDescription.
   */
  describeAll(): Record<string, ComponentDescription> {
    const result: Record<string, ComponentDescription> = {};
    for (const [id, component] of this.components) {
      result[id] = component.describe();
    }
    return result;
  }

  /**
   * List all registered component IDs.
   */
  list(): string[] {
    return Array.from(this.components.keys());
  }

  /**
   * Check if a component is registered.
   */
  has(id: string): boolean {
    return this.components.has(id);
  }

  /**
   * Get the count of registered components.
   */
  get size(): number {
    return this.components.size;
  }
}

// Singleton instance
export const ComponentRegistry = new ComponentRegistryImpl();
