import React, { forwardRef } from 'react';

interface ClearableInputProps extends Omit<React.InputHTMLAttributes<HTMLInputElement>, 'type'> {
  onClear?: () => void;
}

/**
 * Text input with an × clear button at the right edge.
 * Drop-in replacement for <input type="text" ... />.
 */
const ClearableInput = forwardRef<HTMLInputElement, ClearableInputProps>(
  ({ onClear, value, onChange, className, style, ...rest }, ref) => {
    const hasValue = value !== undefined && value !== null && String(value).length > 0;
    return (
      <div className="clearable-input-wrapper" style={style}>
        <input
          ref={ref}
          type="text"
          className={`clearable-input ${className ?? ''}`}
          value={value}
          onChange={onChange}
          {...rest}
        />
        {hasValue && (
          <button
            type="button"
            className="clearable-input-x"
            onClick={(e) => {
              e.stopPropagation();
              if (onClear) {
                onClear();
              } else if (onChange) {
                // Synthesize a change event with empty value
                const synth = { target: { value: '' } } as React.ChangeEvent<HTMLInputElement>;
                onChange(synth);
              }
            }}
            tabIndex={-1}
            title="Clear"
          >
            ×
          </button>
        )}
      </div>
    );
  }
);

ClearableInput.displayName = 'ClearableInput';
export default ClearableInput;
