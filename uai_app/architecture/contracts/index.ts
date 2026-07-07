/**
 * UAI Architecture Contracts — Phase 0A
 *
 * Central export for all frozen contract types.
 * These types are the foundation that all implementation builds against.
 *
 * Contract files:
 *   identity.ts   — Session identity per spec_session_identity_v5.4
 *   entities.ts   — Entity model: Session, Brief, Project, Team, Tag, Relationships
 *   commands.ts   — Command bus: envelope, result, access control, capabilities
 *   events.ts     — Events: store changes, runtime changes, notifications, AI comms
 *   components.ts — Component API: self-description, action context, focus model
 */

export * from './identity';
export * from './entities';
export * from './commands';
export * from './events';
export * from './components';
export * from './cards';
export * from './viewport';
