/**
 * Breadcrumbs — folder path navigation.
 *
 * Workstream 1C: Organization Entities
 *
 * Shows path from root to current folder. Each segment is clickable
 * to navigate directly to that folder.
 *
 * Supports three location types per UCI data architecture:
 * - Folder: "/ > projects > uci_app"
 * - Card detail: "/ > projects > uci_app > Pixel"
 * - Filter view: "All Sessions > View: Claude"
 */

import React from 'react';
import { useFolderStore } from '../../stores/folder-store';

// ─── Props ───────────────────────────────────────────────────────────────

interface BreadcrumbsProps {
  folderId: string;
  cardLabel?: string;  // If showing a card detail, the card's display name
  onNavigate: (folderId: string) => void;
}

// ─── Component ───────────────────────────────────────────────────────────

export function Breadcrumbs({ folderId, cardLabel, onNavigate }: BreadcrumbsProps): React.ReactElement {
  const { breadcrumbSegments } = useFolderStore();
  const segments = breadcrumbSegments(folderId);

  return (
    <nav className="breadcrumbs" aria-label="Folder path">
      {segments.map((segment, index) => {
        const isLast = index === segments.length - 1 && !cardLabel;
        return (
          <React.Fragment key={segment.id}>
            {index > 0 && <span className="breadcrumbs-separator">&gt;</span>}
            {isLast ? (
              <span className="breadcrumbs-current">{segment.name}</span>
            ) : (
              <button
                className="breadcrumbs-link"
                onClick={() => onNavigate(segment.id)}
                title={`Navigate to ${segment.name}`}
              >
                {segment.name}
              </button>
            )}
          </React.Fragment>
        );
      })}
      {cardLabel && (
        <>
          <span className="breadcrumbs-separator">&gt;</span>
          <span className="breadcrumbs-current">{cardLabel}</span>
        </>
      )}
    </nav>
  );
}
