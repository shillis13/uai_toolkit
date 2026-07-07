/**
 * FilterPills — Reusable filter pill bar.
 *
 * Used by TaskManagerPane, TodoManagerPane, etc.
 * Toggle behavior: clicking an active pill deselects it (returns to null/all).
 */

export interface FilterPillGroup<T extends string = string> {
  /** Unique key for this group (used for CSS class scoping) */
  groupKey: string;
  /** Currently selected value, or null for "all" */
  value: T | null;
  /** Called when a pill is clicked */
  onChange: (value: T | null) => void;
  /** Available options */
  options: T[];
  /** Label for the "all" pill. Omit to hide the all pill. */
  allLabel?: string;
  /** Map of option value to accent color CSS variable or raw color */
  colors?: Record<string, string>;
  /** Format the label for display. Defaults to identity. */
  formatLabel?: (option: T) => string;
}

interface FilterPillsProps {
  groups: FilterPillGroup[];
}

const FilterPills = ({ groups }: FilterPillsProps): JSX.Element => {
  return (
    <div className="filter-pills-bar">
      {groups.map((group, gi) => (
        <div key={group.groupKey} className="filter-pills-group">
          {gi > 0 && <span className="filter-pills-sep" />}
          {group.allLabel && (
            <button
              className={`filter-pill ${group.value === null ? 'active' : ''}`}
              onClick={() => group.onChange(null)}
            >
              {group.allLabel}
            </button>
          )}
          {group.options.map(option => {
            const isActive = group.value === option;
            const color = group.colors?.[option];
            return (
              <button
                key={option}
                className={`filter-pill ${isActive ? 'active' : ''}`}
                style={color ? {
                  borderColor: isActive ? color : undefined,
                  color: isActive ? color : undefined,
                  background: isActive ? `${color}15` : undefined,
                } : undefined}
                onClick={() => group.onChange(isActive ? null : option)}
              >
                {group.formatLabel ? group.formatLabel(option) : option}
              </button>
            );
          })}
        </div>
      ))}
    </div>
  );
};

export default FilterPills;
