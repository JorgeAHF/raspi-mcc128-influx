import { ChangeEvent } from "react";
import { Calibration } from "../types";

interface CalibrationInputProps {
  value: Calibration;
  onChange: (value: Calibration) => void;
  disabled?: boolean;
}

export function CalibrationInput({ value, onChange, disabled }: CalibrationInputProps) {
  const handleChange = (event: ChangeEvent<HTMLInputElement>) => {
    const { name, value: raw } = event.target;
    const numeric = Number.parseFloat(raw);
    onChange({
      ...value,
      [name]: Number.isFinite(numeric) ? numeric : 0,
    });
  };

  return (
    <div className="calibration-input">
      <label className="field">
        <span>Ganancia</span>
        <input
          type="number"
          name="gain"
          step="0.0001"
          value={value.gain}
          onChange={handleChange}
          disabled={disabled}
        />
      </label>
      <label className="field">
        <span>Offset</span>
        <input
          type="number"
          name="offset"
          step="0.0001"
          value={value.offset}
          onChange={handleChange}
          disabled={disabled}
        />
      </label>
    </div>
  );
}
