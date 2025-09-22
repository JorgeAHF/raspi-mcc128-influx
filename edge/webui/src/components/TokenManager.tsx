import { FormEvent, useEffect, useState } from "react";

interface TokenManagerProps {
  token: string | null;
  onUpdate: (token: string | null) => void;
}

export function TokenManager({ token, onUpdate }: TokenManagerProps) {
  const [value, setValue] = useState(token ?? "");

  useEffect(() => {
    setValue(token ?? "");
  }, [token]);

  const handleSubmit = (event: FormEvent) => {
    event.preventDefault();
    onUpdate(value.trim() ? value.trim() : null);
  };

  const handleClear = () => {
    if (confirm("¿Eliminar token guardado?")) {
      setValue("");
      onUpdate(null);
    }
  };

  return (
    <form className="token-manager" onSubmit={handleSubmit}>
      <label>
        <span>Token de acceso</span>
        <input
          type="password"
          value={value}
          onChange={(event) => setValue(event.target.value)}
          placeholder="Bearer token"
        />
      </label>
      <div className="actions">
        <button type="submit">Guardar</button>
        {token && (
          <button type="button" className="secondary" onClick={handleClear}>
            Limpiar
          </button>
        )}
      </div>
    </form>
  );
}
