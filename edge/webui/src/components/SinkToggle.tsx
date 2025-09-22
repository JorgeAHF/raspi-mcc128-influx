interface SinkToggleProps {
  sink: string;
  label: string;
  enabled: boolean;
  onToggle: (sink: string, enabled: boolean) => void;
  disabled?: boolean;
}

export function SinkToggle({ sink, label, enabled, onToggle, disabled }: SinkToggleProps) {
  return (
    <label className="sink-toggle">
      <input
        type="checkbox"
        checked={enabled}
        onChange={(event) => onToggle(sink, event.target.checked)}
        disabled={disabled}
      />
      <span>{label}</span>
    </label>
  );
}
