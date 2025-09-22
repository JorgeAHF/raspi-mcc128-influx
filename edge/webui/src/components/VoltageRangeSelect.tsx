interface VoltageRangeSelectProps {
  value: number;
  onChange: (value: number) => void;
  options?: number[];
  disabled?: boolean;
}

const DEFAULT_VOLTAGE_RANGES = [10, 5, 2.5, 1, 0.5, 0.25, 0.1];

export function VoltageRangeSelect({ value, onChange, options, disabled }: VoltageRangeSelectProps) {
  const handleSelect = (event: React.ChangeEvent<HTMLSelectElement>) => {
    onChange(Number.parseFloat(event.target.value));
  };

  const handleInput = (event: React.ChangeEvent<HTMLInputElement>) => {
    const parsed = Number.parseFloat(event.target.value);
    if (Number.isFinite(parsed)) {
      onChange(parsed);
    }
  };

  const ranges = options?.length ? options : DEFAULT_VOLTAGE_RANGES;

  return (
    <div className="voltage-select">
      <select value={value} onChange={handleSelect} disabled={disabled}>
        {ranges.map((range) => (
          <option key={range} value={range}>
            ±{range} V
          </option>
        ))}
      </select>
      <input
        type="number"
        step="0.1"
        value={value}
        onChange={handleInput}
        disabled={disabled}
      />
    </div>
  );
}
