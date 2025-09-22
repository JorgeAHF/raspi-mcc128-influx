interface ErrorBannerProps {
  message: string | null;
  onClose?: () => void;
}

export function ErrorBanner({ message, onClose }: ErrorBannerProps) {
  if (!message) {
    return null;
  }

  return (
    <div className="error-banner" role="alert">
      <span>{message}</span>
      {onClose && (
        <button type="button" onClick={onClose} aria-label="Cerrar">
          ×
        </button>
      )}
    </div>
  );
}
